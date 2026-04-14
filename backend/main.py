from __future__ import annotations

import html
import json
import statistics
import time
from pathlib import Path

import cv2
import numpy as np
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

for d in [DATA_DIR, STATIC_DIR, VIDEOS_DIR, THUMBS_DIR, HEATMAPS_DIR]:
    d.mkdir(parents=True, exist_ok=True)

app.mount("/videos", StaticFiles(directory=str(VIDEOS_DIR)), name="videos")
app.mount("/thumbs", StaticFiles(directory=str(THUMBS_DIR)), name="thumbs")
app.mount("/heatmaps", StaticFiles(directory=str(HEATMAPS_DIR)), name="heatmaps")


def nice_tag(tag: str) -> str:
    mapping = {
        "ACTIVITY_SPIKE": "활동 증가",
        "MOVE_FLOW": "이동 흐름 증가",
        "CLUSTER_SPREAD": "군집 분산 증가",
        "ROI_PEAK": "집중 구간 활성화",
        "ROI_PEAK_MED": "집중 구간 활성화",
        "HIGH_ACTIVITY": "활동 증가",
        "MID_ACTIVITY": "중간 활동",
        "LOW_ACTIVITY": "낮은 활동",
    }
    return mapping.get(tag, tag.replace("_", " ").title())


def detect_objects(frame: np.ndarray, bgsub) -> tuple[list[tuple[int, int, int, int]], list[tuple[int, int]]]:
    fg = bgsub.apply(frame, learningRate=0)
    _, fg = cv2.threshold(fg, 200, 255, cv2.THRESH_BINARY)

    k1 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    k2 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (11, 11))
    fg = cv2.morphologyEx(fg, cv2.MORPH_OPEN, k1)
    fg = cv2.morphologyEx(fg, cv2.MORPH_CLOSE, k2)

    contours, _ = cv2.findContours(fg, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    boxes = []
    centers = []
    for c in contours:
        area = cv2.contourArea(c)
        if area < 100 or area > 16000:
            continue
        x, y, w, h = cv2.boundingRect(c)
        if w < 10 or h < 10:
            continue
        boxes.append((x, y, w, h))
        centers.append((x + w // 2, y + h // 2))
    return boxes, centers


def build_heatmap(h: int, w: int, centers: list[tuple[int, int]]) -> tuple[np.ndarray, np.ndarray]:
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


def make_tags(motion_ratio: float, flow_mean: float, compactness: float, roi_peak: float) -> list[str]:
    tags = []
    if motion_ratio >= 0.14:
        tags.append("ACTIVITY_SPIKE")
    if flow_mean >= 2.3:
        tags.append("MOVE_FLOW")
    if compactness >= 2.0:
        tags.append("CLUSTER_SPREAD")
    if roi_peak >= 0.10:
        tags.append("ROI_PEAK")
    return tags


def analyze_demo_video_if_needed() -> None:
    video_path = VIDEOS_DIR / "demo.mp4"
    if not video_path.exists():
        return

    need_build = True
    if EVENTS_FILE.exists():
        try:
            if EVENTS_FILE.stat().st_size > 0:
                need_build = False
        except Exception:
            pass

    if not need_build:
        return

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        return

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    sample_step = max(1, int(fps * 2.0))

    bgsub = cv2.createBackgroundSubtractorMOG2(history=500, varThreshold=36, detectShadows=False)

    prev_gray = None
    idx = 0
    rows = []

    while True:
        ok, frame = cap.read()
        if not ok:
            break

        bgsub.apply(frame, learningRate=0.01)

        if idx % sample_step != 0:
            idx += 1
            continue

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (7, 7), 0)

        if prev_gray is None:
            prev_gray = gray
            idx += 1
            continue

        boxes, centers = detect_objects(frame, bgsub)

        diff = cv2.absdiff(prev_gray, gray)
        _, th = cv2.threshold(diff, 25, 255, cv2.THRESH_BINARY)
        motion_ratio = float(np.count_nonzero(th)) / float(th.size)

        flow = cv2.calcOpticalFlowFarneback(
            prev_gray, gray, None,
            0.5, 3, 15, 3, 5, 1.2, 0
        )
        mag = np.sqrt(flow[..., 0] ** 2 + flow[..., 1] ** 2)
        flow_mean = float(np.mean(mag))

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

        _, heat_color = build_heatmap(frame.shape[0], frame.shape[1], centers)

        uid = f"ev_{idx}"
        thumb_path = THUMBS_DIR / f"{uid}.jpg"
        heatmap_path = HEATMAPS_DIR / f"{uid}.jpg"

        thumb = frame.copy()
        for (x, y, bw, bh) in boxes:
            cv2.rectangle(thumb, (x, y), (x + bw, y + bh), (0, 255, 0), 2)
        for (cx, cy) in centers:
            cv2.circle(thumb, (cx, cy), 4, (0, 255, 255), -1)

        cv2.imwrite(str(thumb_path), thumb)
        cv2.imwrite(str(heatmap_path), heat_color)

        rows.append({
            "uid": uid,
            "motion_ratio": round(motion_ratio, 4),
            "flow_mean_mag": round(flow_mean, 4),
            "cluster_compactness": round(compactness, 4),
            "roi_peak": round(roi_peak, 4),
            "count_estimate": len(centers),
            "tags": make_tags(motion_ratio, flow_mean, compactness, roi_peak),
            "thumb_path": f"/thumbs/{uid}.jpg",
            "heatmap_path": f"/heatmaps/{uid}.jpg",
            "video_path": "/videos/demo.mp4",
        })

        prev_gray = gray
        idx += 1

    cap.release()

    if not rows:
        return

    now = time.time()
    total = len(rows)
    for i, row in enumerate(rows):
        offset = (total - i) * 1800
        row["time"] = now - offset
        row["farm_id"] = "farm1"
        row["lot_id"] = "lotA"
        row["severity"] = "alert" if len(row["tags"]) >= 3 else "info"

    with EVENTS_FILE.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def read_events(farm_id: str, lot_id: str, days: int) -> list[dict]:
    if not EVENTS_FILE.exists():
        return []

    now = time.time()
    rows = []
    for line in EVENTS_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            e = json.loads(line)
        except Exception:
            continue

        if farm_id and e.get("farm_id") != farm_id:
            continue
        if lot_id and e.get("lot_id") != lot_id:
            continue

        ts = e.get("time", 0)
        if isinstance(ts, (int, float)) and ts > 946684800:
            if now - ts > days * 86400:
                continue

        rows.append(e)

    rows.sort(key=lambda x: x.get("time", 0), reverse=True)
    return rows


def build_summary(events: list[dict]) -> str:
    if not events:
        return "영상 분석 데이터가 아직 충분하지 않습니다."

    tags = []
    for e in events[:12]:
        tags.extend(e.get("tags", []))

    tag_set = set(tags)
    parts = []

    if "ACTIVITY_SPIKE" in tag_set:
        parts.append("일부 시간대에 활동량 증가 패턴이 관찰되었습니다")
    if "CLUSTER_SPREAD" in tag_set:
        parts.append("군집이 넓게 분산되는 흐름이 확인되었습니다")
    if "MOVE_FLOW" in tag_set:
        parts.append("이동 흐름이 평소보다 활발한 구간이 있었습니다")
    if "ROI_PEAK" in tag_set or "ROI_PEAK_MED" in tag_set:
        parts.append("특정 구간에 개체가 집중되는 장면이 감지되었습니다")

    if not parts:
        return "최근 구간에서는 급격한 이상 패턴 없이 비교적 안정적인 활동 흐름이 유지되었습니다."

    return "최근 분석 결과, " + " / ".join(parts) + "."


def compute_metrics(events: list[dict]) -> dict:
    if not events:
        return {
            "avg_motion": 0.0,
            "avg_flow": 0.0,
            "avg_compact": 0.0,
            "bvi": 0.0,
            "score": 0,
            "label": "데이터 없음",
        }

    motions = [float(e.get("motion_ratio", 0) or 0) for e in events]
    flows = [float(e.get("flow_mean_mag", 0) or 0) for e in events]
    compacts = [float(e.get("cluster_compactness", 0) or 0) for e in events]

    avg_motion = sum(motions) / len(motions)
    avg_flow = sum(flows) / len(flows)
    avg_compact = sum(compacts) / len(compacts)
    bvi = statistics.pstdev(motions) if len(motions) > 1 else 0.0

    score = 92
    score -= min(18, int(avg_motion * 35))
    score -= min(16, int(avg_flow * 0.7))
    score -= min(14, int(bvi * 100))
    score = max(58, min(96, score))

    if score >= 85:
        label = "안정적"
    elif score >= 70:
        label = "양호"
    else:
        label = "관찰 필요"

    return {
        "avg_motion": avg_motion,
        "avg_flow": avg_flow,
        "avg_compact": avg_compact,
        "bvi": bvi,
        "score": score,
        "label": label,
    }


@app.on_event("startup")
def startup():
    analyze_demo_video_if_needed()


@app.get("/", response_class=HTMLResponse)
def root():
    return RedirectResponse("/p/EGG-0001")


@app.get("/events", response_class=JSONResponse)
def events(days: int = 30, farm_id: str = "farm1", lot_id: str = "lotA"):
    rows = read_events(farm_id=farm_id, lot_id=lot_id, days=days)
    return JSONResponse({"count": len(rows), "events": rows})


@app.get("/p/{code}", response_class=HTMLResponse)
def product_page(code: str, days: int = 30, farm_id: str = "farm1", lot_id: str = "lotA"):
    events = read_events(farm_id=farm_id, lot_id=lot_id, days=days)
    metrics = compute_metrics(events)
    summary = build_summary(events)

    if metrics["avg_flow"] >= 4:
        flow_state = "활발해요"
    elif metrics["avg_flow"] >= 2:
        flow_state = "보통이에요"
    else:
        flow_state = "차분해요"

    if metrics["avg_compact"] >= 1.2:
        compact_state = "적절해요"
    elif metrics["avg_compact"] >= 0.7:
        compact_state = "조금 몰려 있어요"
    else:
        compact_state = "한쪽에 몰려 있어요"

    if metrics["score"] >= 90:
        stable_state = "안정적이에요"
    elif metrics["score"] >= 75:
        stable_state = "대체로 괜찮아요"
    else:
        stable_state = "조금 더 볼 필요가 있어요"

    if metrics["bvi"] < 0.03:
        bvi_state = "크지 않았어요"
    elif metrics["bvi"] < 0.08:
        bvi_state = "조금 있었어요"
    else:
        bvi_state = "비교적 컸어요"

    recent_cards = []
    for e in events[:3]:
        ts = e.get("time", 0)
        tstr = time.strftime("%I:%M %p", time.localtime(ts)) if isinstance(ts, (int, float)) and ts > 946684800 else "최근 기록"
        tags = e.get("tags", [])
        msg = " / ".join(nice_tag(t) for t in tags[:2]) if tags else "특이 패턴 없음"
        sev = e.get("severity", "info")
        recent_cards.append((tstr, msg, sev, e.get("thumb_path"), e.get("heatmap_path"), e.get("video_path", "/videos/demo.mp4")))

    while len(recent_cards) < 3:
        recent_cards.append(("최근 기록", "특이 패턴 없음", "info", None, None, "/videos/demo.mp4"))

    e1, e2, e3 = recent_cards[0], recent_cards[1], recent_cards[2]

    def card_html(ev, icon):
        t, msg, sev, thumb, heat, video = ev
        alert_cls = " alert-row" if sev == "alert" else ""
        links = [f'<a class="mini-btn" href="{video}" target="_blank">영상 보기</a>']
        if thumb:
            links.append(f'<a class="mini-btn" href="{thumb}" target="_blank">탐지 화면</a>')
        if heat:
            links.append(f'<a class="mini-btn" href="{heat}" target="_blank">히트맵</a>')
        return f"""
        <div class="event-row{alert_cls}">
          <div class="icon-box">{icon}</div>
          <div style="flex:1">
            <div class="event-time">{html.escape(t)}</div>
            <div class="event-text">{html.escape(msg)}</div>
            <div class="link-row">{''.join(links)}</div>
          </div>
        </div>
        """

    # 소비자용 문장 변환
    if metrics["score"] >= 85:
        one_line = "오늘 닭들은 넓게 움직이며 안정적인 환경에서 활동했습니다 🟢"
        move_text = "움직임: 활발함"
        dense_text = "밀집도: 적절함"
        safe_text = "안정성: 안정적"
    elif metrics["score"] >= 70:
        one_line = "오늘 닭들은 전반적으로 안정적이지만, 일부 시간대에 활동량이 증가했어요 🟡"
        move_text = "움직임: 보통보다 많음"
        dense_text = "밀집도: 약간 몰림"
        safe_text = "안정성: 양호"
    else:
        one_line = "오늘 닭들은 일부 구간에서 평소보다 많이 몰리거나 활발하게 움직였어요 🟠"
        move_text = "움직임: 변화 큼"
        dense_text = "밀집도: 몰림 있음"
        safe_text = "안정성: 관찰 필요"

    def human_event_text(msg: str) -> str:
        text = msg
        text = text.replace("활동 증가", "닭들이 평소보다 더 활발하게 움직이고 있어요")
        text = text.replace("이동 흐름 증가", "닭들의 움직임이 평소보다 커졌어요")
        text = text.replace("군집 분산 증가", "닭들이 한 곳에 몰리지 않고 넓게 움직이고 있어요")
        text = text.replace("집중 구간 활성화", "특정 구역에 닭들이 모이는 경향이 있어요")
        text = text.replace("특이 패턴 없음", "큰 이상 없이 안정적인 흐름을 보이고 있어요")
        return text

    e1_h = human_event_text(e1[1])
    e2_h = human_event_text(e2[1])
    e3_h = human_event_text(e3[1])

    page = f"""
<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
  <title>JCR</title>
  <style>
    * {{ box-sizing:border-box; }}
    body {{
      margin:0;
      background:#f3f4f2;
      font-family:-apple-system,BlinkMacSystemFont,"Apple SD Gothic Neo","Noto Sans KR",sans-serif;
      color:#111;
    }}
    .page {{
      max-width:1180px;
      margin:0 auto;
      padding:28px 20px 40px;
    }}
    .top {{
      display:flex;
      justify-content:space-between;
      align-items:center;
      margin-bottom:18px;
    }}
    .logo {{
      font-size:38px;
      font-weight:900;
      letter-spacing:-1.5px;
    }}
    .menu {{
      font-size:34px;
      color:#444;
      line-height:1;
    }}
    .headline {{
      font-size:34px;
      font-weight:900;
      letter-spacing:-0.8px;
      margin:0 0 10px;
    }}
    .sub {{
      color:#666;
      font-size:15px;
      margin-bottom:20px;
    }}
    .layout {{
      display:grid;
      grid-template-columns:1.2fr 0.8fr;
      gap:18px;
    }}
    .card {{
      background:#fff;
      border-radius:28px;
      padding:18px;
      box-shadow:0 6px 18px rgba(0,0,0,0.06);
      margin-bottom:18px;
    }}
    .video-box {{
      position:relative;
      overflow:hidden;
      border-radius:24px;
      background:#ddd;
    }}
    video {{
      width:100%;
      display:block;
      border-radius:24px;
      background:#111;
    }}
    .play {{
      position:absolute;
      left:50%;
      top:50%;
      transform:translate(-50%,-50%);
      width:82px;
      height:82px;
      border-radius:50%;
      background:#b8efd4;
      display:flex;
      align-items:center;
      justify-content:center;
      font-size:36px;
      color:#1f4b39;
      box-shadow:0 8px 24px rgba(112,220,176,0.35);
      pointer-events:none;
      transition:opacity .2s ease;
    }}
    .play.hidden {{
      opacity:0;
    }}
    .section-title {{
      font-size:22px;
      font-weight:800;
      margin-bottom:8px;
      letter-spacing:-0.4px;
    }}
    .section-sub {{
      color:#666;
      font-size:14px;
      margin-bottom:12px;
      line-height:1.5;
    }}
    .summary-hero {{
      background:#f7fbf8;
      border:1px solid #dceee2;
      border-radius:22px;
      padding:18px;
      margin-bottom:14px;
    }}
    .summary-hero .big {{
      font-size:24px;
      font-weight:900;
      line-height:1.45;
      letter-spacing:-0.5px;
      margin-bottom:8px;
    }}
    .summary-hero .small {{
      color:#5f6b63;
      font-size:15px;
      line-height:1.7;
    }}
    .score-row {{
      display:flex;
      gap:10px;
      flex-wrap:wrap;
      margin:8px 0 14px;
    }}
    .pill {{
      display:inline-flex;
      align-items:center;
      gap:6px;
      padding:10px 14px;
      border-radius:999px;
      background:#f7f7f7;
      font-weight:700;
      font-size:14px;
      border:1px solid #ececec;
    }}
    .human-metrics {{
      display:grid;
      grid-template-columns:repeat(3, 1fr);
      gap:10px;
      margin-top:10px;
    }}
    .human-box {{
      background:#fafafa;
      border:1px solid #efefef;
      border-radius:18px;
      padding:14px;
    }}
    .human-box .label {{
      font-size:13px;
      color:#7a7a7a;
      margin-bottom:8px;
    }}
    .human-box .value {{
      font-size:20px;
      font-weight:900;
      letter-spacing:-0.4px;
    }}
    .mini-chart {{
      width:100%;
      height:150px;
      border-radius:20px;
      background:linear-gradient(180deg,#fafafa,#f1f1f1);
      overflow:hidden;
      margin-top:14px;
    }}
    .mini-chart svg {{
      width:100%;
      height:100%;
      display:block;
    }}
    .metrics {{
      display:grid;
      grid-template-columns:repeat(2, 1fr);
      gap:10px;
    }}
    .metric {{
      background:#fafafa;
      border:1px solid #efefef;
      border-radius:18px;
      padding:14px;
    }}
    .metric .k {{
      font-size:13px;
      color:#7a7a7a;
      margin-bottom:6px;
    }}
    .metric .v {{
      font-size:24px;
      font-weight:900;
      letter-spacing:-0.5px;
    }}
    .event-row {{
      background:#fff;
      border-radius:20px;
      box-shadow:0 2px 8px rgba(0,0,0,0.05);
      padding:12px 14px;
      display:flex;
      align-items:flex-start;
      gap:12px;
      margin-bottom:12px;
    }}
    .icon-box {{
      width:48px;
      height:48px;
      border-radius:16px;
      background:#d9f5e7;
      display:flex;
      align-items:center;
      justify-content:center;
      font-size:22px;
      color:#2b5c49;
      flex:0 0 auto;
    }}
    .event-time {{
      color:#8a8a8a;
      font-size:13px;
      margin-bottom:3px;
    }}
    .event-text {{
      font-size:16px;
      font-weight:700;
      line-height:1.55;
      margin-bottom:8px;
      word-break:keep-all;
    }}
    .alert-row {{
      background:#ff5d5d;
      color:#fff;
    }}
    .alert-row .icon-box {{
      background:rgba(255,255,255,0.18);
      color:#fff;
    }}
    .alert-row .event-time {{
      color:#ffe4e4;
    }}
    .link-row {{
      display:flex;
      gap:8px;
      flex-wrap:wrap;
    }}
    .mini-btn {{
      display:inline-block;
      padding:8px 12px;
      border-radius:999px;
      text-decoration:none;
      font-size:13px;
      font-weight:700;
      background:#f2f2f2;
      color:#111;
      border:1px solid #e5e5e5;
    }}
    .alert-row .mini-btn {{
      background:rgba(255,255,255,0.18);
      color:#fff;
      border:1px solid rgba(255,255,255,0.28);
    }}
    @media (max-width:900px) {{
      .layout {{ grid-template-columns:1fr; }}
      .headline {{ font-size:28px; }}
      .page {{ padding:18px 14px 28px; }}
      .human-metrics {{ grid-template-columns:1fr; }}
    }}
  </style>
</head>
<body>
  <div class="page">
    <a href="https://smartstore.naver.com/" style="
      display:inline-flex;
      align-items:center;
      gap:6px;
      text-decoration:none;
      color:#111;
      font-size:14px;
      font-weight:700;
      margin-bottom:14px;
    ">← 구매 페이지로 돌아가기</a>

    <div class="top">
      <div class="logo">JCR.</div>
      <div class="menu">☰</div>
    </div>

    <div class="headline">닭의 하루 요약</div>
    <div class="sub">AI가 실제 영상 흐름을 바탕으로 오늘의 환경을 쉽게 정리했어요.</div>

    <div class="layout">
      <div>
        <div class="card">
          <div class="video-box">
            <video id="mainVideo" controls playsinline muted preload="metadata">
              <source src="/videos/demo.mp4" type="video/mp4">
            </video>
            <div id="playBadge" class="play">▶</div>
          </div>
        </div>

        <div class="card">
          <div class="section-title">오늘 한 줄 요약</div>

          <div class="summary-hero">
            <div class="big">{html.escape(one_line)}</div>
            <div class="small">{html.escape(summary)}</div>
          </div>

          <div class="human-metrics">
            <div class="human-box">
              <div class="label">움직임</div>
              <div class="value">{html.escape(move_text)}</div>
            </div>
            <div class="human-box">
              <div class="label">밀집도</div>
              <div class="value">{html.escape(dense_text)}</div>
            </div>
            <div class="human-box">
              <div class="label">안정성</div>
              <div class="value">{html.escape(safe_text)}</div>
            </div>
          </div>

          <div class="score-row">
            
            <div class="pill">이벤트 {len(events)}건</div>
          </div>

          <div class="mini-chart">
            <svg viewBox="0 0 100 40" preserveAspectRatio="none">
              <polyline fill="none" stroke="#111" stroke-width="1.2"
                points="0,27 8,25 16,26 24,18 32,12 40,19 48,24 56,18 64,10 72,8 80,9 88,12 100,18"/>
              <polyline fill="none" stroke="#777" stroke-width="0.8"
                points="0,30 12,28 24,26 36,20 48,14 60,22 72,28 84,29 100,27"/>
              <line x1="0" y1="34" x2="100" y2="34" stroke="#ddd" stroke-width="0.6"/>
              <line x1="0" y1="26" x2="100" y2="26" stroke="#eee" stroke-width="0.6"/>
              <line x1="0" y1="18" x2="100" y2="18" stroke="#eee" stroke-width="0.6"/>
              <line x1="0" y1="10" x2="100" y2="10" stroke="#eee" stroke-width="0.6"/>
            </svg>
          </div>
        </div>
      </div>

      <div>
        <div class="card">
          <div class="section-title">숫자로 보는 오늘</div>
          <div class="metrics">
            <div class="metric"><div class="k">움직임</div><div class="v">{flow_state}</div></div>
            <div class="metric"><div class="k">모여 있는 정도</div><div class="v">{compact_state}</div></div>
            <div class="metric"><div class="k">전체 상태</div><div class="v">{stable_state}</div></div>
            <div class="metric"><div class="k">패턴 흔들림</div><div class="v">{metrics["bvi"]:.3f}</div></div>
          </div>
        </div>

        <div class="card">
          <div class="section-title">최근 패턴 변화</div>
          {card_html((e1[0], e1_h, e1[2], e1[3], e1[4], e1[5]), "🪺")}
          {card_html((e2[0], e2_h, e2[2], e2[3], e2[4], e2[5]), "♡")}
          {card_html((e3[0], e3_h, e3[2], e3[3], e3[4], e3[5]), "⚠")}
        </div>
      </div>
    </div>
  </div>

  <script>
    const video = document.getElementById("mainVideo");
    const badge = document.getElementById("playBadge");

    function hideBadge() {{
      badge.classList.add("hidden");
    }}

    function showBadge() {{
      if (video.paused) {{
        badge.classList.remove("hidden");
      }}
    }}

    video.addEventListener("play", hideBadge);
    video.addEventListener("playing", hideBadge);
    video.addEventListener("pause", showBadge);
    video.addEventListener("ended", showBadge);
  </script>
</body>
</html>
"""
    return HTMLResponse(page)
