import json, time
from pathlib import Path
import cv2

BASE = Path(__file__).resolve().parents[1]
DATA = BASE / "data"

VIDEO = DATA / "sample.mp4"
EVENTS = DATA / "events.jsonl"
CLIPS = DATA / "clips"
THUMBS = DATA / "thumbs"

FARM_ID="farm1"
LOT_ID="lotA"

# 촬영용 세팅
EVERY_SEC = 3          # 몇 초마다 이벤트 만들지
CLIP_PRE_SEC = 2       # 이벤트 전 몇초
CLIP_POST_SEC = 3      # 이벤트 후 몇초
MAX_EVENTS = 12        # 최대 몇개 만들지

def ensure_dirs():
    CLIPS.mkdir(parents=True, exist_ok=True)
    THUMBS.mkdir(parents=True, exist_ok=True)
    DATA.mkdir(parents=True, exist_ok=True)

def reset_data():
    for p in [EVENTS]:
        if p.exists(): p.unlink()
    for d in [CLIPS, THUMBS]:
        if d.exists():
            for f in d.glob("*"):
                try: f.unlink()
                except: pass

def save_clip(cap, fps, start_frame, end_frame, out_path):
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    writer = cv2.VideoWriter(str(out_path), fourcc, fps, (w, h))

    cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
    n = 0
    for _ in range(end_frame - start_frame):
        ok, frame = cap.read()
        if not ok:
            break
        writer.write(frame)
        n += 1
    writer.release()
    return n

def save_thumb(frame, out_path):
    cv2.imwrite(str(out_path), frame)

def main():
    ensure_dirs()
    if not VIDEO.exists():
        raise SystemExit(f"sample video not found: {VIDEO}")

    cap = cv2.VideoCapture(str(VIDEO))
    if not cap.isOpened():
        raise SystemExit("failed to open video")

    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    dur = total / fps if total else 0

    print(f"[INFO] video={VIDEO} fps={fps:.2f} frames={total} duration={dur:.1f}s")

    step_frames = int(EVERY_SEC * fps)
    pre = int(CLIP_PRE_SEC * fps)
    post = int(CLIP_POST_SEC * fps)

    events = []
    frame_idx = step_frames  # 첫 이벤트는 조금 뒤부터
    made = 0

    while frame_idx < total and made < MAX_EVENTS:
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        ok, frame = cap.read()
        if not ok:
            break

        ts = time.time() + made  # uid 겹침 방지
        uid = f"{int(ts)}_{frame_idx}"

        start = max(0, frame_idx - pre)
        end = min(total-1, frame_idx + post)

        clip_path = CLIPS / f"{uid}.mp4"
        thumb_path = THUMBS / f"{uid}.jpg"

        clip_frames = save_clip(cap, fps, start, end, clip_path)
        save_thumb(frame, thumb_path)

        e = {
            "time": ts,
            "uid": uid,
            "farm_id": FARM_ID,
            "lot_id": LOT_ID,
            "event_type": "activity_detected",
            "motion_ratio": round(0.15 + 0.02*(made%5), 3),   # 데모용 수치
            "flow_mean_mag": round(5.0 + 0.5*(made%6), 3),    # 데모용 수치
            "cluster_compactness": round(0.01 + 0.003*(made%4), 4),
            "roi_peak": round(0.20 + 0.05*(made%3), 3),
            "clip_path": str(clip_path),
            "thumb_path": str(thumb_path),
            "clip_saved": True,
            "clip_frames": clip_frames,
            "clip_pre_sec": CLIP_PRE_SEC,
            "clip_post_sec": CLIP_POST_SEC,
            "src_fps": fps
        }
        events.append(e)

        print(f"[OK] event {made+1}: {uid} clip_frames={clip_frames}")

        made += 1
        frame_idx += step_frames

    cap.release()

    EVENTS.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in events) + "\n", encoding="utf-8")
    print(f"[DONE] wrote events: {len(events)} -> {EVENTS}")

if __name__ == "__main__":
    reset_data()
    main()
