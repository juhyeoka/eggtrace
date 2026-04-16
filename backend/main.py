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
    return "차분해요"


def density_text(metrics: dict) -> str:
    avg_compact = metrics.get("avg_compact", 0.0)
    if avg_compact >= 1.2:
        return "적절해요"
    if avg_compact >= 0.7:
        return "조금 몰려 있어요"
    return "한쪽에 모여 있어요"


def change_text(metrics: dict) -> str:
    bvi = metrics.get("bvi", 0.0)
    if bvi < 0.03:
        return "크지 않았어요"
    if bvi < 0.08:
        return "조금 있었어요"
    return "비교적 컸어요"


def human_event_text(tags: list[str]) -> str:
    tag_set = set(tags or [])

    if not tag_set:
        return "큰 이상 없이 차분한 흐름을 보이고 있어요."
    if "ACTIVITY_SPIKE" in tag_set and "CLUSTER_SPREAD" in tag_set:
        return "닭들이 한곳에 치우치지 않고 농장 곳곳을 자연스럽게 움직이고 있어요."
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
        return "🐣 오늘 농장은 전반적으로 차분하고 편안한 흐름을 보여주고 있어요."

    recent_tags: list[str] = []
    for e in events[:5]:
        recent_tags.extend(e.get("tags", []))

    tag_set = set(recent_tags)

    if "ACTIVITY_SPIKE" in tag_set and "CLUSTER_SPREAD" in tag_set:
        return "🐥 오늘은 닭들이 한곳에 치우치지 않고 농장 전체를 자연스럽게 움직이며 지냈어요."
    if "ROI_PEAK" in tag_set and "MOVE_FLOW" in tag_set:
        return "🌿 오늘은 쉬는 구역과 움직이는 흐름이 균형 있게 이어지는 모습이 보였어요."
    if "ACTIVITY_SPIKE" in tag_set:
        return "🐤 오늘은 평소보다 조금 더 활발한 분위기가 느껴졌어요."
    if "CLUSTER_SPREAD" in tag_set:
        return "🍃 오늘은 닭들이 넓게 퍼져 편안하게 움직이는 흐름이 보였어요."
    return "🐣 오늘 농장은 전반적으로 무리 없이 편안한 흐름을 보여주고 있어요."


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

    one_line = build_one_line(events)
    summary = human_event_text([t for e in events[:5] for t in e.get("tags", [])])

    recent_cards = []
    for e in events[:3]:
        ts = e.get("time", 0)
        tstr = (
            time.strftime("%I:%M %p", time.localtime(ts))
            if isinstance(ts, (int, float)) and ts > 946684800
            else "최근 기록"
        )
        msg = human_event_text(e.get("tags", []))
        sev = e.get("severity", "info")
        recent_cards.append(
            (
                tstr,
                msg,
                sev,
                e.get("thumb_path"),
                e.get("heatmap_path"),
                e.get("video_path", "/videos/demo.mp4"),
            )
        )

    while len(recent_cards) < 3:
        recent_cards.append(
            (
                "최근 기록",
                "큰 이상 없이 차분한 흐름을 보이고 있어요.",
                "info",
                None,
                None,
                "/videos/demo.mp4",
            )
        )

    e1, e2, e3 = recent_cards[0], recent_cards[1], recent_cards[2]
    video_source = "/videos/demo.mp4" if (VIDEOS_DIR / "demo.mp4").exists() else ""

    def card_html(ev, icon: str) -> str:
        t, msg, sev, thumb, heat, video = ev
        row_cls = "event-row alert-row" if sev == "alert" else "event-row"

        links = []
        if video_source:
            links.append(f'<a class="mini-btn" href="{video}" target="_blank">영상 보기</a>')
        if thumb:
            links.append(f'<a class="mini-btn" href="{thumb}" target="_blank">탐지 화면</a>')
        if heat:
            links.append(f'<a class="mini-btn" href="{heat}" target="_blank">히트맵</a>')

        return f"""
        <div class="{row_cls}">
          <div class="icon-box">{icon}</div>
          <div style="flex:1">
            <div class="event-time">{html.escape(t)}</div>
            <div class="event-text">{html.escape(msg)}</div>
            <div class="link-row">{''.join(links)}</div>
          </div>
        </div>
        """

    video_html = (
        f'''
        <div class="video-box">
          <video id="mainVideo" controls playsinline muted preload="metadata">
            <source src="{video_source}" type="video/mp4">
          </video>
          <div id="playBadge" class="play">▶</div>
        </div>
        '''
        if video_source
        else '''
        <div class="video-box" style="display:flex;align-items:center;justify-content:center;min-height:320px;color:#5f7466;font-weight:700;">
          아직 표시할 영상이 준비되지 않았어요.
        </div>
        '''
    )

    page = f"""
<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>JCR</title>
<style>
* {{ box-sizing:border-box; }}
body {{
  margin:0;
  background:linear-gradient(180deg,#eef8f1 0%,#f6fbf7 45%,#eef5ef 100%);
  font-family:-apple-system,BlinkMacSystemFont,"Apple SD Gothic Neo",sans-serif;
  color:#173323;
}}
.page {{
  max-width:760px;
  margin:0 auto;
  padding:18px 14px 40px;
}}
.card {{
  background:#fcfffd;
  border-radius:24px;
  padding:18px;
  box-shadow:0 10px 28px rgba(56,108,73,0.10);
  margin-bottom:16px;
  border:1px solid #e0efe4;
}}
.hero {{
  background:linear-gradient(180deg,#e5f7ea,#f9fffb);
}}
.hero h1 {{
  font-size:30px;
  line-height:1.2;
  margin:0 0 10px;
}}
.hero p {{
  color:#5f7466;
  line-height:1.6;
}}
.hero-btn {{
  display:block;
  text-align:center;
  padding:16px;
  border-radius:18px;
  background:linear-gradient(180deg,#c9efd5,#aee4c1);
  color:#173323;
  text-decoration:none;
  font-weight:800;
  margin-top:16px;
}}
.brand {{
  font-size:34px;
  font-weight:900;
  margin-bottom:14px;
  color:#163525;
}}
.section-title {{
  font-size:22px;
  font-weight:900;
  margin-bottom:12px;
}}
.metric {{
  padding:14px;
  background:#edf7f0;
  border-radius:18px;
  margin-bottom:10px;
  border:1px solid #d9ebdf;
}}
.metric .k {{
  font-size:13px;
  color:#888;
  margin-bottom:4px;
}}
.metric .v {{
  font-size:22px;
  font-weight:900;
}}
.cta {{
  display:block;
  width:100%;
  text-align:center;
  text-decoration:none;
  background:#1d6b42;
  color:#ffffff;
  padding:16px;
  border-radius:18px;
  font-weight:900;
  margin-top:14px;
}}
</style>
</head>
<body>
<div class="page">

<div class="brand">JCR.</div>

<div class="card hero">
  <h1>농장의 하루를<br>직접 확인해보세요</h1>
  <p>내가 먹는 계란이 어떤 환경에서 왔는지, 농장의 흐름과 분위기를 직접 보고 확인할 수 있어요.</p>
  <a href="#farm-video" class="hero-btn">농장 실시간 기록 보러가기</a>
</div>

<div class="card" id="farm-video">
  {video_html}
</div>

<div class="card">
  <div class="section-title">오늘의 농장 이야기</div>
  <p style="font-size:20px;font-weight:800;line-height:1.5;">{html.escape(one_line)}</p>
  <p style="line-height:1.7;color:#5f7466;">{html.escape(summary)}</p>
</div>

<div class="card">
  <div class="section-title">오늘의 흐름</div>
  <div class="metric"><div class="k">움직임</div><div class="v">{motion_text(metrics)}</div></div>
  <div class="metric"><div class="k">군집 흐름</div><div class="v">{density_text(metrics)}</div></div>
  <div class="metric"><div class="k">변화 정도</div><div class="v">{change_text(metrics)}</div></div>
</div>

<div class="card">
  <div class="section-title">왜 더 믿을 수 있을까요?</div>
  <p style="line-height:1.7;color:#5f7466;">
    JCR은 단순히 계란만 판매하는 것이 아니라,
    소비자가 직접 농장의 흐름을 보고 안심하고 선택할 수 있도록
    투명한 브랜드 경험을 제공합니다.
  </p>
</div>

<div class="card">
  <div class="section-title">정기 구독</div>
  <p style="line-height:1.7;color:#5f7466;">
    오늘 확인한 농장 환경 그대로,
    더 편하게 JCR 계란을 집에서 받아보세요.
  </p>
  <a href="https://junada040828.cafe24.com/skin-skin7" target="_blank" class="cta">JCR 계란 구독하기</a>
</div>

<div class="card">
  <div class="section-title">최근 패턴 변화</div>
  {card_html(e1, "🌿")}
  {card_html(e2, "🐔")}
  {card_html(e3, "🥚")}
</div>

</div>
</body>
</html>
"""
    return HTMLResponse(page)

