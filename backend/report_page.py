"""Render the consumer report using recorded events and configured store details."""

from __future__ import annotations

import html
import json
import math
import os
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
KST = ZoneInfo("Asia/Seoul")


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
        name = "자연방사 유정란 20구"

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
        "videoUrl": "/videos/highlight.mp4",
        "posterUrl": "/assets/jcr-farm-poster-20261105.webp",
    }


def render_report(code: str, analytics: dict) -> str:
    """Return page HTML; the legacy analytics argument is kept for route compatibility."""
    payload = build_report_data(code)
    safe_json = json.dumps(payload, ensure_ascii=False, allow_nan=False).replace("<", "\\u003c")
    template = Template(TEMPLATE_FILE.read_text(encoding="utf-8"))
    return template.substitute(
        product_code=html.escape(code, quote=True),
        report_json=safe_json,
    )
