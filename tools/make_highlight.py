import json
import subprocess
import sys
from pathlib import Path

src = Path(sys.argv[1] if len(sys.argv) > 1 else "data/videos/clip0525.mp4")
out = Path(sys.argv[2] if len(sys.argv) > 2 else "data/videos/highlight.mp4")

if not src.exists():
    raise SystemExit(f"영상 없음: {src}")

out.parent.mkdir(parents=True, exist_ok=True)

print("영상 분석 시작...")

# 영상 길이 확인
probe_cmd = [
    "ffprobe",
    "-v", "error",
    "-show_entries", "format=duration",
    "-of", "json",
    str(src)
]

duration = float(
    json.loads(
        subprocess.check_output(probe_cmd)
    )["format"]["duration"]
)

# 장면 변화 감지
detect_cmd = [
    "ffmpeg",
    "-i", str(src),
    "-vf", "select=gt(scene\\,0.015),showinfo",
    "-f", "null",
    "-"
]

result = subprocess.run(
    detect_cmd,
    stderr=subprocess.PIPE,
    stdout=subprocess.PIPE,
    text=True
)

times = []

for line in result.stderr.splitlines():
    if "pts_time:" in line:
        try:
            t = float(
                line.split("pts_time:")[1].split()[0]
            )
            times.append(t)
        except:
            pass

window = 20
best_start = 0
best_score = -1

max_start = max(0, int(duration - window))

# 20초 구간 중 이벤트 가장 많은 부분 탐색
for start in range(max_start + 1):

    end = start + window

    score = sum(
        1 for t in times
        if start <= t < end
    )

    if score > best_score:
        best_score = score
        best_start = start

print(f"최적 하이라이트 시작: {best_start}초")
print(f"감지 이벤트 수: {best_score}")

# 하이라이트 생성
cut_cmd = [
    "ffmpeg",
    "-y",
    "-ss", str(best_start),
    "-i", str(src),
    "-t", "20",
    "-c:v", "libx264",
    "-c:a", "aac",
    "-movflags", "+faststart",
    str(out)
]

subprocess.run(cut_cmd, check=True)

print("AI 하이라이트 생성 완료")
print(f"저장 위치: {out}")
