#!/usr/bin/env python3
"""Prepare and publish stable videos from a dedicated local inbox."""
from __future__ import annotations

import argparse
import base64
from contextlib import contextmanager
from datetime import datetime, timedelta
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import tempfile
import time
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INBOX = Path.home() / "Documents" / "Eggtrace 영상함"
DEFAULT_STATE = Path.home() / "Library" / "Application Support" / "EggtraceWeekly"
MANIFEST = "configs/weekly_video.json"
EXTENSIONS = {".mp4", ".mov", ".m4v"}
VERSION = re.compile(r"^\d{4}-\d{2}-\d{2}-[a-f0-9]{12}$")
KST = ZoneInfo("Asia/Seoul")


class WatchError(RuntimeError):
    pass


class PreparationError(WatchError):
    pass


def atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix="." + path.name, dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def fingerprint(path: Path) -> dict:
    stat = path.stat()
    return {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns}


def week_monday(timestamp: float) -> str:
    today = datetime.fromtimestamp(timestamp, KST).date()
    return (today - timedelta(days=today.weekday())).isoformat()


def safe_error(value: str) -> str:
    return re.sub(r"(https?://)[^/@\s]+@", r"\1[hidden]@", value.strip())[-1200:]


class Watcher:
    def __init__(self, repo=ROOT, inbox=DEFAULT_INBOX, state_dir=DEFAULT_STATE,
                 python=None, stable_seconds=30, now=time.time, week=None):
        self.repo = Path(repo).resolve()
        self.inbox = Path(inbox).expanduser().absolute()
        self.state_dir = Path(state_dir).expanduser().absolute()
        self.python = str(Path(python or self.repo / ".venv/bin/python").absolute())
        self.stable_seconds = stable_seconds
        self.now = now
        self.week = week
        self.state_path = self.state_dir / "state.json"
        self.manifest_path = self.repo / MANIFEST
        self.state = self.load_state()

    def load_state(self):
        if not self.state_path.exists():
            return {"schemaVersion": 1, "candidates": {}, "processed": {}, "pending": None}
        try:
            state = json.loads(self.state_path.read_text())
            if state.get("schemaVersion") != 1 or not isinstance(state.get("processed"), dict):
                raise ValueError("unknown state format")
            return state
        except (ValueError, OSError) as error:
            raise WatchError("상태 파일을 읽지 못했어요. 파일을 지우지 말고 확인해 주세요.") from error

    def save(self):
        atomic_write(self.state_path, (json.dumps(self.state, ensure_ascii=False, indent=2) + "\n").encode())

    def log(self, message):
        self.state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        path = self.state_dir / "watch.log"
        if path.exists() and path.stat().st_size > 1024 * 1024:
            path.replace(self.state_dir / "watch.previous.log")
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        stamp = datetime.fromtimestamp(self.now(), KST).isoformat(timespec="seconds")
        with os.fdopen(fd, "a") as stream:
            stream.write(f"{stamp} {message}\n")
        print(message, flush=True)

    @contextmanager
    def lock(self):
        self.state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(self.state_dir / "watch.lock", os.O_CREAT | os.O_RDWR, 0o600)
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                yield False
            else:
                yield True
        finally:
            os.close(fd)

    def git(self, *args):
        result = subprocess.run(["git", *args], cwd=self.repo, capture_output=True,
                                text=True, timeout=120,
                                env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
        if result.returncode:
            raise WatchError(f"Git {args[0]} 작업을 끝내지 못했어요: {safe_error(result.stderr)}")
        return result.stdout.strip()

    def head(self):
        return self.git("rev-parse", "HEAD")

    def remote_head(self):
        lines = self.git("ls-remote", "--exit-code", "origin", "refs/heads/main").splitlines()
        if len(lines) != 1:
            raise WatchError("원격 main을 확인하지 못했어요.")
        return lines[0].split()[0]

    def staged(self):
        output = self.git("diff", "--cached", "--name-only", "-z")
        return set(output.split("\0")) - {""}

    def preflight(self, *, manifest_clean=True, expected_head=None):
        if self.git("branch", "--show-current") != "main":
            raise WatchError("main 브랜치가 아니어서 자동 게시를 멈췄어요.")
        if self.staged():
            raise WatchError("스테이징한 변경이 있어 자동 게시를 멈췄어요. 기존 작업을 확인해 주세요.")
        head = self.head()
        if expected_head and head != expected_head:
            raise WatchError("준비하는 동안 main이 바뀌어 자동 게시를 멈췄어요.")
        if head != self.remote_head():
            raise WatchError("로컬 main과 원격 main이 달라 자동 게시를 멈췄어요. 자동으로 pull하지 않아요.")
        if manifest_clean and self.git("status", "--porcelain", "--", MANIFEST):
            raise WatchError("주간 영상 설정에 저장하지 않은 변경이 있어 자동 게시를 멈췄어요.")
        return head

    def candidates(self):
        if not self.inbox.exists():
            return []
        current = {}
        ready = []
        for path in sorted(self.inbox.iterdir(), key=lambda p: p.name.casefold()):
            if path.is_symlink() or not path.is_file() or path.suffix.lower() not in EXTENSIONS:
                continue
            info = fingerprint(path)
            previous = self.state.get("candidates", {}).get(path.name, {})
            same = all(previous.get(key) == value for key, value in info.items())
            entry = previous if same else {**info, "seenAt": self.now()}
            current[path.name] = entry
            old_enough = self.now() - info["mtime_ns"] / 1e9 >= self.stable_seconds
            observed_stable = same and self.now() - entry["seenAt"] >= self.stable_seconds
            if info["size"] > 0 and old_enough and observed_stable and self.now() >= entry.get("retryAfter", 0):
                ready.append(path)
        self.state["candidates"] = current
        return sorted(ready, key=lambda p: (p.stat().st_mtime_ns, p.name.casefold()))

    def bundle_paths(self, manifest, source_hash, week):
        version = manifest.get("version", "")
        if not isinstance(version, str) or not VERSION.fullmatch(version) or not version.startswith(week + "-"):
            raise WatchError("새 영상 폴더 이름을 확인하지 못했어요.")
        if manifest.get("schemaVersion") != 1 or manifest.get("sourceSha256") != source_hash or manifest.get("week") != week:
            raise WatchError("새 영상과 주간 영상 설정이 일치하지 않아요.")
        root = self.repo / "static/weekly" / version
        if root.is_symlink() or not root.is_dir() or not root.resolve().is_relative_to(self.repo):
            raise WatchError("새 영상 폴더를 확인하지 못했어요.")
        release_manifest = root / "manifest.json"
        try:
            if release_manifest.is_symlink() or json.loads(release_manifest.read_text()) != manifest:
                raise ValueError("release metadata mismatch")
        except (OSError, ValueError) as error:
            raise WatchError("영상 폴더의 설정과 게시할 설정이 일치하지 않아요.") from error
        try:
            videos, posters, moments = manifest["videos"], manifest["posters"], manifest["moments"]
            modes = {"farm", "activity", "density", "pattern"}
            if set(videos) != modes or set(posters) != modes or len(moments) != 3:
                raise ValueError("incomplete media")
            urls = [manifest["analysisUrl"], *videos.values(), *posters.values(), *[item["url"] for item in moments]]
        except (KeyError, TypeError, ValueError) as error:
            raise WatchError("새 영상 구성에 빠진 파일이 있어요.") from error
        paths = {MANIFEST, release_manifest.relative_to(self.repo).as_posix()}
        prefix = f"/weekly/{version}/"
        for url in urls:
            if not isinstance(url, str) or not url.startswith(prefix) or any(c in url for c in ("%", "?", "#", "\\")):
                raise WatchError("게시할 영상 파일 경로가 올바르지 않아요.")
            relative = PurePosixPath(url[len(prefix):])
            if relative.is_absolute() or ".." in relative.parts or relative.suffix not in {".mp4", ".webp", ".json"}:
                raise WatchError("허용되지 않은 게시 파일이 있어요.")
            path = root.joinpath(*relative.parts)
            if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root.resolve()):
                raise WatchError("게시할 영상 파일을 확인하지 못했어요.")
            paths.add(path.relative_to(self.repo).as_posix())
        return version, sorted(paths)

    def rollback_manifest(self, before, generated_hash):
        current = self.manifest_path.read_bytes() if self.manifest_path.exists() else None
        if current == before:
            return
        if current is not None and hashlib.sha256(current).hexdigest() == generated_hash:
            if before is None:
                self.manifest_path.unlink()
            else:
                atomic_write(self.manifest_path, before)
        elif self.manifest_path.exists():
            raise WatchError("영상 설정이 다른 작업에서 바뀌었어요. 덮어쓰지 않고 멈췄어요.")

    def finish(self, pending):
        self.state["processed"][pending["sourceSha256"]] = {
            "week": pending["week"], "version": pending["version"],
            "commit": pending["commit"], "publishedAt": self.now(),
        }
        self.state["lastPublished"] = self.state["processed"][pending["sourceSha256"]]
        self.state["pending"] = None
        self.state.pop("lastError", None)
        self.save()
        self.log(f"게시 완료: {pending['week']} / {pending['version']}")

    def retry_pending(self):
        pending = self.state["pending"]
        head = self.head()
        if not pending.get("commit"):
            if head != pending["beforeHead"]:
                changed = set(self.git("diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD", "-z").split("\0")) - {""}
                if (self.git("rev-parse", "HEAD^") != pending["beforeHead"]
                    or self.git("log", "-1", "--format=%B") != pending["message"]
                    or not changed <= set(pending["paths"])):
                    raise WatchError("게시 준비 뒤 다른 커밋이 생겼어요. 기존 작업을 확인해 주세요.")
                pending["commit"] = head
                self.save()
            else:
                own_staged = self.staged() & set(pending["paths"])
                if own_staged:
                    self.git("restore", "--staged", "--source=HEAD", "--", *sorted(own_staged))
                before = base64.b64decode(pending["beforeManifest"]) if pending["beforeManifest"] is not None else None
                self.rollback_manifest(before, pending["generatedHash"])
                self.state["pending"] = None
                self.save()
                return
        if self.git("branch", "--show-current") != "main" or self.head() != pending["commit"]:
            raise WatchError("대기 중인 게시 커밋 뒤에 다른 작업이 있어 자동 push를 멈췄어요.")
        changed = set(self.git("diff-tree", "--no-commit-id", "--name-only", "-r", pending["commit"], "-z").split("\0")) - {""}
        if (self.git("rev-parse", pending["commit"] + "^") != pending["beforeHead"]
            or self.git("log", "-1", "--format=%B", pending["commit"]) != pending["message"]
            or not changed or not changed <= set(pending["paths"])):
            raise WatchError("대기 중인 커밋에 게시 대상 외의 변경이 있어 자동 push를 멈췄어요.")
        if self.staged():
            raise WatchError("스테이징한 변경이 있어 대기 중인 push를 멈췄어요.")
        remote = self.remote_head()
        if remote == pending["commit"]:
            self.finish(pending)
            return
        if remote != pending["beforeHead"]:
            raise WatchError("원격 main이 바뀌어 대기 중인 push를 멈췄어요. 자동으로 합치지 않아요.")
        self.git("push", "origin", f"{pending['commit']}:refs/heads/main")
        self.finish(pending)

    def prepare_and_publish(self, source, source_hash):
        before_head = self.preflight()
        before = self.manifest_path.read_bytes() if self.manifest_path.exists() else None
        source_info = fingerprint(source)
        week = self.week or week_monday(self.now())
        generated_hash = None
        candidate = self.state_dir / f"candidate-{os.getpid()}-{time.time_ns()}.json"
        try:
            result = subprocess.run([
                self.python, str(self.repo / "tools/prepare_weekly_video.py"),
                "--input", str(source), "--week", week,
                "--output-root", str(self.repo / "static/weekly"),
                "--manifest", str(candidate), "--json",
            ], cwd=self.repo, text=True, capture_output=True, timeout=1800)
            if result.returncode:
                raise PreparationError("영상을 준비하지 못했어요: " + safe_error(result.stderr))
            generated = candidate.read_bytes()
            manifest = json.loads(generated)
            version, paths = self.bundle_paths(manifest, source_hash, week)
            if fingerprint(source) != source_info:
                raise WatchError("준비하는 동안 원본 영상이 바뀌었어요. 복사가 끝나면 다시 확인할게요.")
            self.preflight(expected_head=before_head)
            generated_hash = hashlib.sha256(generated).hexdigest()
            pending = {
                "sourceSha256": source_hash, "sourceName": source.name, "week": week,
                "version": version, "paths": paths, "beforeHead": before_head,
                "beforeManifest": base64.b64encode(before).decode() if before is not None else None,
                "generatedHash": generated_hash, "commit": None,
                "message": f"Update weekly farm video: {week} {source_hash[:12]}",
            }
            self.state["pending"] = pending
            self.save()
            atomic_write(self.manifest_path, generated)
            self.git("add", "-f", "--", *paths)
            changed = self.staged()
            if not changed <= set(paths):
                raise WatchError("다른 파일이 스테이징되어 자동 커밋을 멈췄어요.")
            if not changed:
                pending["commit"] = before_head
                self.finish(pending)
                return
            self.git("commit", "--only", "-m", pending["message"], "--", *paths)
            pending["commit"] = self.head()
            self.save()
            if self.git("rev-parse", "HEAD^") != before_head:
                raise WatchError("준비 중 main이 바뀌어 자동 push를 멈췄어요.")
            self.retry_pending()
        except Exception:
            pending = self.state.get("pending")
            if pending and pending.get("commit"):
                raise
            if pending:
                # This also recovers a commit made immediately before a process interruption.
                if self.head() != pending["beforeHead"]:
                    raise
                own_staged = self.staged() & set(pending["paths"])
                if own_staged:
                    self.git("restore", "--staged", "--source=HEAD", "--", *sorted(own_staged))
                self.state["pending"] = None
            if generated_hash:
                self.rollback_manifest(before, generated_hash)
            self.save()
            raise
        finally:
            candidate.unlink(missing_ok=True)

    def mark_published(self, source):
        head = self.preflight()
        manifest = json.loads(self.manifest_path.read_text())
        source_hash = digest(source)
        version, _ = self.bundle_paths(manifest, source_hash, manifest.get("week", ""))
        self.finish({"sourceSha256": source_hash, "week": manifest["week"], "version": version, "commit": head})

    def run_once(self, *, dry_run=False):
        if self.state.get("pending"):
            if dry_run:
                return {"pendingCommit": self.state["pending"].get("commit"), "action": "retry_push_first"}
            self.retry_pending()
            return {"action": "pending_checked"}
        ready = self.candidates()
        if dry_run:
            return {"inbox": str(self.inbox), "ready": [p.name for p in ready],
                    "waiting": [name for name in self.state["candidates"] if name not in {p.name for p in ready}]}
        self.save()
        for source in ready:
            entry = self.state["candidates"][source.name]
            source_hash = entry.get("sha256") or digest(source)
            if fingerprint(source) != {key: entry[key] for key in ("size", "mtime_ns")}:
                continue
            entry["sha256"] = source_hash
            if source_hash in self.state["processed"]:
                self.save()
                continue
            self.log(f"새 영상 준비: {source.name}")
            try:
                self.prepare_and_publish(source, source_hash)
            except Exception as error:
                if isinstance(error, (PreparationError, subprocess.TimeoutExpired)):
                    entry["retryAfter"] = self.now() + 600
                self.save()
                raise
            return {"action": "published", "source": source.name}
        return {"action": "waiting", "files": len(self.state["candidates"])}


def main(argv=None):
    parser = argparse.ArgumentParser(description="영상함의 새 영상을 확인하고 안전하게 게시해요.")
    parser.add_argument("--repo", type=Path, default=ROOT)
    parser.add_argument("--inbox", type=Path, default=DEFAULT_INBOX)
    parser.add_argument("--state-dir", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--python", type=Path)
    parser.add_argument("--week", help="직접 지정할 주의 월요일 YYYY-MM-DD")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--once", action="store_true", help="한 번 확인하고 종료")
    modes.add_argument("--status", action="store_true", help="상태 확인")
    modes.add_argument("--dry-run", action="store_true", help="파일 변경 없이 대기열 확인")
    modes.add_argument("--mark-published", type=Path, metavar="FILE", help="현재 게시한 원본을 중복 방지 목록에 등록")
    args = parser.parse_args(argv)
    if args.week:
        try:
            day = datetime.strptime(args.week, "%Y-%m-%d").date()
            if day.weekday() != 0:
                raise ValueError()
        except ValueError:
            parser.error("--week에는 월요일 날짜를 YYYY-MM-DD로 적어 주세요.")
    watcher = None
    try:
        watcher = Watcher(args.repo, args.inbox, args.state_dir, args.python, week=args.week)
        if args.status:
            pending = watcher.state.get("pending")
            pending_summary = {key: pending.get(key) for key in ("commit", "week", "version", "sourceName")} if pending else None
            result = {"inbox": str(watcher.inbox), "processedCount": len(watcher.state["processed"]),
                      "pending": pending_summary, "lastPublished": watcher.state.get("lastPublished"),
                      "lastError": watcher.state.get("lastError")}
        elif args.dry_run:
            result = watcher.run_once(dry_run=True)
        else:
            with watcher.lock() as acquired:
                if not acquired:
                    print("이미 영상을 확인하고 있어요.")
                    return 0
                # Re-read after acquiring the lock; another run may have finished in the meantime.
                watcher.state = watcher.load_state()
                if args.mark_published:
                    watcher.mark_published(args.mark_published)
                    result = {"action": "marked_published"}
                else:
                    result = watcher.run_once()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (WatchError, OSError, ValueError, subprocess.SubprocessError) as error:
        message = safe_error(str(error))
        if watcher and not args.dry_run and not args.status:
            watcher.state["lastError"] = {"message": message, "at": watcher.now()}
            watcher.save()
            watcher.log(message)
        else:
            print(message, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
