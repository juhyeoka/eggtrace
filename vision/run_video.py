import cv2
import time
import json
from pathlib import Path
import yaml

from event_engine import EventEngine


def load_yaml(path):
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def main():
    print("RUN_VIDEO START")

    base = Path(__file__).resolve().parents[1]
    video_path = base / "data" / "sample.mp4"
    cfg_path = base / "configs" / "config.yaml"
    out_path = base / "data" / "events.jsonl"

    if not video_path.exists():
        print("❌ video not found:", video_path)
        return

    cfg = load_yaml(cfg_path)

    # ROI는 지금 단계에서는 안 씀 (없어도 됨)
    rois = {}

    engine = EventEngine(rois=rois, cfg=cfg)

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        print("❌ cannot open video")
        return

    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    fps_sample = int(cfg.get("fps_sample", 5))
    sample_every = max(1, int(round(fps / fps_sample)))

    print(f"video fps={fps:.2f}, sample_every={sample_every}")

    frame_idx = 0
    out_path.write_text("", encoding="utf-8")

    while True:
        ok, frame = cap.read()
        if not ok:
            break

        if frame_idx % sample_every == 0:
            ts = time.time()

            # ⭐ 핵심: frame을 그대로 event_engine에 넘김
            events = engine.update(ts, frame)

            for e in events:
                out_path.open("a", encoding="utf-8").write(
                    json.dumps(e, ensure_ascii=False) + "\n"
                )
                print("EVENT:", e)

        frame_idx += 1

    cap.release()
    print("RUN_VIDEO END")


if __name__ == "__main__":
    main()
