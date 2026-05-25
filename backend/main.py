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
        return "✦ AI가 영상 속 활동량 변화와 군집 흐름을 분석하고 있습니다."

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
                e.get("video_path", "/videos/ai_event_1.mp4"),
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
                f"/videos/ai_event_{len(recent_cards)+1}.mp4",
            )
        )

    e1, e2, e3 = recent_cards[0], recent_cards[1], recent_cards[2]
    
    video_source = "/videos/demo.mp4"

    if (VIDEOS_DIR / "ai_event_1.mp4").exists():
        video_source = "/videos/ai_event_1.mp4"


    def card_html(ev, icon: str) -> str:
        t, msg, sev, thumb, heat, video = ev
        row_cls = "event-row alert-row" if sev == "alert" else "event-row"

        links = []
        if video:
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
<title>EYERAN</title>
<style>
* {{ box-sizing:border-box; }}

:root {{
  --bg:#FFFBEA;
  --bg2:#FFFDF5;
  --card:#ffffff;
  --line:#F6E7B0;
  --text:#4A3B00;
  --sub:#7A6A2F;
  --mint:#FFF3C4;
  --mint2:#FFE89A;
  --deep:#F5B700;
  --shadow:0 12px 28px rgba(245,183,0,0.10);
  --radius:26px;
}}

body {{
  margin:0;
  background:linear-gradient(180deg,var(--bg) 0%, var(--bg2) 45%, #eef4ef 100%);
  color:var(--text);
  font-family:-apple-system,BlinkMacSystemFont,"Apple SD Gothic Neo","Noto Sans KR",sans-serif;
}}

.page {{
  max-width:1180px;
  margin:0 auto;
  padding:24px 18px 48px;
}}

.topbar {{
  display:flex;
  justify-content:space-between;
  align-items:center;
  margin-bottom:18px;
}}

.brand {{
  font-size:42px;
  font-weight:900;
  letter-spacing:-1.6px;
  color:#4A3B00;
}}

.back-link {{
  display:inline-flex;
  align-items:center;
  gap:8px;
  text-decoration:none;
  color:var(--deep);
  font-size:14px;
  font-weight:900;
  background:rgba(255,255,255,0.8);
  border:1px solid var(--line);
  border-radius:999px;
  padding:11px 16px;
  box-shadow:0 6px 16px rgba(245,183,0,0.06);
}}

.hero-grid {{
  display:grid;
  grid-template-columns:1.02fr 0.98fr;
  gap:18px;
  align-items:stretch;
  margin-bottom:18px;
}}

.card {{
  background:var(--card);
  border:1px solid var(--line);
  border-radius:var(--radius);
  box-shadow:var(--shadow);
}}

.hero-copy-card {{
  padding:28px 24px;
  display:flex;
  flex-direction:column;
  justify-content:center;
  background:linear-gradient(180deg,#FFF8D9 0%, #ffffff 100%);
}}

.hero-badge {{
  display:inline-flex;
  align-items:center;
  gap:6px;
  width:max-content;
  padding:8px 12px;
  border-radius:999px;
  background:#FFFDF5;
  border:1px solid var(--line);
  font-size:12px;
  font-weight:900;
  color:#7A6A2F;
  margin-bottom:14px;
}}

.hero-title {{
  font-size:42px;
  line-height:1.12;
  letter-spacing:-1.4px;
  font-weight:900;
  margin:0 0 12px;
  color:#4A3B00;
}}

.hero-sub {{
  font-size:16px;
  line-height:1.75;
  color:var(--sub);
  margin:0 0 20px;
}}

.hero-cta {{
  display:inline-flex;
  align-items:center;
  justify-content:center;
  width:max-content;
  min-width:220px;
  padding:16px 22px;
  border-radius:18px;
  background:#F5B700;
  color:#fff;
  text-decoration:none;
  font-weight:900;
  font-size:16px;
  box-shadow:0 10px 20px rgba(245,183,0,0.18);
}}

.hero-note {{
  margin-top:18px;
  padding:14px 16px;
  background:#FFFDF5;
  border:1px solid var(--line);
  border-radius:18px;
  color:var(--sub);
  font-size:14px;
  line-height:1.7;
}}

.video-card {{
  padding:14px;
  background:linear-gradient(180deg,#FFFDF0,#ffffff);
}}

.video-label {{
  display:flex;
  align-items:center;
  gap:8px;
  font-size:14px;
  font-weight:900;
  color:#7A6A2F;
  margin:0 0 10px;
}}

.video-box {{
  position:relative;
  overflow:hidden;
  border-radius:22px;
  background:#F6E7B0;
  min-height:340px;
  max-height:420px;
}}

video {{
  width:100%;
  height:100%;
  min-height:340px;
  max-height:420px;
  object-fit:cover;
  display:block;
  border-radius:22px;
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
  background:rgba(255,248,217,0.97);
  display:flex;
  align-items:center;
  justify-content:center;
  font-size:34px;
  color:#E0A100;
  box-shadow:0 10px 24px rgba(245,183,0,0.20);
  pointer-events:none;
  transition:opacity .2s ease;
}}

.play.hidden {{
  opacity:0;
}}

.summary-card {{
  padding:22px;
  margin-bottom:18px;
}}

.section-title {{
  font-size:28px;
  font-weight:900;
  letter-spacing:-0.8px;
  margin:0 0 12px;
}}

.summary-main {{
  font-size:24px;
  line-height:1.5;
  font-weight:900;
  letter-spacing:-0.5px;
  margin:0 0 10px;
}}

.summary-sub {{
  font-size:15px;
  line-height:1.75;
  color:var(--sub);
  margin:0 0 16px;
}}

.metrics {{
  display:grid;
  grid-template-columns:repeat(3,1fr);
  gap:12px;
}}

.metric {{
  padding:16px;
  background:#FFFBEA;
  border:1px solid #F6E7B0;
  border-radius:20px;
}}

.metric .k {{
  font-size:12px;
  font-weight:900;
  color:#7A6A2F;
  margin-bottom:8px;
}}

.metric .v {{
  font-size:26px;
  font-weight:900;
  letter-spacing:-0.7px;
  margin-bottom:6px;
}}

.metric .d {{
  font-size:13px;
  line-height:1.6;
  color:var(--sub);
}}

.lower-grid {{
  display:grid;
  grid-template-columns:0.95fr 1.05fr;
  gap:18px;
}}

.info-card {{
  padding:22px;
}}

.info-head {{
  font-size:30px;
  line-height:1.12;
  font-weight:900;
  letter-spacing:-1px;
  margin:0 0 10px;
}}

.info-copy {{
  font-size:15px;
  line-height:1.75;
  color:var(--sub);
  margin:0 0 16px;
}}

.feature-list {{
  display:grid;
  gap:12px;
}}

.feature {{
  display:flex;
  gap:12px;
  align-items:flex-start;
  padding:14px;
  background:#FFFDF5;
  border:1px solid var(--line);
  border-radius:18px;
}}

.feature-icon {{
  width:42px;
  height:42px;
  border-radius:14px;
  background:var(--mint);
  display:flex;
  align-items:center;
  justify-content:center;
  font-size:20px;
  flex:0 0 auto;
}}

.feature-title {{
  font-size:16px;
  font-weight:900;
  margin:0 0 4px;
}}

.feature-copy {{
  font-size:13px;
  line-height:1.7;
  color:var(--sub);
  margin:0;
}}

.subscribe-card {{
  padding:22px;
  margin-bottom:18px;
  background:linear-gradient(180deg,#FFF8D9,#ffffff);
}}

.subscribe-head {{
  display:flex;
  align-items:center;
  justify-content:space-between;
  gap:10px;
  margin-bottom:8px;
}}

.subscribe-emoji {{
  font-size:40px;
  line-height:1;
}}

.subscribe-copy {{
  font-size:15px;
  line-height:1.75;
  color:var(--sub);
  margin:0 0 16px;
}}

.cta {{
  display:block;
  width:100%;
  text-align:center;
  text-decoration:none;
  background:#F5B700;
  color:#fff;
  padding:18px;
  border-radius:18px;
  font-size:17px;
  font-weight:900;
  letter-spacing:-0.3px;
  box-shadow:0 10px 20px rgba(245,183,0,0.18);
}}

.events-card {{
  padding:22px;
}}

.event-row {{
  background:#FFFDF5;
  border-radius:20px;
  padding:14px;
  display:flex;
  align-items:flex-start;
  gap:12px;
  margin-bottom:12px;
  border:1px solid #F6E7B0;
}}

.event-row:last-child {{
  margin-bottom:0;
}}

.alert-row {{
  background:#FFF3C4;
  border:1px solid #F6E7B0;
}}

.icon-box {{
  width:46px;
  height:46px;
  border-radius:14px;
  background:#FFE89A;
  display:flex;
  align-items:center;
  justify-content:center;
  font-size:21px;
  color:#E0A100;
  flex:0 0 auto;
}}

.event-time {{
  color:#7A6A2F;
  font-size:12px;
  font-weight:900;
  margin-bottom:4px;
}}

.event-text {{
  font-size:15px;
  line-height:1.65;
  font-weight:800;
  color:#4A3B00;
  margin-bottom:10px;
  word-break:keep-all;
}}

.link-row {{
  display:flex;
  gap:10px;
  flex-wrap:wrap;
  margin-top:8px;
}}

.mini-btn {{
  display:inline-flex;
  align-items:center;
  justify-content:center;
  min-width:88px;
  padding:9px 14px;
  border-radius:999px;
  text-decoration:none;
  font-size:12px;
  font-weight:900;
  background:#FFFBEA;
  color:#F5B700;
  border:1px solid #F6E7B0;
  white-space:nowrap;
}}

@media (max-width: 900px) {{
  .page {{
    max-width:460px;
    padding:18px 14px 34px;
  }}

  .hero-grid,
  .lower-grid {{
    grid-template-columns:1fr;
  }}

  .hero-title {{
    font-size:34px;
  }}

  .metrics {{
    grid-template-columns:1fr;
  }}

  .video-box,
  video {{
    min-height:240px;
    max-height:300px;
  }}
}}
</style>
</head>
<body>
<div class="page">
  <div class="topbar"><div class="brand">EYERAN</div></div>
    
  </div>

  <div class="hero-grid">
    <div class="card hero-copy-card">
      <div class="hero-badge">✦ EYERAN Farm Story</div>
      <h1 class="hero-title">내가 먹는 계란,<br>농장 이야기를 보고 선택하세요</h1>
      <p class="hero-sub">단순히 계란을 판매하는 것이 아니라, 소비자가 직접 농장의 흐름과 분위기를 보고 안심하고 선택할 수 있는 경험을 만들고 싶었습니다.</p>
      <a href="https://www.instagram.com/eyeran_egg?igsh=cmtzaDliN3Nhdzdt&utm_source=qr" target="_blank" class="hero-cta">✦ EYERAN 인스타그램</a>
      <div class="hero-note">이번주 농장 기록, 최근 흐름, 변화 요약까지 한 화면에서 편하게 확인할 수 있어요. 보고 고르는 경험이 EYERAN의 핵심입니다 ✨</div>
    </div>

    <div class="card video-card" id="farm-video">
      <div class="video-label">🎥 이번주 농장 영상</div>
      {video_html}
    </div>
  </div>

  <div class="card summary-card">
    <div class="section-title">✦ 이번주 한 줄 요약</div>
    <div class="summary-main">{html.escape(one_line)}</div>
    <p class="summary-sub">{html.escape(summary)}</p>

    <div class="metrics">
      <div class="metric">
        <div class="k">움직임</div>
        <div class="v">{motion_text(metrics)}</div>
        <div class="d">이번주 농장 안에서 보이는 움직임의 리듬을 쉽게 풀어낸 결과예요.</div>
      </div>
      <div class="metric">
        <div class="k">모여 있는 정도</div>
        <div class="v">{density_text(metrics)}</div>
        <div class="d">한 공간에 과하게 몰리지 않는지, 농장 전체 흐름을 보여줘요.</div>
      </div>
      <div class="metric">
        <div class="k">이번주 변화</div>
        <div class="v">{change_text(metrics)}</div>
        <div class="d">평소보다 흐름이 흔들렸는지, 큰 변화 없이 안정적인지 살펴본 내용이에요.</div>
      </div>
    </div>
  </div>

  <div class="lower-grid">
    <div class="card info-card">
      <div class="info-head">왜 더 믿을 수 있을까요? 🌿</div>
      <p class="info-copy">EYERAN은 소비자가 직접 보고 선택할 수 있는 투명한 브랜드 경험을 제공합니다. 계란의 출발점인 농장 환경을 먼저 보여주는 게 맞다고 생각했습니다.</p>

      <div class="feature-list">
        <div class="feature">
          <div class="feature-icon">🎥</div>
          <div>
            <div class="feature-title">농장 기록을 직접 확인</div>
            <p class="feature-copy">문장으로만 설명하지 않고, 실제 영상과 흐름을 함께 보여드려요.</p>
          </div>
        </div>

        <div class="feature">
          <div class="feature-icon">🐓</div>
          <div>
            <div class="feature-title">더 자연스러운 농장 흐름</div>
            <p class="feature-copy">닭들이 어떻게 움직이고 쉬는지 직관적으로 이해할 수 있도록 정리했어요.</p>
          </div>
        </div>

        <div class="feature">
          <div class="feature-icon">🥚</div>
          <div>
            <div class="feature-title">보고 나서 선택하는 경험</div>
            <p class="feature-copy">그냥 믿는 것이 아니라, 직접 보고 안심하고 고를 수 있는 페이지를 지향합니다.</p>
          </div>
        </div>
      </div>
    </div>

    <div>
      <div class="card subscribe-card">
        <div class="subscribe-head">
          <div class="section-title" style="margin:0;">정기 구독</div>
          <div class="subscribe-emoji">📦</div>
        </div>
        <p class="subscribe-copy">농장을 직접 확인한 계란이니까, 믿고 꾸준히 드실 수 있어요. 정기배송으로 신청하면 매번 주문할 필요 없이 신선한 아이란이 정해진 날에 집 앞에 옵니다.</p>
        <a href="https://www.instagram.com/eyeran_egg?igsh=cmtzaDliN3Nhdzdt&utm_source=qr" target="_blank" class="cta">EYERAN 인스타그램</a>
      </div>

      <div class="card events-card">

        <div class="feature" style="margin-bottom:16px;">
          <div class="feature-icon">🤖</div>
          <div>
            <div class="feature-title">AI 영상 분석 리포트</div>
            <p class="feature-copy">
              AI가 영상 속 움직임 변화, 군집 흐름, 활동량이 높은 구간을 자동 분석해 주요 이벤트를 추출했습니다.
            </p>
          </div>
        </div>

        <div class="section-title">AI 최근 패턴 분석 🍃</div>

        <div class="feature" style="margin-bottom:14px;">
          <div class="feature-icon">🤖</div>
          <div>
            <div class="feature-title">AI 영상 분석 결과</div>
            <p class="feature-copy">업로드된 농장 영상에서 움직임 변화가 큰 구간을 자동으로 분리해 주요 이벤트 영상으로 정리했습니다.</p>
          </div>
        </div>

        {card_html(e1, "🌿")}
        {card_html(e2, "🐔")}
        {card_html(e3, "🥚")}
      </div>
    </div>
  </div>
</div>

<script>
const video = document.getElementById("mainVideo");
const badge = document.getElementById("playBadge");

if (video && badge) {{
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
}}
</script>
</body>
</html>
"""
    return HTMLResponse(page)



