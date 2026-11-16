#!/usr/bin/env python3
"""Prepare an immutable, browser-ready weekly farm-video release.

All media are completed in a staging directory before the active manifest is
replaced. The original input stays on the operator's computer.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from fractions import Fraction
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Any
from zoneinfo import ZoneInfo

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
FPS = 24
SAMPLE_INTERVAL = 0.5
SAMPLE_STEP = int(FPS * SAMPLE_INTERVAL)
PIPELINE_VERSION = "weekly-video-v2-chicken-mask"
MODEL_NAME = "yolo11m-seg"
MODEL_SHA256 = "eb9a06f63e2206c35d68d839b08c362429ebecf933ad54c1ad68b2fd001c17cf"
MODEL_URL = "https://github.com/ultralytics/assets/releases/download/v8.3.0/yolo11m-seg.pt"
MODEL_PATH = Path.home() / "Library" / "Application Support" / "EggtraceWeekly" / "yolo11m-seg.pt"
ZONES = [
    "좌측 상단", "상단 중앙", "우측 상단",
    "좌측 중앙", "중앙", "우측 중앙",
    "좌측 하단", "하단 중앙", "우측 하단",
]
FRIENDLY_ZONES = [
    "왼쪽 위", "가운데 위", "오른쪽 위",
    "왼쪽", "가운데", "오른쪽",
    "왼쪽 아래", "가운데 아래", "오른쪽 아래",
]
MODES = ("farm", "activity", "density", "pattern")


@dataclass(frozen=True)
class VideoInfo:
    width: int
    height: int
    duration: float
    fps: float
    codec: str = ""
    pixel_format: str = ""
    has_audio: bool = False


@dataclass
class SampleVisual:
    mask: np.ndarray
    flow: np.ndarray
    heat: np.ndarray


@dataclass
class DetectedSubjects:
    mask: np.ndarray
    count: int


class ChickenMaskDetector:
    """Keep only confident bird-instance masks, reviewed as chickens in this footage.

    COCO's bird class is broader than chicken. This is not a flock census, and
    overlapping/distant chickens can be missed. Missing detections never trigger
    an all-class or whole-scene motion fallback.
    """

    def __init__(self, model_path: Path = MODEL_PATH, confidence: float = 0.4):
        if not math.isfinite(confidence) or not 0.25 <= confidence <= 0.95:
            raise ValueError("Detection confidence must be between 0.25 and 0.95")
        if not model_path.is_file():
            raise RuntimeError(f"Chicken mask weights are missing at {model_path}. Download the pinned official weights from {MODEL_URL}")
        if sha256_file(model_path) != MODEL_SHA256:
            raise RuntimeError("The chicken mask model checksum does not match the pinned official weights")
        try:
            from ultralytics import YOLO
        except ImportError as error:
            raise RuntimeError("Install tools/requirements-weekly.txt to enable chicken-only analysis") from error
        self.model = YOLO(str(model_path))
        if self.model.task != "segment" or self.model.names.get(14) != "bird":
            raise RuntimeError("The chicken mask model does not provide the expected bird segmentation class")
        self.confidence = confidence
        self.metadata = {
            "enabled": True, "model": MODEL_NAME, "modelSha256": MODEL_SHA256,
            "className": "bird", "classId": 14, "maskMethod": "instance-segmentation",
            "confidence": confidence, "imageSize": 960,
            "missedDetectionsExcluded": True,
            "normalization": "valid-current-detected-mask-pixels",
        }

    def detect(self, frame: np.ndarray) -> DetectedSubjects:
        result = self.model.predict(frame, imgsz=960, classes=[14], conf=self.confidence,
                                    retina_masks=True, device="cpu", verbose=False)[0]
        combined = np.zeros(frame.shape[:2], dtype=np.uint8)
        count = 0
        if result.masks is not None and result.boxes is not None:
            for polygon, class_id, confidence in zip(result.masks.xy, result.boxes.cls.tolist(), result.boxes.conf.tolist()):
                if int(class_id) != 14 or confidence < self.confidence or len(polygon) < 3:
                    continue
                cv2.fillPoly(combined, [np.rint(polygon).astype(np.int32)], 255)
                count += 1
        return DetectedSubjects(combined, count)


def current_week() -> str:
    today = datetime.now(ZoneInfo("Asia/Seoul")).date()
    return (today - timedelta(days=today.weekday())).isoformat()


def validate_week(value: str) -> str:
    parsed = date.fromisoformat(value)
    if parsed.weekday() != 0:
        raise ValueError("--week must be the Monday of the publication week")
    return parsed.isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def command(name: str) -> str:
    override = os.environ.get(f"EGGTRACE_{name.upper()}_BIN")
    executable = shutil.which(override or name)
    if not executable:
        raise RuntimeError(f"{name} is required to prepare weekly videos")
    return executable


def probe_video(path: Path) -> VideoInfo:
    result = subprocess.run(
        [command("ffprobe"), "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
        check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    payload = json.loads(result.stdout)
    video = next((stream for stream in payload.get("streams", []) if stream.get("codec_type") == "video"), None)
    if video is None:
        raise ValueError("The input does not contain a video stream")
    width, height = int(video["width"]), int(video["height"])
    rotation = float(video.get("tags", {}).get("rotate", 0))
    for side_data in video.get("side_data_list", []):
        if "rotation" in side_data:
            rotation = float(side_data["rotation"])
    sar_text = video.get("sample_aspect_ratio", "1:1")
    if sar_text not in (None, "N/A", "0:1"):
        try:
            width = round(width * float(Fraction(sar_text.replace(":", "/"))))
        except (ValueError, ZeroDivisionError):
            pass
    if abs(round(rotation / 90)) % 2:
        width, height = height, width
    duration = float(video.get("duration") or payload.get("format", {}).get("duration", 0))
    try:
        fps = float(Fraction(video.get("avg_frame_rate", "0/1")))
    except (ValueError, ZeroDivisionError):
        fps = 0
    if width < 2 or height < 2 or not math.isfinite(duration) or duration < 1:
        raise ValueError("The video must have valid dimensions and be at least one second long")
    return VideoInfo(width, height, duration, fps, video.get("codec_name", ""), video.get("pix_fmt", ""), any(stream.get("codec_type") == "audio" for stream in payload.get("streams", [])))


def fit_dimensions(width: int, height: int, max_side: int = 960) -> tuple[int, int]:
    factor = min(1.0, max_side / max(width, height))
    return max(2, int(width * factor) // 2 * 2), max(2, int(height * factor) // 2 * 2)


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", prefix=f".{path.name}.", dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(payload, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def small_gray(frame: np.ndarray) -> np.ndarray:
    height, width = frame.shape[:2]
    factor = min(1.0, 480 / max(width, height))
    resized = cv2.resize(frame, (max(4, round(width * factor)), max(4, round(height * factor))))
    return cv2.GaussianBlur(cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY), (5, 5), 0)


def align_previous(previous: np.ndarray, current: np.ndarray, previous_subject: np.ndarray | None = None, current_subject: np.ndarray | None = None) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    """Align background features so camera movement is not counted as bird movement."""
    height, width = current.shape
    valid = np.ones_like(current, dtype=np.uint8) * 255
    metadata: dict[str, Any] = {"registered": False, "cameraShiftPixels": 0.0, "transform": np.float32([[1, 0, 0], [0, 1, 0]])}
    background = None if previous_subject is None else cv2.bitwise_not(cv2.dilate(previous_subject, np.ones((9, 9), np.uint8)))
    points = cv2.goodFeaturesToTrack(previous, mask=background, maxCorners=300, qualityLevel=0.015, minDistance=7, blockSize=7)
    if points is None or len(points) < 12:
        return previous, valid, metadata
    tracked, status, _ = cv2.calcOpticalFlowPyrLK(previous, current, points, None, winSize=(21, 21), maxLevel=3)
    if tracked is None or status is None:
        return previous, valid, metadata
    backwards, back_status, _ = cv2.calcOpticalFlowPyrLK(current, previous, tracked, None, winSize=(21, 21), maxLevel=3)
    if backwards is None or back_status is None:
        return previous, valid, metadata
    good = (status.ravel() == 1) & (back_status.ravel() == 1)
    good &= np.linalg.norm(points.reshape(-1, 2) - backwards.reshape(-1, 2), axis=1) < 1.5
    if current_subject is not None:
        locations = np.rint(tracked.reshape(-1, 2)).astype(int)
        inside = (locations[:, 0] >= 0) & (locations[:, 0] < width) & (locations[:, 1] >= 0) & (locations[:, 1] < height)
        clean = np.zeros(len(locations), dtype=bool)
        clean[inside] = current_subject[locations[inside, 1], locations[inside, 0]] == 0
        good &= clean
    before, after = points.reshape(-1, 2)[good], tracked.reshape(-1, 2)[good]
    if len(before) < 12:
        return previous, valid, metadata
    matrix, inliers = cv2.estimateAffinePartial2D(before, after, method=cv2.RANSAC, ransacReprojThreshold=2, maxIters=1500, confidence=0.98)
    if matrix is None or inliers is None:
        return previous, valid, metadata
    scale = math.hypot(float(matrix[0, 0]), float(matrix[1, 0]))
    angle = math.degrees(math.atan2(float(matrix[1, 0]), float(matrix[0, 0])))
    shift = math.hypot(float(matrix[0, 2]), float(matrix[1, 2]))
    if inliers.mean() < 0.4 or int(inliers.sum()) < 12 or not 0.94 <= scale <= 1.06 or abs(angle) > 8 or shift > min(width, height) * 0.2:
        return previous, valid, metadata
    aligned = cv2.warpAffine(previous, matrix, (width, height), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    valid = cv2.warpAffine(valid, matrix, (width, height), flags=cv2.INTER_NEAREST, borderMode=cv2.BORDER_CONSTANT)
    valid = cv2.erode(valid, np.ones((5, 5), np.uint8))
    metadata.update(registered=True, cameraShiftPixels=round(shift, 3), transform=matrix)
    return aligned, valid, metadata


def measure_motion(previous: np.ndarray, current: np.ndarray, previous_subject: np.ndarray | None = None, current_subject: np.ndarray | None = None) -> tuple[dict[str, Any], np.ndarray, np.ndarray]:
    aligned, valid, camera = align_previous(previous, current, previous_subject, current_subject)
    difference = current.astype(np.float32) - aligned.astype(np.float32)
    valid_pixels = valid > 0
    exposure = float(np.median(difference[valid_pixels])) if valid_pixels.any() else 0
    absolute = np.abs(difference - exposure)
    mask = ((absolute > 18) & valid_pixels).astype(np.uint8) * 255
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)))
    flow = cv2.calcOpticalFlowFarneback(aligned, current, None, 0.5, 3, 15, 3, 5, 1.2, 0)
    flow[~valid_pixels] = 0
    magnitude = np.linalg.norm(flow, axis=2)
    denominator = int(np.count_nonzero(valid_pixels))
    metric_pixels = valid_pixels
    motion = float(np.count_nonzero(mask)) / denominator * 100 if denominator else 0
    scene_transition = not camera["registered"] and motion > 65 and float(np.median(magnitude[valid_pixels])) > 12
    subjects_measured = True
    if previous_subject is not None and current_subject is not None:
        metric_pixels = (current_subject > 0) & valid_pixels
        eligible = metric_pixels
        subjects_measured = bool(np.any(previous_subject) and np.any(metric_pixels))
        mask[~eligible] = 0
        flow[current_subject == 0] = 0
        magnitude = np.linalg.norm(flow, axis=2)
        denominator = int(np.count_nonzero(metric_pixels))
        motion = float(np.count_nonzero(mask)) / denominator * 100 if denominator and subjects_measured else 0
        if not subjects_measured:
            mask[:] = 0
            flow[:] = 0
    if scene_transition:
        mask[:] = 0
        flow[:] = 0
        motion = 0
    rows, columns = np.linspace(0, current.shape[0], 4, dtype=int), np.linspace(0, current.shape[1], 4, dtype=int)
    zones = []
    for row in range(3):
        for column in range(3):
            region = np.s_[rows[row]:rows[row + 1], columns[column]:columns[column + 1]]
            count = int(np.count_nonzero(metric_pixels[region]))
            zones.append(round(float(np.count_nonzero(mask[region])) / count * 100, 2) if count else 0.0)
    record = {
        "motionPercent": round(motion, 2), "zones": zones,
        "flow": round(float(magnitude[metric_pixels].mean()), 3) if denominator and subjects_measured and not scene_transition else 0.0,
        "dominantZone": ZONES[int(np.argmax(zones))] if max(zones) > 0 else "움직임이 적었어요",
        "measured": not scene_transition and subjects_measured, "sceneTransition": bool(scene_transition),
        "cameraCompensated": camera["registered"], "cameraShiftPixels": camera["cameraShiftPixels"],
    }
    return record, mask, flow


def choose_clip_start(path: Path, info: VideoInfo, max_duration: float, detector: ChickenMaskDetector) -> float:
    if info.duration <= max_duration:
        return 0.0
    capture = cv2.VideoCapture(str(path))
    scores: list[tuple[float, float]] = []
    previous = previous_subject = None
    try:
        for second in range(0, math.ceil(info.duration), 2):
            capture.set(cv2.CAP_PROP_POS_MSEC, second * 1000)
            ok, frame = capture.read()
            if not ok:
                break
            gray = small_gray(frame)
            subject = cv2.resize(detector.detect(frame).mask, (gray.shape[1], gray.shape[0]), interpolation=cv2.INTER_NEAREST)
            if previous is not None:
                record, _, _ = measure_motion(previous, gray, previous_subject, subject)
                score = record["motionPercent"] if record["measured"] else 0
                # A stable camera makes the automatic excerpt easier to watch.
                if record["cameraShiftPixels"] > 12:
                    score *= 0.5
                scores.append((float(second), score))
            previous = gray
            previous_subject = subject
    finally:
        capture.release()
    if not scores:
        return 0.0
    candidates = sorted({0.0, max(0.0, info.duration - max_duration)} | {min(max(0.0, time - max_duration / 2), info.duration - max_duration) for time, _ in scores})
    return round(max(candidates, key=lambda start: sum(score for time, score in scores if start <= time < start + max_duration)), 3)


def encode_original(source: Path, output: Path, width: int, height: int, start: float, duration: float) -> None:
    subprocess.run(
        [command("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y", "-ss", str(start), "-i", str(source),
         "-t", str(duration), "-map", "0:v:0", "-an", "-vf", f"scale={width}:{height}:flags=lanczos,setsar=1,fps={FPS}",
         "-c:v", "libx264", "-preset", "fast", "-crf", "24", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
         "-map_metadata", "-1", "-metadata:s:v:0", "rotate=0", str(output)],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )


def analyze_video(path: Path, observation: str | None, detector: ChickenMaskDetector) -> tuple[dict[str, Any], list[SampleVisual], int]:
    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        raise ValueError("The prepared video could not be decoded")
    frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    records: list[dict[str, Any]] = []
    visuals: list[SampleVisual] = []
    previous = previous_subject = rolling = None
    index = 0
    sharpest = (0.0, 0)
    try:
        while capture.grab():
            if index % SAMPLE_STEP == 0:
                ok, frame = capture.retrieve()
                if not ok:
                    raise ValueError("A sampled video frame could not be decoded")
                gray = small_gray(frame)
                detected = detector.detect(frame)
                subject = cv2.resize(detected.mask, (gray.shape[1], gray.shape[0]), interpolation=cv2.INTER_NEAREST)
                sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
                if index > FPS and detected.count > 0 and sharpness > sharpest[0]:
                    sharpest = (sharpness, index)
                if previous is None:
                    mask = np.zeros_like(gray)
                    flow = np.zeros((*gray.shape, 2), np.float32)
                    record = {"motionPercent": 0.0, "zones": [0.0] * 9, "flow": 0.0, "dominantZone": "살펴보는 중", "measured": False, "sceneTransition": False, "cameraCompensated": False, "cameraShiftPixels": 0.0}
                else:
                    record, mask, flow = measure_motion(previous, gray, previous_subject, subject)
                raw = cv2.GaussianBlur(mask.astype(np.float32) / 255, (0, 0), 11)
                rolling = raw if rolling is None or record["sceneTransition"] else rolling * 0.6 + raw * 0.4
                records.append({"t": round(index / FPS, 3), "detectedCount": detected.count,
                                "detectionCoveragePercent": round(np.count_nonzero(subject) / subject.size * 100, 3), **record})
                visuals.append(SampleVisual(mask, flow, rolling.copy()))
                previous = gray
                previous_subject = subject
            index += 1
    finally:
        capture.release()
    if index != frame_count or len(records) < 2:
        raise ValueError("The prepared video is incomplete or too short to compare scenes")
    measured = [record for record in records if record["measured"]]
    if not measured:
        raise ValueError("No consecutive scenes with confidently detected chickens could be measured; the active video has not been replaced")
    peak = max(measured, key=lambda record: record["motionPercent"])
    average = round(float(np.mean([record["motionPercent"] for record in measured])), 2)
    zone_averages = np.mean([record["zones"] for record in measured], axis=0)
    active_index = int(np.argmax(zone_averages))
    if observation is None:
        observation = f"닭으로 인식된 부분을 살펴보니 {FRIENDLY_ZONES[active_index]} 쪽에서 움직임이 많이 잡혔어요." if average > 0 else "닭으로 인식된 부분에서는 움직임이 적게 잡혔어요."
    registered = sum(bool(record["cameraCompensated"]) for record in measured)
    payload = {
        "duration": round(frame_count / FPS, 3), "sampleInterval": SAMPLE_INTERVAL,
        "sourceLabel": "주간 농장 영상", "method": "닭으로 인식된 부분의 앞뒤 장면을 비교했어요. 카메라 움직임은 배경 위치를 맞춰 줄였고, 인식하지 못한 장면은 비교에서 뺐어요.",
        "detection": detector.metadata,
        "cameraCompensation": {"enabled": True, "method": "background-feature-ransac", "registeredSamples": registered, "measuredSamples": len(measured), "sceneTransitions": sum(bool(record["sceneTransition"]) for record in records)},
        "baselineMethod": "same-video-measured-samples-only", "frames": records,
        "summary": {
            "averageMotionPercent": average, "peakMotionPercent": peak["motionPercent"], "peakTime": peak["t"],
            "measuredCount": len(measured), "unmeasuredCount": len(records) - len(measured),
            "activeZoneLabel": ZONES[active_index] if float(zone_averages.max()) > 0 else "움직임이 적었어요",
            "averageFlow": round(float(np.mean([record["flow"] for record in measured])), 3),
            "zoneAverages": [round(float(value), 2) for value in zone_averages], "observation": observation,
        },
    }
    return payload, visuals, sharpest[1]


def find_font(explicit: Path | None) -> Path | None:
    candidates = [explicit] if explicit else []
    candidates += [
        Path("/System/Library/Fonts/AppleSDGothicNeo.ttc"),
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
        Path("/usr/share/fonts/truetype/noto/NotoSansKR-Regular.ttf"),
    ]
    return next((path for path in candidates if path is not None and path.is_file()), None)


def make_plate(label: str, font_path: Path | None, width: int) -> np.ndarray | None:
    if font_path is None or width < 240:
        return None
    font = ImageFont.truetype(str(font_path), 20 if width >= 500 else 17)
    bounds = font.getbbox(label)
    plate = Image.new("RGBA", (bounds[2] - bounds[0] + 28, 42), (0, 0, 0, 0))
    drawer = ImageDraw.Draw(plate)
    drawer.rounded_rectangle((0, 0, plate.width - 1, 41), radius=10, fill=(24, 31, 29, 210))
    drawer.text((14, 9 - bounds[1]), label, fill="white", font=font)
    return np.asarray(plate)


def apply_plate(frame: np.ndarray, plate: np.ndarray | None) -> None:
    if plate is None:
        return
    region = frame[16:16 + plate.shape[0], 16:16 + plate.shape[1]]
    alpha = plate[:, :, 3:4] / 255
    region[:] = (region * (1 - alpha) + plate[:, :, :3][:, :, ::-1] * alpha).astype(np.uint8)


def clock(seconds: float) -> str:
    whole = max(0, int(seconds))
    return f"{whole // 60:02d}:{whole % 60:02d}"


def open_encoder(path: Path, width: int, height: int) -> subprocess.Popen:
    return subprocess.Popen(
        [command("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{width}x{height}", "-r", str(FPS), "-i", "pipe:0", "-an", "-c:v", "libx264", "-preset", "fast", "-crf", "24", "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-map_metadata", "-1", str(path)],
        stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )


def render_views(directory: Path, analysis: dict[str, Any], visuals: list[SampleVisual], poster_index: int, font_path: Path | None, detector: ChickenMaskDetector) -> tuple[int, int, list[dict[str, Any]]]:
    capture = cv2.VideoCapture(str(directory / "farm.mp4"))
    width, height = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH)), int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    moment_indices = sorted({min(count - 1, max(0, round((count - 1) * fraction))) for fraction in (0.1, 0.5, 0.85)})
    poster_index = min(count - 1, max(0, poster_index))
    moments = [{"time": round(index / FPS, 3), "file": f"moment-{number + 1}.webp"} for number, index in enumerate(moment_indices)]
    labels = {"activity": "움직임", "density": "움직인 곳", "pattern": "이동 방향"}
    plates = {mode: make_plate(label, font_path, width) for mode, label in labels.items()}
    encoders: dict[str, subprocess.Popen] = {}
    successful = False
    try:
        for mode in labels:
            encoders[mode] = open_encoder(directory / f"{mode}.mp4", width, height)
        heat_max = max((float(visual.heat.max()) for visual in visuals), default=0)
        index = 0
        while True:
            ok, original = capture.read()
            if not ok:
                break
            sample = visuals[min(index // SAMPLE_STEP, len(visuals) - 1)]
            # Segment the CURRENT frame. A previous sample's mask must never
            # mark empty floor after the chicken has moved out of that place.
            subject = detector.detect(original).mask
            mask = cv2.resize(sample.mask, (width, height), interpolation=cv2.INTER_NEAREST)
            mask[subject == 0] = 0
            activity = original.copy()
            alpha = mask.astype(np.float32)[:, :, None] / 255 * 0.28
            color = np.zeros_like(activity); color[:] = (123, 219, 86)
            activity = (activity * (1 - alpha) + color * alpha).astype(np.uint8)
            # Keep the overlay inside the detected silhouette, including edges.
            edges = mask - cv2.erode(mask, np.ones((3, 3), np.uint8))
            activity[edges > 0] = (135, 237, 101)
            heat = cv2.resize(sample.heat, (width, height))
            normalized = np.clip(heat / max(heat_max, 0.01), 0, 1)
            normalized[subject == 0] = 0
            colors = cv2.applyColorMap((normalized * 255).astype(np.uint8), cv2.COLORMAP_TURBO)
            heat_alpha = (normalized * 0.58)[:, :, None]
            density = (original * (1 - heat_alpha) + colors * heat_alpha).astype(np.uint8)
            pattern = original.copy()
            flow_height, flow_width = sample.flow.shape[:2]
            small_subject = cv2.resize(subject, (flow_width, flow_height), interpolation=cv2.INTER_NEAREST)
            scale_x, scale_y = width / flow_width, height / flow_height
            step = max(20, min(flow_width, flow_height) // 11)
            for y in range(step // 2, flow_height, step):
                for x in range(step // 2, flow_width, step):
                    if not small_subject[y, x]:
                        continue
                    dx, dy = sample.flow[y, x]
                    magnitude = math.hypot(float(dx), float(dy))
                    if 0.45 < magnitude < min(flow_width, flow_height) * 0.15:
                        factor = min(2.8, 18 / magnitude)
                        start = (round(x * scale_x), round(y * scale_y))
                        end = (round((x + float(dx) * factor) * scale_x), round((y + float(dy) * factor) * scale_y))
                        arrow = pattern.copy()
                        cv2.arrowedLine(arrow, start, end, (254, 205, 99), 2, cv2.LINE_AA, tipLength=0.35)
                        pattern[subject > 0] = arrow[subject > 0]
            outputs = {"activity": activity, "density": density, "pattern": pattern}
            for mode, frame in outputs.items():
                apply_plate(frame, plates[mode])
                if width >= 160 and height >= 120:
                    time_text = f"{clock(index / FPS)} / {clock(math.ceil(analysis['duration']))}"
                    text_width = cv2.getTextSize(time_text, cv2.FONT_HERSHEY_SIMPLEX, 0.46, 1)[0][0]
                    cv2.rectangle(frame, (12, height - 38), (text_width + 28, height - 10), (28, 31, 29), -1)
                    cv2.putText(frame, time_text, (20, height - 19), cv2.FONT_HERSHEY_SIMPLEX, 0.46, (255, 255, 255), 1, cv2.LINE_AA)
                assert encoders[mode].stdin is not None
                encoders[mode].stdin.write(frame.tobytes())
                if index == poster_index:
                    Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)).save(directory / f"{mode}.webp", quality=88)
            if index == poster_index:
                Image.fromarray(cv2.cvtColor(original, cv2.COLOR_BGR2RGB)).save(directory / "farm.webp", quality=88)
            if index in moment_indices:
                number = moment_indices.index(index)
                Image.fromarray(cv2.cvtColor(original, cv2.COLOR_BGR2RGB)).save(directory / moments[number]["file"], quality=88)
            index += 1
        if index != count:
            raise ValueError("The video stopped decoding before its end")
        for mode, encoder in encoders.items():
            assert encoder.stdin is not None
            encoder.stdin.close()
            encoder.stdin = None
            _, stderr = encoder.communicate()
            if encoder.returncode:
                raise RuntimeError(f"The {mode} video encoder failed: {stderr.decode(errors='replace')[-400:]}")
        successful = True
    finally:
        capture.release()
        if not successful:
            for encoder in encoders.values():
                if encoder.stdin is not None:
                    try:
                        encoder.stdin.close()
                    except OSError:
                        pass
                if encoder.poll() is None:
                    encoder.terminate()
                encoder.wait()
    return width, height, moments


def validate_release(directory: Path, manifest: dict[str, Any]) -> None:
    try:
        analysis = json.loads((directory / "analysis.json").read_text(encoding="utf-8"))
        if (analysis["version"] != manifest["version"]
                or analysis["width"] != manifest["width"]
                or analysis["height"] != manifest["height"]
                or abs(analysis["duration"] - manifest["duration"]) > 0.001
                or not analysis["frames"] or not isinstance(analysis["summary"], dict)):
            raise ValueError("mismatched analysis")
        if manifest.get("detection"):
            if analysis.get("detection") != manifest["detection"] or not analysis["detection"].get("enabled"):
                raise ValueError("mismatched chicken detection method")
        last_time = -1.0
        measured = []
        for frame in analysis["frames"]:
            time, motion = float(frame["t"]), float(frame["motionPercent"])
            if (not math.isfinite(time) or not last_time < time <= manifest["duration"]
                    or not math.isfinite(motion) or not 0 <= motion <= 100
                    or len(frame["zones"]) != 9
                    or any(not math.isfinite(float(value)) or not 0 <= value <= 100 for value in frame["zones"])):
                raise ValueError("invalid measurement")
            last_time = time
            if frame.get("measured", True):
                if manifest.get("detection") and (frame.get("detectedCount", 0) < 1 or not 0 < frame.get("detectionCoveragePercent", 0) <= 100):
                    raise ValueError("a measured scene has no detected chickens")
                measured.append(frame)
        if not measured:
            raise ValueError("missing measured scenes")
        expected_average = round(float(np.mean([frame["motionPercent"] for frame in measured])), 2)
        expected_peak = max(measured, key=lambda frame: frame["motionPercent"])
        summary = analysis["summary"]
        if (summary["averageMotionPercent"] != expected_average
                or summary["peakMotionPercent"] != expected_peak["motionPercent"]
                or summary["peakTime"] != expected_peak["t"]):
            raise ValueError("mismatched measurement summary")
    except (OSError, ValueError, TypeError, KeyError) as error:
        raise ValueError("The prepared analysis is missing, incomplete, or does not match this release") from error

    def check_image(path: Path) -> None:
        try:
            with Image.open(path) as image:
                if image.size != (manifest["width"], manifest["height"]):
                    raise ValueError("wrong image shape")
                image.load()
        except (OSError, ValueError) as error:
            raise ValueError("A prepared video poster or scene thumbnail is missing or invalid") from error

    for mode in MODES:
        info = probe_video(directory / f"{mode}.mp4")
        if (info.width != manifest["width"] or info.height != manifest["height"]
                or abs(info.duration - manifest["duration"]) > 1 / FPS + 0.01
                or abs(info.fps - FPS) > 0.01 or info.codec != "h264"
                or info.pixel_format != "yuv420p" or info.has_audio):
            raise ValueError("The prepared video modes do not share one timeline and shape")
        check_image(directory / f"{mode}.webp")
    for moment in manifest["moments"]:
        if not 0 <= moment["time"] < manifest["duration"]:
            raise ValueError("A scene thumbnail does not match the video timeline")
        check_image(directory / Path(moment["url"]).name)


def prepare_video(input_path: Path, *, week: str | None = None, output_root: Path = ROOT / "static" / "weekly", manifest_path: Path = ROOT / "configs" / "weekly_video.json", max_duration: float = 30, observation: str | None = None, font_path: Path | None = None, url_prefix: str = "/weekly", start_time: float | None = None, model_path: Path = MODEL_PATH, confidence: float = 0.4, detector: ChickenMaskDetector | None = None) -> dict[str, Any]:
    if not input_path.is_file():
        raise ValueError("The input video does not exist")
    if not math.isfinite(max_duration) or not 1 <= max_duration <= 300:
        raise ValueError("--max-duration must be between 1 and 300 seconds")
    max_duration = float(max_duration)
    if start_time is not None and (not math.isfinite(start_time) or start_time < 0):
        raise ValueError("--start must be a finite nonnegative video time")
    week = validate_week(week or current_week())
    if not url_prefix.startswith("/") or ".." in url_prefix or "?" in url_prefix or "#" in url_prefix:
        raise ValueError("The media URL prefix must be a local absolute URL path")
    if font_path is not None and not font_path.is_file():
        raise ValueError("The requested video-label font does not exist")
    font_path = find_font(font_path)
    observation = observation.strip() if observation and observation.strip() else None
    detector = detector or ChickenMaskDetector(model_path, confidence)
    source_hash = sha256_file(input_path)
    options = {"pipeline": PIPELINE_VERSION, "source": source_hash, "week": week, "maxDuration": max_duration, "start": start_time, "detection": detector.metadata, "observation": observation, "font": sha256_file(font_path) if font_path else None, "urlPrefix": url_prefix.rstrip("/")}
    digest = hashlib.sha256(json.dumps(options, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:12]
    version = f"{week}-{digest}"
    output_root = output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    final_directory = output_root / version
    release_url = f"{url_prefix.rstrip('/')}/{version}"
    if final_directory.exists():
        cached = json.loads((final_directory / "manifest.json").read_text(encoding="utf-8"))
        if cached.get("version") != version or cached.get("sourceSha256") != source_hash:
            raise ValueError("The immutable release directory is not the expected video")
        validate_release(final_directory, cached)
        atomic_json(manifest_path, cached)
        return cached
    info = probe_video(input_path)
    if start_time is not None and start_time > info.duration - 1:
        raise ValueError("--start must leave at least one second of footage")
    width, height = fit_dimensions(info.width, info.height)
    start = start_time if start_time is not None else choose_clip_start(input_path, info, max_duration, detector)
    duration = min(max_duration, info.duration - start)
    with tempfile.TemporaryDirectory(prefix=".weekly-staging-", dir=output_root.parent) as temporary:
        staging = Path(temporary) / "release"
        staging.mkdir()
        encode_original(input_path, staging / "farm.mp4", width, height, start, duration)
        analysis, visuals, poster_index = analyze_video(staging / "farm.mp4", observation, detector)
        width, height, moments = render_views(staging, analysis, visuals, poster_index, font_path, detector)
        manifest = {
            "schemaVersion": 1, "version": version, "week": week,
            "createdAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "sourceSha256": source_hash, "duration": analysis["duration"],
            "width": width, "height": height, "aspectRatio": f"{width} / {height}",
            "analysisUrl": f"{release_url}/analysis.json",
            "videos": {mode: f"{release_url}/{mode}.mp4" for mode in MODES},
            "posters": {mode: f"{release_url}/{mode}.webp" for mode in MODES},
            "posterTime": round(poster_index / FPS, 3),
            "moments": [{"time": moment["time"], "url": f"{release_url}/{moment['file']}"} for moment in moments],
            "observation": analysis["summary"]["observation"],
            "detection": detector.metadata,
            "editing": {"sourceDuration": round(info.duration, 3), "start": start, "end": round(start + analysis["duration"], 3), "strategy": "reviewed-window" if start_time is not None else "full-video" if info.duration <= max_duration else "detected-chicken-movement-window"},
        }
        analysis.update(version=version, week=week, width=width, height=height, editing=manifest["editing"])
        atomic_json(staging / "analysis.json", analysis)
        atomic_json(staging / "manifest.json", manifest)
        validate_release(staging, manifest)
        try:
            staging.rename(final_directory)
        except FileExistsError:
            concurrent = json.loads((final_directory / "manifest.json").read_text(encoding="utf-8"))
            if concurrent.get("version") != version or concurrent.get("sourceSha256") != source_hash:
                raise ValueError("Another video already occupies this release directory")
            validate_release(final_directory, concurrent)
            manifest = concurrent
    atomic_json(manifest_path, manifest)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path, help="Video to prepare; the original is not published")
    parser.add_argument("--week", help="Publication week Monday, YYYY-MM-DD (default: this week in Korea)")
    parser.add_argument("--output-root", type=Path, default=ROOT / "static" / "weekly")
    parser.add_argument("--manifest", type=Path, default=ROOT / "configs" / "weekly_video.json")
    parser.add_argument("--max-duration", type=float, default=30)
    parser.add_argument("--start", type=float, help="Optional reviewed excerpt start in source-video seconds")
    parser.add_argument("--model", type=Path, default=MODEL_PATH, help="Local pinned official segmentation weights")
    parser.add_argument("--confidence", type=float, default=0.4)
    parser.add_argument("--observation", help="Optional reviewed observation for this specific footage")
    parser.add_argument("--font", type=Path, help="Optional Korean font for small video labels")
    parser.add_argument("--url-prefix", default="/weekly")
    parser.add_argument("--json", action="store_true", help="Print the completed public manifest as JSON")
    args = parser.parse_args()
    try:
        result = prepare_video(args.input, week=args.week, output_root=args.output_root, manifest_path=args.manifest, max_duration=args.max_duration, observation=args.observation, font_path=args.font, url_prefix=args.url_prefix, start_time=args.start, model_path=args.model, confidence=args.confidence)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError, json.JSONDecodeError, cv2.error) as error:
        print(f"Weekly video preparation failed: {error}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    else:
        print(f"Prepared {result['version']}: {result['duration']:.3f}s, {result['width']}x{result['height']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
