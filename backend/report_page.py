"""Render the consumer report using recorded events and configured store details."""

from __future__ import annotations

import html
import json
import math
import os
import re
from datetime import datetime
from pathlib import Path
from statistics import fmean
from string import Template
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo


BASE_DIR = Path(__file__).resolve().parents[1]
EVENTS_FILE = BASE_DIR / "data" / "events.jsonl"
STORE_FILE = BASE_DIR / "configs" / "store.json"
TEMPLATE_FILE = BASE_DIR / "backend" / "templates" / "report.html"
WEEKLY_MANIFEST_FILE = BASE_DIR / "configs" / "weekly_video.json"
WEEKLY_DIR = BASE_DIR / "static" / "weekly"
KST = ZoneInfo("Asia/Seoul")
VIDEO_MODES = ("farm", "activity", "density", "pattern")


def _invalid_json_number(value: str) -> None:
    raise ValueError(f"Invalid JSON number: {value}")


def _weekly_video(code: str) -> dict | None:
    """Activate one complete published bundle, or keep the legacy report intact."""
    if code != "EGG-0001":
        return None
    try:
        manifest = json.loads(WEEKLY_MANIFEST_FILE.read_text(encoding="utf-8"), parse_constant=_invalid_json_number)
        if not isinstance(manifest, dict) or manifest.get("schemaVersion") != 1:
            return None
        if manifest.get("productCode", code) != code:
            return None
        version = manifest.get("version")
        if not isinstance(version, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", version):
            return None
        duration = _number(manifest.get("duration"))
        width = _number(manifest.get("width"))
        height = _number(manifest.get("height"))
        if duration is None or not 0 < duration <= 600:
            return None
        if width is None or height is None or not (1 <= width <= 7680 and 1 <= height <= 7680):
            return None

        def asset_path(url: object) -> Path:
            if not isinstance(url, str) or not url.startswith(f"/weekly/{version}/"):
                raise ValueError("asset outside bundle")
            if any(character in url for character in ("%", "?", "#", "\\")):
                raise ValueError("invalid asset URL")
            relative = Path(url.removeprefix("/weekly/"))
            if ".." in relative.parts:
                raise ValueError("invalid asset path")
            path = (WEEKLY_DIR / relative).resolve()
            version_root = (WEEKLY_DIR / version).resolve()
            if not version_root.is_relative_to(WEEKLY_DIR.resolve()) or not path.is_relative_to(version_root):
                raise ValueError("asset outside bundle")
            if not path.is_file() or path.stat().st_size == 0:
                raise ValueError("incomplete bundle")
            return path

        for group in ("videos", "posters"):
            if not isinstance(manifest.get(group), dict):
                return None
            for mode in VIDEO_MODES:
                path = asset_path(manifest[group].get(mode))
                if path.suffix != (".mp4" if group == "videos" else ".webp"):
                    return None
        moments = manifest.get("moments")
        if not isinstance(moments, list) or len(moments) != 3:
            return None
        for moment in moments:
            if not isinstance(moment, dict):
                return None
            time = _number(moment.get("time"))
            if time is None or not 0 <= time < duration:
                return None
            asset_path(moment.get("url"))
        analysis = json.loads(asset_path(manifest.get("analysisUrl")).read_text(encoding="utf-8"), parse_constant=_invalid_json_number)
        if not isinstance(analysis, dict) or not isinstance(analysis.get("frames"), list) or not analysis["frames"]:
            return None
        summary = analysis.get("summary")
        if not isinstance(summary, dict):
            return None
        if not isinstance(summary.get("activeZoneLabel"), str):
            return None
        if any(_number(summary.get(key)) is None for key in ("averageMotionPercent", "peakMotionPercent", "peakTime")):
            return None
        average, peak, peak_time = (float(summary[key]) for key in ("averageMotionPercent", "peakMotionPercent", "peakTime"))
        if not (0 <= average <= peak <= 100 and 0 <= peak_time < duration):
            return None
        analysis_duration = _number(analysis.get("duration"))
        if analysis_duration is None or abs(analysis_duration - duration) > 0.1:
            return None
        interval = _number(analysis.get("sampleInterval"))
        if interval is None or not 0 < interval <= duration:
            return None
        previous_time = -1.0
        for frame in analysis["frames"]:
            if not isinstance(frame, dict):
                return None
            time, motion = _number(frame.get("t")), _number(frame.get("motionPercent"))
            if time is None or motion is None or not (0 <= time < duration and previous_time < time and 0 <= motion <= 100):
                return None
            previous_time = time
            zones = frame.get("zones")
            if not isinstance(zones, list) or len(zones) != 9:
                return None
            if any(_number(zone) is None or not 0 <= float(zone) <= 100 for zone in zones):
                return None
        manifest["duration"] = duration
        manifest["width"], manifest["height"] = int(width), int(height)
        manifest["aspectRatio"] = f"{int(width)} / {int(height)}"
        return manifest
    except (OSError, ValueError, TypeError, KeyError):
        return None


def _number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _timestamp(value: object) -> float | None:
    number = _number(value)
    if number is None or number < 0:
        return None
    try:
        datetime.fromtimestamp(number, KST)
    except (ValueError, OverflowError, OSError):
        return None
    return number


def _read_records(code: str) -> list[dict]:
    """Ignore malformed rows and keep product/farm boundaries explicit."""
    records = []
    try:
        with EVENTS_FILE.open(encoding="utf-8", errors="replace") as source:
            for line in source:
                try:
                    row = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue
                if not isinstance(row, dict):
                    continue

                product = next(
                    (
                        str(row[key])
                        for key in ("product_code", "egg_code", "product", "code")
                        if row.get(key) not in (None, "")
                    ),
                    None,
                )
                if product is not None:
                    if product != code:
                        continue
                elif not (
                    code == "EGG-0001"
                    and row.get("farm_id") == "farm1"
                    and row.get("lot_id") == "lotA"
                ):
                    continue

                motion = _number(row.get("motion_ratio", row.get("activity_ratio")))
                if motion is None or not 0 <= motion <= 1:
                    continue
                timestamp = _timestamp(row.get("time", row.get("timestamp")))
                records.append({"motion": motion, "timestamp": timestamp})
    except OSError:
        return []

    # Missing observation times do not override the latest dated observation.
    records.sort(key=lambda row: row["timestamp"] if row["timestamp"] is not None else -1)
    return records


def _store_details() -> tuple[str, str]:
    try:
        settings = json.loads(STORE_FILE.read_text(encoding="utf-8"))
        if not isinstance(settings, dict):
            settings = {}
    except (OSError, ValueError):
        settings = {}

    name = settings.get("product_name")
    if not isinstance(name, str) or not name.strip():
        name = "클로렐라 자연방사 유정란 20구"

    url = os.environ.get("EGGTRACE_PURCHASE_URL", settings.get("purchase_url", ""))
    if not isinstance(url, str):
        return "", name.strip()
    url = url.strip()
    try:
        parts = urlsplit(url)
        valid = (
            parts.scheme in ("http", "https")
            and bool(parts.hostname)
            and not any(ord(character) < 32 for character in url)
            and parts.username is None
            and parts.password is None
        )
    except ValueError:
        valid = False
    return (url if valid else ""), name.strip()


def build_report_data(code: str) -> dict:
    """Keep historical observations labelled with their actual recording period."""
    records = _read_records(code)
    purchase_url, product_name = _store_details()
    weekly_video = _weekly_video(code)
    dated = [row for row in records if row["timestamp"] is not None]
    latest = datetime.fromtimestamp(dated[-1]["timestamp"], KST) if dated else None
    earliest = datetime.fromtimestamp(dated[0]["timestamp"], KST) if dated else None
    average = fmean(row["motion"] for row in records) * 100 if records else None

    if average is None:
        activity_label = "기록 준비 중"
        summary = "농장 영상의 분석 기록이 준비되면 이곳에서 확인할 수 있어요."
    else:
        activity_label = "움직임이 적은 편" if average <= 5 else "움직임 관찰" if average <= 20 else "움직임이 많은 편"
        summary = f"등록된 영상 분석 {len(records)}건에서 평균 움직임 비율 {average:.1f}%가 관찰됐어요."

    if earliest and latest:
        period = earliest.strftime("%Y.%m.%d")
        if earliest.date() != latest.date():
            period += " – " + latest.strftime("%Y.%m.%d")
        else:
            period += earliest.strftime(" %H:%M") + " – " + latest.strftime("%H:%M")
    else:
        period = "관찰 시간 미등록" if records else "기록 준비 중"

    return {
        "productCode": code,
        "hasData": bool(records),
        "recordCount": len(records),
        "latestLabel": latest.strftime("%Y.%m.%d %H:%M · KST") if latest else "기록 준비 중",
        "periodLabel": period,
        "averageMotionPercent": round(average, 1) if average is not None else None,
        "activityLabel": activity_label,
        "summary": summary,
        "chart": [
            {
                "label": datetime.fromtimestamp(row["timestamp"], KST).strftime("%H:%M"),
                "value": round(row["motion"] * 100, 2),
            }
            for row in dated[-10:]
        ],
        "purchaseUrl": purchase_url,
        "productName": product_name,
        "weeklyVideo": weekly_video,
        "videoUrl": weekly_video["videos"]["farm"] if weekly_video else "/videos/jcr-farm-web-20261105.mp4",
        "posterUrl": weekly_video["posters"]["farm"] if weekly_video else "/assets/jcr-farm-poster-v2.webp",
    }


def render_report(code: str, analytics: dict) -> str:
    """Return page HTML; the legacy analytics argument is kept for route compatibility."""
    payload = build_report_data(code)
    safe_json = json.dumps(payload, ensure_ascii=False, allow_nan=False).replace("<", "\\u003c")
    template = Template(TEMPLATE_FILE.read_text(encoding="utf-8"))
    weekly = payload["weeklyVideo"]
    duration = weekly["duration"] if weekly else 19.958
    moments = weekly["moments"] if weekly else [
        {"time": time, "url": f"/assets/jcr-moment-{index}-v2.webp"}
        for index, time in enumerate((2, 10, 17), start=1)
    ]
    moments_html = []
    for moment, label in zip(moments, ("처음 모습", "중간 모습", "후반 모습")):
        seconds = float(moment["time"])
        stamp = f"{int(seconds) // 60:02d}:{int(seconds) % 60:02d}"
        url = html.escape(moment["url"], quote=True)
        moments_html.append(
            f'<button type="button" data-seek="{seconds:g}">'
            f'<img src="{url}" alt="{stamp} 장면" loading="lazy">'
            f'<span><strong>{label}</strong><time>{stamp}</time>'
            '<svg class="icon fill"><use href="#i-play"/></svg></span></button>'
        )
    updated = ""
    if weekly and isinstance(weekly.get("createdAt"), str):
        try:
            timestamp = datetime.fromisoformat(weekly["createdAt"].replace("Z", "+00:00"))
            if timestamp.tzinfo is not None:
                published = timestamp.astimezone(KST)
                updated = f"{published.month}월 {published.day}일 업데이트"
        except ValueError:
            pass
    return template.substitute(
        product_code=html.escape(code, quote=True),
        report_json=safe_json,
        video_url=html.escape(payload["videoUrl"], quote=True),
        video_poster_url=html.escape(payload["posterUrl"], quote=True),
        video_duration=f"{int(duration + 0.5)}초 영상",
        video_aspect=weekly["aspectRatio"] if weekly else "16 / 9",
        video_portrait="is-portrait" if weekly and weekly["height"] > weekly["width"] else "",
        video_update=updated,
        video_update_hidden="" if updated else "hidden",
        video_moments="".join(moments_html),
    )
