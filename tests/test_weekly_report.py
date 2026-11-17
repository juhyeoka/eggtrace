"""A weekly release must switch all report media together and fail closed."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from backend import report_page


class WeeklyReportTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.weekly = self.root / 'weekly'
        self.version = '2026-11-16-123456abcdef'
        self.release = self.weekly / self.version
        self.release.mkdir(parents=True)
        self.manifest_path = self.root / 'current.json'
        self.context_path = self.root / 'context.json'
        self.url = f'/weekly/{self.version}'
        self.manifest = {
            'schemaVersion': 1, 'version': self.version, 'week': '2026-11-16',
            'createdAt': '2026-11-15T15:30:00Z', 'width': 540, 'height': 960, 'duration': 2.0,
            'analysisUrl': f'{self.url}/analysis.json',
            'videos': {mode: f'{self.url}/{mode}.mp4' for mode in report_page.VIDEO_MODES},
            'posters': {mode: f'{self.url}/{mode}.webp' for mode in report_page.VIDEO_MODES},
            'moments': [{'time': time, 'url': f'{self.url}/moment-{index}.webp'} for index, time in enumerate((0.25, 1.0, 1.75), 1)],
        }
        for group in ('videos', 'posters'):
            for url in self.manifest[group].values():
                (self.release / Path(url).name).write_bytes(b'prepared asset')
        for moment in self.manifest['moments']:
            (self.release / Path(moment['url']).name).write_bytes(b'prepared poster')
        self.analysis = {
            'duration': 2.0, 'sampleInterval': 0.5,
            'frames': [
                {'t': 0, 'motionPercent': 0, 'zones': [0] * 9, 'measured': False},
                {'t': 0.5, 'motionPercent': 4, 'zones': [1] * 9, 'measured': True},
                {'t': 1.0, 'motionPercent': 2, 'zones': [1] * 9, 'measured': True},
            ],
            'summary': {'averageMotionPercent': 3, 'peakMotionPercent': 4, 'peakTime': 0.5, 'activeZoneLabel': '중앙'},
        }
        self.write_analysis()
        self.write_manifest()
        self.patch = patch.multiple(report_page, WEEKLY_DIR=self.weekly, WEEKLY_MANIFEST_FILE=self.manifest_path, VIDEO_CONTEXT_FILE=self.context_path)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def write_analysis(self):
        (self.release / 'analysis.json').write_text(json.dumps(self.analysis), encoding='utf-8')

    def write_manifest(self):
        self.manifest_path.write_text(json.dumps(self.manifest), encoding='utf-8')

    def test_complete_portrait_release_replaces_all_initial_urls_and_moments(self):
        data = report_page.build_report_data('EGG-0001')
        self.assertEqual(data['videoUrl'], self.manifest['videos']['farm'])
        page = report_page.render_report('EGG-0001', {})
        self.assertIn('540 / 960', page)
        self.assertIn(self.manifest['videos']['farm'], page)
        self.assertIn(self.manifest['posters']['farm'], page)
        self.assertIn('data-seek="1.75"', page)
        self.assertIn('11월 16일 업데이트', page)
        self.assertNotIn('jcr-farm-web-20261105.mp4', page)
        self.assertNotIn('data-seek="17"', page)

    def test_missing_one_annotation_falls_back_as_one_bundle(self):
        (self.release / 'density.mp4').unlink()
        self.assertIsNone(report_page._weekly_video('EGG-0001'))
        page = report_page.render_report('EGG-0001', {})
        self.assertIn('/videos/jcr-farm-web-20261105.mp4', page)
        self.assertNotIn(self.url, page)
        self.assertIn('data-seek="17"', page)

    def test_invalid_urls_and_symlinked_releases_are_rejected(self):
        original = deepcopy(self.manifest)
        for invalid in ('https://other.invalid/a.mp4', f'{self.url}/../outside.mp4', f'{self.url}/%2e%2e/a.mp4'):
            self.manifest = deepcopy(original)
            self.manifest['videos']['farm'] = invalid
            self.write_manifest()
            self.assertIsNone(report_page._weekly_video('EGG-0001'))
        self.manifest = original
        self.write_manifest()
        outside = self.root / 'outside'
        self.release.rename(outside)
        self.release.symlink_to(outside, target_is_directory=True)
        self.assertIsNone(report_page._weekly_video('EGG-0001'))

    def test_corrupted_or_inconsistent_analysis_does_not_activate(self):
        original = deepcopy(self.analysis)
        for invalid in (99, -1, float('nan')):
            self.analysis = deepcopy(original)
            self.analysis['summary']['peakTime'] = invalid
            self.write_analysis()
            self.assertIsNone(report_page._weekly_video('EGG-0001'))
        self.analysis = deepcopy(original)
        self.analysis['frames'][0]['t'] = -0.5
        self.write_analysis()
        self.assertIsNone(report_page._weekly_video('EGG-0001'))
        self.analysis = deepcopy(original)
        self.analysis['duration'] = 3
        self.write_analysis()
        self.assertIsNone(report_page._weekly_video('EGG-0001'))

    def test_other_products_and_private_candidate_do_not_activate(self):
        self.assertIsNone(report_page._weekly_video('EGG-OTHER'))
        self.manifest_path.rename(self.root / 'candidate.json')
        self.assertIsNone(report_page._weekly_video('EGG-0001'))

    def test_numeric_duration_is_normalized_before_rendering(self):
        self.manifest['duration'] = '2.0'
        self.write_manifest()
        self.assertIn('2초 영상', report_page.render_report('EGG-0001', {}))

    def test_full_source_media_uses_a_wide_player_without_padding(self):
        page = report_page.render_report('EGG-0001', {})
        self.assertIn('class="video-frame"', page)
        self.assertIn('style="--video-aspect:16 / 9"', page)
        self.assertNotIn('video-backdrop', page)
        self.assertNotIn('video-viewing-tip', page)
        self.assertIn(self.manifest['videos']['farm'], page)
        self.assertNotIn('is-portrait', page)

    def test_farm_notice_applies_only_to_the_video_it_describes(self):
        self.manifest['sourceSha256'] = 'a' * 64
        self.write_manifest()
        self.context_path.write_text(json.dumps({
            'source_sha256': 'a' * 64,
            'indoor_notice': {'heading': '이 영상의 안내', 'body': '농장에서 확인한 이번 영상의 사육 이유'},
        }))
        page = report_page.render_report('EGG-0001', {})
        self.assertIn('농장에서 확인한 이번 영상의 사육 이유', page)
        self.manifest['sourceSha256'] = 'b' * 64
        self.write_manifest()
        page = report_page.render_report('EGG-0001', {})
        self.assertNotIn('농장에서 확인한 이번 영상의 사육 이유', page)
        self.assertIn('실내에서 지내기도 하나요?', page)

    def test_unbound_or_malformed_notice_keeps_general_guidance(self):
        for context in ({'indoor_notice': {'heading': '실내 단정', 'body': '이 영상에 적용하면 안 되는 설명'}}, ['wrong format']):
            self.context_path.write_text(json.dumps(context))
            page = report_page.render_report('EGG-0001', {})
            self.assertNotIn('이 영상에 적용하면 안 되는 설명', page)
            self.assertIn('실내에서 지내기도 하나요?', page)


if __name__ == '__main__':
    unittest.main()
