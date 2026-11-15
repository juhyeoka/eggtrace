# 매주 농장 영상 올리기

이 Mac의 `문서 > Eggtrace 영상함`에 새 `mp4`, `mov`, `m4v` 파일을 넣으면 됩니다. 원본은 이동하거나 지우지 않아요. 폴더 안의 하위 폴더는 확인하지 않습니다.

자동 확인은 2분마다 실행됩니다. 파일 크기와 수정 시간이 두 번 연속 같고 30초 이상 지나면 새 영상을 준비합니다. 이미 게시한 영상과 내용이 같으면 다시 올리지 않아요. 여러 파일을 넣으면 한 번에 하나씩 처리합니다.

영상은 처리한 주의 월요일 날짜로 묶이고 홈페이지용 영상은 최대 30초로 준비해요. 화면용 영상·움직임 표시·분석 자료를 모두 만든 뒤 사이트 설정을 바꾸고 GitHub `main`에 게시합니다. 이후 Render 자동 배포가 끝나면 사이트가 바뀝니다. 준비에 실패하면 기존 영상이 계속 보입니다. 파일 자체의 준비가 실패하면 해당 파일은 10분 뒤에 다시 시도해요.

**이 Mac이 켜져 있고 해당 사용자로 로그인되어 있어야 하며 인터넷 연결이 필요합니다.** 잠자기나 전원 꺼짐 중에는 처리하지 못하고, 다시 실행 가능한 상태가 되면 확인합니다. GitHub 인증은 이 Mac에 설정된 기존 로그인을 사용하며 로그인 정보는 자동 실행 파일에 저장하지 않아요.

## 상태 확인

프로젝트 폴더에서 다음 명령을 실행합니다.

```sh
.venv/bin/python tools/watch_weekly_videos.py --status
.venv/bin/python tools/watch_weekly_videos.py --dry-run
```

로그와 처리 기록은 `~/Library/Application Support/EggtraceWeekly`에 있습니다. `watch.log`에서 마지막 게시 결과나 실패 이유를 볼 수 있어요.

로컬 `main`과 원격 `main`이 다르거나 스테이징한 변경이 있으면 자동 게시를 멈춥니다. 기존 작업을 확인한 뒤 다시 실행하면 됩니다. 자동으로 pull·rebase·stash하거나 다른 작업 파일을 커밋하지 않아요. push가 실패하면 그 커밋을 먼저 다시 보내고 다음 영상을 확인합니다.

## 설치와 첫 영상 등록

프로젝트 코드와 첫 영상이 먼저 GitHub에 게시된 뒤 실행합니다.

```sh
.venv/bin/python tools/install_weekly_video_watch.py --dry-run
.venv/bin/python tools/install_weekly_video_watch.py
```

첫 영상을 수동으로 이미 올렸다면 원본을 중복 방지 목록에 등록할 수 있어요. 현재 게시 설정의 원본 해시와 일치하고 원격 `main`까지 게시된 경우만 등록됩니다.

```sh
.venv/bin/python tools/watch_weekly_videos.py --mark-published '/원본/영상.mp4'
```

과거 주를 직접 처리할 때는 `--week YYYY-MM-DD`에 해당 주의 월요일을 지정합니다. 자동 실행에는 이 옵션을 넣지 않습니다.

자동 실행을 멈추려면 다음 명령을 사용합니다. 원본과 게시된 영상은 삭제하지 않아요.

```sh
launchctl bootout "gui/$(id -u)/com.i4company.eggtrace.weeklyvideo"
```

다시 켜려면 설치 명령을 실행하면 됩니다. 이미 실행 중인 작업은 중복으로 시작하지 않아요.
