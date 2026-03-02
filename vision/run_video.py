import cv2
import time
import json
import subprocess
from pathlib import Path
import yaml
from backend.characters import select_character
from collections import deque

from vision.event_engine import EventEngine

def load_yaml(path: Path):
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}

def save_clip_mp4(frames, out_path: Path, fps: int):
    if not frames:
        return False
    h, w = frames[0].shape[:2]
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(out_path), fourcc, fps, (w, h))
    if not writer.isOpened():
        return False
    for fr in frames:
        writer.write(fr)
    writer.release()
    return True

def transcode_h264(src_path: Path, dst_path: Path):
    cmd = [
        "ffmpeg", "-y",
        "-i", str(src_path),
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        str(dst_path),
    ]
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if p.returncode != 0:
        return False, p.stderr[-500:]
    return True, ""

def main():
    print("RUN_VIDEO START")

    base = Path(__file__).resolve().parents[1]
    video_path = base / "data" / "sample.mp4"
    cfg_path = base / "configs" / "config.yaml"
    out_events = base / "data" / "events.jsonl"
    clips_dir = base / "data" / "clips"
    thumbs_dir = base / "data" / "thumbs"
    heatmaps_dir = base / "data" / "heatmaps"

    clips_dir.mkdir(parents=True, exist_ok=True)
    thumbs_dir.mkdir(parents=True, exist_ok=True)
    heatmaps_dir.mkdir(parents=True, exist_ok=True)

    print("video_path =", video_path)
    if not video_path.exists():
        print("❌ video not found")
        return

    cfg = load_yaml(cfg_path)

    clip_pre_sec = float(cfg.get("clip_pre_sec", 5))
    clip_post_sec = float(cfg.get("clip_post_sec", 5))
    fps_sample = int(cfg.get("fps_sample", 5))

    engine = EventEngine(rois={}, cfg=cfg)

    cap = cv2.VideoCapture(str(video_path))
    print("cap opened:", cap.isOpened())
    if not cap.isOpened():
        print("❌ cannot open video")
        return

    src_fps = cap.get(cv2.CAP_PROP_FPS) or 25
    sample_every = max(1, int(round(src_fps / fps_sample)))
    pre_frames = int(round(clip_pre_sec * src_fps))
    post_frames = int(round(clip_post_sec * src_fps))

    print(f"src_fps={src_fps:.2f}, fps_sample={fps_sample}, sample_every={sample_every}")
    print(f"pre_frames={pre_frames}, post_frames={post_frames}")

    out_events.write_text("", encoding="utf-8")

    prebuf = deque(maxlen=max(1, pre_frames))
    recording = False
    clip_frames = []
    post_remaining = 0
    pending_event = None

    frame_idx = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break

        prebuf.append(frame.copy())

        if (frame_idx % sample_every) == 0 and not recording:
            ts = time.time()
            events = engine.update(ts, frame)
            if events:
                e = events[0]
                event_ts = e["time"]
                uid = f"{int(event_ts)}_{frame_idx}"

                raw_clip = clips_dir / f"{uid}_raw.mp4"
                h264_clip = clips_dir / f"{uid}.mp4"
                thumb_path = thumbs_dir / f"{uid}.jpg"
                heatmap_path = heatmaps_dir / f"{uid}.png"

                # 썸네일 저장
                cv2.imwrite(str(thumb_path), frame)

                # 히트맵 저장 (event_engine에서 온 이미지)
                heat_img = e.pop("_heatmap_img", None)
                if heat_img is not None:
                    cv2.imwrite(str(heatmap_path), heat_img)

                recording = True
                clip_frames = list(prebuf) + [frame.copy()]
                post_remaining = post_frames

                pending_event = {
                    **e,
                    "uid": uid,
                    "clip_path": str(h264_clip.relative_to(base)),
                    "thumb_path": str(thumb_path.relative_to(base)),
                    "heatmap_path": str(heatmap_path.relative_to(base)) if heatmap_path.exists() else None,
                    "clip_pre_sec": clip_pre_sec,
                    "clip_post_sec": clip_post_sec,
                    "src_fps": float(src_fps),
                }
                pending_event["_raw_clip_path"] = str(raw_clip)

        if recording:
            if post_remaining > 0:
                clip_frames.append(frame.copy())
                post_remaining -= 1
            else:
                raw_clip = Path(pending_event["_raw_clip_path"])
                ok_save = save_clip_mp4(clip_frames, raw_clip, int(round(src_fps)) or 25)

                pending_event["raw_saved"] = bool(ok_save)
                pending_event["clip_frames"] = len(clip_frames)

                final_clip = base / pending_event["clip_path"]
                if ok_save:
                    ok_h264, err = transcode_h264(raw_clip, final_clip)
                    pending_event["clip_saved"] = bool(ok_h264)
                    if not ok_h264:
                        pending_event["ffmpeg_error"] = err
                else:
                    pending_event["clip_saved"] = False

                try:
                    if raw_clip.exists():
                        raw_clip.unlink()
                except Exception:
                    pass

                pending_event.pop("_raw_clip_path", None)
                with out_events.open("a", encoding="utf-8") as out:
                    out.write(json.dumps(pending_event, ensure_ascii=False) + "\n")

                print("EVENT+EVIDENCE:", pending_event)

                recording = False
                clip_frames = []
                post_remaining = 0
                pending_event = None

        frame_idx += 1

    cap.release()
    print("RUN_VIDEO END")

def _attach_character_to_event(evt: dict):
    # run_video에서 만든 evt를 metrics 형태로 감싸서 캐릭터 선택에 넣는다
    # (select_character는 metrics dict를 기대)
    metrics = {
        "avg_motion": float(evt.get("motion_ratio", 0) or 0),
        "avg_flow": float(evt.get("flow_mean_mag", 0) or 0) if evt.get("flow_mean_mag") is not None else None,
        "avg_compactness": float(evt.get("cluster_compactness", 0) or 0) if evt.get("cluster_compactness") is not None else None,
        "roi_peak_avg": float(evt.get("roi_peak", 0) or 0) if evt.get("roi_peak") is not None else None,
        "behavior_variance_index": 0.0,  # 이벤트 단위라 일단 0
        "event_count": 1,
    }
    res = select_character(metrics)
    evt["character"] = res.character
    evt["character_score"] = res.score
    evt["character_label"] = res.label
    evt["character_rationale"] = res.rationale
    evt["character_signals"] = {
        "signal_cluster": res.context.get("signal_cluster"),
        "signal_flow": res.context.get("signal_flow"),
        "signal_variance": res.context.get("signal_variance"),
    }
    return evt


if __name__ == "__main__":
    main()
