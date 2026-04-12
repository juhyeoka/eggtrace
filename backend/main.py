import html
import statistics
import time
import json, hashlib, time
from pathlib import Path
from statistics import mean, pstdev
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles

from backend.llm_summary import generate_summary

app = FastAPI()
app.mount("/videos", StaticFiles(directory="./static/videos"), name="videos")

BASE = Path(__file__).resolve().parents[1]
EVENTS = BASE / "data" / "events.jsonl"
PRODUCTS = BASE / "configs" / "products.json"

DATA_DIR = BASE / "data"
CLIPS_DIR = DATA_DIR / "clips"
THUMBS_DIR = DATA_DIR / "thumbs"
HEATMAPS_DIR = DATA_DIR / "heatmaps"

HASH_FIELDS = {"hash", "prev_hash", "seq", "sealed_at"}

# ----------------------------
# 파일 서빙(증거)
# ----------------------------
@app.get("/clips/{filename}")
def clip_file(filename: str):
    p = CLIPS_DIR / filename
    if not p.exists():
        raise HTTPException(status_code=404, detail="clip not found")
    return FileResponse(p, media_type="video/mp4")

@app.get("/thumbs/{filename}")
def thumb_file(filename: str):
    p = THUMBS_DIR / filename
    if not p.exists():
        raise HTTPException(status_code=404, detail="thumb not found")
    return FileResponse(p, media_type="image/jpeg")

@app.get("/heatmaps/{filename}")
def heatmap_file(filename: str):
    p = HEATMAPS_DIR / filename
    if not p.exists():
        raise HTTPException(status_code=404, detail="heatmap not found")
    return FileResponse(p, media_type="image/png")

def _file_url(path_str: str | None):
    if not path_str:
        return None
    s = str(path_str).replace("\\", "/")

    # 절대경로/상대경로 모두 처리
    if "/data/clips/" in s or s.startswith("data/clips/") or s.endswith(".mp4"):
        return "/clips/" + s.split("/")[-1]
    if "/data/thumbs/" in s or s.startswith("data/thumbs/") or s.endswith((".jpg", ".jpeg")):
        return "/thumbs/" + s.split("/")[-1]
    if "/data/heatmaps/" in s or s.startswith("data/heatmaps/") or s.endswith(".png"):
        return "/heatmaps/" + s.split("/")[-1]
    return None

# ----------------------------
# 데이터 로드
# ----------------------------
def read_events():
    if not EVENTS.exists():
        return []
    txt = EVENTS.read_text(encoding="utf-8").strip()
    if not txt:
        return []
    return [json.loads(l) for l in txt.splitlines()]

def read_products():
    if not PRODUCTS.exists():
        return {}
    return json.loads(PRODUCTS.read_text(encoding="utf-8"))

# ----------------------------
# 무결성(해시체인) 검증
# ----------------------------
def _canonical_for_hash(e: dict) -> str:
    clean = {k: v for k, v in e.items() if k not in HASH_FIELDS}
    return json.dumps(clean, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

def _sha256_hex(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

def verify_integrity(events: list, genesis: str = "GENESIS"):
    if not events:
        return {"ok": True, "last_hash": None, "reason": "no events"}
    prev = genesis
    last_hash = None
    for idx, e in enumerate(events, start=1):
        expected = _sha256_hex(prev + "|" + _canonical_for_hash(e))
        if e.get("seq") != idx:
            return {"ok": False, "last_hash": None, "reason": f"seq mismatch at {idx}"}
        if e.get("prev_hash") != prev:
            return {"ok": False, "last_hash": None, "reason": f"prev_hash mismatch at {idx}"}
        if e.get("hash") != expected:
            return {"ok": False, "last_hash": None, "reason": f"hash mismatch at {idx}"}
        prev = expected
        last_hash = expected
    return {"ok": True, "last_hash": last_hash, "reason": None}

# ----------------------------
# 지표/점수
# ----------------------------
def compute_metrics(events):
    if not events:
        return {}
    motions = [float(e.get("motion_ratio", 0) or 0) for e in events]
    flows = [float(e.get("flow_mean_mag", 0) or 0) for e in events if e.get("flow_mean_mag") is not None]
    comps = [float(e.get("cluster_compactness", 0) or 0) for e in events if e.get("cluster_compactness") is not None]

    return {
        "avg_motion": round(mean(motions), 3),
        "avg_flow": round(mean(flows), 3) if flows else None,
        "avg_compactness": round(mean(comps), 3) if comps else None,
        "behavior_variance_index": round(pstdev(motions), 4) if len(motions) > 1 else 0.0,
        "night_stability_score": 50,
        "event_count": len(events),
    }

def compute_score(metrics):
    score = 100
    bvi = metrics.get("behavior_variance_index", 0.0)
    comp = metrics.get("avg_compactness")

    if bvi > 0.12:
        score -= 20
    elif bvi > 0.08:
        score -= 10

    if comp is not None and comp < 0.10:
        score -= 10

    score = max(0, min(100, int(score)))
    if score >= 80:
        label = "안정적"
    elif score >= 60:
        label = "보통"
    else:
        label = "주의"
    return score, label

def filter_window(events, days: int):
    now = time.time()
    cutoff = now - days * 86400
    return [e for e in events if float(e.get("time", 0) or 0) >= cutoff]

def _tag_badge(e):
    tags = e.get("tags") or []
    sev = e.get("severity") or "low"
    if not tags:
        return ""
    color = {"low":"#16a34a","mid":"#d97706","high":"#dc2626"}.get(sev, "#111")
    return f"<span style='display:inline-block;padding:3px 8px;border-radius:999px;border:1px solid #eee;color:{color};font-weight:800;font-size:12px;background:#fff;'>{sev.upper()}: {', '.join(tags)}</span>"

def _evidence_buttons(e):
    clip = _file_url(e.get("clip_path"))
    thumb = _file_url(e.get("thumb_path"))
    heat = _file_url(e.get("heatmap_path"))

    btns = []
    if clip:
        btns.append(f"<a class='btn' href='{clip}' target='_blank'>▶ clip</a>")
    if thumb:
        btns.append(f"<a class='btn' href='{thumb}' target='_blank'>🖼 thumb</a>")
    if heat:
        btns.append(f"<a class='btn' href='{heat}' target='_blank'>🌡 heatmap</a>")
    return " ".join(btns) if btns else "<span style='color:#999'>증거 파일 없음</span>"

STYLE = """
<style>
  body { font-family: -apple-system, BlinkMacSystemFont, sans-serif; padding: 30px; max-width: 980px; margin: 0 auto; background:#fafafa; }
  a { color:#2563eb; text-decoration:none; }
  .toplinks { display:flex; gap:12px; margin-bottom:14px; }
  .pill { display:inline-block; padding:6px 10px; border:1px solid #ddd; border-radius:999px; background:#fff; }
  .row { display:flex; gap:12px; align-items:center; margin:10px 0 18px 0; flex-wrap:wrap; }
  .box { padding:8px 12px; border:1px solid #ddd; border-radius:10px; background:#fff; }
  .btn { display:inline-block; padding:6px 10px; border:1px solid #ddd; border-radius:10px; background:#fff; color:#111; font-size:13px; }
  .btn:hover { background:#f3f4f6; }
  table { width:100%; border-collapse:collapse; background:#fff; border:1px solid #eee; border-radius:12px; overflow:hidden; }
  th, td { padding:10px; border-bottom:1px solid #f1f1f1; vertical-align:top; font-size:14px; }
  th { background:#fafafa; text-align:left; }
  code { background:#fff; border:1px solid #eee; padding:2px 6px; border-radius:8px; }
</style>
"""




def product_page(code: str, days: int = 30, farm_id: str = "farm1", lot_id: str = "lotA"):
    return HTMLResponse(f"""
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
      background:#f4f4f1;
      font-family:-apple-system,BlinkMacSystemFont,"Apple SD Gothic Neo","Noto Sans KR",sans-serif;
      color:#111;
    }}
    .app {{
      max-width:430px;
      margin:0 auto;
      min-height:100vh;
      padding:18px 14px 28px;
      background:#f4f4f1;
    }}
    .top {{
      display:flex;
      justify-content:space-between;
      align-items:center;
      margin-bottom:10px;
    }}
    .logo {{
      font-size:34px;
      font-weight:900;
      letter-spacing:-1.5px;
    }}
    .menu {{
      font-size:34px;
      line-height:1;
      color:#444;
    }}
    .title {{
      font-size:24px;
      font-weight:900;
      margin:8px 0 14px;
      letter-spacing:-0.6px;
    }}
    .card {{
      background:#fff;
      border-radius:24px;
      padding:14px;
      margin-bottom:14px;
      box-shadow:0 2px 10px rgba(0,0,0,0.06);
    }}
    .video-box {{
      position:relative;
      overflow:hidden;
      border-radius:22px;
      background:#ddd;
    }}
    video {{
      width:100%;
      display:block;
      border-radius:22px;
      background:#111;
    }}
    .play {{
      position:absolute;
      left:50%;
      top:50%;
      transform:translate(-50%,-50%);
      width:74px;
      height:74px;
      border-radius:50%;
      background:#aeeccf;
      display:flex;
      align-items:center;
      justify-content:center;
      font-size:34px;
      color:#1f4b39;
      box-shadow:0 8px 24px rgba(112,220,176,0.35);
      pointer-events:none;
    }}
    .analysis-title {{
      font-size:18px;
      font-weight:800;
      margin-bottom:2px;
    }}
    .analysis-sub {{
      color:#555;
      font-size:14px;
      margin-bottom:10px;
    }}
    .mini-chart {{
      width:100%;
      height:120px;
      border-radius:18px;
      background:linear-gradient(180deg,#fafafa,#f2f2f2);
      overflow:hidden;
    }}
    .mini-chart svg {{
      width:100%;
      height:100%;
      display:block;
    }}
    .score {{
      margin-top:8px;
      color:#444;
      font-size:14px;
      font-weight:700;
      line-height:1.5;
    }}
    .event-row {{
      background:#fff;
      border-radius:18px;
      box-shadow:0 2px 8px rgba(0,0,0,0.05);
      padding:10px 12px;
      display:flex;
      align-items:center;
      gap:12px;
      margin-bottom:10px;
    }}
    .icon-box {{
      width:44px;
      height:44px;
      border-radius:14px;
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
      margin-bottom:2px;
    }}
    .event-text {{
      font-size:15px;
      font-weight:700;
      line-height:1.3;
    }}
    .alert-row {{
      background:#ff5d5d;
      color:#fff;
    }}
    .alert-row .icon-box {{
      background:rgba(255,255,255,0.2);
      color:#fff;
    }}
    .alert-row .event-time {{
      color:#ffe4e4;
    }}
    .bottom-nav {{
      position:sticky;
      bottom:0;
      margin-top:8px;
      background:rgba(255,255,255,0.86);
      backdrop-filter:blur(14px);
      border-radius:24px;
      box-shadow:0 4px 16px rgba(0,0,0,0.08);
      display:flex;
      justify-content:space-around;
      padding:10px 6px;
    }}
    .nav-item {{
      font-size:24px;
      color:#666;
    }}
  </style>
</head>
<body>
  <div class="app">
    <div class="top">
      <div class="logo">JCR.</div>
      <div class="menu">☰</div>
    </div>

    <div class="title">월암농장 2026.04.01</div>

    <div class="card">
      <div class="video-box">
        <video controls playsinline muted preload="metadata">
          <source src="/videos/demo.mp4" type="video/mp4">
        </video>
        <div class="play">▶</div>
      </div>
    </div>

    <div class="card">
      <div class="analysis-title">Chicken Behavior Analysis</div>
      <div class="analysis-sub">A-2구역 행동 지표</div>
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
      <div class="score">신뢰 점수 90/100 · 최근 농장 환경은 전반적으로 안정적으로 유지되고 있습니다.</div>
    </div>

    <div class="event-row">
      <div class="icon-box">🪺</div>
      <div>
        <div class="event-time">09:10 AM</div>
        <div class="event-text">산란 구역 체류 패턴 증가</div>
      </div>
    </div>

    <div class="event-row">
      <div class="icon-box">♡</div>
      <div>
        <div class="event-time">02:40 PM</div>
        <div class="event-text">군집 밀집 활성화</div>
      </div>
    </div>

    <div class="event-row alert-row">
      <div class="icon-box">⚠</div>
      <div>
        <div class="event-time">04:10 PM</div>
        <div class="event-text">사료 급여 이후 활동 변화 감지</div>
      </div>
    </div>

    <div class="bottom-nav">
      <div class="nav-item">⚙︎</div>
      <div class="nav-item">⌘</div>
      <div class="nav-item">◯</div>
    </div>
  </div>
</body>
</html>
""")


def product_page(code: str, days: int = 30, farm_id: str = "farm1", lot_id: str = "lotA"):
    return HTMLResponse(f"""
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
      background:#f5f5f3;
      font-family:-apple-system,BlinkMacSystemFont,"Apple SD Gothic Neo","Noto Sans KR",sans-serif;
      color:#111;
    }}
    .phone {{
      max-width:430px;
      margin:0 auto;
      min-height:100vh;
      padding:18px 14px 28px;
      background:#f5f5f3;
    }}
    .top {{
      display:flex;
      justify-content:space-between;
      align-items:center;
      margin-bottom:10px;
    }}
    .logo {{
      font-size:34px;
      font-weight:900;
      letter-spacing:-1.5px;
    }}
    .menu {{
      font-size:34px;
      color:#444;
    }}
    .title {{
      font-size:24px;
      font-weight:900;
      margin:8px 0 14px;
      letter-spacing:-0.5px;
    }}
    .card {{
      background:#fff;
      border-radius:24px;
      padding:14px;
      margin-bottom:14px;
      box-shadow:0 2px 10px rgba(0,0,0,0.06);
    }}
    .video-box {{
      position:relative;
      overflow:hidden;
      border-radius:22px;
      background:#ddd;
    }}
    video {{
      width:100%;
      display:block;
      border-radius:22px;
      background:#111;
    }}
    .play {{
      position:absolute;
      left:50%;
      top:50%;
      transform:translate(-50%,-50%);
      width:74px;
      height:74px;
      border-radius:50%;
      background:#aeeccf;
      display:flex;
      align-items:center;
      justify-content:center;
      font-size:34px;
      color:#1f4b39;
      box-shadow:0 8px 24px rgba(112,220,176,0.35);
      pointer-events:none;
    }}
    .analysis-title {{
      font-size:18px;
      font-weight:800;
      margin-bottom:2px;
    }}
    .analysis-sub {{
      color:#555;
      font-size:14px;
      margin-bottom:10px;
    }}
    .mini-chart {{
      width:100%;
      height:120px;
      border-radius:18px;
      background:linear-gradient(180deg,#fafafa,#f2f2f2);
      overflow:hidden;
    }}
    .mini-chart svg {{
      width:100%;
      height:100%;
      display:block;
    }}
    .score {{
      margin-top:8px;
      color:#444;
      font-size:14px;
      font-weight:700;
      line-height:1.5;
    }}
    .event-row {{
      background:#fff;
      border-radius:18px;
      box-shadow:0 2px 8px rgba(0,0,0,0.05);
      padding:10px 12px;
      display:flex;
      align-items:center;
      gap:12px;
      margin-bottom:10px;
    }}
    .icon-box {{
      width:44px;
      height:44px;
      border-radius:14px;
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
      margin-bottom:2px;
    }}
    .event-text {{
      font-size:15px;
      font-weight:700;
      line-height:1.3;
    }}
    .alert-row {{
      background:#ff5d5d;
      color:#fff;
    }}
    .alert-row .icon-box {{
      background:rgba(255,255,255,0.2);
      color:#fff;
    }}
    .alert-row .event-time {{
      color:#ffe4e4;
    }}
    .bottom-nav {{
      position:sticky;
      bottom:0;
      margin-top:8px;
      background:rgba(255,255,255,0.86);
      backdrop-filter:blur(14px);
      border-radius:24px;
      box-shadow:0 4px 16px rgba(0,0,0,0.08);
      display:flex;
      justify-content:space-around;
      padding:10px 6px;
    }}
    .nav-item {{
      font-size:24px;
      color:#666;
    }}
  </style>
</head>
<body>
  <div class="phone">
    <div class="top">
      <div class="logo">JCR.</div>
      <div class="menu">☰</div>
    </div>

    <div class="title">월암농장 2026.04.01</div>

    <div class="card">
      <div class="video-box">
        <video controls playsinline muted preload="metadata">
          <source src="/videos/demo.mp4" type="video/mp4">
        </video>
        <div class="play">▶</div>
      </div>
    </div>

    <div class="card">
      <div class="analysis-title">Chicken Behavior Analysis</div>
      <div class="analysis-sub">A-2구역 행동 지표</div>
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
      <div class="score">신뢰 점수 90/100 · 최근 농장 환경은 전반적으로 안정적으로 유지되고 있습니다.</div>
    </div>

    <div class="event-row">
      <div class="icon-box">🪺</div>
      <div>
        <div class="event-time">09:10 AM</div>
        <div class="event-text">산란 구역 체류 패턴 증가</div>
      </div>
    </div>

    <div class="event-row">
      <div class="icon-box">♡</div>
      <div>
        <div class="event-time">02:40 PM</div>
        <div class="event-text">군집 밀집 활성화</div>
      </div>
    </div>

    <div class="event-row alert-row">
      <div class="icon-box">⚠</div>
      <div>
        <div class="event-time">04:10 PM</div>
        <div class="event-text">사료 급여 이후 활동 변화 감지</div>
      </div>
    </div>

    <div class="bottom-nav">
      <div class="nav-item">⚙︎</div>
      <div class="nav-item">⌘</div>
      <div class="nav-item">◯</div>
    </div>
  </div>
</body>
</html>
""")


def product_page(code: str):
    products = read_products()
    if code not in products:
        return HTMLResponse("<h2>Invalid code</h2>")

    meta = products[code]
    farm_id = meta["farm_id"]
    lot_id = meta["lot_id"]
    title = meta.get("title") or f"J Crova 달걀 10구 ({lot_id})"

    all_events = read_events()
    events = [e for e in all_events if e.get("farm_id")==farm_id and e.get("lot_id")==lot_id]

    metrics = compute_metrics(events)
    score, label = compute_score(metrics)
    trend_info = compute_trend(all_events, farm_id, lot_id)

    integrity = verify_integrity(all_events)
    integrity_badge = "✅ Integrity OK" if integrity["ok"] else "❌ Integrity FAIL"
    integrity_detail = integrity["last_hash"] or integrity.get("reason") or "N/A"

    headline, bullets = generate_summary(title, score, label, metrics)
    bullets_html = "".join([f"<li>{b}</li>" for b in bullets])

    tagged = [e for e in events if (e.get("tags") or [])]
    tagged.sort(key=lambda x: x.get("time", 0), reverse=True)
    rows = []
    for e in tagged[:10]:
        ts = float(e.get("time", 0) or 0)
        tstr = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts)) if ts else "N/A"
        rows.append(f"""
          <tr>
            <td style="white-space:nowrap">{tstr}</td>
            <td>{_tag_badge(e)}</td>
            <td>{_evidence_buttons(e)}</td>
          </tr>
        """)
    tagged_table = f"""
      <table>
        <thead><tr><th>시간</th><th>태그</th><th>증거</th></tr></thead>
        <tbody>{''.join(rows) if rows else '<tr><td colspan="3">태그된 이벤트가 없습니다.</td></tr>'}</tbody>
      </table>
    """


    video_html = """
    <div style="background:#fff;border:1px solid #e5e7eb;border-radius:16px;padding:16px;margin:16px 0;">
      <div style="font-size:24px;font-weight:800;margin-bottom:12px;">농장 영상</div>
      <video width="100%" controls playsinline style="border-radius:12px;background:#000;">
        <source src="/videos/demo.mp4" type="video/mp4">
      </video>
      <div style="color:#666;margin-top:8px;">농장 관찰 영상이 웹에서 바로 재생됩니다.</div>
    </div>
    """

    return HTMLResponse(f"""
    <html><head><meta charset="utf-8"/>{STYLE}</head>
    <body>
    <body>
    <a href="https://junada040828.cafe24.com"
    style="
    position:fixed;
    top:20px;
    left:20px;
    background:white;
    padding:10px 16px;
    border-radius:30px;
    box-shadow:0 4px 12px rgba(0,0,0,0.1);
    font-weight:600;
    text-decoration:none;
    color:black;
    z-index:9999;
    ">
    ← J CROVA 홈으로
    </a>
    
      <div class="toplinks">
        <a class="pill" href="/report?days=7&farm_id={farm_id}&lot_id={lot_id}">📊 7일 리포트</a>
        <a class="pill" href="/report?days=30&farm_id={farm_id}&lot_id={lot_id}">📊 30일 리포트</a>
      </div>

      <h2>{title}</h2>

      <div class="row">
        <div class="box"><b>신뢰 점수</b>: {score}/100 ({label})</div>
        <div class="box"><b>로그 무결성</b>: {integrity_badge}</div>
      </div>
      <div style="color:#555;font-size:12px;margin-bottom:18px;">
        무결성 last_hash / reason: <code>{integrity_detail}</code>
      </div>

      <h3>AI 요약(소비자용)</h3>
      <p><b>{headline}</b></p>
      <ul>{bullets_html}</ul>

      <h3 style="margin-top:18px;">최근 이상치(태그) — 클릭해서 증거 보기</h3>
      {tagged_table}
    </body></html>
    """)

@app.get("/report", response_class=HTMLResponse)
def report(days: int = 7, farm_id: str | None = None, lot_id: str | None = None):
    days = 7 if days not in (7, 30) else days

    all_events = read_events()
    integrity = verify_integrity(all_events)
    integrity_badge = "✅ Integrity OK" if integrity["ok"] else "❌ Integrity FAIL"

    e = all_events
    if farm_id:
        e = [x for x in e if x.get("farm_id")==farm_id]
    if lot_id:
        e = [x for x in e if x.get("lot_id")==lot_id]
    e = filter_window(e, days)

    metrics = compute_metrics(e)
    score, label = compute_score(metrics)

    anomalies = [x for x in e if (x.get("tags") or [])]
    anomalies.sort(key=lambda x: x.get("time", 0), reverse=True)

    rows = []
    for x in anomalies[:100]:
        ts = float(x.get("time", 0) or 0)
        tstr = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts)) if ts else "N/A"
        rows.append(f"""
          <tr>
            <td style="white-space:nowrap">{tstr}</td>
            <td>{_tag_badge(x)}</td>
            <td>{_evidence_buttons(x)}</td>
          </tr>
        """)

    table = f"""
      <table>
        <thead><tr><th>시간</th><th>태그</th><th>증거</th></tr></thead>
        <tbody>{''.join(rows) if rows else '<tr><td colspan="3">이상치 태그가 없습니다.</td></tr>'}</tbody>
      </table>
    """

    return HTMLResponse(f"""
    <html><head><meta charset="utf-8"/>{STYLE}</head>
    <body>
      <div class="toplinks">
        <a class="pill" href="/report?days=7&farm_id={farm_id or ''}&lot_id={lot_id or ''}">7일</a>
        <a class="pill" href="/report?days=30&farm_id={farm_id or ''}&lot_id={lot_id or ''}">30일</a>
        <a class="pill" href="/p/EGG-0001">상품 페이지</a>
      </div>

      <h2>리포트 ({days}일) — {farm_id or '-'} / {lot_id or '-'}</h2>

      <div class="row">
        <div class="box"><b>신뢰 점수</b>: {score}/100 ({label})</div>
        <div class="box"><b>무결성</b>: {integrity_badge}</div>
      </div>

      <div class="box" style="margin:12px 0;">
        <b>요약 지표</b>
        <ul style="margin:8px 0 0 0;">
          <li>이벤트 수: {metrics.get("event_count","N/A")}</li>
          <li>평균 활동: {metrics.get("avg_motion","N/A")}</li>
          <li>평균 Flow: {metrics.get("avg_flow","N/A")}</li>
          <li>평균 Compactness: {metrics.get("avg_compactness","N/A")}</li>
          <li>BVI: {metrics.get("behavior_variance_index","N/A")}</li>
        </ul>
      </div>

      <h3>이상치 이벤트(태그) — 클릭해서 증거 보기</h3>
      {table}
    </body></html>
    """)

def compute_trend(all_events, farm_id, lot_id):
    # 7일 데이터
    e7 = [e for e in all_events if e.get("farm_id")==farm_id and e.get("lot_id")==lot_id]
    e7 = filter_window(e7, 7)
    m7 = compute_metrics(e7)
    s7, _ = compute_score(m7)

    # 30일 데이터
    e30 = [e for e in all_events if e.get("farm_id")==farm_id and e.get("lot_id")==lot_id]
    e30 = filter_window(e30, 30)
    m30 = compute_metrics(e30)
    s30, _ = compute_score(m30)

    diff = s7 - s30

    if diff > 5:
        trend = "상승"
        comment = "최근 안정성이 개선되는 추세입니다."
    elif diff < -5:
        trend = "하락"
        comment = "최근 활동 변동성이 증가하는 경향이 있습니다."
    else:
        trend = "유지"
        comment = "최근 패턴은 전반적으로 안정적으로 유지되고 있습니다."

    return {
        "score_7": s7,
        "score_30": s30,
        "diff": diff,
        "trend": trend,
        "comment": comment
    }


@app.get("/p/{code}", response_class=HTMLResponse)
def product_page(code: str, days: int = 30, farm_id: str = "farm1", lot_id: str = "lotA"):
    def read_events():
        path = Path("data/events.jsonl")
        if not path.exists():
            return []
        rows = []
        now = time.time()
        for line in path.read_text(encoding="utf-8").splitlines():
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
            keep = True
            if isinstance(ts, (int, float)) and ts > 946684800:
                keep = (now - ts) <= days * 86400
            if keep:
                rows.append(e)

        rows.sort(key=lambda x: x.get("time", 0), reverse=True)
        return rows

    def nice_tag(tag: str) -> str:
        mapping = {
            "HIGH_ACTIVITY": "활동 증가",
            "MID_ACTIVITY": "중간 활동",
            "LOW_ACTIVITY": "낮은 활동",
            "ACTIVITY_SPIKE": "활동 급증",
            "MOVE_FLOW": "이동 흐름 증가",
            "CLUSTER_SPREAD": "군집 분산 증가",
            "ROI_PEAK": "집중 구간 활성화",
            "ROI_PEAK_MED": "집중 구간 활성화",
            "HIGH": "고강도",
            "MID": "중간 수준",
            "LOW": "낮은 수준",
        }
        return mapping.get(tag, tag.replace("_", " ").title())

    def build_summary(events):
        if not events:
            return "최근 분석 데이터가 아직 충분하지 않지만, 현재까지 수집된 범위에서는 전반적으로 안정적인 상태를 보입니다."

        tags = []
        for e in events[:12]:
            tags.extend(e.get("tags", []))

        tag_set = set(tags)
        pieces = []

        if "ACTIVITY_SPIKE" in tag_set or "HIGH_ACTIVITY" in tag_set:
            pieces.append("일부 시간대에 활동량 증가 패턴이 관찰되었습니다")
        if "CLUSTER_SPREAD" in tag_set:
            pieces.append("군집이 넓게 분산되는 흐름이 확인되었습니다")
        if "MOVE_FLOW" in tag_set:
            pieces.append("이동 흐름이 평소보다 활발한 구간이 있었습니다")
        if "ROI_PEAK" in tag_set or "ROI_PEAK_MED" in tag_set:
            pieces.append("특정 구간에 개체가 집중되는 장면이 감지되었습니다")

        if not pieces:
            return "최근 구간에서는 급격한 이상 패턴 없이 비교적 안정적인 활동 흐름이 유지되었습니다."

        return "최근 분석 결과, " + " / ".join(pieces) + "."

    def score_label(score):
        if score >= 85:
            return "안정적"
        if score >= 70:
            return "양호"
        return "관찰 필요"

    events = read_events()

    motions = [float(e.get("motion_ratio", 0) or 0) for e in events] or [0.0]
    flows = [float(e.get("flow_mean_mag", 0) or 0) for e in events] or [0.0]
    compacts = [float(e.get("cluster_compactness", 0) or 0) for e in events] or [0.0]

    avg_motion = sum(motions) / len(motions)
    avg_flow = sum(flows) / len(flows)
    avg_compact = sum(compacts) / len(compacts)
    bvi = statistics.pstdev(motions) if len(motions) > 1 else 0.0

    score = 92
    score -= min(18, int(avg_motion * 35))
    score -= min(16, int(avg_flow * 0.7))
    score -= min(14, int(bvi * 100))
    score = max(58, min(96, score))

    summary = build_summary(events)
    label = score_label(score)

    recent_cards = []
    for e in events[:3]:
        ts = e.get("time", 0)
        if isinstance(ts, (int, float)) and ts > 946684800:
            tstr = time.strftime("%I:%M %p", time.localtime(ts))
        else:
            tstr = "최근 기록"

        tags = e.get("tags", [])
        if tags:
            msg = " / ".join(nice_tag(t) for t in tags[:2])
        else:
            msg = "특이 패턴 없음"

        sev = e.get("severity", "info")
        recent_cards.append((tstr, msg, sev))

    fallback = [
        ("09:10 AM", "활동 변화 관찰", "info"),
        ("02:40 PM", "군집 흐름 변화 관찰", "info"),
        ("04:10 PM", "추가 관찰 필요 구간 감지", "alert"),
    ]
    while len(recent_cards) < 3:
        recent_cards.append(fallback[len(recent_cards)])

    e1, e2, e3 = recent_cards[0], recent_cards[1], recent_cards[2]

    return HTMLResponse(f"""
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
      grid-template-columns: 1.2fr 0.8fr;
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
    .mini-chart {{
      width:100%;
      height:150px;
      border-radius:20px;
      background:linear-gradient(180deg,#fafafa,#f1f1f1);
      overflow:hidden;
      margin-top:8px;
    }}
    .mini-chart svg {{
      width:100%;
      height:100%;
      display:block;
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
    .summary-box {{
      font-size:16px;
      line-height:1.7;
      color:#222;
      background:#fafafa;
      border-radius:18px;
      padding:14px 16px;
      border:1px solid #efefef;
    }}
    .event-row {{
      background:#fff;
      border-radius:20px;
      box-shadow:0 2px 8px rgba(0,0,0,0.05);
      padding:12px 14px;
      display:flex;
      align-items:center;
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
      line-height:1.35;
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
    @media (max-width: 900px) {{
      .layout {{
        grid-template-columns:1fr;
      }}
      .headline {{
        font-size:28px;
      }}
      .page {{
        padding:18px 14px 28px;
      }}
    }}
  </style>
</head>
<body>
  <div class="page">
    <div class="top">
      <div class="logo">JCR.</div>
      <div class="menu">☰</div>
    </div>

    <div class="headline">Chicken Behavior Analysis</div>
    <div class="sub">영상 기반 행동 분석 리포트 · 최근 {days}일 기준</div>

    <div class="layout">
      <div>
        <div class="card">
          <div class="video-box">
            <video controls playsinline muted preload="metadata">
              <source src="/videos/demo.mp4" type="video/mp4">
            </video>
            <div class="play">▶</div>
          </div>
        </div>

        <div class="card">
          <div class="section-title">AI 분석 요약</div>
          <div class="section-sub">최근 기록을 기반으로 활동 리듬, 군집 분포, 이동 흐름 변화를 정리했습니다.</div>

          <div class="score-row">
            <div class="pill">신뢰 점수 {score}/100</div>
            <div class="pill">상태 {label}</div>
            <div class="pill">이벤트 {len(events)}건</div>
          </div>

          <div class="summary-box">{html.escape(summary)}</div>

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
          <div class="section-title">핵심 지표</div>
          <div class="metrics">
            <div class="metric">
              <div class="k">평균 활동</div>
              <div class="v">{avg_motion:.2f}</div>
            </div>
            <div class="metric">
              <div class="k">평균 Flow</div>
              <div class="v">{avg_flow:.2f}</div>
            </div>
            <div class="metric">
              <div class="k">평균 Compactness</div>
              <div class="v">{avg_compact:.3f}</div>
            </div>
            <div class="metric">
              <div class="k">변동성(BVI)</div>
              <div class="v">{bvi:.3f}</div>
            </div>
          </div>
        </div>

        <div class="card">
          <div class="section-title">최근 패턴 변화</div>

          <div class="event-row">
            <div class="icon-box">🪺</div>
            <div>
              <div class="event-time">{e1[0]}</div>
              <div class="event-text">{html.escape(e1[1])}</div>
            </div>
          </div>

          <div class="event-row">
            <div class="icon-box">♡</div>
            <div>
              <div class="event-time">{e2[0]}</div>
              <div class="event-text">{html.escape(e2[1])}</div>
            </div>
          </div>

          <div class="event-row alert-row">
            <div class="icon-box">⚠</div>
            <div>
              <div class="event-time">{e3[0]}</div>
              <div class="event-text">{html.escape(e3[1])}</div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</body>
</html>
""")

