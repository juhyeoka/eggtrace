from __future__ import annotations

import json
import time
from pathlib import Path

import cv2
import numpy as np
from ultralytics import YOLO

BASE_DIR = Path(__file__).resolve().parent.parent
VIDEO_PATH = BASE_DIR / "static" / "videos" / "demo.mp4"
DATA_DIR = BASE_DIR / "data"
THUMBS_DIR = DATA_DIR / "thumbs"
HEATMAPS_DIR = DATA_DIR / "heatmaps"
EVENTS_FILE = DATA_DIR / "events.jsonl"

THUMBS_DIR.mkdir(parents=True, exist_ok=True)
HEATMAPS_DIR.mkdir(parents=True, exist_ok=True)
DATA_DIR.mkdir(parents=True, exist_ok=True)

# coco class ids
# bird = 14
TARGET_CLASS_IDS = {14}

def build_heatmap(shape, centers):
    h, w = shape[:2]
    heat = np.zeros((h, w), dtype=np.float32)
    for (cx, cy) in centers:
        cv2.circle(heat, (cx, cy), 110, 1.0, -1)
    heat = cv2.GaussianBlur(heat, (0, 0), 45)

    if heat.max() > 0:
        heat_norm = np.uint8(np.clip(heat / heat.max() * 255, 0, 255))
    else:
        heat_norm = np.zeros((h, w), dtype=np.uint8)

    heat_color = cv2.applyColorMap(heat_norm, cv2.COLORMAP_JET)
    return heat_norm, heat_color

def calc_metrics(centers, frame_shape):
    h, w = frame_shape[:2]
    count = len(centers)

    # 활동량 근사: 개체 수 기반
    motion_ratio = min(1.0, count / 80.0)

    if count >= 2:
        pts = np.array(centers, dtype=np.float32)
        center = np.mean(pts, axis=0)
        compactness = float(np.mean(np.sum((pts - center) ** 2, axis=1)) / 1e5)
    else:
        compactness = 0.0

    # 중앙 ROI 집중도
    rw, rh = int(w * 0.4), int(h * 0.4)
    x1 = (w - rw) // 2
    y1 = (h - rh) // 2
    in_roi = 0
    for (cx, cy) in centers:
        if x1 <= cx <= x1 + rw and y1 <= cy <= y1 + rh:
            in_roi += 1
    roi_peak = in_roi / max(count, 1)

    # flow 대체값: 좌표 분산 기반 근사
    flow_mean_mag = min(20.0, compactness * 2.5 + count * 0.12)

    return round(motion_ratio, 4), round(flow_mean_mag, 4), round(compactness, 4), round(roi_peak, 4)

def make_tags(motion_ratio, flow_mean_mag, compactness, roi_peak):
    tags = []
    if motion_ratio >= 0.15:
        tags.append("ACTIVITY_SPIKE")
    if flow_mean_mag >= 2.2:
        tags.append("MOVE_FLOW")
    if compactness >= 1.8:
        tags.append("CLUSTER_SPREAD")
    if roi_peak >= 0.28:
        tags.append("ROI_PEAK")
    return tags

def main():
    if not VIDEO_PATH.exists():
        raise SystemExit(f"❌ 영상 없음: {VIDEO_PATH}")

    model = YOLO("yolov8n.pt")

    cap = cv2.VideoCapture(str(VIDEO_PATH))
    if not cap.isOpened():
        raise SystemExit(f"❌ 영상 열기 실패: {VIDEO_PATH}")

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    sample_step = max(1, int(fps * 2.0))  # 2초마다 분석

    rows = []
    idx = 0

    print(f"video={VIDEO_PATH}")
    print(f"fps={fps:.2f}, sample_step={sample_step}")

    while True:
        ok, frame = cap.read()
        if not ok:
            break

        if idx % sample_step != 0:
            idx += 1
            continue

        result = model.predict(frame, imgsz=960, conf=0.2, verbose=False)[0]

        boxes = []
        centers = []

        if result.boxes is not None and len(result.boxes) > 0:
            xyxy = result.boxes.xyxy.cpu().numpy()
            cls = result.boxes.cls.cpu().numpy().astype(int)
            conf = result.boxes.conf.cpu().numpy()

            for box, c, cf in zip(xyxy, cls, conf):
                if c not in TARGET_CLASS_IDS:
                    continue
                x1, y1, x2, y2 = map(int, box.tolist())
                if x2 <= x1 or y2 <= y1:
                    continue
                boxes.append((x1, y1, x2 - x1, y2 - y1, float(cf)))
                centers.append((int((x1 + x2) / 2), int((y1 + y2) / 2)))

        # bird가 너무 적게 잡히면 fallback: 모든 box 허용
        if len(centers) == 0 and result.boxes is not None and len(result.boxes) > 0:
            xyxy = result.boxes.xyxy.cpu().numpy()
            conf = result.boxes.conf.cpu().numpy()
            for box, cf in zip(xyxy, conf):
                x1, y1, x2, y2 = map(int, box.tolist())
                if x2 <= x1 or y2 <= y1:
                    continue
                area = (x2 - x1) * (y2 - y1)
                if area < 400:
                    continue
                boxes.append((x1, y1, x2 - x1, y2 - y1, float(cf)))
                centers.append((int((x1 + x2) / 2), int((y1 + y2) / 2)))

        motion_ratio, flow_mean_mag, compactness, roi_peak = calc_metrics(centers, frame.shape)
        tags = make_tags(motion_ratio, flow_mean_mag, compactness, roi_peak)

        uid = f"yolo_{idx}"
        thumb_path = THUMBS_DIR / f"{uid}.jpg"
        heatmap_path = HEATMAPS_DIR / f"{uid}.jpg"

        thumb = frame.copy()
        for (x, y, w, h, cf) in boxes:
            cv2.rectangle(thumb, (x, y), (x + w, y + h), (0, 255, 0), 2)
            cv2.putText(
                thumb,
                f"{cf:.2f}",
                (x, max(20, y - 6)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                (0, 255, 0),
                2,
                cv2.LINE_AA,
            )
        for (cx, cy) in centers:
            cv2.circle(thumb, (cx, cy), 4, (0, 255, 255), -1)

        _, heat_color = build_heatmap(frame.shape, centers)
        cv2.imwrite(str(thumb_path), thumb)
        cv2.imwrite(str(heatmap_path), heat_color)

        rows.append({
            "uid": uid,
            "time": time.time() - (len(rows) * 1800),
            "farm_id": "farm1",
            "lot_id": "lotA",
            "motion_ratio": motion_ratio,
            "flow_mean_mag": flow_mean_mag,
            "cluster_compactness": compactness,
            "roi_peak": roi_peak,
            "count_estimate": len(centers),
            "tags": tags,
            "thumb_path": f"/thumbs/{uid}.jpg",
            "heatmap_path": f"/heatmaps/{uid}.jpg",
            "video_path": "/videos/demo.mp4",
            "severity": "alert" if len(tags) >= 3 else "info",
        })

        print(f"[{idx}] count={len(centers)} tags={tags}")
        idx += 1

    cap.release()

    with EVENTS_FILE.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(f"✅ saved events: {len(rows)} -> {EVENTS_FILE}")

if __name__ == "__main__":
    main()
