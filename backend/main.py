from __future__ import annotations

import html
import json
import statistics
import time
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

app = FastAPI()

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
STATIC_DIR = BASE_DIR / "static"
VIDEOS_DIR = STATIC_DIR / "videos"
THUMBS_DIR = DATA_DIR / "thumbs"
HEATMAPS_DIR = DATA_DIR / "heatmaps"
EVENTS_FILE = DATA_DIR / "events.jsonl"

for d in (DATA_DIR, STATIC_DIR, VIDEOS_DIR, THUMBS_DIR, HEATMAPS_DIR):
    d.mkdir(parents=True, exist_ok=True)

app.mount("/assets", StaticFiles(directory=str(STATIC_DIR / "assets")), name="assets")
app.mount("/videos", StaticFiles(directory=str(VIDEOS_DIR)), name="videos")
app.mount("/thumbs", StaticFiles(directory=str(THUMBS_DIR)), name="thumbs")
app.mount("/heatmaps", StaticFiles(directory=str(HEATMAPS_DIR)), name="heatmaps")


def read_events(farm_id: str = "farm1", lot_id: str = "lotA", days: int = 30) -> list[dict]:
    if not EVENTS_FILE.exists():
        return []

    rows: list[dict] = []
    now = time.time()

    for line in EVENTS_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue

        try:
            e = json.loads(line)
        except Exception:
            continue

        if farm_id and e.get("farm_id") not in (None, "", farm_id):
            continue
        if lot_id and e.get("lot_id") not in (None, "", lot_id):
            continue

        ts = e.get("time", 0)
        if isinstance(ts, (int, float)) and ts > 946684800:
            if now - ts > days * 86400:
                continue

        rows.append(e)

    rows.sort(key=lambda x: x.get("time", 0), reverse=True)
    return rows


def compute_metrics(events: list[dict]) -> dict:
    if not events:
        return {
            "avg_motion": 0.0,
            "avg_flow": 0.0,
            "avg_compact": 0.0,
            "bvi": 0.0,
        }

    motions = [float(e.get("motion_ratio", 0) or 0) for e in events]
    flows = [float(e.get("flow_mean_mag", 0) or 0) for e in events]
    compacts = [float(e.get("cluster_compactness", 0) or 0) for e in events]

    return {
        "avg_motion": sum(motions) / len(motions),
        "avg_flow": sum(flows) / len(flows),
        "avg_compact": sum(compacts) / len(compacts),
        "bvi": statistics.pstdev(motions) if len(motions) > 1 else 0.0,
    }


def motion_text(metrics: dict) -> str:
    avg_flow = metrics.get("avg_flow", 0.0)
    if avg_flow >= 4:
        return "활발해요"
    if avg_flow >= 2:
        return "보통이에요"
    return "보통 수준"


def density_text(metrics: dict) -> str:
    avg_compact = metrics.get("avg_compact", 0.0)
    if avg_compact >= 1.2:
        return "적절해요"
    if avg_compact >= 0.7:
        return "조금 몰려 있어요"
    return "우측 구역 집중"


def change_text(metrics: dict) -> str:
    bvi = metrics.get("bvi", 0.0)
    if bvi < 0.03:
        return "평소 범위 유지"
    if bvi < 0.08:
        return "조금 있었어요"
    return "비교적 컸어요"


def human_event_text(tags: list[str]) -> str:
    tag_set = set(tags or [])

    if not tag_set:
        return "큰 이상 없이 차분한 흐름을 보이고 있어요."
    if "ACTIVITY_SPIKE" in tag_set and "CLUSTER_SPREAD" in tag_set:
        return "닭들의 이동 패턴과 활동 반경이 안정적으로 유지되고 있습니다."
    if "ACTIVITY_SPIKE" in tag_set:
        return "오늘은 평소보다 움직임이 조금 더 활발하게 느껴졌어요."
    if "MOVE_FLOW" in tag_set:
        return "움직임이 자연스럽게 이어지면서 전체 흐름이 살아 있었어요."
    if "CLUSTER_SPREAD" in tag_set:
        return "한 곳에 몰리기보다 넓게 퍼져 움직이는 모습이 보였어요."
    if "ROI_PEAK" in tag_set:
        return "특정 공간에 자연스럽게 모여 쉬는 흐름이 보였어요."
    return "전반적으로 무리 없이 편안한 흐름을 보이고 있어요."


def build_one_line(events: list[dict]) -> str:
    if not events:
        return "✦ 인공지능이 영상 속 활동량 변화와 밀집도 히트맵을 분석하고 있습니다."

    recent_tags: list[str] = []
    for e in events[:5]:
        recent_tags.extend(e.get("tags", []))

    tag_set = set(recent_tags)

    if "ACTIVITY_SPIKE" in tag_set and "CLUSTER_SPREAD" in tag_set:
        return "🐥 이번주는 닭들이 한곳에 치우치지 않고 농장 전체를 자연스럽게 움직이며 지냈어요."
    if "ROI_PEAK" in tag_set and "MOVE_FLOW" in tag_set:
        return "🌿 이번주는 쉬는 구역과 움직이는 흐름이 균형 있게 이어지는 모습이 보였어요."
    if "ACTIVITY_SPIKE" in tag_set:
        return "🐤 이번주는 평소보다 조금 더 활발한 분위기가 느껴졌어요."
    if "CLUSTER_SPREAD" in tag_set:
        return "🍃 이번주 닭들이 넓게 퍼져 편안하게 움직이는 흐름이 보였어요."
    return "✦ 영상 내 이벤트 밀도가 높은 구간을 자동 추출해 분석합니다."


@app.get("/", response_class=HTMLResponse)
def root():
    return RedirectResponse("/p/EGG-0001", status_code=302)


@app.get("/events", response_class=JSONResponse)
def events(days: int = 30, farm_id: str = "farm1", lot_id: str = "lotA"):
    rows = read_events(farm_id=farm_id, lot_id=lot_id, days=days)
    return JSONResponse({"count": len(rows), "events": rows})


@app.get("/p/{code}", response_class=HTMLResponse)
def product_page(code: str, days: int = 30, farm_id: str = "farm1", lot_id: str = "lotA"):
    from backend.report_page import render_report

    return HTMLResponse(render_report(code, {}))


# === EGGTRACE_REAL_ANALYTICS_API_V3_START ===

@app.get("/api/products/{product_code}/analytics")
def eggtrace_real_product_analytics(product_code: str):
    """
    data/events.jsonl의 실제 이벤트를 읽어
    소비자용 분석 결과를 계산한다.
    임의의 시연 기본값은 사용하지 않는다.
    """
    from collections import Counter, defaultdict
    from datetime import datetime
    from pathlib import Path
    import hashlib
    import json
    import math
    import statistics

    base_dir = Path(__file__).resolve().parents[1]

    candidates = [
        base_dir / "data" / "events.jsonl",
        base_dir / "data" / "events" / "events.jsonl",
        base_dir / "data" / "output" / "events.jsonl",
    ]

    events_path = next(
        (
            candidate
            for candidate in candidates
            if candidate.exists()
            and candidate.is_file()
        ),
        None,
    )

    if events_path is None:
        return {
            "has_data": False,
            "product_code": product_code,
            "message": "events.jsonl 파일을 찾지 못했습니다.",
        }

    records = []

    with events_path.open(
        "r",
        encoding="utf-8",
        errors="ignore",
    ) as file:
        for line in file:
            line = line.strip()

            if not line:
                continue

            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue

            if isinstance(item, dict):
                records.append(item)

    if not records:
        return {
            "has_data": False,
            "product_code": product_code,
            "source_name": str(
                events_path.relative_to(base_dir)
            ),
            "message": "분석 기록이 비어 있습니다.",
        }

    def record_product(record):
        for key in (
            "product_code",
            "egg_code",
            "product",
            "code",
        ):
            value = record.get(key)

            if value:
                return str(value)

        return None

    product_records = [
        record
        for record in records
        if record_product(record) == product_code
    ]

    if product_records:
        records = product_records

    # 최근 기록만 사용해 현재 화면이
    # 지나치게 오래된 데이터에 끌려가지 않도록 한다.
    records = records[-300:]

    def finite_number(value):
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None

        return (
            number
            if math.isfinite(number)
            else None
        )

    def values_for(*keys):
        values = []

        for record in records:
            value = None

            for key in keys:
                if key in record:
                    value = finite_number(
                        record.get(key)
                    )

                    if value is not None:
                        break

            if value is not None:
                values.append(value)

        return values

    motion_values = values_for(
        "motion_ratio",
        "activity_ratio",
    )

    flow_values = values_for(
        "flow_mean_mag",
        "flow_magnitude",
    )

    confidence_values = values_for(
        "confidence",
        "analysis_confidence",
    )

    zone_sums = defaultdict(float)
    zone_counts = defaultdict(int)

    for record in records:
        roi_activity = record.get("roi_activity")

        if not isinstance(roi_activity, dict):
            continue

        for zone_name, raw_value in roi_activity.items():
            value = finite_number(raw_value)

            if value is None:
                continue

            zone_sums[str(zone_name)] += value
            zone_counts[str(zone_name)] += 1

    zones = []

    for index, zone_name in enumerate(
        sorted(zone_sums)
    ):
        count = max(zone_counts[zone_name], 1)
        average = zone_sums[zone_name] / count

        zones.append(
            {
                "name": zone_name,
                "index": index,
                "value": round(average, 6),
            }
        )

    zone_total = sum(
        max(zone["value"], 0.0)
        for zone in zones
    )

    for zone in zones:
        zone["share"] = (
            max(zone["value"], 0.0) / zone_total
            if zone_total > 0
            else 0.0
        )

    zones.sort(
        key=lambda zone: zone["value"],
        reverse=True,
    )

    top_zone = (
        zones[0]
        if zones
        else {
            "name": None,
            "index": 0,
            "value": 0.0,
            "share": 0.0,
        }
    )

    average_motion = (
        statistics.fmean(motion_values)
        if motion_values
        else 0.0
    )

    peak_motion = (
        max(motion_values)
        if motion_values
        else 0.0
    )

    motion_variability = (
        statistics.pstdev(motion_values)
        if len(motion_values) >= 2
        else 0.0
    )

    average_flow = (
        statistics.fmean(flow_values)
        if flow_values
        else 0.0
    )

    average_confidence = (
        statistics.fmean(confidence_values)
        if confidence_values
        else None
    )

    zone_concentration = float(
        top_zone.get("share", 0.0)
    )

    direction_counter = Counter()

    for record in records:
        direction = (
            record.get("flow_direction")
            or record.get("direction")
        )

        if direction:
            direction_counter[str(direction)] += 1

    main_direction = (
        direction_counter.most_common(1)[0][0]
        if direction_counter
        else None
    )

    event_counter = Counter(
        str(record.get("event_type"))
        for record in records
        if record.get("event_type")
    )

    if average_motion <= 0.05:
        activity_label = "대체로 차분하게 지냈어요"
        activity_sentence = (
            "움직임이 적고 차분한 시간이 "
            "많이 확인됐습니다."
        )
    elif average_motion <= 0.20:
        activity_label = "평소처럼 안정적으로 움직였어요"
        activity_sentence = (
            "과도하게 움직이거나 지나치게 "
            "움직임이 적은 모습 없이 "
            "안정적인 활동이 확인됐습니다."
        )
    elif average_motion <= 0.25:
        activity_label = "비교적 활발하게 움직였어요"
        activity_sentence = (
            "평소보다 활동적인 구간이 "
            "조금 더 많이 확인됐습니다."
        )
    else:
        activity_label = "움직임이 많은 시간이 있었어요"
        activity_sentence = (
            "움직임이 크게 늘어난 구간이 있어 "
            "해당 시간대의 영상을 함께 확인하는 것이 좋습니다."
        )

    if zone_concentration >= 0.60:
        space_label = "한 구역에 활동이 많이 모였어요"
        space_sentence = (
            "특정 구역에서 움직임이 집중된 "
            "모습이 확인됐습니다."
        )
    elif zone_concentration >= 0.42:
        space_label = "자주 이용한 구역이 있었어요"
        space_sentence = (
            "일부 구역을 조금 더 자주 이용했지만 "
            "한곳에만 계속 머문 모습은 아닙니다."
        )
    else:
        space_label = "공간을 비교적 고르게 이용했어요"
        space_sentence = (
            "여러 구역에서 움직임이 고르게 확인됐습니다."
        )

    if motion_variability < 0.10:
        variation_label = "시간별 변화가 크지 않았어요"
        variation_sentence = (
            "시간이 지나도 움직임의 변화 폭이 "
            "크지 않았습니다."
        )
    elif motion_variability < 0.25:
        variation_label = "일부 시간대에 변화가 있었어요"
        variation_sentence = (
            "일부 시간대에서 움직임 차이가 있었지만 "
            "전체적으로는 크게 불안정하지 않았습니다."
        )
    else:
        variation_label = "시간대별 차이가 크게 나타났어요"
        variation_sentence = (
            "움직임의 차이가 큰 구간이 있어 "
            "반복되는 현상인지 추가 확인이 필요합니다."
        )

    headline = activity_label

    description = " ".join(
        [
            activity_sentence,
            space_sentence,
            variation_sentence,
        ]
    )

    chain_records = [
        record
        for record in records
        if record.get("hash")
        and record.get("prev_hash") is not None
    ]

    integrity_available = len(chain_records) >= 2
    integrity_ok = None

    if integrity_available:
        integrity_ok = True

        for previous, current in zip(
            chain_records,
            chain_records[1:],
        ):
            if str(current.get("prev_hash")) != str(
                previous.get("hash")
            ):
                integrity_ok = False
                break

    file_fingerprint = hashlib.sha256(
        events_path.read_bytes()
    ).hexdigest()

    def readable_time(value):
        if value is None:
            return None

        numeric = finite_number(value)

        if numeric is not None and numeric > 1_000_000_000:
            try:
                return datetime.fromtimestamp(
                    numeric
                ).strftime("%Y-%m-%d %H:%M:%S")
            except (ValueError, OSError):
                pass

        return str(value)

    latest_time = None

    for record in reversed(records):
        for key in (
            "time",
            "timestamp",
            "created_at",
            "sealed_at",
        ):
            if record.get(key) is not None:
                latest_time = readable_time(
                    record.get(key)
                )
                break

        if latest_time:
            break

    return {
        "has_data": True,
        "product_code": product_code,
        "source_name": str(
            events_path.relative_to(base_dir)
        ),
        "records_analyzed": len(records),
        "latest_time": latest_time,
        "overview": {
            "headline": headline,
            "description": description,
            "activity_label": activity_label,
            "space_label": space_label,
            "variation_label": variation_label,
        },
        "metrics": {
            "average_motion": round(
                average_motion,
                6,
            ),
            "peak_motion": round(
                peak_motion,
                6,
            ),
            "motion_variability": round(
                motion_variability,
                6,
            ),
            "average_flow": round(
                average_flow,
                6,
            ),
            "zone_concentration": round(
                zone_concentration,
                6,
            ),
            "average_confidence": (
                round(average_confidence, 6)
                if average_confidence is not None
                else None
            ),
        },
        "top_zone": top_zone,
        "zones": zones,
        "main_direction": main_direction,
        "event_types": dict(event_counter),
        "integrity": {
            "available": integrity_available,
            "ok": integrity_ok,
            "checked_records": len(
                chain_records
            ),
            "file_fingerprint": file_fingerprint,
        },
    }

# === EGGTRACE_REAL_ANALYTICS_API_V3_END ===
