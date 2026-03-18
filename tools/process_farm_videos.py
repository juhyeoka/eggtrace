from pathlib import Path
import time
import json
import math
import requests
import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
VIDEOS = DATA / "videos"
THUMBS = DATA / "thumbs"
HEATMAPS = DATA / "heatmaps"

THUMBS.mkdir(parents=True, exist_ok=True)
HEATMAPS.mkdir(parents=True, exist_ok=True)

SERVER = "https://eggtrace-82hy.onrender.com/ingest/event" 
FARM_ID = "farm1"
LOT_ID = "lotA"

VIDEO_LIST = [
    VIDEOS / "farm_video_1.mp4",
    VIDEOS / "farm_video_2.mp4",
]

SAMPLE_EVERY_SEC = 10

def save_thumb(frame, uid):
    out = THUMBS / f"{uid}.jpg"
    cv2.imwrite(str(out), frame)
    return f"/thumbs/{uid}.jpg"

def save_heatmap(binary_mask, uid):
    heat = cv2.applyColorMap(binary_mask, cv2.COLORMAP_JET)
    out = HEATMAPS / f"{uid}.png"
    cv2.imwrite(str(out), heat)
    return f"/heatmaps/{uid}.png"

def calc_metrics(prev_gray, gray):
    diff = cv2.absdiff(prev_gray, gray)
    _, th = cv2.threshold(diff, 25, 255, cv2.THRESH_BINARY)

    motion_ratio = float(np.count_nonzero(th)) / float(th.size)

    flow = cv2.calcOpticalFlowFarneback(
        prev_gray, gray, None,
        0.5, 3, 15, 3, 5, 1.2, 0
    )
    mag = np.sqrt(flow[..., 0] ** 2 + flow[..., 1] ** 2)
    flow_mean_mag = float(np.mean(mag))

    ys, xs = np.where(th > 0)
    if len(xs) > 0:
        pts = np.stack([xs, ys], axis=1).astype(np.float32)
        center = np.mean(pts, axis=0)
        compactness = float(np.mean(np.sum((pts - center) ** 2, axis=1)) / 1e5)
    else:
        compactness = 0.0

    h, w = gray.shape
    rw, rh = int(w * 0.4), int(h * 0.4)
    x1 = (w - rw) // 2
    y1 = (h - rh) // 2
    roi = th[y1:y1+rh, x1:x1+rw]
    roi_peak = float(np.count_nonzero(roi)) / float(roi.size)

    return motion_ratio, flow_mean_mag, compactness, roi_peak, th

def make_tags(motion_ratio, flow_mean_mag, compactness, roi_peak):
    tags = []
    if motion_ratio >= 0.22:
        tags.append("ACTIVITY_SPIKE")
    if compactness >= 0.012:
        tags.append("CLUSTER_SPREAD")
    if roi_peak >= 0.22:
        tags.append("ROI_PEAK_MED")
    return tags

def character_from_metrics(compactness, flow_mean_mag, roi_peak):
    if compactness > 0.014 and flow_mean_mag > 5.5:
        return "분산"
    if roi_peak > 0.22 and flow_mean_mag < 4.0:
        return "집중"
    return "균형"

def send_event(payload):
    try:
        r = requests.post(SERVER, json=payload, timeout=10)
        print("sent:", r.status_code, payload["uid"], payload["tags"])
    except Exception as e:
        print("send failed:", e)

def process_video(video_path: Path, offset_seq: int = 0):
    if not video_path.exists():
        print(f"[SKIP] 파일 없음: {video_path}")
        return 0

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        print(f"[SKIP] 열 수 없음: {video_path}")
        return 0

    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    duration = frame_count / fps if fps > 0 else 0.0
    step = max(1, int(fps * SAMPLE_EVERY_SEC))

    print(f"\n=== processing: {video_path.name} ===")
    print(f"fps={fps:.2f}, frames={frame_count}, duration={duration:.1f}s, sample_step={step}")

    prev_gray = None
    idx = 0
    sent = 0

    while True:
        ok, frame = cap.read()
        if not ok:
            break

        if idx % step != 0:
            idx += 1
            continue

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (7, 7), 0)

        if prev_gray is None:
            prev_gray = gray
            idx += 1
            continue

        motion_ratio, flow_mean_mag, compactness, roi_peak, th = calc_metrics(prev_gray, gray)
        tags = make_tags(motion_ratio, flow_mean_mag, compactness, roi_peak)

        # 이상치일 때만 이벤트 생성
        if tags:
            ts = time.time() + idx / max(fps, 1.0)
            uid = f"{int(ts)}_{idx+offset_seq}"

            thumb_path = save_thumb(frame, uid)
            heatmap_path = save_heatmap(th, uid)

            payload = {
                "time": ts,
                "uid": uid,
                "farm_id": FARM_ID,
                "lot_id": LOT_ID,
                "event_type": "activity_detected",
                "motion_ratio": round(motion_ratio, 4),
                "flow_mean_mag": round(flow_mean_mag, 4),
                "cluster_compactness": round(compactness, 4),
                "roi_peak": round(roi_peak, 4),
                "thumb_path": thumb_path,
                "heatmap_path": heatmap_path,
                "clip_path": None,
                "tags": tags,
                "character": character_from_metrics(compactness, flow_mean_mag, roi_peak),
                "severity": "warning" if len(tags) == 1 else "alert",
                "video_source": video_path.name
            }
            send_event(payload)
            sent += 1

        prev_gray = gray
        idx += 1

    cap.release()
    print(f"[DONE] {video_path.name}: events_sent={sent}")
    return sent

def main():
    total = 0
    seq_offset = 0
    for vp in VIDEO_LIST:
        n = process_video(vp, offset_seq=seq_offset)
        total += n
        seq_offset += 100000

    print(f"\n✅ 전체 완료: total_events_sent={total}")
    print("이제 브라우저에서 http://127.0.0.1:8000/p/EGG-0001 새로고침")

if __name__ == "__main__":
    main()
