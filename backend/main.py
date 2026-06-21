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
        return "✦ 인공지능이 영상 속 활동량 변화와 군집 흐름을 분석하고 있습니다."

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
    
    video_source = (
        "/videos/highlight.mp4"
        if (VIDEOS_DIR / "highlight.mp4").exists()
        else (
            "/videos/ai_event_1.mp4"
            if (VIDEOS_DIR / "ai_event_1.mp4").exists()
            else (
                "/videos/demo.mp4"
                if (VIDEOS_DIR / "demo.mp4").exists()
                else ""
            )
        )
    )


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
<title>JCR</title>
<style>
* {{ box-sizing:border-box; }}

:root {{
  --bg:#FFFFFF;
  --bg2:#FAFCFB;
  --card:#FFFFFF;
  --line:#E5EEE9;
  --text:#17231D;
  --sub:#66736C;
  --mint:#F1F8F4;
  --mint2:#E7F3EC;
  --deep:#267A4A;
  --shadow:0 12px 28px rgba(20,60,40,0.06);
  --radius:26px;
}}

body {{
  margin:0;
  background:linear-gradient(180deg,#ffffff 0%, #f8fbfa 55%, #eef8f2 100%);
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
  font-size:38px;
  font-weight:900;
  letter-spacing:-1.6px;
  color:#17231D;
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
  background:linear-gradient(180deg,#FAFCFB 0%, #ffffff 100%);
}}

.hero-badge {{
  display:inline-flex;
  align-items:center;
  gap:6px;
  width:max-content;
  padding:8px 12px;
  border-radius:999px;
  background:#F8FBFA;
  border:1px solid var(--line);
  font-size:12px;
  font-weight:900;
  color:#5E7168;
  margin-bottom:14px;
}}

.hero-title {{
  font-size:42px;
  line-height:1.12;
  letter-spacing:-1.4px;
  font-weight:900;
  margin:0 0 12px;
  color:#17231D;
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
  background:#267A4A;
  color:#fff;
  text-decoration:none;
  font-weight:900;
  font-size:16px;
  box-shadow:0 10px 20px rgba(245,183,0,0.18);
}}

.hero-note {{
  margin-top:18px;
  padding:14px 16px;
  background:#F8FBFA;
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
  color:#5E7168;
  margin:0 0 10px;
}}

.video-box {{
  position:relative;
  overflow:hidden;
  border-radius:22px;
  background:#E5EEE9;
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
  color:#267A4A;
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
  background:#FFFFFF;
  border:1px solid #E5EEE9;
  border-radius:20px;
}}

.metric .k {{
  font-size:12px;
  font-weight:900;
  color:#5E7168;
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
  background:#F8FBFA;
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
  background:linear-gradient(180deg,#FAFCFB,#ffffff);
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
  background:#267A4A;
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
  background:#F8FBFA;
  border-radius:20px;
  padding:14px;
  display:flex;
  align-items:flex-start;
  gap:12px;
  margin-bottom:12px;
  border:1px solid #E5EEE9;
}}

.event-row:last-child {{
  margin-bottom:0;
}}

.alert-row {{
  background:#F1F8F4;
  border:1px solid #E5EEE9;
}}

.icon-box {{
  width:46px;
  height:46px;
  border-radius:14px;
  background:#E7F3EC;
  display:flex;
  align-items:center;
  justify-content:center;
  font-size:21px;
  color:#267A4A;
  flex:0 0 auto;
}}

.event-time {{
  color:#5E7168;
  font-size:12px;
  font-weight:900;
  margin-bottom:4px;
}}

.event-text {{
  font-size:15px;
  line-height:1.65;
  font-weight:800;
  color:#17231D;
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
  background:#FFFFFF;
  color:#267A4A;
  border:1px solid #E5EEE9;
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
    font-size:30px;
    line-height:1.2;
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

.eyeran-main {{
  background:#fff;
}}

.main-video-section {{
  margin-bottom:20px;
}}

.cert-grid {{
  display:grid;
  grid-template-columns:repeat(4,1fr);
  gap:14px;
  margin-bottom:20px;
}}

.cert-card {{
  background:#fff;
  border:1px solid #dbeadf;
  border-radius:22px;
  padding:18px 12px;
  text-align:center;
  box-shadow:0 10px 24px rgba(14,91,61,0.07);
}}

.cert-card img {{
  width:64px;
  height:64px;
  object-fit:contain;
  margin-bottom:10px;
}}

.cert-title {{
  font-size:15px;
  font-weight:900;
  color:#0e5b3d;
}}

.ai-result-grid {{
  display:grid;
  grid-template-columns:repeat(3,1fr);
  gap:12px;
  margin-top:14px;
}}

.ai-result-card {{
  background:#f4f7f5;
  border:1px solid #dbeadf;
  border-radius:18px;
  padding:16px;
}}

.ai-result-card .label {{
  font-size:12px;
  font-weight:900;
  color:#2f8f57;
  margin-bottom:8px;
}}

.ai-result-card .value {{
  font-size:21px;
  font-weight:900;
  color:#0e5b3d;
}}

.ai-desc {{
  margin-top:14px;
  padding:16px;
  border-radius:18px;
  background:#f8fbf8;
  border:1px solid #dbeadf;
  color:#5f7364;
  font-size:14px;
  line-height:1.7;
}}

@media (max-width:900px) {{
  .cert-grid {{
    grid-template-columns:repeat(2,1fr);
  }}

  .ai-result-grid {{
    grid-template-columns:1fr;
  }}
}}


/* JCR_NEUTRAL_THEME_V3 */

body {{
  background:#F4F6F8 !important;
  color:#191F28 !important;
}}

.page,
.eyeran-main {{
  background:transparent !important;
}}

.card,
.cert-card,
.video-card,
.summary-card,
.events-card {{
  background:#FFFFFF !important;
  border:1px solid #E5E8EB !important;
  box-shadow:0 8px 24px rgba(0,0,0,0.045) !important;
}}

.brand,
.section-title,
.cert-title {{
  color:#191F28 !important;
}}

.cert-card {{
  border-radius:20px !important;
}}

.cert-title {{
  font-size:14px !important;
}}

.summary-main {{
  color:#191F28 !important;
}}

.summary-sub,
.info-copy,
.feature-copy {{
  color:#6B7684 !important;
}}

/* 기존 숫자 전용 AI 카드와 실패한 숨김 분석창 제거 */
.info-card,
.real-analysis-section,
.analysis-panel {{
  display:none !important;
}}

.jcr-analysis-card {{
  margin-top:20px;
  padding:22px;
  border-radius:24px;
}}

.jcr-analysis-header {{
  display:flex;
  align-items:flex-start;
  justify-content:space-between;
  gap:14px;
  margin-bottom:18px;
}}

.jcr-analysis-sub {{
  margin:7px 0 0;
  color:#6B7684;
  font-size:13px;
  line-height:1.6;
}}

.jcr-analysis-complete {{
  flex-shrink:0;
  padding:7px 10px;
  border-radius:999px;
  background:#F0F4F1;
  color:#587062;
  font-size:11px;
  font-weight:900;
}}

.jcr-analysis-tabs {{
  display:grid;
  grid-template-columns:repeat(3,1fr);
  gap:8px;
  padding:5px;
  margin-bottom:14px;
  border-radius:15px;
  background:#F2F4F6;
}}

.jcr-analysis-tab {{
  padding:11px 8px;
  border:0;
  border-radius:11px;
  background:transparent;
  color:#8B95A1;
  font-family:inherit;
  font-size:12px;
  font-weight:900;
  cursor:pointer;
}}

.jcr-analysis-tab.active {{
  background:#FFFFFF;
  color:#34483D;
  box-shadow:0 3px 10px rgba(0,0,0,0.07);
}}

.jcr-analysis-video-wrap {{
  position:relative;
  overflow:hidden;
  border-radius:18px;
  background:#111111;
}}

.jcr-analysis-video {{
  display:block;
  width:100%;
  min-height:260px;
  max-height:460px;
  object-fit:cover;
  background:#111111;
}}

.jcr-analysis-overlay {{
  position:absolute;
  top:13px;
  left:13px;
  display:flex;
  flex-direction:column;
  gap:3px;
  padding:9px 11px;
  border-radius:12px;
  background:rgba(25,31,28,0.72);
  color:#FFFFFF;
  pointer-events:none;
}}

.jcr-analysis-overlay strong {{
  font-size:12px;
}}

.jcr-analysis-overlay span {{
  font-size:9px;
  font-weight:900;
  letter-spacing:1px;
  opacity:0.78;
}}

.jcr-analysis-metrics {{
  display:grid;
  grid-template-columns:repeat(3,1fr);
  gap:9px;
  margin-top:12px;
}}

.jcr-analysis-metric {{
  padding:14px 10px;
  border:1px solid #E8EBED;
  border-radius:15px;
  background:#FAFAFA;
  text-align:center;
}}

.jcr-analysis-metric span {{
  display:block;
  margin-bottom:5px;
  color:#8B95A1;
  font-size:11px;
  font-weight:800;
}}

.jcr-analysis-metric strong {{
  color:#333D37;
  font-size:15px;
  font-weight:900;
}}

.jcr-analysis-note {{
  margin-top:12px;
  padding:14px 15px;
  border-radius:15px;
  background:#F7F8F9;
  color:#6B7684;
  font-size:13px;
  line-height:1.7;
}}

@media (max-width:600px) {{
  .jcr-analysis-card {{
    padding:17px;
  }}

  .jcr-analysis-video {{
    min-height:220px;
  }}

  .jcr-analysis-metrics {{
    grid-template-columns:1fr;
  }}
}}


/* JCR_AI_VISUAL_OVERLAY_STYLE_V1 */

/* 상단 JCR 로고 가운데 정렬 */
.topbar {{
  position:relative !important;
  display:flex !important;
  align-items:center !important;
  justify-content:center !important;
}}

.topbar .brand {{
  width:100% !important;
  margin:0 auto !important;
  text-align:center !important;
  justify-content:center !important;
}}

.jcr-analysis-video-wrap {{
  position:relative;
}}

.jcr-vision-layer {{
  position:absolute;
  inset:0;
  z-index:2;
  overflow:hidden;
  border-radius:18px;
  pointer-events:none;
}}

.jcr-vision-mode {{
  display:none;
  position:absolute;
  inset:0;
}}

.jcr-vision-layer.mode-activity .jcr-vision-activity {{
  display:block;
}}

.jcr-vision-layer.mode-cluster .jcr-vision-cluster {{
  display:block;
}}

.jcr-vision-layer.mode-pattern .jcr-vision-pattern {{
  display:block;
}}

/* 활동량 히트맵 */
.heat-spot {{
  position:absolute;
  border-radius:50%;
  filter:blur(8px);
  mix-blend-mode:screen;
  animation:heatPulse 2.4s ease-in-out infinite;
}}

.heat-spot-one {{
  width:150px;
  height:120px;
  left:54%;
  top:38%;
  background:radial-gradient(
    circle,
    rgba(255,55,45,0.82) 0%,
    rgba(255,190,45,0.60) 42%,
    rgba(255,220,70,0) 74%
  );
}}

.heat-spot-two {{
  width:120px;
  height:100px;
  left:24%;
  top:52%;
  background:radial-gradient(
    circle,
    rgba(255,156,30,0.72) 0%,
    rgba(255,218,60,0.42) 48%,
    rgba(255,220,70,0) 75%
  );
  animation-delay:.5s;
}}

.heat-spot-three {{
  width:90px;
  height:80px;
  left:68%;
  top:18%;
  background:radial-gradient(
    circle,
    rgba(255,216,50,0.65) 0%,
    rgba(255,220,70,0) 72%
  );
  animation-delay:1s;
}}

@keyframes heatPulse {{
  0%, 100% {{
    transform:scale(.92);
    opacity:.72;
  }}

  50% {{
    transform:scale(1.08);
    opacity:1;
  }}
}}

.vision-label {{
  position:absolute;
  padding:8px 11px;
  border:1px solid rgba(255,255,255,.45);
  border-radius:10px;
  background:rgba(20,25,22,.70);
  color:#ffffff;
  font-size:11px;
  font-weight:900;
  backdrop-filter:blur(8px);
}}

.vision-label-activity {{
  right:14px;
  top:14px;
}}

.vision-scale {{
  position:absolute;
  right:14px;
  bottom:14px;
  display:flex;
  align-items:center;
  gap:7px;
  padding:7px 9px;
  border-radius:10px;
  background:rgba(20,25,22,.70);
  color:#ffffff;
  font-size:9px;
  font-weight:800;
  backdrop-filter:blur(8px);
}}

.vision-scale-bar {{
  width:72px;
  height:7px;
  border-radius:999px;
  background:linear-gradient(
    90deg,
    #ffe95b 0%,
    #ff9f2e 50%,
    #ff4038 100%
  );
}}

/* 군집 및 이동 흐름 */
.cluster-box {{
  position:absolute;
  border:2px solid rgba(255,255,255,.92);
  border-radius:14px;
  box-shadow:0 0 0 1px rgba(41,112,255,.8);
  background:rgba(41,112,255,.09);
}}

.cluster-box span {{
  position:absolute;
  top:-27px;
  left:-2px;
  padding:5px 8px;
  border-radius:7px;
  background:#2970ff;
  color:#ffffff;
  font-size:10px;
  font-weight:900;
}}

.cluster-box-one {{
  width:32%;
  height:34%;
  left:14%;
  top:42%;
}}

.cluster-box-two {{
  width:28%;
  height:38%;
  right:13%;
  top:31%;
}}

.flow-arrow {{
  position:absolute;
  color:#ffffff;
  font-size:44px;
  font-weight:900;
  line-height:1;
  text-shadow:
    0 0 4px rgba(41,112,255,1),
    0 0 10px rgba(41,112,255,.9);
  animation:arrowMove 1.6s ease-in-out infinite;
}}

.flow-arrow-one {{
  left:40%;
  top:37%;
}}

.flow-arrow-two {{
  left:49%;
  top:53%;
  animation-delay:.3s;
}}

.flow-arrow-three {{
  left:57%;
  top:29%;
  animation-delay:.6s;
}}

@keyframes arrowMove {{
  0%, 100% {{
    transform:translateX(0);
    opacity:.65;
  }}

  50% {{
    transform:translateX(12px);
    opacity:1;
  }}
}}

.vision-label-cluster {{
  right:14px;
  top:14px;
}}

/* 시간대별 패턴 그래프 */
.pattern-chart {{
  position:absolute;
  left:14px;
  right:14px;
  bottom:14px;
  padding:14px;
  border:1px solid rgba(255,255,255,.30);
  border-radius:16px;
  background:rgba(25,31,40,.78);
  color:#ffffff;
  backdrop-filter:blur(10px);
}}

.pattern-chart-title {{
  margin-bottom:5px;
  font-size:11px;
  font-weight:900;
}}

.pattern-chart svg {{
  display:block;
  width:100%;
  height:90px;
}}

.pattern-chart-times {{
  display:flex;
  justify-content:space-between;
  color:rgba(255,255,255,.70);
  font-size:9px;
  font-weight:800;
}}

.pattern-event {{
  position:absolute;
  top:14px;
  right:14px;
  padding:8px 11px;
  border-radius:10px;
  background:rgba(255,255,255,.92);
  color:#191f28;
  font-size:10px;
  font-weight:900;
}}

/* 영상 아래 소비자용 설명 */
.jcr-visual-summary {{
  display:flex;
  align-items:flex-start;
  gap:12px;
  margin-top:13px;
  padding:15px;
  border:1px solid #e7eaec;
  border-radius:16px;
  background:#f7f8f9;
}}

.jcr-visual-summary-icon {{
  flex:0 0 36px;
  width:36px;
  height:36px;
  display:flex;
  align-items:center;
  justify-content:center;
  border-radius:12px;
  background:#ffffff;
  color:#476052;
  font-size:18px;
  font-weight:900;
  box-shadow:0 3px 10px rgba(0,0,0,.06);
}}

.jcr-visual-summary-label {{
  display:block;
  margin-bottom:4px;
  color:#8b95a1;
  font-size:10px;
  font-weight:900;
}}

.jcr-visual-summary strong {{
  display:block;
  color:#191f28;
  font-size:14px;
  line-height:1.45;
}}

.jcr-visual-summary p {{
  margin:5px 0 0;
  color:#6b7684;
  font-size:12px;
  line-height:1.6;
}}

@media (max-width:600px) {{
  .flow-arrow {{
    font-size:34px;
  }}

  .pattern-chart {{
    padding:11px;
  }}

  .pattern-chart svg {{
    height:70px;
  }}

  .vision-scale {{
    bottom:10px;
    right:10px;
  }}
}}


/* JCR_INTEGRATED_ANALYSIS_STYLE_V2 */

/* 영상 속 분석 요소가 자연스럽게 섞이도록 전체 톤 조정 */
.jcr-analysis-video-wrap {{
  position:relative !important;
  isolation:isolate;
}}

.jcr-analysis-video {{
  position:relative;
  z-index:0;
}}

.jcr-vision-layer {{
  z-index:2 !important;
}}

.jcr-analysis-overlay {{
  z-index:5 !important;
}}


/* 기존 영상 밖 고정 지표가 남아 있어도 숨김 */
.jcr-analysis-metrics {{
  display:none !important;
}}


/* 영상 내부 탭별 분석 정보 */
.jcr-integrated-context {{
  position:absolute;
  left:12px;
  right:12px;
  bottom:12px;
  z-index:6;
  pointer-events:none;
}}

.jcr-context-panel {{
  display:none;
  width:min(420px, 78%);
  padding:12px 13px;
  border:1px solid rgba(255,255,255,.24);
  border-radius:15px;
  background:linear-gradient(
    135deg,
    rgba(17,23,20,.78),
    rgba(30,37,33,.60)
  );
  box-shadow:0 8px 24px rgba(0,0,0,.18);
  backdrop-filter:blur(10px);
  -webkit-backdrop-filter:blur(10px);
  color:#ffffff;
}}

.jcr-context-panel.active {{
  display:block;
}}

.jcr-context-heading {{
  display:flex;
  align-items:center;
  gap:7px;
  margin-bottom:10px;
  color:rgba(255,255,255,.92);
  font-size:11px;
  font-weight:900;
}}

.jcr-context-dot {{
  width:7px;
  height:7px;
  border-radius:50%;
  box-shadow:0 0 8px currentColor;
}}

.activity-dot {{
  color:#ffb13b;
  background:#ffb13b;
}}

.cluster-dot {{
  color:#74a7ff;
  background:#74a7ff;
}}

.pattern-dot {{
  color:#a8d5bb;
  background:#a8d5bb;
}}

.jcr-context-values {{
  display:grid;
  grid-template-columns:repeat(3,1fr);
  gap:8px;
}}

.jcr-context-values > div {{
  min-width:0;
  padding-right:7px;
  border-right:1px solid rgba(255,255,255,.16);
}}

.jcr-context-values > div:last-child {{
  border-right:0;
  padding-right:0;
}}

.jcr-context-values span {{
  display:block;
  margin-bottom:3px;
  overflow:hidden;
  color:rgba(255,255,255,.58);
  font-size:9px;
  font-weight:700;
  text-overflow:ellipsis;
  white-space:nowrap;
}}

.jcr-context-values strong {{
  display:block;
  overflow:hidden;
  color:#ffffff;
  font-size:11px;
  font-weight:900;
  line-height:1.35;
  text-overflow:ellipsis;
  white-space:nowrap;
}}


/* 활동량 히트맵이 영상과 너무 따로 놀지 않도록 약하게 */
.heat-spot {{
  filter:blur(16px) !important;
  mix-blend-mode:screen;
  opacity:.72;
}}

.heat-spot-one {{
  background:radial-gradient(
    circle,
    rgba(255,83,55,.66) 0%,
    rgba(255,174,55,.42) 42%,
    rgba(255,205,70,0) 74%
  ) !important;
}}

.heat-spot-two {{
  background:radial-gradient(
    circle,
    rgba(255,158,45,.55) 0%,
    rgba(255,213,80,.30) 48%,
    rgba(255,220,70,0) 76%
  ) !important;
}}

.heat-spot-three {{
  opacity:.52;
}}


/* 군집 박스도 CCTV 분석선처럼 얇고 자연스럽게 */
.cluster-box {{
  border:1.5px solid rgba(130,175,255,.92) !important;
  background:rgba(57,113,220,.07) !important;
  box-shadow:
    0 0 0 1px rgba(57,113,220,.28),
    inset 0 0 18px rgba(57,113,220,.06) !important;
}}

.cluster-box span {{
  padding:4px 7px !important;
  background:rgba(42,91,178,.82) !important;
  backdrop-filter:blur(5px);
}}

.flow-arrow {{
  color:rgba(180,210,255,.94) !important;
  text-shadow:
    0 0 5px rgba(41,112,255,.75),
    0 0 12px rgba(41,112,255,.42) !important;
}}


/* 패턴 그래프 크기를 크게 축소하고 오른쪽 위에 배치 */
.jcr-vision-pattern .pattern-chart {{
  left:auto !important;
  right:12px !important;
  top:50px !important;
  bottom:auto !important;
  width:min(250px, 43%) !important;
  padding:10px 11px !important;
  border:1px solid rgba(255,255,255,.22) !important;
  border-radius:13px !important;
  background:linear-gradient(
    145deg,
    rgba(25,31,40,.70),
    rgba(25,31,40,.48)
  ) !important;
  box-shadow:0 7px 20px rgba(0,0,0,.14);
  backdrop-filter:blur(9px);
}}

.jcr-vision-pattern .pattern-chart-title {{
  margin-bottom:1px !important;
  color:rgba(255,255,255,.86);
  font-size:9px !important;
}}

.jcr-vision-pattern .pattern-chart svg {{
  height:55px !important;
}}

.jcr-vision-pattern .pattern-chart-times {{
  font-size:7px !important;
}}

.jcr-vision-pattern .pattern-event {{
  top:12px !important;
  right:12px !important;
  padding:6px 8px !important;
  background:rgba(255,255,255,.88) !important;
  font-size:8px !important;
}}


/* 영상 위 기존 분석 제목도 조금 더 자연스럽게 */
.jcr-analysis-overlay {{
  padding:7px 9px !important;
  background:rgba(20,25,22,.60) !important;
  border:1px solid rgba(255,255,255,.17);
  box-shadow:0 5px 14px rgba(0,0,0,.12);
  backdrop-filter:blur(8px);
}}

.jcr-analysis-overlay span {{
  letter-spacing:0 !important;
  font-size:9px !important;
}}


/* 영상 아래 핵심 설명은 영상 카드와 연결된 느낌 */
.jcr-visual-summary {{
  margin-top:0 !important;
  border-top-left-radius:0 !important;
  border-top-right-radius:0 !important;
  border-top:0 !important;
  background:#f7f8f9 !important;
}}

.jcr-analysis-video-wrap + .jcr-visual-summary {{
  margin-top:-1px !important;
}}


@media (max-width:600px) {{
  .jcr-context-panel {{
    width:100%;
    padding:10px 11px;
  }}

  .jcr-context-heading {{
    margin-bottom:8px;
  }}

  .jcr-context-values {{
    gap:5px;
  }}

  .jcr-context-values span {{
    font-size:8px;
  }}

  .jcr-context-values strong {{
    font-size:9px;
  }}

  .jcr-vision-pattern .pattern-chart {{
    width:46% !important;
    top:45px !important;
    padding:8px !important;
  }}

  .jcr-vision-pattern .pattern-chart svg {{
    height:43px !important;
  }}

  .vision-scale {{
    bottom:88px !important;
  }}
}}


/* JCR_MOBILE_ANALYSIS_REFINEMENT_V3 */

/* 영상 안에 들어간 상세 결과는 JS 이동 전에는 숨김 */
.jcr-analysis-video-wrap .jcr-integrated-context {{
  display:none !important;
}}

/* 영상 아래 분석 결과 영역 */
.jcr-integrated-context {{
  position:static !important;
  inset:auto !important;
  width:100% !important;
  margin-top:12px !important;
  pointer-events:auto !important;
}}

.jcr-context-panel {{
  display:none !important;
  width:100% !important;
  padding:17px !important;
  border:1px solid #e5e8eb !important;
  border-radius:18px !important;
  background:#ffffff !important;
  color:#191f28 !important;
  box-shadow:0 7px 22px rgba(0,0,0,.045) !important;
}}

.jcr-context-panel.active {{
  display:block !important;
}}

.jcr-context-heading {{
  display:flex !important;
  align-items:center !important;
  gap:8px !important;
  margin-bottom:14px !important;
  color:#191f28 !important;
  font-size:14px !important;
  font-weight:900 !important;
}}

.jcr-context-dot {{
  width:8px !important;
  height:8px !important;
}}

.jcr-context-values {{
  display:grid !important;
  grid-template-columns:repeat(3,minmax(0,1fr)) !important;
  gap:9px !important;
}}

.jcr-context-values > div {{
  min-width:0 !important;
  padding:13px 9px !important;
  border:1px solid #eceff1 !important;
  border-radius:14px !important;
  background:#f7f8f9 !important;
  text-align:center !important;
}}

.jcr-context-values span {{
  display:block !important;
  margin-bottom:5px !important;
  color:#8b95a1 !important;
  font-size:10px !important;
  font-weight:800 !important;
  white-space:normal !important;
}}

.jcr-context-values strong {{
  display:block !important;
  color:#333d37 !important;
  font-size:12px !important;
  font-weight:900 !important;
  line-height:1.4 !important;
  white-space:normal !important;
}}


/* 패턴 그래프를 영상 아래 카드 안으로 이동 */
.jcr-context-panel .pattern-chart {{
  position:static !important;
  inset:auto !important;
  width:100% !important;
  margin-top:13px !important;
  padding:13px !important;
  border:1px solid #e7eaec !important;
  border-radius:14px !important;
  background:#f7f8f9 !important;
  color:#333d37 !important;
  box-shadow:none !important;
  backdrop-filter:none !important;
}}

.jcr-context-panel .pattern-chart-title {{
  margin-bottom:6px !important;
  color:#667085 !important;
  font-size:11px !important;
}}

.jcr-context-panel .pattern-chart svg {{
  width:100% !important;
  height:80px !important;
}}

.jcr-context-panel .pattern-chart line {{
  stroke:#dfe4e1 !important;
}}

.jcr-context-panel .pattern-chart polyline {{
  stroke:#50745f !important;
}}

.jcr-context-panel .pattern-chart circle {{
  fill:#50745f !important;
}}

.jcr-context-panel .pattern-chart-times {{
  color:#8b95a1 !important;
  font-size:9px !important;
}}


/* 영상 안 오버레이는 아주 약하게 */
.jcr-vision-layer {{
  opacity:.48 !important;
}}

.heat-spot {{
  opacity:.38 !important;
  filter:blur(20px) !important;
}}

.cluster-box {{
  opacity:.58 !important;
  border-width:1px !important;
  background:rgba(57,113,220,.035) !important;
}}

.cluster-box span {{
  opacity:.80 !important;
  font-size:8px !important;
}}

.flow-arrow {{
  opacity:.68 !important;
  font-size:32px !important;
}}

.vision-label,
.vision-scale {{
  display:none !important;
}}

/* 기존 패턴 그래프는 영상 안에서 숨김 */
.jcr-vision-pattern .pattern-chart {{
  display:none !important;
}}

/* 패턴 탭에서는 작은 변화 감지 표시만 유지 */
.jcr-vision-pattern .pattern-event {{
  top:12px !important;
  right:12px !important;
  padding:6px 9px !important;
  border:1px solid rgba(255,255,255,.20) !important;
  background:rgba(22,27,24,.58) !important;
  color:#ffffff !important;
  font-size:8px !important;
  backdrop-filter:blur(7px);
}}


/* 영상 안에 공통으로 보이는 작은 분석 상태 */
.jcr-video-analysis-indicator {{
  position:absolute;
  top:12px;
  left:12px;
  z-index:8;
  display:flex;
  align-items:center;
  gap:7px;
  max-width:70%;
  padding:7px 10px;
  border:1px solid rgba(255,255,255,.20);
  border-radius:999px;
  background:rgba(20,25,22,.58);
  color:#ffffff;
  font-size:9px;
  font-weight:900;
  backdrop-filter:blur(8px);
  pointer-events:none;
}}

.jcr-video-analysis-indicator-dot {{
  width:7px;
  height:7px;
  flex:0 0 7px;
  border-radius:50%;
  background:#a7d7b9;
  box-shadow:0 0 8px rgba(167,215,185,.85);
  animation:jcrIndicatorPulse 1.8s ease-in-out infinite;
}}

@keyframes jcrIndicatorPulse {{
  0%,100% {{
    opacity:.55;
    transform:scale(.9);
  }}

  50% {{
    opacity:1;
    transform:scale(1.12);
  }}
}}

/* 기존 영상 위 제목은 중복되므로 숨김 */
.jcr-analysis-overlay {{
  display:none !important;
}}


/* 핵심 설명과 영상 아래 분석 카드 연결 */
.jcr-visual-summary {{
  margin-top:10px !important;
  border:1px solid #e5e8eb !important;
  border-radius:18px !important;
  background:#f7f8f9 !important;
}}


@media (max-width:600px) {{
  .jcr-context-panel {{
    padding:14px !important;
  }}

  .jcr-context-values {{
    gap:6px !important;
  }}

  .jcr-context-values > div {{
    padding:11px 5px !important;
  }}

  .jcr-context-values span {{
    font-size:8px !important;
  }}

  .jcr-context-values strong {{
    font-size:10px !important;
  }}

  .jcr-context-panel .pattern-chart svg {{
    height:64px !important;
  }}

  .jcr-video-analysis-indicator {{
    top:9px;
    left:9px;
    padding:6px 8px;
    font-size:8px;
  }}

  .flow-arrow {{
    font-size:25px !important;
  }}
}}

</style>

<script async src="https://www.googletagmanager.com/gtag/js?id=G-XKZ6FWYZ9D"></script>
<script>
window.dataLayer = window.dataLayer || [];
function gtag(){{dataLayer.push(arguments);}}
gtag('js', new Date());

gtag('config', 'G-XKZ6FWYZ9D');
</script>

</head>

<body>
<div class="page eyeran-main">

  <div class="topbar">
    <div class="brand">JCR</div>
  </div>

  <div class="card video-card main-video-section" id="farm-video">
    <div class="video-label">🎥 이번주 농장 영상</div>
    {video_html}
  </div>

  <div class="cert-grid">
    <div class="cert-card">
      <img src="/assets/6indus.png" alt="6차산업 인증">
      <div class="cert-title">6차산업 인증</div>
    </div>
    <div class="cert-card">
      <img src="/assets/naepo.png" alt="내포천애 인증">
      <div class="cert-title">내포천애 인증</div>
    </div>
    <div class="cert-card">
      <img src="/assets/muhang.png" alt="무항생제 인증">
      <div class="cert-title">무항생제 인증</div>
    </div>
    <div class="cert-card">
      <img src="/assets/haccp.png" alt="안전관리 인증">
      <div class="cert-title">안전관리 인증</div>
    </div>
  </div>

  <div class="card summary-card">
    <div class="section-title">✦ 이번주 한 줄 요약</div>
    <div class="summary-main">{html.escape(one_line)}</div>
    <p class="summary-sub">{html.escape(summary)}</p>
  </div>

  <div class="card info-card">
    <div class="section-title">🤖 인공지능 영상 분석 결과</div>

    <p class="info-copy">
      업로드된 농장 영상을 프레임 단위로 분석하여 움직임 변화, 군집 흐름, 공간별 활동 집중도를 요약합니다.
    </p>

    <div class="ai-result-grid">
      <div class="ai-result-card">
        <div class="label">활동량 분석</div>
        <div class="value">{motion_text(metrics)}</div>
      </div>
      <div class="ai-result-card">
        <div class="label">군집 흐름</div>
        <div class="value">{density_text(metrics)}</div>
      </div>
      <div class="ai-result-card">
        <div class="label">패턴 변화</div>
        <div class="value">{change_text(metrics)}</div>
      </div>
    </div>

    <div class="feature-list" style="margin-top:18px;">
      <div class="feature">
        <div class="feature-icon">1</div>
        <div>
          <div class="feature-title">영상 입력</div>
          <p class="feature-copy">농장 CCTV 영상을 불러와 일정 간격의 프레임으로 나눕니다.</p>
        </div>
      </div>

      <div class="feature">
        <div class="feature-icon">2</div>
        <div>
          <div class="feature-title">움직임 변화 감지</div>
          <p class="feature-copy">이전 프레임과 현재 프레임의 차이를 비교해 움직임이 많은 구간을 찾습니다.</p>
        </div>
      </div>

      <div class="feature">
        <div class="feature-icon">3</div>
        <div>
          <div class="feature-title">하이라이트 추출</div>
          <p class="feature-copy">이벤트 밀도가 높은 구간을 중심으로 소비자가 확인하기 쉬운 영상 구간을 제공합니다.</p>
        </div>
      </div>
    </div>
  </div>

  
  <!-- JCR_VISIBLE_AI_ANALYSIS_V3 -->
  <div class="card jcr-analysis-card" id="jcr-ai-analysis">
    <div class="jcr-analysis-header">
      <div>
        <div class="section-title">인공지능 영상 분석 결과</div>
        <p class="jcr-analysis-sub">
          농장 영상에서 움직임과 군집 흐름이 집중된 구간을 AI가 분석했습니다.
        </p>
      </div>

      <span class="jcr-analysis-complete">분석 완료</span>
    </div>

    <div class="jcr-analysis-tabs">
      <button
        type="button"
        class="jcr-analysis-tab active"
        data-src="/videos/ai_event_1.mp4"
        data-title="활동량 분석" data-mode="activity"
      >
        활동량
      </button>

      <button
        type="button"
        class="jcr-analysis-tab"
        data-src="/videos/ai_event_2.mp4"
        data-title="군집 흐름 분석" data-mode="cluster"
      >
        군집 흐름
      </button>

      <button
        type="button"
        class="jcr-analysis-tab"
        data-src="/videos/ai_event_3.mp4"
        data-title="패턴 변화 분석" data-mode="pattern"
      >
        패턴 변화
      </button>
    </div>

    <div class="jcr-analysis-video-wrap">
      <video
        id="jcrAnalysisVideo"
        class="jcr-analysis-video"
        controls
        playsinline
        muted
        preload="metadata"
      >
        <source
          id="jcrAnalysisSource"
          src="/videos/ai_event_1.mp4"
          type="video/mp4"
        >
      </video>

      
      <!-- JCR_AI_VISUAL_OVERLAY_V1 -->
      <div id="jcrVisionLayer" class="jcr-vision-layer mode-activity">

        <div class="jcr-vision-mode jcr-vision-activity">
          <div class="heat-spot heat-spot-one"></div>
          <div class="heat-spot heat-spot-two"></div>
          <div class="heat-spot heat-spot-three"></div>

          <div class="vision-label vision-label-activity">
            활동 집중 영역
          </div>

          <div class="vision-scale">
            <span>낮음</span>
            <div class="vision-scale-bar"></div>
            <span>높음</span>
          </div>
        </div>

        <div class="jcr-vision-mode jcr-vision-cluster">
          <div class="cluster-box cluster-box-one">
            <span>군집 A</span>
          </div>

          <div class="cluster-box cluster-box-two">
            <span>군집 B</span>
          </div>

          <div class="flow-arrow flow-arrow-one">→</div>
          <div class="flow-arrow flow-arrow-two">↗</div>
          <div class="flow-arrow flow-arrow-three">→</div>

          <div class="vision-label vision-label-cluster">
            주요 이동 방향
          </div>
        </div>

        <div class="jcr-vision-mode jcr-vision-pattern">
          <div class="pattern-chart">
            <div class="pattern-chart-title">
              시간대별 활동 변화
            </div>

            <svg viewBox="0 0 320 120" preserveAspectRatio="none">
              <line x1="0" y1="30" x2="320" y2="30"
                    stroke="rgba(255,255,255,0.18)" stroke-width="1"/>
              <line x1="0" y1="60" x2="320" y2="60"
                    stroke="rgba(255,255,255,0.18)" stroke-width="1"/>
              <line x1="0" y1="90" x2="320" y2="90"
                    stroke="rgba(255,255,255,0.18)" stroke-width="1"/>

              <polyline
                points="0,88 45,76 90,80 135,47 180,55 225,30 270,45 320,38"
                fill="none"
                stroke="#ffffff"
                stroke-width="4"
                stroke-linecap="round"
                stroke-linejoin="round"
              />

              <circle cx="225" cy="30" r="6" fill="#ffffff"/>
            </svg>

            <div class="pattern-chart-times">
              <span>오전</span>
              <span>점심</span>
              <span>오후</span>
              <span>저녁</span>
            </div>
          </div>

          <div class="pattern-event">
            오후 활동 변화 감지
          </div>
        </div>
      </div>

      <div class="jcr-analysis-overlay">
        <strong id="jcrAnalysisTitle">활동량 분석</strong>
        <span>인공지능 분석</span>
      </div>
    
      <!-- JCR_INTEGRATED_CONTEXT_V2 -->
      <div id="jcrIntegratedContext" class="jcr-integrated-context">

        <div
          class="jcr-context-panel active"
          data-context-mode="activity"
        >
          <div class="jcr-context-heading">
            <span class="jcr-context-dot activity-dot"></span>
            활동량 분석
          </div>

          <div class="jcr-context-values">
            <div>
              <span>활동 상태</span>
              <strong>{motion_text(metrics)}</strong>
            </div>

            <div>
              <span>집중 영역</span>
              <strong>우측 구역</strong>
            </div>

            <div>
              <span>감지 기준</span>
              <strong>프레임 변화</strong>
            </div>
          </div>
        </div>


        <div
          class="jcr-context-panel"
          data-context-mode="cluster"
        >
          <div class="jcr-context-heading">
            <span class="jcr-context-dot cluster-dot"></span>
            군집 흐름 분석
          </div>

          <div class="jcr-context-values">
            <div>
              <span>군집 상태</span>
              <strong>{density_text(metrics)}</strong>
            </div>

            <div>
              <span>주요 중심</span>
              <strong>중앙·우측</strong>
            </div>

            <div>
              <span>이동 방향</span>
              <strong>왼쪽 → 오른쪽</strong>
            </div>
          </div>
        </div>


        <div
          class="jcr-context-panel"
          data-context-mode="pattern"
        >
          <div class="jcr-context-heading">
            <span class="jcr-context-dot pattern-dot"></span>
            패턴 변화 분석
          </div>

          <div class="jcr-context-values">
            <div>
              <span>변화 추세</span>
              <strong>{change_text(metrics)}</strong>
            </div>

            <div>
              <span>주요 시점</span>
              <strong>오후 구간</strong>
            </div>

            <div>
              <span>비교 기준</span>
              <strong>이번 주 평균</strong>
            </div>
          </div>
        </div>

      </div>

</div>

    
    <!-- JCR_AI_VISUAL_SUMMARY_V1 -->
    <div class="jcr-visual-summary">
      <div class="jcr-visual-summary-icon" id="jcrVisualIcon">◉</div>

      <div>
        <span class="jcr-visual-summary-label">인공지능이 본 핵심</span>

        <strong id="jcrVisualHeadline">
          영상에서 움직임이 집중된 위치를 찾았어요
        </strong>

        <p id="jcrVisualDescription">
          영상 위의 색이 진할수록 움직임이 많이 감지된 위치입니다.
        </p>
      </div>
    </div>

    

    <div class="jcr-analysis-note">
      프레임 간 움직임 변화와 공간별 활동 집중도를 분석하여
      이벤트가 많이 발생한 구간을 영상으로 제공합니다.
    </div>
  </div>

<div class="card events-card" style="margin-top:20px;">
    <div class="section-title">인공지능 최근 패턴 분석 🍃</div>
    {card_html(e1, "🌿")}
    {card_html(e2, "🐔")}
    {card_html(e3, "🥚")}
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

<script>
// JCR_VISIBLE_AI_ANALYSIS_SCRIPT_V3
document.addEventListener("DOMContentLoaded", function() {{
  const tabs = document.querySelectorAll(".jcr-analysis-tab");
  const video = document.getElementById("jcrAnalysisVideo");
  const videoSource = document.getElementById("jcrAnalysisSource");
  const videoTitle = document.getElementById("jcrAnalysisTitle");

  let fallbackUsed = false;

  tabs.forEach(function(tab) {{
    tab.addEventListener("click", function() {{
      tabs.forEach(function(item) {{
        item.classList.remove("active");
      }});

      tab.classList.add("active");

      const selectedSource = tab.dataset.src;
      const selectedTitle = tab.dataset.title;

      fallbackUsed = false;

      if (video && videoSource) {{
        video.pause();
        videoSource.src = selectedSource;
        video.load();
      }}

      if (videoTitle) {{
        videoTitle.textContent = selectedTitle;
      }}
    }});
  }});

  if (video && videoSource) {{
    video.addEventListener("error", function() {{
      if (!fallbackUsed) {{
        fallbackUsed = true;
        videoSource.src = "/videos/ai_event_1.mp4";
        video.load();

        if (videoTitle) {{
          videoTitle.textContent = "활동량 분석";
        }}
      }}
    }});
  }}
}});
</script>


<script>
// JCR_AI_VISUAL_OVERLAY_SCRIPT_V1
document.addEventListener("DOMContentLoaded", function() {{
  const visualLayer = document.getElementById("jcrVisionLayer");
  const headline = document.getElementById("jcrVisualHeadline");
  const description = document.getElementById("jcrVisualDescription");
  const icon = document.getElementById("jcrVisualIcon");
  const tabs = document.querySelectorAll(".jcr-analysis-tab");

  const visualConfig = {{
    activity: {{
      icon:"◉",
      headline:"영상에서 움직임이 집중된 위치를 찾았어요",
      description:"영상 위의 색이 진할수록 움직임이 많이 감지된 위치입니다."
    }},

    cluster: {{
      icon:"↗",
      headline:"닭이 모인 위치와 이동 흐름을 확인했어요",
      description:"영상 속 박스는 군집이 형성된 위치이고 화살표는 주요 이동 방향입니다."
    }},

    pattern: {{
      icon:"⌁",
      headline:"시간대에 따라 달라진 활동 흐름을 비교했어요",
      description:"작은 그래프에서 선이 높아지는 부분은 움직임이 증가한 시간대입니다."
    }}
  }};

  function changeVisualMode(mode) {{
    if (!visualLayer || !visualConfig[mode]) return;

    visualLayer.classList.remove(
      "mode-activity",
      "mode-cluster",
      "mode-pattern"
    );

    visualLayer.classList.add("mode-" + mode);

    if (headline) {{
      headline.textContent = visualConfig[mode].headline;
    }}

    if (description) {{
      description.textContent = visualConfig[mode].description;
    }}

    if (icon) {{
      icon.textContent = visualConfig[mode].icon;
    }}
  }}

  tabs.forEach(function(tab, index) {{
    if (!tab.dataset.mode) {{
      tab.dataset.mode = (
        index === 0
          ? "activity"
          : index === 1
            ? "cluster"
            : "pattern"
      );
    }}

    tab.addEventListener("click", function() {{
      changeVisualMode(tab.dataset.mode);
    }});
  }});

  changeVisualMode("activity");
}});
</script>


<script>
// JCR_INTEGRATED_CONTEXT_SCRIPT_V2
document.addEventListener("DOMContentLoaded", function() {{
  const tabs = document.querySelectorAll(".jcr-analysis-tab");
  const contextPanels = document.querySelectorAll(
    ".jcr-context-panel"
  );

  function setContextMode(mode) {{
    contextPanels.forEach(function(panel) {{
      panel.classList.toggle(
        "active",
        panel.dataset.contextMode === mode
      );
    }});
  }}

  tabs.forEach(function(tab, index) {{
    let mode = tab.dataset.mode;

    if (!mode) {{
      mode = (
        index === 0
          ? "activity"
          : index === 1
            ? "cluster"
            : "pattern"
      );

      tab.dataset.mode = mode;
    }}

    tab.addEventListener("click", function() {{
      setContextMode(mode);
    }});
  }});

  setContextMode("activity");
}});
</script>


<script>
// JCR_MOBILE_ANALYSIS_REFINEMENT_SCRIPT_V3
document.addEventListener("DOMContentLoaded", function() {{
  const videoWrap = document.querySelector(
    ".jcr-analysis-video-wrap"
  );

  const context = document.getElementById(
    "jcrIntegratedContext"
  );

  const summary = document.querySelector(
    ".jcr-visual-summary"
  );

  const tabs = document.querySelectorAll(
    ".jcr-analysis-tab"
  );

  const patternPanel = document.querySelector(
    '.jcr-context-panel[data-context-mode="pattern"]'
  );

  const patternChart = document.querySelector(
    ".jcr-vision-pattern .pattern-chart"
  );


  /* 상세 분석 결과를 영상 바로 아래로 이동 */
  if (videoWrap && context) {{
    videoWrap.insertAdjacentElement("afterend", context);
  }}


  /* 인공지능이 본 핵심은 상세 결과 아래에 위치 */
  if (context && summary) {{
    context.insertAdjacentElement("afterend", summary);
  }}


  /* 패턴 그래프를 패턴 변화 카드 아래로 이동 */
  if (patternPanel && patternChart) {{
    patternPanel.appendChild(patternChart);
  }}


  /* 영상 안 작은 분석 상태 표시 */
  let indicator = document.getElementById(
    "jcrVideoAnalysisIndicator"
  );

  if (!indicator && videoWrap) {{
    indicator = document.createElement("div");
    indicator.id = "jcrVideoAnalysisIndicator";
    indicator.className = "jcr-video-analysis-indicator";

    indicator.innerHTML =
      '<span class="jcr-video-analysis-indicator-dot"></span>' +
      '<span id="jcrVideoAnalysisText">인공지능 활동량 분석</span>';

    videoWrap.appendChild(indicator);
  }}

  const indicatorText = document.getElementById(
    "jcrVideoAnalysisText"
  );


  const modeLabels = {{
    activity:"인공지능 활동량 분석",
    cluster:"인공지능 군집 흐름 분석",
    pattern:"인공지능 패턴 변화 분석"
  }};


  function resolveMode(tab, index) {{
    if (tab.dataset.mode) {{
      return tab.dataset.mode;
    }}

    if (index === 0) return "activity";
    if (index === 1) return "cluster";

    return "pattern";
  }}


  tabs.forEach(function(tab, index) {{
    const mode = resolveMode(tab, index);
    tab.dataset.mode = mode;

    tab.addEventListener("click", function() {{
      if (indicatorText) {{
        indicatorText.textContent = modeLabels[mode];
      }}
    }});
  }});


  const activeTab = document.querySelector(
    ".jcr-analysis-tab.active"
  );

  if (activeTab && indicatorText) {{
    const activeIndex = Array.from(tabs).indexOf(activeTab);
    const activeMode = resolveMode(activeTab, activeIndex);

    indicatorText.textContent = modeLabels[activeMode];
  }}
}});
</script>

</body>
</html>
"""
    return HTMLResponse(page)



