from pathlib import Path
import json
import requests

EVENTS = Path("data/events.jsonl")
SERVER = "https://eggtrace-82hy.onrender.com/ingest/event"

if not EVENTS.exists():
    raise SystemExit("❌ data/events.jsonl 없음")

count = 0
for line in EVENTS.read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if not line:
        continue
    e = json.loads(line)

    # Render에는 우선 이벤트/지표만 올림
    payload = {
        "time": e.get("time"),
        "uid": e.get("uid"),
        "farm_id": e.get("farm_id", "farm1"),
        "lot_id": e.get("lot_id", "lotA"),
        "event_type": e.get("event_type", "activity_detected"),
        "motion_ratio": e.get("motion_ratio", 0),
        "flow_mean_mag": e.get("flow_mean_mag", 0),
        "cluster_compactness": e.get("cluster_compactness", 0),
        "roi_peak": e.get("roi_peak", 0),
        "thumb_path": None,
        "heatmap_path": None,
        "clip_path": None,
        "tags": e.get("tags", []),
        "character": e.get("character", "균형"),
        "severity": e.get("severity", "warning"),
        "video_source": e.get("video_source", "")
    }

    try:
        r = requests.post(SERVER, json=payload, timeout=20)
        if r.ok:
            count += 1
            print("sent", count, payload["uid"])
        else:
            print("failed", r.status_code, r.text[:200])
    except Exception as ex:
        print("error", ex)

print(f"✅ 업로드 완료: {count}건")
