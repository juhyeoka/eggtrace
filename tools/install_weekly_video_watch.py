#!/usr/bin/env python3
"""Install the user LaunchAgent which checks the dedicated video inbox."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import plistlib
import subprocess
import sys

from watch_weekly_videos import DEFAULT_INBOX, DEFAULT_STATE, ROOT, atomic_write

LABEL = "com.i4company.eggtrace.weeklyvideo"


def launch_agent(repo: Path, inbox: Path, state_dir: Path, python: Path) -> dict:
    return {
        "Label": LABEL,
        "ProgramArguments": [str(python), str(repo / "tools/watch_weekly_videos.py"),
                             "--repo", str(repo), "--inbox", str(inbox),
                             "--state-dir", str(state_dir), "--python", str(python), "--once"],
        "WorkingDirectory": str(repo),
        "RunAtLoad": True,
        "StartInterval": 120,
        "ProcessType": "Background",
        "EnvironmentVariables": {"PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"},
        "StandardOutPath": str(state_dir / "launch.stdout.log"),
        "StandardErrorPath": str(state_dir / "launch.stderr.log"),
    }


def install(repo, inbox, state_dir, python, *, dry_run=False, home=None, run=subprocess.run):
    repo, inbox, state_dir = [Path(value).expanduser().absolute() for value in (repo, inbox, state_dir)]
    python = Path(python or repo / ".venv/bin/python").expanduser().absolute()
    if not python.is_file() or not os.access(python, os.X_OK):
        raise RuntimeError(f"프로젝트 Python을 확인해 주세요: {python}")
    if not (repo / "tools/watch_weekly_videos.py").is_file() or not (repo / "tools/prepare_weekly_video.py").is_file():
        raise RuntimeError("주간 영상 준비·감시 스크립트를 먼저 설치해 주세요.")
    agent = launch_agent(repo, inbox, state_dir, python)
    if dry_run:
        return {"action": "dry_run", "launchAgent": agent}
    if sys.platform != "darwin":
        raise RuntimeError("이 자동 실행 설치는 macOS에서 사용할 수 있어요.")
    inbox.mkdir(parents=True, exist_ok=True)
    state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    for name in ("launch.stdout.log", "launch.stderr.log"):
        fd = os.open(state_dir / name, os.O_CREAT | os.O_WRONLY | os.O_APPEND, 0o600)
        os.close(fd)
    agent_path = Path(home or Path.home()) / "Library/LaunchAgents" / f"{LABEL}.plist"
    contents = plistlib.dumps(agent, sort_keys=False)
    changed = not agent_path.exists() or agent_path.read_bytes() != contents
    target = f"gui/{os.getuid()}/{LABEL}"
    loaded = run(["launchctl", "print", target], capture_output=True, text=True).returncode == 0
    if changed:
        atomic_write(agent_path, contents)
        if loaded:
            result = run(["launchctl", "bootout", target], capture_output=True, text=True)
            if result.returncode:
                raise RuntimeError("기존 자동 실행을 갱신하지 못했어요: " + result.stderr.strip())
            loaded = False
    if not loaded:
        result = run(["launchctl", "bootstrap", f"gui/{os.getuid()}", str(agent_path)], capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError("자동 실행을 등록하지 못했어요: " + result.stderr.strip())
    result = run(["launchctl", "kickstart", target], capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError("자동 실행을 시작하지 못했어요: " + result.stderr.strip())
    return {"action": "installed", "inbox": str(inbox), "intervalSeconds": 120,
            "launchAgent": str(agent_path), "stateDirectory": str(state_dir)}


def main(argv=None):
    parser = argparse.ArgumentParser(description="영상함 자동 확인을 이 Mac의 로그인 계정에 등록해요.")
    parser.add_argument("--repo", type=Path, default=ROOT)
    parser.add_argument("--inbox", type=Path, default=DEFAULT_INBOX)
    parser.add_argument("--state-dir", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--python", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    try:
        print(json.dumps(install(args.repo, args.inbox, args.state_dir, args.python, dry_run=args.dry_run), ensure_ascii=False, indent=2))
        return 0
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
