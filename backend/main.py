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

@app.get("/p/{code}", response_class=HTMLResponse)
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