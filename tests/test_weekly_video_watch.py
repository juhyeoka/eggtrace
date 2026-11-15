from __future__ import annotations

from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from watch_weekly_videos import MANIFEST, Watcher, WatchError, digest
from install_weekly_video_watch import install

FAKE_PIPELINE = r'''
import argparse, hashlib, json, subprocess
from pathlib import Path
p=argparse.ArgumentParser()
for name in ['input','week','output-root','manifest']:p.add_argument('--'+name,required=True)
p.add_argument('--json',action='store_true')
a=p.parse_args()
repo=Path.cwd()
if (repo/'.fail_prepare').exists():raise SystemExit('intentional preparation failure')
sha=hashlib.sha256(Path(a.input).read_bytes()).hexdigest()
version=a.week+'-'+sha[:12]
root=Path(a.output_root)/version
root.mkdir(parents=True,exist_ok=True)
prefix='/weekly/'+version+'/'
videos={mode:prefix+mode+'.mp4' for mode in ['farm','activity','density','pattern']}
posters={mode:prefix+mode+'.webp' for mode in videos}
moments=[{'time':i,'url':prefix+'moment'+str(i)+'.webp'} for i in [1,2,3]]
for url in [prefix+'analysis.json',*videos.values(),*posters.values(),*[m['url'] for m in moments]]:
    (root/url.split('/')[-1]).write_bytes(b'generated media')
# A private/debug artifact must never be staged just because it is in the new bundle.
(root/'private-debug.txt').write_text('not public')
data={'schemaVersion':1,'version':version,'week':a.week,'sourceSha256':sha,
      'analysisUrl':prefix+'analysis.json','videos':videos,'posters':posters,'moments':moments}
if (repo/'.unsafe_manifest').exists():data['videos']['farm']=prefix+'../../private.mp4'
cached=dict(data)
if (repo/'.bad_release_manifest').exists():cached['sourceSha256']='different source'
(root/'manifest.json').write_text(json.dumps(cached))
Path(a.manifest).write_text(json.dumps(data))
if (repo/'.stage_during_prepare').exists():
    subprocess.run(['git','add','--','unrelated.txt'],check=True)
print(json.dumps(data))
'''


class WatcherGitTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.base=Path(self.tmp.name)
        self.repo=self.base/'repo'
        self.remote=self.base/'remote.git'
        self.repo.mkdir()
        self.inbox=self.base/'inbox'
        self.inbox.mkdir()
        self.state_dir=self.base/'state'
        self.now=datetime.fromisoformat('2026-11-16T12:00:00+09:00').timestamp()
        self.git_external('init','--bare','--initial-branch=main',str(self.remote))
        self.git_external('init','-b','main',str(self.repo))
        self.git('config','user.name','Watcher Test')
        self.git('config','user.email','watcher@example.invalid')
        self.git('config','commit.gpgsign','false')
        (self.repo/'configs').mkdir()
        self.old_manifest=b'{"old":"keep this active"}\n'
        (self.repo/MANIFEST).write_bytes(self.old_manifest)
        (self.repo/'unrelated.txt').write_text('baseline\n')
        (self.repo/'.gitignore').write_text('*.mp4\n')
        self.git('add','.')
        self.git('commit','-m','baseline')
        self.git('remote','add','origin',str(self.remote))
        self.git('push','-u','origin','main')
        (self.repo/'tools').mkdir()
        (self.repo/'tools/prepare_weekly_video.py').write_text(FAKE_PIPELINE)
        (self.repo/'tools/watch_weekly_videos.py').write_text('# installed watcher placeholder')
        self.watcher=self.make_watcher()

    def tearDown(self):
        self.tmp.cleanup()

    def git_external(self,*args):
        return subprocess.run(['git',*args],check=True,capture_output=True,text=True).stdout.strip()

    def git(self,*args):
        return subprocess.run(['git',*args],cwd=self.repo,check=True,capture_output=True,text=True).stdout.strip()

    def remote_head(self):
        return self.git_external('--git-dir='+str(self.remote),'rev-parse','refs/heads/main')

    def make_watcher(self):
        return Watcher(self.repo,self.inbox,self.state_dir,sys.executable,now=lambda:self.now)

    def source(self,name='week.mp4',data=b'new farm video'):
        path=self.inbox/name
        path.write_bytes(data)
        os.utime(path,(self.now-1000,self.now-1000))
        return path

    def settle(self):
        self.watcher.run_once()
        self.now+=31
        return self.watcher.run_once()

    def test_stable_copy_two_checks_and_changed_file_waits_again(self):
        source=self.source()
        baseline=self.git('rev-parse','HEAD')
        self.assertEqual(self.watcher.run_once()['action'],'waiting')
        self.now+=31
        source.write_bytes(b'copy still in progress and larger')
        os.utime(source,(self.now-1000,self.now-1000))
        self.assertEqual(self.watcher.run_once()['action'],'waiting')
        self.assertEqual(self.git('rev-parse','HEAD'),baseline)
        self.now+=31
        self.assertEqual(self.watcher.run_once()['action'],'published')
        self.assertTrue(source.exists())
        self.assertEqual(self.remote_head(),self.git('rev-parse','HEAD'))

    def test_whitelist_preserves_unrelated_dirty_files_and_deduplicates(self):
        original=self.source()
        (self.repo/'unrelated.txt').write_text('user work stays here\n')
        (self.repo/'private.txt').write_text('do not stage')
        self.settle()
        commit=self.git('rev-parse','HEAD')
        paths=self.git('diff-tree','--no-commit-id','--name-only','-r','HEAD').splitlines()
        self.assertIn(MANIFEST,paths)
        self.assertTrue(any(path.endswith('.mp4') for path in paths))
        self.assertTrue(any(path.startswith('static/weekly/') and path.endswith('/manifest.json') for path in paths))
        self.assertTrue(all(path==MANIFEST or path.startswith('static/weekly/') for path in paths))
        self.assertFalse(any('private-debug' in path for path in paths))
        self.assertEqual((self.repo/'unrelated.txt').read_text(),'user work stays here\n')
        self.assertEqual(self.git('diff','--cached','--name-only'),'')
        self.assertEqual(original.read_bytes(),b'new farm video')
        self.source('same-content.MOV',original.read_bytes())
        self.watcher.run_once()
        self.now+=31
        self.watcher.run_once()
        self.assertEqual(self.git('rev-parse','HEAD'),commit)
        self.assertEqual(len(self.watcher.state['processed']),1)

    def test_existing_staged_work_is_not_changed(self):
        self.source()
        self.watcher.run_once()
        self.now+=31
        (self.repo/'unrelated.txt').write_text('staged by user')
        self.git('add','unrelated.txt')
        before=self.git('diff','--cached')
        with self.assertRaisesRegex(WatchError,'스테이징'):
            self.watcher.run_once()
        self.assertEqual(self.git('diff','--cached'),before)
        self.assertEqual((self.repo/MANIFEST).read_bytes(),self.old_manifest)

    def test_remote_difference_and_local_ahead_never_auto_push(self):
        self.source()
        self.watcher.run_once()
        self.now+=31
        remote_before=self.remote_head()
        (self.repo/'user-commit.txt').write_text('unpublished user work')
        self.git('add','user-commit.txt')
        self.git('commit','-m','user commit')
        with self.assertRaisesRegex(WatchError,'원격 main'):
            self.watcher.run_once()
        self.assertEqual(self.remote_head(),remote_before)
        self.assertEqual((self.repo/MANIFEST).read_bytes(),self.old_manifest)

    def test_remote_ahead_and_non_main_branch_stop_before_preparation(self):
        self.source()
        self.watcher.run_once()
        self.now+=31
        other=self.base/'other'
        self.git_external('clone',str(self.remote),str(other))
        def other_git(*args):
            return subprocess.run(['git',*args],cwd=other,check=True,capture_output=True,text=True).stdout.strip()
        other_git('config','user.name','Other Work')
        other_git('config','user.email','other@example.invalid')
        other_git('config','commit.gpgsign','false')
        (other/'remote-change.txt').write_text('new remote work')
        other_git('add','remote-change.txt')
        other_git('commit','-m','remote work')
        other_git('push','origin','main')
        remote_after=self.remote_head()
        with self.assertRaisesRegex(WatchError,'원격 main'):
            self.watcher.run_once()
        self.assertEqual(self.remote_head(),remote_after)
        self.assertEqual((self.repo/MANIFEST).read_bytes(),self.old_manifest)
        self.git('checkout','-b','user-feature')
        self.now+=601
        with self.assertRaisesRegex(WatchError,'main 브랜치'):
            self.watcher.run_once()
        self.assertEqual(self.git('branch','--show-current'),'user-feature')

    def test_commit_failure_rolls_back_only_owned_files(self):
        self.source()
        self.watcher.run_once()
        self.now+=31
        hook=self.repo/'.git/hooks/pre-commit'
        hook.write_text('#!/bin/sh\necho intentional commit failure >&2\nexit 1\n')
        hook.chmod(0o755)
        (self.repo/'unrelated.txt').write_text('unfinished user text')
        before=self.git('rev-parse','HEAD')
        with self.assertRaisesRegex(WatchError,'commit'):
            self.watcher.run_once()
        self.assertEqual(self.git('rev-parse','HEAD'),before)
        self.assertEqual((self.repo/MANIFEST).read_bytes(),self.old_manifest)
        self.assertEqual((self.repo/'unrelated.txt').read_text(),'unfinished user text')
        self.assertEqual(self.git('diff','--cached','--name-only'),'')
        self.assertIsNone(self.watcher.state['pending'])

    def test_crash_before_commit_clears_only_owned_staging(self):
        self.source()
        self.watcher.run_once()
        self.now+=31
        actual_git=self.watcher.git
        def crash_after_add(*args):
            result=actual_git(*args)
            if args[0]=='add':raise KeyboardInterrupt('simulated interruption after staging')
            return result
        with patch.object(self.watcher,'git',side_effect=crash_after_add):
            with self.assertRaises(KeyboardInterrupt):self.watcher.run_once()
        (self.repo/'unrelated.txt').write_text('staged after interruption')
        self.git('add','unrelated.txt')
        restored=self.make_watcher()
        restored.run_once()
        self.assertEqual(self.git('diff','--cached','--name-only'),'unrelated.txt')
        self.assertEqual((self.repo/MANIFEST).read_bytes(),self.old_manifest)
        self.assertIsNone(restored.state['pending'])

    def test_pipeline_failure_and_concurrent_stage_leave_active_manifest(self):
        self.source()
        self.watcher.run_once()
        self.now+=31
        (self.repo/'.fail_prepare').touch()
        with self.assertRaisesRegex(WatchError,'영상을 준비하지'):
            self.watcher.run_once()
        self.assertEqual((self.repo/MANIFEST).read_bytes(),self.old_manifest)
        self.assertFalse(self.watcher.state['processed'])
        (self.repo/'.fail_prepare').unlink()
        self.now+=601
        (self.repo/'.stage_during_prepare').touch()
        (self.repo/'unrelated.txt').write_text('concurrent work')
        with self.assertRaisesRegex(WatchError,'스테이징'):
            self.watcher.run_once()
        self.assertEqual((self.repo/MANIFEST).read_bytes(),self.old_manifest)
        self.assertEqual(self.git('diff','--cached','--name-only'),'unrelated.txt')
        self.assertFalse(self.watcher.state['pending'])

    def test_unsafe_generated_path_never_activates_or_stages(self):
        self.source()
        (self.repo/'.unsafe_manifest').touch()
        self.watcher.run_once()
        self.now+=31
        with self.assertRaisesRegex(WatchError,'허용되지 않은'):
            self.watcher.run_once()
        self.assertEqual((self.repo/MANIFEST).read_bytes(),self.old_manifest)
        self.assertFalse(self.git('diff','--cached','--name-only'))

    def test_release_manifest_must_match_before_staging(self):
        self.source()
        (self.repo/'.bad_release_manifest').touch()
        self.watcher.run_once()
        self.now+=31
        with self.assertRaisesRegex(WatchError,'영상 폴더의 설정'):
            self.watcher.run_once()
        self.assertEqual((self.repo/MANIFEST).read_bytes(),self.old_manifest)
        self.assertFalse(self.git('diff','--cached','--name-only'))

    def test_push_failure_retries_same_commit_before_new_source(self):
        source=self.source()
        hook=self.remote/'hooks/pre-receive'
        hook.write_text('#!/bin/sh\nif test -f "$(dirname "$0")/../reject"; then echo rejected >&2; exit 1; fi\n')
        hook.chmod(0o755)
        reject=self.remote/'reject'
        reject.touch()
        remote_before=self.remote_head()
        self.watcher.run_once()
        self.now+=31
        with self.assertRaisesRegex(WatchError,'push'):
            self.watcher.run_once()
        pending_commit=self.git('rev-parse','HEAD')
        self.assertNotEqual(pending_commit,remote_before)
        self.assertEqual(self.remote_head(),remote_before)
        self.assertFalse(self.watcher.state['processed'])
        self.assertEqual(self.watcher.state['pending']['commit'],pending_commit)
        self.source('next.mov',b'next source must wait')
        reject.unlink()
        self.watcher=self.make_watcher()
        self.assertEqual(self.watcher.run_once()['action'],'pending_checked')
        self.assertEqual(self.remote_head(),pending_commit)
        self.assertIn(digest(source),self.watcher.state['processed'])
        self.assertEqual(len(self.watcher.state['processed']),1)
        self.assertIsNone(self.watcher.state['pending'])

    def test_crash_after_commit_is_recovered_without_duplicate_commit(self):
        self.source()
        self.watcher.run_once()
        self.now+=31
        actual_git=self.watcher.git
        def crash_after_commit(*args):
            result=actual_git(*args)
            if args[0]=='commit':raise KeyboardInterrupt('simulated process interruption')
            return result
        with patch.object(self.watcher,'git',side_effect=crash_after_commit):
            with self.assertRaises(KeyboardInterrupt):self.watcher.run_once()
        committed=self.git('rev-parse','HEAD')
        restored=self.make_watcher()
        self.assertIsNone(restored.state['pending']['commit'])
        restored.run_once()
        self.assertEqual(self.remote_head(),committed)
        self.assertEqual(self.git('rev-parse','HEAD'),committed)
        self.assertIsNone(restored.state['pending'])

    def test_mark_published_seeds_current_source_after_remote_success(self):
        source=self.source()
        self.settle()
        fresh=Watcher(self.repo,self.inbox,self.base/'fresh-state',sys.executable,now=lambda:self.now)
        fresh.mark_published(source)
        self.assertIn(digest(source),fresh.state['processed'])
        self.assertEqual(fresh.state['lastPublished']['commit'],self.remote_head())
        other=self.source('different.mov',b'different')
        with self.assertRaisesRegex(WatchError,'일치하지'):
            fresh.mark_published(other)

    def test_dry_run_does_not_create_state_or_encode(self):
        self.source()
        result=self.watcher.run_once(dry_run=True)
        self.assertEqual(result['ready'],[])
        self.assertFalse(self.state_dir.exists())
        self.assertEqual((self.repo/MANIFEST).read_bytes(),self.old_manifest)

    def test_installer_is_idempotent_and_does_not_copy_secrets(self):
        calls=[]
        loaded=False
        def launchctl(args,**kwargs):
            nonlocal loaded
            calls.append(args)
            code=0
            if args[1]=='print':code=0 if loaded else 1
            elif args[1]=='bootstrap':loaded=True
            elif args[1]=='bootout':loaded=False
            return subprocess.CompletedProcess(args,code,stdout='',stderr='')
        with patch.dict(os.environ,{'PRIVATE_SECRET_TEST':'must not enter plist'}),patch('install_weekly_video_watch.sys.platform','darwin'):
            first=install(self.repo,self.inbox,self.state_dir,Path(sys.executable),home=self.base/'fake-home',run=launchctl)
            before=Path(first['launchAgent']).read_bytes()
            second=install(self.repo,self.inbox,self.state_dir,Path(sys.executable),home=self.base/'fake-home',run=launchctl)
            self.assertEqual(Path(second['launchAgent']).read_bytes(),before)
            self.assertNotIn(b'PRIVATE_SECRET_TEST',before)
            self.assertEqual(sum(call[1]=='bootstrap' for call in calls),1)
            self.assertFalse(any(call[1]=='bootout' for call in calls))
            self.assertEqual(sum(call[1]=='kickstart' for call in calls),2)
            self.assertEqual(second['intervalSeconds'],120)


if __name__=='__main__':
    unittest.main()
