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
        <div class="video-box" style="display:flex;align-items:center;justify-content:center;min-height:320px;color:#666;font-weight:700;">
          아직 표시할 영상이 준비되지 않았어요.
        </div>
        '''
    )

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
    .back-link {{
      display:inline-flex;
      align-items:center;
      gap:6px;
      text-decoration:none;
      color:#111;
      font-size:14px;
      font-weight:700;
      margin-bottom:14px;
    }}
    .top {{
      display:flex;
      align-items:center;
      margin-bottom:18px;
    }}
    .logo {{
      font-size:38px;
      font-weight:900;
      letter-spacing:-1.5px;
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
    .hero-grid {{
      display:grid;
      grid-template-columns:1.1fr 0.9fr;
      gap:18px;
      align-items:start;
      margin-bottom:18px;
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
    .summary-hero {{
      background:#f7fbf8;
      border:1px solid #dceee2;
      border-radius:22px;
      padding:18px;
      margin-bottom:14px;
    }}
    .summary-hero .big {{
      font-size:20px;
      font-weight:800;
      line-height:1.5;
      letter-spacing:-0.3px;
      margin-bottom:8px;
    }}
    .summary-hero .small {{
      color:#5f6b63;
      font-size:15px;
      line-height:1.7;
    }}
    .status-grid {{
      display:grid;
      grid-template-columns:repeat(3,1fr);
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
      color:#6b8a74;
      font-size:13px;
      margin-bottom:3px;
    }}
    .event-text {{
      font-size:16px;
      font-weight:700;
      line-height:1.55;
      margin-bottom:8px;
      word-break:keep-all;
      color:#234030;
    }}
    .alert-row {{
      background:#e8f7ec;
      color:#234030;
      border:1px solid #d6eedc;
    }}
    .alert-row .icon-box {{
      background:#d8f0df;
      color:#2b5c49;
    }}
    .alert-row .event-time {{
      color:#6b8a74;
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
    .cta-wrap {{
      margin-top:18px;
    }}
    .cta-btn {{
      display:block;
      width:100%;
      text-align:center;
      text-decoration:none;
      padding:18px 20px;
      border-radius:18px;
      background:#111;
      color:#fff;
      font-size:18px;
      font-weight:800;
      letter-spacing:-0.3px;
    }}
    @media (max-width:900px) {{
      .hero-grid {{ grid-template-columns:1fr; }}
      .status-grid {{ grid-template-columns:1fr; }}
      .headline {{ font-size:28px; }}
      .page {{ padding:18px 14px 28px; }}
    }}
  </style>
</head>
<body>
  <div class="page">
    <a href="https://junada040828.cafe24.com/skin-skin7" target="_blank" class="back-link">← 구매 페이지로 돌아가기</a>

    <div class="top">
      <div class="logo">JCR.</div>
    </div>

    <div class="headline">농장 하루 요약</div>
    <div class="sub">AI가 오늘 농장의 움직임을 살펴보고 편안하게 읽을 수 있게 정리했어요 🌿</div>

    <div class="hero-grid">
      <div>
        <div class="card">
          {video_html}
        </div>
      </div>

      <div>
        <div class="card">
          <div class="section-title">오늘 한 줄 요약</div>

          <div class="summary-hero">
            <div class="big">{html.escape(one_line)}</div>
            <div class="small">{html.escape(summary)}</div>
          </div>

          <div class="status-grid">
            <div class="human-box">
              <div class="label">움직임</div>
              <div class="value">{motion_text(metrics)}</div>
            </div>
            <div class="human-box">
              <div class="label">모여 있는 정도</div>
              <div class="value">{density_text(metrics)}</div>
            </div>
            <div class="human-box">
              <div class="label">오늘의 변화</div>
              <div class="value">{change_text(metrics)}</div>
            </div>
          </div>

          <div class="cta-wrap">
            <a href="https://junada040828.cafe24.com/skin-skin7" target="_blank" class="cta-btn">
              JCR 계란 구독하기
            </a>
          </div>
        </div>
      </div>
    </div>

    <div class="card">
      <div class="section-title">최근 패턴 변화</div>
      {card_html(e1, "🪺")}
      {card_html(e2, "♡")}
      {card_html(e3, "⚠")}
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
'''

new_s, n = pattern.subn(new_func, s, count=1)
if n != 1:
    raise SystemExit("product_page replace failed")

p.write_text(new_s, encoding="utf-8")
print("DONE")
