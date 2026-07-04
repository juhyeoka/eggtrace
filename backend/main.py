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
                e.get("video_path", "/videos/highlight.mp4?v=20"),
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
    
    video_source = "/videos/highlight.mp4?v=20"


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


/* JCR_WEEKLY_VIDEO_QUALITY_FIX */
.main-video-section .video-box,
.main-video-section video,
#farm-video .video-box,
#farm-video video {{
  width:100% !important;
  height:auto !important;
  min-height:0 !important;
  max-height:none !important;
  aspect-ratio:auto !important;
  object-fit:contain !important;
  image-rendering:auto !important;
  transform:none !important;
  filter:none !important;
}}

.main-video-section {{
  overflow:hidden !important;
}}



/* JCR_PREMIUM_UI_REDESIGN_V1 */

:root {{
  --jcr-bg:#F5F7F8;
  --jcr-card:#FFFFFF;
  --jcr-text:#191F28;
  --jcr-sub:#6B7684;
  --jcr-line:#E8EBED;
  --jcr-soft:#F2F4F6;
  --jcr-accent:#1E7A68;
  --jcr-accent-soft:#EAF5F1;
  --jcr-shadow:0 10px 30px rgba(0,0,0,.055);
  --jcr-radius:24px;
}}

* {{
  box-sizing:border-box;
}}

html {{
  background:var(--jcr-bg);
}}

body {{
  margin:0 !important;
  background:
    radial-gradient(
      circle at 50% -120px,
      rgba(30,122,104,.09),
      transparent 360px
    ),
    var(--jcr-bg) !important;
  color:var(--jcr-text) !important;
  font-family:
    -apple-system,
    BlinkMacSystemFont,
    "Pretendard",
    "Apple SD Gothic Neo",
    "Noto Sans KR",
    sans-serif !important;
}}

.page {{
  width:100% !important;
  max-width:720px !important;
  margin:0 auto !important;
  padding:20px 18px 60px !important;
  background:transparent !important;
}}

/* 상단 브랜드 */
.topbar {{
  position:relative !important;
  display:flex !important;
  align-items:center !important;
  justify-content:center !important;
  min-height:72px !important;
  margin-bottom:16px !important;
  padding:10px 0 !important;
}}

.topbar::after {{
  content:"FARM TRANSPARENCY REPORT";
  position:absolute;
  bottom:4px;
  left:50%;
  transform:translateX(-50%);
  color:#98A1AA;
  font-size:9px;
  font-weight:800;
  letter-spacing:1.8px;
  white-space:nowrap;
}}

.brand {{
  width:auto !important;
  margin:0 !important;
  color:var(--jcr-text) !important;
  font-size:27px !important;
  font-weight:950 !important;
  letter-spacing:-1.3px !important;
  text-align:center !important;
}}

.brand::first-letter {{
  color:var(--jcr-accent);
}}

/* 공통 카드 */
.card {{
  margin-bottom:16px !important;
  padding:22px !important;
  border:1px solid var(--jcr-line) !important;
  border-radius:var(--jcr-radius) !important;
  background:var(--jcr-card) !important;
  box-shadow:var(--jcr-shadow) !important;
}}

.section-title {{
  display:flex !important;
  align-items:center !important;
  gap:8px !important;
  margin-bottom:8px !important;
  color:var(--jcr-text) !important;
  font-size:18px !important;
  font-weight:900 !important;
  letter-spacing:-.45px !important;
}}

.section-title::before {{
  content:"";
  width:5px;
  height:18px;
  flex:0 0 5px;
  border-radius:999px;
  background:var(--jcr-accent);
}}

.info-copy,
.summary-sub,
.jcr-analysis-sub,
.jcr-analysis-note,
.feature-copy {{
  color:var(--jcr-sub) !important;
  font-size:13px !important;
  line-height:1.75 !important;
}}

/* 이번 주 영상 */
.main-video-section {{
  position:relative !important;
  padding:14px !important;
  overflow:hidden !important;
}}

.main-video-section::before {{
  content:"이번 주 기록";
  display:inline-flex;
  align-items:center;
  margin:2px 0 12px 4px;
  padding:6px 10px;
  border-radius:999px;
  background:var(--jcr-accent-soft);
  color:var(--jcr-accent);
  font-size:11px;
  font-weight:900;
}}

.video-label {{
  display:none !important;
}}

.main-video-section video,
.main-video-section .video-box {{
  width:100% !important;
  min-height:0 !important;
  max-height:none !important;
  border-radius:18px !important;
  background:#111 !important;
  object-fit:contain !important;
}}

.main-video-section video {{
  display:block !important;
  aspect-ratio:16 / 9 !important;
}}

/* 인증 카드 */
.cert-grid {{
  display:grid !important;
  grid-template-columns:repeat(4,minmax(0,1fr)) !important;
  gap:10px !important;
  margin:0 0 16px !important;
}}

.cert-card {{
  min-width:0 !important;
  padding:14px 7px 12px !important;
  border:1px solid var(--jcr-line) !important;
  border-radius:18px !important;
  background:#FFFFFF !important;
  box-shadow:0 5px 16px rgba(0,0,0,.035) !important;
  transition:
    transform .18s ease,
    box-shadow .18s ease !important;
}}

.cert-card:hover {{
  transform:translateY(-2px);
  box-shadow:0 10px 24px rgba(0,0,0,.07) !important;
}}

.cert-card img {{
  width:56px !important;
  height:56px !important;
  margin-bottom:8px !important;
  object-fit:contain !important;
}}

.cert-title {{
  color:#3D454D !important;
  font-size:11px !important;
  font-weight:850 !important;
  line-height:1.35 !important;
  word-break:keep-all !important;
}}

/* 한 줄 요약 */
.summary-card {{
  position:relative !important;
  overflow:hidden !important;
  padding:24px !important;
  background:
    linear-gradient(
      135deg,
      #FFFFFF 0%,
      #F4FAF7 100%
    ) !important;
}}

.summary-card::after {{
  content:"";
  position:absolute;
  width:130px;
  height:130px;
  right:-55px;
  bottom:-65px;
  border-radius:50%;
  background:rgba(30,122,104,.07);
}}

.summary-main {{
  position:relative;
  z-index:1;
  margin:12px 0 8px !important;
  color:var(--jcr-text) !important;
  font-size:22px !important;
  font-weight:950 !important;
  line-height:1.42 !important;
  letter-spacing:-.7px !important;
}}

.summary-sub {{
  position:relative;
  z-index:1;
  margin:0 !important;
}}

/* 인공지능 분석 카드 */
.jcr-analysis-card {{
  padding:22px !important;
}}

.jcr-analysis-header {{
  margin-bottom:16px !important;
}}

.jcr-analysis-complete {{
  padding:7px 10px !important;
  border-radius:999px !important;
  background:var(--jcr-accent-soft) !important;
  color:var(--jcr-accent) !important;
  font-size:10px !important;
  font-weight:900 !important;
}}

.jcr-analysis-tabs {{
  display:grid !important;
  grid-template-columns:repeat(3,1fr) !important;
  gap:5px !important;
  margin-bottom:14px !important;
  padding:5px !important;
  border:1px solid var(--jcr-line) !important;
  border-radius:16px !important;
  background:var(--jcr-soft) !important;
}}

.jcr-analysis-tab {{
  min-width:0 !important;
  padding:11px 5px !important;
  border:0 !important;
  border-radius:12px !important;
  background:transparent !important;
  color:#8B95A1 !important;
  font-size:12px !important;
  font-weight:900 !important;
  transition:.18s ease !important;
}}

.jcr-analysis-tab.active {{
  background:#FFFFFF !important;
  color:var(--jcr-text) !important;
  box-shadow:0 3px 12px rgba(0,0,0,.07) !important;
}}

.jcr-analysis-video-wrap {{
  overflow:hidden !important;
  border-radius:18px !important;
  background:#111 !important;
}}

.jcr-analysis-video {{
  display:block !important;
  width:100% !important;
  aspect-ratio:16 / 9 !important;
  min-height:0 !important;
  object-fit:cover !important;
}}

/* 영상 아래 분석 결과 */
.jcr-integrated-context {{
  margin-top:12px !important;
}}

.jcr-context-panel {{
  padding:16px !important;
  border:1px solid var(--jcr-line) !important;
  border-radius:18px !important;
  background:#FFFFFF !important;
  box-shadow:none !important;
}}

.jcr-context-heading {{
  margin-bottom:12px !important;
  color:var(--jcr-text) !important;
  font-size:14px !important;
  font-weight:900 !important;
}}

.jcr-context-values {{
  display:grid !important;
  grid-template-columns:repeat(3,minmax(0,1fr)) !important;
  gap:8px !important;
}}

.jcr-context-values > div {{
  min-width:0 !important;
  padding:13px 7px !important;
  border:0 !important;
  border-radius:14px !important;
  background:var(--jcr-soft) !important;
  text-align:center !important;
}}

.jcr-context-values span {{
  display:block !important;
  margin-bottom:5px !important;
  color:#8B95A1 !important;
  font-size:9px !important;
  font-weight:800 !important;
}}

.jcr-context-values strong {{
  display:block !important;
  color:var(--jcr-text) !important;
  font-size:11px !important;
  font-weight:900 !important;
  line-height:1.4 !important;
}}

/* 인공지능이 본 핵심 */
.jcr-visual-summary {{
  display:flex !important;
  align-items:flex-start !important;
  gap:12px !important;
  margin-top:10px !important;
  padding:16px !important;
  border:0 !important;
  border-radius:18px !important;
  background:#F7F9FA !important;
}}

.jcr-visual-summary-icon {{
  width:38px !important;
  height:38px !important;
  flex:0 0 38px !important;
  border-radius:13px !important;
  background:#FFFFFF !important;
  color:var(--jcr-accent) !important;
}}

.jcr-visual-summary-label {{
  color:#8B95A1 !important;
  font-size:9px !important;
  font-weight:900 !important;
}}

.jcr-visual-summary strong {{
  color:var(--jcr-text) !important;
  font-size:14px !important;
  font-weight:900 !important;
  line-height:1.45 !important;
}}

.jcr-visual-summary p {{
  margin-top:5px !important;
  color:var(--jcr-sub) !important;
  font-size:12px !important;
  line-height:1.65 !important;
}}

/* 최근 패턴 카드 */
.events-card {{
  padding:22px !important;
}}

.events-card .feature,
.events-card .event-card {{
  margin-top:10px !important;
  padding:15px !important;
  border:1px solid var(--jcr-line) !important;
  border-radius:16px !important;
  background:#FAFBFB !important;
  box-shadow:none !important;
}}

/* 버튼 */
button,
.cta,
.hero-cta {{
  font-family:inherit !important;
}}

.cta,
.hero-cta {{
  border:0 !important;
  border-radius:15px !important;
  background:var(--jcr-text) !important;
  color:#FFFFFF !important;
  box-shadow:0 8px 18px rgba(25,31,40,.14) !important;
}}

/* 모바일 */
@media (max-width:600px) {{
  .page {{
    padding:12px 12px 40px !important;
  }}

  .topbar {{
    min-height:66px !important;
    margin-bottom:10px !important;
  }}

  .brand {{
    font-size:25px !important;
  }}

  .card {{
    margin-bottom:12px !important;
    padding:17px !important;
    border-radius:21px !important;
  }}

  .main-video-section {{
    padding:10px !important;
  }}

  .main-video-section::before {{
    margin:1px 0 9px 3px;
    padding:5px 9px;
    font-size:10px;
  }}

  .cert-grid {{
    grid-template-columns:repeat(2,1fr) !important;
    gap:8px !important;
    margin-bottom:12px !important;
  }}

  .cert-card {{
    display:flex !important;
    align-items:center !important;
    justify-content:flex-start !important;
    gap:9px !important;
    min-height:76px !important;
    padding:10px 11px !important;
    text-align:left !important;
  }}

  .cert-card img {{
    width:47px !important;
    height:47px !important;
    flex:0 0 47px !important;
    margin:0 !important;
  }}

  .cert-title {{
    font-size:11px !important;
  }}

  .summary-main {{
    font-size:19px !important;
  }}

  .section-title {{
    font-size:16px !important;
  }}

  .jcr-analysis-card {{
    padding:16px !important;
  }}

  .jcr-analysis-tabs {{
    gap:3px !important;
  }}

  .jcr-analysis-tab {{
    padding:10px 3px !important;
    font-size:10px !important;
  }}

  .jcr-context-panel {{
    padding:13px !important;
  }}

  .jcr-context-values {{
    gap:6px !important;
  }}

  .jcr-context-values > div {{
    padding:11px 4px !important;
  }}

  .jcr-context-values span {{
    font-size:8px !important;
  }}

  .jcr-context-values strong {{
    font-size:9px !important;
  }}

  .jcr-visual-summary {{
    padding:13px !important;
  }}
}}


/* JCR_SIGNATURE_UI_V1 */

:root {{
  --lux-bg:#F3F5F4;
  --lux-paper:#FFFFFF;
  --lux-ink:#101A17;
  --lux-muted:#69746F;
  --lux-line:rgba(17,50,40,.10);
  --lux-emerald:#0D6B50;
  --lux-emerald-deep:#084B39;
  --lux-emerald-soft:#E7F3EE;
  --lux-gold:#C7A76A;
  --lux-gold-soft:#F5EEE1;
  --lux-navy:#111B2A;
  --lux-shadow:
    0 2px 4px rgba(14,38,30,.02),
    0 16px 45px rgba(14,38,30,.075);
  --lux-shadow-large:
    0 10px 25px rgba(8,32,24,.08),
    0 35px 90px rgba(8,32,24,.13);
}}

html {{
  scroll-behavior:smooth !important;
  background:var(--lux-bg) !important;
}}

body {{
  position:relative;
  overflow-x:hidden;
  margin:0 !important;
  background:
    radial-gradient(
      circle at 8% 2%,
      rgba(13,107,80,.10),
      transparent 360px
    ),
    radial-gradient(
      circle at 94% 26%,
      rgba(199,167,106,.09),
      transparent 330px
    ),
    linear-gradient(
      180deg,
      #F8FAF9 0%,
      #F3F5F4 40%,
      #EEF2F0 100%
    ) !important;
  color:var(--lux-ink) !important;
}}

body::before {{
  content:"";
  position:fixed;
  inset:0;
  z-index:-1;
  pointer-events:none;
  opacity:.32;
  background-image:
    linear-gradient(
      rgba(13,107,80,.025) 1px,
      transparent 1px
    ),
    linear-gradient(
      90deg,
      rgba(13,107,80,.025) 1px,
      transparent 1px
    );
  background-size:42px 42px;
}}

.page {{
  width:100% !important;
  max-width:940px !important;
  margin:0 auto !important;
  padding:20px 22px 76px !important;
  background:transparent !important;
}}


/* ---------------------------------------------------------
   상단 로고
--------------------------------------------------------- */

.topbar {{
  position:relative !important;
  display:flex !important;
  align-items:center !important;
  justify-content:center !important;
  min-height:72px !important;
  margin:0 0 18px !important;
}}

.topbar::before {{
  content:"";
  position:absolute;
  left:0;
  right:0;
  bottom:0;
  height:1px;
  background:linear-gradient(
    90deg,
    transparent,
    rgba(13,107,80,.18),
    transparent
  );
}}

.topbar::after {{
  content:"FARM INTELLIGENCE";
  position:absolute;
  right:2px;
  bottom:16px;
  color:#909994;
  font-size:8px;
  font-weight:900;
  letter-spacing:1.7px;
}}

.topbar .brand {{
  position:relative;
  width:auto !important;
  color:var(--lux-ink) !important;
  font-size:30px !important;
  font-weight:950 !important;
  letter-spacing:-1.6px !important;
  text-align:center !important;
}}

.topbar .brand::before {{
  content:"";
  position:absolute;
  left:50%;
  bottom:-9px;
  width:20px;
  height:3px;
  border-radius:999px;
  transform:translateX(-50%);
  background:linear-gradient(
    90deg,
    var(--lux-emerald),
    var(--lux-gold)
  );
}}


/* ---------------------------------------------------------
   시그니처 히어로
--------------------------------------------------------- */

.jcr-signature-hero {{
  position:relative;
  display:grid;
  grid-template-columns:minmax(0,1fr) 220px;
  min-height:440px;
  margin-bottom:14px;
  padding:54px 54px 48px;
  overflow:hidden;
  border:1px solid rgba(255,255,255,.10);
  border-radius:36px;
  background:
    linear-gradient(
      135deg,
      #101E1A 0%,
      #0C332A 48%,
      #0B5A43 100%
    );
  box-shadow:var(--lux-shadow-large);
  isolation:isolate;
}}

.jcr-signature-hero::before {{
  content:"";
  position:absolute;
  inset:0;
  z-index:-1;
  opacity:.19;
  background-image:
    linear-gradient(
      rgba(255,255,255,.08) 1px,
      transparent 1px
    ),
    linear-gradient(
      90deg,
      rgba(255,255,255,.08) 1px,
      transparent 1px
    );
  background-size:48px 48px;
  mask-image:linear-gradient(
    90deg,
    #000,
    transparent 85%
  );
}}

.jcr-signature-hero::after {{
  content:"JCR";
  position:absolute;
  right:-24px;
  bottom:-76px;
  z-index:-1;
  color:rgba(255,255,255,.035);
  font-size:230px;
  font-weight:950;
  line-height:1;
  letter-spacing:-18px;
}}

.jcr-hero-content {{
  position:relative;
  z-index:2;
  align-self:center;
}}

.jcr-hero-eyebrow {{
  display:inline-flex;
  align-items:center;
  gap:9px;
  margin-bottom:22px;
  padding:8px 12px;
  border:1px solid rgba(255,255,255,.14);
  border-radius:999px;
  background:rgba(255,255,255,.07);
  color:rgba(255,255,255,.78);
  font-size:9px;
  font-weight:900;
  letter-spacing:1.5px;
  backdrop-filter:blur(10px);
}}

.jcr-live-dot {{
  width:7px;
  height:7px;
  border-radius:50%;
  background:#70E5AF;
  box-shadow:0 0 0 5px rgba(112,229,175,.12);
  animation:jcrLivePulse 2s ease-in-out infinite;
}}

@keyframes jcrLivePulse {{
  0%,100% {{
    opacity:.62;
    transform:scale(.9);
  }}

  50% {{
    opacity:1;
    transform:scale(1.15);
  }}
}}

.jcr-hero-heading {{
  margin:0 0 18px;
  color:#FFFFFF;
  font-size:48px;
  font-weight:950;
  line-height:1.12;
  letter-spacing:-2.3px;
}}

.jcr-hero-heading span {{
  color:#B6E1CE;
  background:linear-gradient(
    90deg,
    #A7DAC3,
    #E9D1A0
  );
  -webkit-background-clip:text;
  background-clip:text;
  -webkit-text-fill-color:transparent;
}}

.jcr-hero-description {{
  max-width:520px;
  margin:0 0 31px;
  color:rgba(255,255,255,.68);
  font-size:15px;
  line-height:1.82;
  word-break:keep-all;
}}

.jcr-hero-meta {{
  display:flex;
  align-items:center;
  width:max-content;
  max-width:100%;
  padding:13px 17px;
  border:1px solid rgba(255,255,255,.12);
  border-radius:18px;
  background:rgba(5,20,16,.28);
  backdrop-filter:blur(12px);
}}

.jcr-meta-item {{
  display:flex;
  flex-direction:column;
  gap:3px;
}}

.jcr-meta-item span {{
  color:rgba(255,255,255,.40);
  font-size:8px;
  font-weight:900;
  letter-spacing:1.2px;
}}

.jcr-meta-item strong {{
  color:rgba(255,255,255,.90);
  font-size:11px;
  font-weight:850;
  white-space:nowrap;
}}

.jcr-status-ok {{
  color:#82E4B3 !important;
}}

.jcr-meta-divider {{
  width:1px;
  height:28px;
  margin:0 18px;
  background:rgba(255,255,255,.12);
}}

.jcr-hero-symbol {{
  position:relative;
  display:flex;
  align-items:center;
  justify-content:center;
  align-self:center;
  width:210px;
  height:210px;
}}

.jcr-symbol-ring {{
  position:absolute;
  border:1px solid rgba(255,255,255,.15);
  border-radius:50%;
}}

.jcr-ring-one {{
  inset:0;
  animation:jcrRingSpin 22s linear infinite;
}}

.jcr-ring-one::before,
.jcr-ring-two::before {{
  content:"";
  position:absolute;
  top:-4px;
  left:50%;
  width:7px;
  height:7px;
  border-radius:50%;
  background:var(--lux-gold);
  box-shadow:0 0 16px rgba(199,167,106,.8);
}}

.jcr-ring-two {{
  inset:30px;
  border-style:dashed;
  opacity:.65;
  animation:jcrRingSpin 16s linear infinite reverse;
}}

@keyframes jcrRingSpin {{
  to {{
    transform:rotate(360deg);
  }}
}}

.jcr-symbol-core {{
  position:relative;
  display:flex;
  align-items:center;
  justify-content:center;
  width:112px;
  height:112px;
  border:1px solid rgba(255,255,255,.17);
  border-radius:34px;
  transform:rotate(45deg);
  background:
    linear-gradient(
      135deg,
      rgba(255,255,255,.15),
      rgba(255,255,255,.045)
    );
  box-shadow:
    inset 0 1px 0 rgba(255,255,255,.18),
    0 24px 55px rgba(0,0,0,.22);
  backdrop-filter:blur(14px);
}}

.jcr-symbol-core span {{
  transform:rotate(-45deg);
  color:#FFFFFF;
  font-size:58px;
  font-weight:950;
  letter-spacing:-4px;
}}


/* ---------------------------------------------------------
   퀵 내비게이션
--------------------------------------------------------- */

.jcr-section-navigation {{
  display:grid;
  grid-template-columns:repeat(3,1fr);
  gap:9px;
  margin-bottom:17px;
  padding:7px;
  border:1px solid rgba(13,107,80,.09);
  border-radius:20px;
  background:rgba(255,255,255,.72);
  box-shadow:0 8px 25px rgba(17,50,40,.045);
  backdrop-filter:blur(16px);
}}

.jcr-section-navigation a {{
  display:flex;
  align-items:center;
  justify-content:center;
  gap:8px;
  padding:12px 8px;
  border-radius:14px;
  color:#52605A;
  text-decoration:none;
  font-size:11px;
  font-weight:850;
  transition:
    transform .2s ease,
    background .2s ease,
    color .2s ease;
}}

.jcr-section-navigation a span {{
  color:var(--lux-gold);
  font-size:9px;
  font-weight:950;
}}

.jcr-section-navigation a:hover {{
  transform:translateY(-1px);
  background:var(--lux-emerald-soft);
  color:var(--lux-emerald-deep);
}}


/* ---------------------------------------------------------
   모든 공통 카드
--------------------------------------------------------- */

.card {{
  position:relative;
  overflow:hidden;
  margin-bottom:17px !important;
  padding:24px !important;
  border:1px solid rgba(17,50,40,.09) !important;
  border-radius:28px !important;
  background:
    linear-gradient(
      145deg,
      rgba(255,255,255,.99),
      rgba(251,253,252,.97)
    ) !important;
  box-shadow:var(--lux-shadow) !important;
}}

.card::before {{
  content:"";
  position:absolute;
  top:0;
  left:28px;
  right:28px;
  height:1px;
  background:linear-gradient(
    90deg,
    transparent,
    rgba(255,255,255,.95),
    transparent
  );
}}

.section-title {{
  display:flex !important;
  align-items:center !important;
  gap:10px !important;
  margin:0 0 9px !important;
  color:var(--lux-ink) !important;
  font-size:19px !important;
  font-weight:950 !important;
  letter-spacing:-.55px !important;
}}

.section-title::before {{
  content:"";
  width:6px;
  height:20px;
  flex:0 0 6px;
  border-radius:999px;
  background:linear-gradient(
    180deg,
    var(--lux-emerald),
    var(--lux-gold)
  );
  box-shadow:0 5px 12px rgba(13,107,80,.18);
}}


/* ---------------------------------------------------------
   대표 농장 영상
--------------------------------------------------------- */

.main-video-section {{
  padding:11px !important;
  border-color:rgba(13,107,80,.15) !important;
  border-radius:31px !important;
  background:
    linear-gradient(
      145deg,
      #FFFFFF,
      #EFF7F3
    ) !important;
  box-shadow:var(--lux-shadow-large) !important;
}}

.main-video-section::before {{
  content:"LIVE FARM RECORD";
  position:absolute;
  top:25px;
  left:25px;
  z-index:5;
  display:flex;
  align-items:center;
  width:auto;
  height:auto;
  padding:8px 11px;
  border-radius:999px;
  background:rgba(11,25,21,.66);
  color:#FFFFFF;
  font-size:8px;
  font-weight:900;
  letter-spacing:1.15px;
  backdrop-filter:blur(8px);
}}

.main-video-section::after {{
  content:"";
  position:absolute;
  top:32px;
  left:137px;
  z-index:6;
  width:6px;
  height:6px;
  border-radius:50%;
  background:#70E5AF;
  box-shadow:0 0 9px #70E5AF;
}}

.main-video-section video,
.main-video-section .video-box {{
  width:100% !important;
  min-height:0 !important;
  max-height:none !important;
  border-radius:22px !important;
  background:#07100D !important;
}}

.main-video-section video {{
  display:block !important;
  aspect-ratio:16 / 9 !important;
  object-fit:cover !important;
}}

.video-label {{
  display:none !important;
}}


/* ---------------------------------------------------------
   인증 카드
--------------------------------------------------------- */

.cert-grid {{
  display:grid !important;
  grid-template-columns:repeat(4,minmax(0,1fr)) !important;
  gap:11px !important;
  margin:0 0 17px !important;
  scroll-margin-top:20px;
}}

.cert-card {{
  position:relative;
  min-width:0 !important;
  min-height:162px;
  padding:18px 10px 15px !important;
  overflow:hidden;
  border:1px solid rgba(17,50,40,.09) !important;
  border-radius:23px !important;
  background:
    linear-gradient(
      145deg,
      #FFFFFF 0%,
      #F7FAF8 100%
    ) !important;
  box-shadow:0 10px 28px rgba(17,50,40,.055) !important;
  transition:
    transform .25s ease,
    box-shadow .25s ease,
    border-color .25s ease !important;
}}

.cert-card::before {{
  content:"VERIFIED";
  position:absolute;
  top:10px;
  right:10px;
  color:rgba(13,107,80,.32);
  font-size:6px;
  font-weight:950;
  letter-spacing:1px;
}}

.cert-card::after {{
  content:"";
  position:absolute;
  right:-35px;
  bottom:-35px;
  width:90px;
  height:90px;
  border-radius:50%;
  background:rgba(13,107,80,.035);
}}

.cert-card:hover {{
  transform:translateY(-5px);
  border-color:rgba(13,107,80,.22) !important;
  box-shadow:0 20px 42px rgba(17,50,40,.10) !important;
}}

.cert-card img {{
  position:relative;
  z-index:1;
  width:70px !important;
  height:70px !important;
  margin:10px auto 11px !important;
  object-fit:contain !important;
  filter:drop-shadow(0 7px 9px rgba(0,0,0,.07));
}}

.cert-title {{
  position:relative;
  z-index:1;
  color:#34423C !important;
  font-size:12px !important;
  font-weight:900 !important;
  line-height:1.4 !important;
  text-align:center !important;
  word-break:keep-all !important;
}}


/* ---------------------------------------------------------
   이번 주 한 줄 요약
--------------------------------------------------------- */

.summary-card {{
  padding:31px 32px !important;
  overflow:hidden !important;
  background:
    radial-gradient(
      circle at 95% 20%,
      rgba(199,167,106,.15),
      transparent 190px
    ),
    linear-gradient(
      135deg,
      #FFFFFF 0%,
      #EEF7F3 100%
    ) !important;
}}

.summary-card::after {{
  content:"WEEKLY";
  position:absolute;
  right:24px;
  bottom:-18px;
  color:rgba(13,107,80,.045);
  font-size:74px;
  font-weight:950;
  letter-spacing:-5px;
}}

.summary-main {{
  position:relative;
  z-index:1;
  max-width:720px;
  margin:16px 0 10px !important;
  color:var(--lux-ink) !important;
  font-size:27px !important;
  font-weight:950 !important;
  line-height:1.4 !important;
  letter-spacing:-1px !important;
}}

.summary-sub {{
  position:relative;
  z-index:1;
  max-width:720px;
  margin:0 !important;
  color:var(--lux-muted) !important;
  font-size:13px !important;
  line-height:1.8 !important;
}}


/* ---------------------------------------------------------
   인공지능 분석
--------------------------------------------------------- */

.jcr-analysis-card {{
  margin-top:0 !important;
  padding:29px !important;
  scroll-margin-top:20px;
}}

.jcr-analysis-card::after {{
  content:"INTELLIGENCE";
  position:absolute;
  top:21px;
  right:27px;
  color:rgba(13,107,80,.055);
  font-size:23px;
  font-weight:950;
  letter-spacing:-1px;
}}

.jcr-analysis-header {{
  position:relative;
  z-index:1;
  margin-bottom:20px !important;
}}

.jcr-analysis-sub {{
  max-width:590px;
  margin:8px 0 0 !important;
  color:var(--lux-muted) !important;
  font-size:13px !important;
  line-height:1.72 !important;
}}

.jcr-analysis-complete {{
  padding:8px 11px !important;
  border:1px solid rgba(13,107,80,.10) !important;
  border-radius:999px !important;
  background:var(--lux-emerald-soft) !important;
  color:var(--lux-emerald) !important;
  font-size:9px !important;
  font-weight:950 !important;
}}

.jcr-analysis-complete::before {{
  content:"●";
  margin-right:5px;
  color:#37A976;
  font-size:7px;
}}

.jcr-analysis-tabs {{
  display:grid !important;
  grid-template-columns:repeat(3,1fr) !important;
  gap:6px !important;
  margin-bottom:15px !important;
  padding:6px !important;
  border:1px solid rgba(17,50,40,.08) !important;
  border-radius:18px !important;
  background:#EDF1EF !important;
}}

.jcr-analysis-tab {{
  position:relative;
  min-height:45px;
  padding:11px 6px !important;
  border:0 !important;
  border-radius:13px !important;
  background:transparent !important;
  color:#84908A !important;
  font-size:11px !important;
  font-weight:900 !important;
  transition:
    background .2s ease,
    color .2s ease,
    transform .2s ease !important;
}}

.jcr-analysis-tab:hover {{
  color:var(--lux-emerald) !important;
}}

.jcr-analysis-tab.active {{
  transform:translateY(-1px);
  background:#FFFFFF !important;
  color:var(--lux-emerald-deep) !important;
  box-shadow:
    0 2px 4px rgba(17,50,40,.03),
    0 7px 18px rgba(17,50,40,.08) !important;
}}

.jcr-analysis-tab.active::after {{
  content:"";
  position:absolute;
  left:35%;
  right:35%;
  bottom:5px;
  height:2px;
  border-radius:999px;
  background:var(--lux-emerald);
}}

.jcr-analysis-video-wrap {{
  overflow:hidden !important;
  border:1px solid rgba(255,255,255,.10);
  border-radius:23px !important;
  background:#07100D !important;
  box-shadow:0 17px 45px rgba(5,20,15,.16);
}}

.jcr-analysis-video {{
  display:block !important;
  width:100% !important;
  min-height:0 !important;
  max-height:none !important;
  aspect-ratio:16 / 9 !important;
  object-fit:cover !important;
}}

.jcr-integrated-context {{
  margin-top:13px !important;
}}

.jcr-context-panel {{
  padding:17px !important;
  border:1px solid rgba(17,50,40,.08) !important;
  border-radius:19px !important;
  background:
    linear-gradient(
      135deg,
      #F8FAF9,
      #F1F6F3
    ) !important;
  box-shadow:none !important;
}}

.jcr-context-heading {{
  margin-bottom:13px !important;
  color:var(--lux-ink) !important;
  font-size:13px !important;
  font-weight:950 !important;
}}

.jcr-context-values {{
  display:grid !important;
  grid-template-columns:repeat(3,minmax(0,1fr)) !important;
  gap:8px !important;
}}

.jcr-context-values > div {{
  padding:14px 8px !important;
  border:1px solid rgba(17,50,40,.06) !important;
  border-radius:15px !important;
  background:rgba(255,255,255,.80) !important;
  text-align:center !important;
}}

.jcr-context-values span {{
  display:block !important;
  margin-bottom:6px !important;
  color:#8B9691 !important;
  font-size:8px !important;
  font-weight:850 !important;
}}

.jcr-context-values strong {{
  display:block !important;
  color:#26332D !important;
  font-size:11px !important;
  font-weight:950 !important;
  line-height:1.4 !important;
}}

.jcr-visual-summary {{
  display:flex !important;
  align-items:flex-start !important;
  gap:13px !important;
  margin-top:11px !important;
  padding:17px !important;
  border:1px solid rgba(199,167,106,.18) !important;
  border-radius:19px !important;
  background:
    linear-gradient(
      135deg,
      #FBFAF7,
      #F5F0E6
    ) !important;
}}

.jcr-visual-summary-icon {{
  width:40px !important;
  height:40px !important;
  flex:0 0 40px !important;
  border:1px solid rgba(199,167,106,.20);
  border-radius:14px !important;
  background:#FFFFFF !important;
  color:#9B783A !important;
  box-shadow:0 5px 14px rgba(100,75,30,.08);
}}

.jcr-visual-summary-label {{
  color:#9D8B69 !important;
  font-size:8px !important;
  font-weight:950 !important;
  letter-spacing:.4px;
}}

.jcr-visual-summary strong {{
  color:#2A302C !important;
  font-size:14px !important;
  font-weight:950 !important;
}}

.jcr-visual-summary p {{
  margin:5px 0 0 !important;
  color:#756D60 !important;
  font-size:12px !important;
  line-height:1.68 !important;
}}


/* ---------------------------------------------------------
   최근 패턴 카드
--------------------------------------------------------- */

.events-card {{
  padding:29px !important;
}}

.events-card .feature,
.events-card .event-card,
.events-card .event-row {{
  position:relative;
  margin-top:10px !important;
  padding:17px !important;
  overflow:hidden;
  border:1px solid rgba(17,50,40,.07) !important;
  border-radius:18px !important;
  background:
    linear-gradient(
      135deg,
      #FAFBFA,
      #F3F7F5
    ) !important;
  box-shadow:none !important;
  transition:
    transform .2s ease,
    border-color .2s ease !important;
}}

.events-card .feature:hover,
.events-card .event-card:hover,
.events-card .event-row:hover {{
  transform:translateX(3px);
  border-color:rgba(13,107,80,.17) !important;
}}

.mini-btn {{
  border:1px solid rgba(13,107,80,.12) !important;
  background:#FFFFFF !important;
  color:var(--lux-emerald) !important;
  box-shadow:0 4px 12px rgba(17,50,40,.04) !important;
}}


/* ---------------------------------------------------------
   등장 애니메이션
--------------------------------------------------------- */

.jcr-reveal {{
  opacity:0;
  transform:translateY(24px);
  transition:
    opacity .65s cubic-bezier(.2,.7,.2,1),
    transform .65s cubic-bezier(.2,.7,.2,1);
}}

.jcr-reveal.jcr-visible {{
  opacity:1;
  transform:translateY(0);
}}


/* ---------------------------------------------------------
   모바일
--------------------------------------------------------- */

@media (max-width:700px) {{
  body::before {{
    background-size:32px 32px;
  }}

  .page {{
    padding:10px 11px 44px !important;
  }}

  .topbar {{
    min-height:64px !important;
    margin-bottom:11px !important;
  }}

  .topbar::after {{
    display:none;
  }}

  .topbar .brand {{
    font-size:26px !important;
  }}

  .jcr-signature-hero {{
    display:block;
    min-height:0;
    padding:34px 25px 29px;
    border-radius:27px;
  }}

  .jcr-signature-hero::after {{
    right:-15px;
    bottom:-38px;
    font-size:120px;
  }}

  .jcr-hero-heading {{
    margin-bottom:15px;
    font-size:35px;
    line-height:1.16;
    letter-spacing:-1.7px;
  }}

  .jcr-hero-description {{
    margin-bottom:24px;
    font-size:13px;
    line-height:1.75;
  }}

  .jcr-hero-meta {{
    width:100%;
    justify-content:space-between;
    padding:12px 13px;
  }}

  .jcr-meta-divider {{
    margin:0 8px;
  }}

  .jcr-meta-item span {{
    font-size:7px;
  }}

  .jcr-meta-item strong {{
    font-size:9px;
  }}

  .jcr-hero-symbol {{
    display:none;
  }}

  .jcr-section-navigation {{
    gap:4px;
    margin-bottom:12px;
    padding:5px;
    border-radius:16px;
  }}

  .jcr-section-navigation a {{
    flex-direction:column;
    gap:2px;
    padding:9px 3px;
    font-size:9px;
  }}

  .card {{
    margin-bottom:12px !important;
    padding:17px !important;
    border-radius:22px !important;
  }}

  .main-video-section {{
    padding:8px !important;
    border-radius:24px !important;
  }}

  .main-video-section::before {{
    top:17px;
    left:17px;
    padding:6px 8px;
    font-size:7px;
  }}

  .main-video-section::after {{
    top:23px;
    left:111px;
  }}

  .main-video-section video,
  .main-video-section .video-box {{
    border-radius:17px !important;
  }}

  .cert-grid {{
    grid-template-columns:repeat(2,1fr) !important;
    gap:8px !important;
    margin-bottom:12px !important;
  }}

  .cert-card {{
    display:flex !important;
    align-items:center !important;
    min-height:82px !important;
    padding:10px !important;
    border-radius:18px !important;
    text-align:left !important;
  }}

  .cert-card::before {{
    top:7px;
    right:7px;
    font-size:5px;
  }}

  .cert-card img {{
    width:48px !important;
    height:48px !important;
    flex:0 0 48px;
    margin:0 9px 0 0 !important;
  }}

  .cert-title {{
    font-size:10px !important;
    text-align:left !important;
  }}

  .summary-card {{
    padding:22px 20px !important;
  }}

  .summary-card::after {{
    right:9px;
    bottom:-8px;
    font-size:43px;
  }}

  .summary-main {{
    margin-top:12px !important;
    font-size:20px !important;
  }}

  .section-title {{
    font-size:16px !important;
  }}

  .section-title::before {{
    width:5px;
    height:17px;
    flex-basis:5px;
  }}

  .jcr-analysis-card {{
    padding:17px !important;
  }}

  .jcr-analysis-card::after {{
    display:none;
  }}

  .jcr-analysis-header {{
    gap:8px !important;
  }}

  .jcr-analysis-complete {{
    padding:6px 8px !important;
    font-size:7px !important;
  }}

  .jcr-analysis-tabs {{
    gap:3px !important;
    padding:4px !important;
  }}

  .jcr-analysis-tab {{
    min-height:40px;
    padding:9px 2px !important;
    font-size:9px !important;
  }}

  .jcr-analysis-video-wrap {{
    border-radius:17px !important;
  }}

  .jcr-context-panel {{
    padding:13px !important;
  }}

  .jcr-context-values {{
    gap:5px !important;
  }}

  .jcr-context-values > div {{
    padding:11px 4px !important;
  }}

  .jcr-context-values span {{
    font-size:7px !important;
  }}

  .jcr-context-values strong {{
    font-size:9px !important;
  }}

  .jcr-visual-summary {{
    padding:14px !important;
  }}

  .jcr-visual-summary-icon {{
    width:35px !important;
    height:35px !important;
    flex-basis:35px !important;
  }}

  .events-card {{
    padding:18px !important;
  }}
}}


/* JCR_REAL_LOGO_V1 */

.topbar .brand {{
  display:flex !important;
  align-items:center !important;
  justify-content:center !important;
  width:auto !important;
}}

.topbar .brand::before {{
  display:none !important;
}}

.jcr-main-logo {{
  display:block !important;
  width:auto !important;
  height:48px !important;
  max-width:190px !important;
  object-fit:contain !important;
  filter:drop-shadow(0 5px 12px rgba(0,0,0,.08));
}}

.jcr-symbol-core {{
  overflow:hidden !important;
  padding:20px !important;
}}

.jcr-symbol-core span {{
  display:none !important;
}}

.jcr-hero-logo {{
  display:block !important;
  width:100% !important;
  height:100% !important;
  object-fit:contain !important;
  transform:rotate(-45deg) !important;
  filter:brightness(0) invert(1)
    drop-shadow(0 6px 16px rgba(0,0,0,.18));
}}

/* 배경에 있던 JCR 글자 장식 제거 */
.jcr-signature-hero::after {{
  content:"" !important;
  display:none !important;
}}

@media (max-width:700px) {{
  .jcr-main-logo {{
    height:42px !important;
    max-width:165px !important;
  }}
}}


/* JCR_LOGO_FIX_V2 */

.topbar .brand {{
  display:flex !important;
  align-items:center !important;
  justify-content:center !important;
  width:100% !important;
}}

.jcr-main-logo {{
  display:block !important;
  width:auto !important;
  height:64px !important;
  max-width:240px !important;
  object-fit:contain !important;
  object-position:center !important;
  filter:none !important;
  transform:none !important;
}}

.jcr-symbol-core {{
  display:flex !important;
  align-items:center !important;
  justify-content:center !important;
  overflow:hidden !important;
  padding:14px !important;
}}

.jcr-hero-logo {{
  display:block !important;
  width:100% !important;
  height:100% !important;
  object-fit:contain !important;
  object-position:center !important;
  filter:none !important;
  transform:rotate(-45deg) !important;
}}

@media (max-width:700px) {{
  .jcr-main-logo {{
    height:54px !important;
    max-width:210px !important;
  }}
}}


/* JCR_REFINED_UI_V2 */

:root {{
  --r-bg:#F6F7F5;
  --r-card:#FFFFFF;
  --r-text:#18221E;
  --r-sub:#6D7772;
  --r-line:#E5E9E6;
  --r-green:#1F6B4E;
  --r-green-dark:#164D39;
  --r-green-soft:#EAF3EE;
  --r-gold:#B89455;
  --r-shadow:0 14px 38px rgba(28,55,43,.07);
}}

body {{
  background:
    linear-gradient(180deg,#F9FAF8 0%,#F4F6F4 100%) !important;
}}

.page {{
  max-width:960px !important;
  padding:18px 22px 64px !important;
}}

/* 상단 로고 영역 */
.topbar {{
  min-height:76px !important;
  margin-bottom:14px !important;
  padding:6px 0 14px !important;
}}

.topbar::before {{
  left:0 !important;
  right:0 !important;
  background:linear-gradient(
    90deg,
    transparent,
    rgba(31,107,78,.12),
    transparent
  ) !important;
}}

.topbar::after {{
  display:none !important;
}}

.jcr-main-logo {{
  height:58px !important;
  max-width:220px !important;
  filter:none !important;
}}

/* 히어로 전면 재구성 */
.jcr-signature-hero {{
  display:block !important;
  min-height:0 !important;
  margin-bottom:14px !important;
  padding:42px 46px 38px !important;
  border:1px solid rgba(255,255,255,.10) !important;
  border-radius:28px !important;
  background:
    linear-gradient(
      135deg,
      #173C2F 0%,
      #205C45 58%,
      #2A7255 100%
    ) !important;
  box-shadow:0 22px 60px rgba(26,69,51,.16) !important;
}}

.jcr-signature-hero::before {{
  opacity:.10 !important;
  background-size:56px 56px !important;
}}

.jcr-signature-hero::after {{
  display:none !important;
}}

.jcr-hero-content {{
  max-width:680px !important;
}}

.jcr-hero-eyebrow {{
  margin-bottom:17px !important;
  padding:7px 11px !important;
  border-color:rgba(255,255,255,.14) !important;
  background:rgba(255,255,255,.07) !important;
  font-size:8px !important;
}}

.jcr-hero-heading {{
  margin-bottom:15px !important;
  font-size:42px !important;
  line-height:1.16 !important;
  letter-spacing:-1.9px !important;
}}

.jcr-hero-heading span {{
  background:none !important;
  -webkit-text-fill-color:initial !important;
  color:#CFE4D8 !important;
}}

.jcr-hero-description {{
  max-width:620px !important;
  margin-bottom:25px !important;
  color:rgba(255,255,255,.72) !important;
  font-size:14px !important;
  line-height:1.8 !important;
}}

.jcr-hero-meta {{
  padding:12px 15px !important;
  border-radius:14px !important;
  background:rgba(10,33,25,.26) !important;
}}

.jcr-meta-divider {{
  margin:0 15px !important;
}}

.jcr-hero-symbol {{
  display:none !important;
}}

/* 네비게이션 단순화 */
.jcr-section-navigation {{
  margin-bottom:14px !important;
  padding:5px !important;
  border:1px solid var(--r-line) !important;
  border-radius:16px !important;
  background:#FFFFFF !important;
  box-shadow:0 7px 20px rgba(28,55,43,.045) !important;
}}

.jcr-section-navigation a {{
  padding:11px 8px !important;
  border-radius:11px !important;
  color:#5B6761 !important;
  font-size:11px !important;
}}

.jcr-section-navigation a span {{
  color:var(--r-green) !important;
}}

.jcr-section-navigation a:hover {{
  background:var(--r-green-soft) !important;
  color:var(--r-green-dark) !important;
}}

/* 영상이 첫 번째 핵심처럼 보이게 */
.main-video-section {{
  padding:9px !important;
  border:1px solid rgba(31,107,78,.12) !important;
  border-radius:24px !important;
  background:#FFFFFF !important;
  box-shadow:var(--r-shadow) !important;
}}

.main-video-section::before {{
  top:18px !important;
  left:18px !important;
  padding:6px 9px !important;
  border-radius:999px !important;
  background:rgba(14,28,22,.70) !important;
  font-size:7px !important;
}}

.main-video-section::after {{
  top:24px !important;
  left:115px !important;
}}

.main-video-section video,
.main-video-section .video-box {{
  border-radius:17px !important;
}}

/* 카드 공통 단순화 */
.card {{
  border:1px solid var(--r-line) !important;
  border-radius:22px !important;
  background:#FFFFFF !important;
  box-shadow:var(--r-shadow) !important;
}}

.card::before {{
  display:none !important;
}}

/* 인증 영역 */
.cert-grid {{
  gap:10px !important;
}}

.cert-card {{
  min-height:145px !important;
  border-radius:18px !important;
  background:#FFFFFF !important;
  box-shadow:0 10px 25px rgba(28,55,43,.045) !important;
}}

.cert-card::before {{
  color:rgba(31,107,78,.28) !important;
}}

.cert-card img {{
  width:64px !important;
  height:64px !important;
}}

.cert-title {{
  font-size:11px !important;
}}

/* 요약 카드 */
.summary-card {{
  padding:26px 28px !important;
  background:
    linear-gradient(
      135deg,
      #FFFFFF 0%,
      #F3F8F5 100%
    ) !important;
}}

.summary-card::after {{
  display:none !important;
}}

.summary-main {{
  font-size:23px !important;
  line-height:1.45 !important;
}}

/* 인공지능 분석 카드 */
.jcr-analysis-card {{
  padding:25px !important;
}}

.jcr-analysis-card::after {{
  display:none !important;
}}

.jcr-analysis-tabs {{
  background:#EFF2F0 !important;
  border-radius:15px !important;
}}

.jcr-analysis-tab {{
  min-height:42px !important;
  border-radius:10px !important;
}}

.jcr-analysis-tab.active {{
  color:var(--r-green-dark) !important;
  box-shadow:0 5px 14px rgba(28,55,43,.07) !important;
}}

.jcr-analysis-tab.active::after {{
  display:none !important;
}}

.jcr-analysis-video-wrap {{
  border-radius:18px !important;
  box-shadow:0 14px 30px rgba(18,41,31,.13) !important;
}}

.jcr-context-panel {{
  background:#F6F8F6 !important;
}}

.jcr-visual-summary {{
  border-color:rgba(184,148,85,.14) !important;
  background:#F8F5EF !important;
}}

/* 모바일 */
@media (max-width:700px) {{
  .page {{
    padding:10px 11px 40px !important;
  }}

  .topbar {{
    min-height:64px !important;
    padding-bottom:10px !important;
  }}

  .jcr-main-logo {{
    height:46px !important;
    max-width:180px !important;
  }}

  .jcr-signature-hero {{
    padding:30px 24px 27px !important;
    border-radius:23px !important;
  }}

  .jcr-hero-heading {{
    font-size:32px !important;
    letter-spacing:-1.3px !important;
  }}

  .jcr-hero-description {{
    font-size:12px !important;
    line-height:1.7 !important;
  }}

  .jcr-hero-meta {{
    width:100% !important;
    padding:11px 12px !important;
  }}

  .jcr-meta-divider {{
    margin:0 8px !important;
  }}

  .jcr-meta-item strong {{
    font-size:9px !important;
  }}

  .jcr-section-navigation a {{
    font-size:9px !important;
  }}

  .card {{
    border-radius:19px !important;
  }}

  .summary-main {{
    font-size:19px !important;
  }}
}}


/* JCR_DENSITY_HEATMAP_V1 */

/* 기존 군집 박스·화살표·가상 객체 전부 제거 */
.jcr-vision-cluster > * {{
  display:none !important;
}}

/* 군집 모드를 밀집도 히트맵 모드로 재사용 */
.jcr-vision-cluster {{
  display:none;
  position:absolute;
  inset:0;
  overflow:hidden;
  opacity:.94;
  background:
    radial-gradient(
      ellipse 19% 25% at 62% 57%,
      rgba(255,42,32,.86) 0%,
      rgba(255,96,27,.74) 22%,
      rgba(255,201,44,.48) 48%,
      rgba(255,224,74,0) 74%
    ),
    radial-gradient(
      ellipse 16% 21% at 34% 65%,
      rgba(255,91,28,.76) 0%,
      rgba(255,173,32,.58) 34%,
      rgba(255,220,60,0) 74%
    ),
    radial-gradient(
      ellipse 13% 18% at 75% 30%,
      rgba(255,161,25,.62) 0%,
      rgba(255,218,58,.38) 42%,
      rgba(255,225,70,0) 75%
    ),
    radial-gradient(
      ellipse 12% 15% at 47% 39%,
      rgba(255,199,35,.48) 0%,
      rgba(255,225,70,0) 72%
    );
  mix-blend-mode:screen;
  filter:blur(2px) saturate(1.12);
  animation:jcrDensityBreath 3.2s ease-in-out infinite;
}}

/* cluster 탭을 눌렀을 때 히트맵 노출 */
.jcr-vision-layer.mode-cluster .jcr-vision-cluster {{
  display:block !important;
}}

/* 히트맵 범례 */
.jcr-vision-layer.mode-cluster::after {{
  content:"낮음   활동 밀집도   높음";
  position:absolute;
  right:14px;
  bottom:14px;
  z-index:8;
  display:block;
  padding:8px 11px 8px 70px;
  border:1px solid rgba(255,255,255,.20);
  border-radius:999px;
  background:
    linear-gradient(
      90deg,
      #2F7BFF 0%,
      #38CFA3 24%,
      #F2DF43 52%,
      #FF8A25 76%,
      #FF3328 100%
    ) 10px 50% / 52px 7px no-repeat,
    rgba(10,18,15,.72);
  color:#FFFFFF;
  font-size:8px;
  font-weight:850;
  letter-spacing:.2px;
  backdrop-filter:blur(8px);
  pointer-events:none;
}}

/* 히트맵 모드 라벨 */
.jcr-vision-layer.mode-cluster::before {{
  content:"DENSITY HEATMAP";
  position:absolute;
  top:14px;
  right:14px;
  z-index:8;
  display:block;
  padding:7px 10px;
  border:1px solid rgba(255,255,255,.16);
  border-radius:999px;
  background:rgba(11,24,20,.68);
  color:#FFFFFF;
  font-size:8px;
  font-weight:900;
  letter-spacing:1px;
  backdrop-filter:blur(8px);
  pointer-events:none;
}}

@keyframes jcrDensityBreath {{
  0%,100% {{
    opacity:.76;
    transform:scale(.985);
  }}

  50% {{
    opacity:.96;
    transform:scale(1.015);
  }}
}}

/* 두 번째 탭 활성화 색상을 히트맵 계열로 강조 */
.jcr-analysis-tab:nth-child(2).active {{
  color:#A8491E !important;
  background:
    linear-gradient(
      135deg,
      #FFFFFF,
      #FFF5ED
    ) !important;
}}

.jcr-analysis-tab:nth-child(2).active::before {{
  content:"";
  display:inline-block;
  width:7px;
  height:7px;
  margin-right:5px;
  border-radius:50%;
  background:linear-gradient(135deg,#FFD43B,#FF4635);
  box-shadow:0 0 0 4px rgba(255,92,44,.08);
}}

@media (max-width:700px) {{
  .jcr-vision-layer.mode-cluster::before {{
    top:9px;
    right:9px;
    padding:5px 7px;
    font-size:6px;
  }}

  .jcr-vision-layer.mode-cluster::after {{
    right:9px;
    bottom:9px;
    padding:6px 8px 6px 56px;
    background-size:40px 6px;
    background-position:9px 50%;
    font-size:6px;
  }}
}}


/* JCR_REAL_DENSITY_HEATMAP_V2 */

.jcr-vision-cluster {{
  display:none !important;
  position:absolute !important;
  inset:0 !important;
  opacity:1 !important;
  background:
    url("/heatmaps/current_density.png?v=20260629")
    center / 100% 100%
    no-repeat !important;
  mix-blend-mode:screen !important;
  filter:none !important;
  transform:none !important;
  animation:none !important;
}}

.jcr-vision-layer.mode-cluster .jcr-vision-cluster {{
  display:block !important;
}}

.jcr-vision-cluster > * {{
  display:none !important;
}}

.jcr-vision-layer.mode-cluster::before {{
  content:"프레임별 움직임 밀집 분석" !important;
  position:absolute !important;
  top:14px !important;
  right:14px !important;
  z-index:8 !important;
  display:block !important;
  padding:7px 10px !important;
  border:1px solid rgba(255,255,255,.18) !important;
  border-radius:999px !important;
  background:rgba(8,18,15,.72) !important;
  color:#FFFFFF !important;
  font-size:8px !important;
  font-weight:900 !important;
  letter-spacing:.3px !important;
  backdrop-filter:blur(8px) !important;
}}

.jcr-vision-layer.mode-cluster::after {{
  content:"낮음   움직임 밀집도   높음" !important;
  position:absolute !important;
  right:14px !important;
  bottom:14px !important;
  z-index:8 !important;
  display:block !important;
  padding:8px 11px 8px 72px !important;
  border:1px solid rgba(255,255,255,.20) !important;
  border-radius:999px !important;
  background:
    linear-gradient(
      90deg,
      #244BFF 0%,
      #1AC7E8 25%,
      #42D36B 48%,
      #FFE342 70%,
      #FF3428 100%
    ) 10px 50% / 54px 7px no-repeat,
    rgba(8,18,15,.72) !important;
  color:#FFFFFF !important;
  font-size:8px !important;
  font-weight:850 !important;
  backdrop-filter:blur(8px) !important;
}}

@media (max-width:700px) {{
  .jcr-vision-layer.mode-cluster::before {{
    top:9px !important;
    right:9px !important;
    padding:5px 7px !important;
    font-size:6px !important;
  }}

  .jcr-vision-layer.mode-cluster::after {{
    right:9px !important;
    bottom:9px !important;
    padding:6px 8px 6px 58px !important;
    background-size:42px 6px !important;
    background-position:9px 50% !important;
    font-size:6px !important;
  }}
}}


/* JCR_DISABLE_STATIC_HEATMAP_V3 */

.jcr-vision-layer.mode-cluster {{
  display:none !important;
}}

.jcr-vision-layer.mode-cluster::before,
.jcr-vision-layer.mode-cluster::after {{
  display:none !important;
}}

.jcr-vision-cluster {{
  display:none !important;
}}

</style>

<script async src="https://www.googletagmanager.com/gtag/js?id=G-XKZ6FWYZ9D"></script>
<script>
window.dataLayer = window.dataLayer || [];
function gtag(){{dataLayer.push(arguments);}}
gtag('js', new Date());

gtag('config', 'G-XKZ6FWYZ9D');
</script>

<link rel="stylesheet" href="/assets/final-presentation.css?v=green-dot-absolute-final-20260629">
<link rel="stylesheet" href="/assets/patent-report-v2.css?v=real-consumer-report-v3-20260704">
</head>

<body>
<div class="page eyeran-main">

  <div class="topbar">
    <div class="brand">
    <img class="jcr-main-logo" src="/assets/logo.png?v=header-video-fix-v2-20260629" alt="JCR 로고">
  </div>
  </div>


  <!-- JCR_SIGNATURE_HERO_V1 -->
  <section class="jcr-signature-hero">
    <div class="jcr-hero-glow jcr-glow-one"></div>
    <div class="jcr-hero-glow jcr-glow-two"></div>

    <div class="jcr-hero-content">
      <div class="jcr-hero-eyebrow">
        <span class="jcr-live-dot"></span>
        FARM TRANSPARENCY REPORT
      </div>

      <h1 class="jcr-hero-heading">
        이번주 농장을<br>
        <span>확인해보세요</span>
      </h1>

      <p class="jcr-hero-description">
        농장 영상부터 인증 정보와 인공지능 행동 분석까지,
        소비자가 직접 확인할 수 있는 투명한 농장 리포트입니다.
      </p>

      <div class="jcr-hero-meta">
        <div class="jcr-meta-item">
          <span>PRODUCT</span>
          <strong>EGG-0001</strong>
        </div>

        <div class="jcr-meta-divider"></div>

        <div class="jcr-meta-item">
          <span>REPORT</span>
          <strong>이번 주 기록</strong>
        </div>

        <div class="jcr-meta-divider"></div>

        <div class="jcr-meta-item">
          <span>STATUS</span>
          <strong class="jcr-status-ok">정상 운영</strong>
        </div>
      </div>
    </div>

    <div class="jcr-hero-symbol">
      <div class="jcr-symbol-ring jcr-ring-one"></div>
      <div class="jcr-symbol-ring jcr-ring-two"></div>
      <div class="jcr-symbol-core">
        <img class="jcr-hero-logo" src="/assets/logo.png?v=header-video-fix-v2-20260629" alt="JCR 로고">
      </div>
    </div>
  </section>

  <div class="jcr-section-navigation">
    <a href="#farm-video">
      <span>01</span>
      농장 영상
    </a>

    <a href="#jcr-ai-analysis">
      <span>02</span>
      인공지능 분석
    </a>

    <a href="#certifications">
      <span>03</span>
      공식 인증
    </a>
  </div>

  <div class="card video-card main-video-section" id="farm-video">
    <div class="video-label">🎥 이번주 농장 영상</div>
    {video_html}
  </div>

  <div class="cert-grid" id="certifications">
    <div class="cert-card">
      <img src="/assets/6indus.png?v=cert-transparent-fix-20260629" alt="6차산업 인증">
      <div class="cert-title">6차산업 인증</div>
    </div>
    <div class="cert-card">
      <img src="/assets/naepo.png?v=cert-transparent-fix-20260629" alt="내포천애 인증">
      <div class="cert-title">내포천애 인증</div>
    </div>
    <div class="cert-card">
      <img src="/assets/muhang.png?v=cert-transparent-fix-20260629" alt="무항생제 인증">
      <div class="cert-title">무항생제 인증</div>
    </div>
    <div class="cert-card">
      <img src="/assets/haccp.png?v=cert-transparent-fix-20260629" alt="안전관리 인증">
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
      업로드된 농장 영상을 프레임 단위로 분석하여 움직임 변화, 밀집도 히트맵, 공간별 활동 집중도를 요약합니다.
    </p>

    <div class="ai-result-grid">
      <div class="ai-result-card">
        <div class="label">활동량 분석</div>
        <div class="value">{motion_text(metrics)}</div>
      </div>
      <div class="ai-result-card">
        <div class="label">밀집도 히트맵</div>
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
          농장 영상에서 움직임과 밀집도 히트맵이 집중된 구간을 AI가 분석했습니다.
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
        data-title="밀집도 히트맵 분석" data-mode="cluster"
      >
        밀집도 히트맵
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
            밀집도 히트맵 분석
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
    cluster:"인공지능 밀집도 히트맵 분석",
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


<script>
// JCR_SIGNATURE_UI_SCRIPT_V1
document.addEventListener("DOMContentLoaded", function() {{
  const revealItems = document.querySelectorAll(
    ".card, .cert-card, .jcr-section-navigation"
  );

  revealItems.forEach(function(item, index) {{
    item.classList.add("jcr-reveal");
    item.style.transitionDelay =
      Math.min(index * 45, 240) + "ms";
  }});

  if ("IntersectionObserver" in window) {{
    const observer = new IntersectionObserver(
      function(entries) {{
        entries.forEach(function(entry) {{
          if (entry.isIntersecting) {{
            entry.target.classList.add("jcr-visible");
            observer.unobserve(entry.target);
          }}
        }});
      }},
      {{
        threshold:0.08,
        rootMargin:"0px 0px -25px 0px"
      }}
    );

    revealItems.forEach(function(item) {{
      observer.observe(item);
    }});
  }} else {{
    revealItems.forEach(function(item) {{
      item.classList.add("jcr-visible");
    }});
  }}
}});
</script>


<script>
// JCR_SYNCED_HEATMAP_VIDEO_V3
document.addEventListener("DOMContentLoaded", function() {{
  const video = document.querySelector(".jcr-analysis-video");
  const tabs = document.querySelectorAll(".jcr-analysis-tab");
  const visionLayer = document.querySelector(".jcr-vision-layer");

  if (!video || !tabs.length) {{
    return;
  }}

  const normalSource = "/videos/highlight.mp4?v=20";
  const heatmapSource = "/videos/density_heatmap.mp4?v=10";

  tabs.forEach(function(tab) {{
    tab.addEventListener("click", function() {{
      const mode = tab.dataset.mode;
      const currentTime = video.currentTime || 0;
      const wasPlaying = !video.paused;

      if (mode === "cluster") {{
        if (!video.src.includes("density_heatmap.mp4")) {{
          video.src = heatmapSource;
          video.load();

          video.addEventListener(
            "loadedmetadata",
            function restoreHeatmapTime() {{
              video.currentTime = Math.min(
                currentTime,
                video.duration || currentTime
              );

              if (wasPlaying) {{
                video.play().catch(function() {{}});
              }}
            }},
            {{ once:true }}
          );
        }}

        if (visionLayer) {{
          visionLayer.style.display = "none";
        }}
      }} else {{
        if (!video.src.includes("highlight.mp4")) {{
          video.src = normalSource;
          video.load();

          video.addEventListener(
            "loadedmetadata",
            function restoreNormalTime() {{
              video.currentTime = Math.min(
                currentTime,
                video.duration || currentTime
              );

              if (wasPlaying) {{
                video.play().catch(function() {{}});
              }}
            }},
            {{ once:true }}
          );
        }}

        if (visionLayer) {{
          visionLayer.style.display = "";
        }}
      }}
    }});
  }});
}});
</script>

<script src="/assets/final-presentation.js?v=green-dot-absolute-final-20260629" defer></script>
<script src="/assets/patent-report-v2.js?v=real-consumer-report-v3-20260704" defer></script>
</body>
</html>
"""
    return HTMLResponse(page)

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
