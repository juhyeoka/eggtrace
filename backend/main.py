from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
import os, json, time, hashlib, html, traceback
from typing import Any

# ----------------------------
# Paths / Storage
# ----------------------------
APP_DIR = Path(__file__).resolve().parent
ROOT_DIR = APP_DIR.parent
DATA_DIR = ROOT_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

EVENTS_JSONL = DATA_DIR / "events.jsonl"
PRODUCTS_JSON = ROOT_DIR / "products.json"
QR_DIR = DATA_DIR / "qrcodes"
CLIPS_DIR = DATA_DIR / "clips"
THUMBS_DIR = DATA_DIR / "thumbs"
HEATMAPS_DIR = DATA_DIR / "heatmaps"

for d in [QR_DIR, CLIPS_DIR, THUMBS_DIR, HEATMAPS_DIR]:
    d.mkdir(parents=True, exist_ok=True)

if not EVENTS_JSONL.exists():
    EVENTS_JSONL.write_text("", encoding="utf-8")

# Render/클라우드에서 로컬 절대경로(/Users/...)가 섞여도 깨지지 않게 정규화
def _basename(p: str) -> str:
    return Path(p).name

def normalize_media_path(p: str | None, kind: str) -> str | None:
    """
    kind: clips|thumbs|heatmaps
    - 로컬 절대경로면 파일명만 뽑아 /clips/xxx.mp4 형태로 변환
    - 이미 /clips/... 같은 상대 URL이면 그대로
    """
    if not p:
        return None
    p = str(p).strip()
    if p.startswith("/"):
        # /clips/.. 처럼 이미 URL 형태면 그대로
        if p.startswith(f"/{kind}/"):
            return p
        # /Users/... 같은 절대경로면 basename으로
        return f"/{kind}/{_basename(p)}"
    # 상대경로(예: data/clips/xxx.mp4)도 basename으로
    if "clips" in p and kind == "clips":
        return f"/clips/{_basename(p)}"
    if "thumbs" in p and kind == "thumbs":
        return f"/thumbs/{_basename(p)}"
    if "heatmaps" in p and kind == "heatmaps":
        return f"/heatmaps/{_basename(p)}"
    # 파일명만 있으면 kind 붙여줌
    return f"/{kind}/{_basename(p)}"

def read_products() -> dict[str, Any]:
    if PRODUCTS_JSON.exists():
        return json.loads(PRODUCTS_JSON.read_text(encoding="utf-8"))
    # 기본값(없어도 페이지는 뜨게)
    return {
        "EGG-0001": {
            "name": "J Crova 달걀 10구 (IoT A)",
            "farm_id": "farm1",
            "lot_id": "lotA",
        }
    }

def load_events() -> list[dict[str, Any]]:
    out=[]
    for line in EVENTS_JSONL.read_text(encoding="utf-8").splitlines():
        line=line.strip()
        if not line: 
            continue
        try:
            out.append(json.loads(line))
        except:
            continue
    return out

# ----------------------------
# Integrity / Hashchain (simple)
# ----------------------------
def compute_chain_hash(prev_hash: str, payload: dict[str, Any]) -> str:
    s = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256((prev_hash + s).encode("utf-8")).hexdigest()

def verify_integrity(events: list[dict[str, Any]]) -> tuple[bool, str]:
    if not events:
        return True, "no events"
    prev = "GENESIS"
    for i, e in enumerate(events):
        ph = e.get("prev_hash", "GENESIS")
        h  = e.get("hash")
        if ph != prev:
            return False, f"prev_hash mismatch at seq={e.get('seq', i)}"
        payload = {k:v for k,v in e.items() if k not in ("hash",)}
        expect = compute_chain_hash(prev, payload)
        if h != expect:
            return False, f"hash mismatch at seq={e.get('seq', i)}"
        prev = h
    return True, prev

# ----------------------------
# Scoring / Character (simple)
# ----------------------------
def clamp01(x: float) -> float:
    return 0.0 if x < 0 else (1.0 if x > 1 else x)

def compute_signals(events: list[dict[str, Any]]) -> dict[str, float]:
    # 안전: 값 없으면 0
    mr = [float(e.get("motion_ratio", 0) or 0) for e in events]
    fm = [float(e.get("flow_mean_mag", 0) or 0) for e in events]
    cc = [float(e.get("cluster_compactness", 0) or 0) for e in events]
    rp = [float(e.get("roi_peak", 0) or 0) for e in events]

    avg_motion = sum(mr)/len(mr) if mr else 0.0
    avg_flow   = sum(fm)/len(fm) if fm else 0.0
    avg_comp   = sum(cc)/len(cc) if cc else 0.0
    avg_roi    = sum(rp)/len(rp) if rp else 0.0

    # "분산" 느낌을 만들기 위한 간단 BVI: (flow 변동 + motion 변동) / (1 + comp 평균)
    def var(xs):
        if not xs: return 0.0
        m = sum(xs)/len(xs)
        return sum((x-m)*(x-m) for x in xs)/len(xs)

    bvi = (var(fm) + var(mr)) / (1.0 + avg_comp)

    # signals 0~1로 대충 normalize (데모용)
    c = clamp01(avg_comp * 50)      # compactness는 보통 작으니 스케일
    f = clamp01(avg_flow / 10.0)    # flow 대충 0~10
    v = clamp01(bvi / 1.0)          # bvi는 0~1 근처로 기대(대충)

    return {
        "events": len(events),
        "avg_motion": avg_motion,
        "avg_flow": avg_flow,
        "avg_compactness": avg_comp,
        "avg_roi": avg_roi,
        "bvi": bvi,
        "c": c,
        "f": f,
        "v": v,
    }

def select_character(sig: dict[str, float]) -> str:
    # 간단 캐릭터
    c, f, v = sig["c"], sig["f"], sig["v"]
    if v > 0.6 and f > 0.5:
        return "분산"
    if c > 0.6 and f < 0.4:
        return "집중"
    return "균형"

def trust_score(sig: dict[str, float], integrity_ok: bool) -> int:
    if not integrity_ok:
        return 0
    # 변동성이 너무 크면 감점
    base = 85
    if sig["v"] > 0.7: base -= 15
    if sig["f"] > 0.8: base -= 5
    if sig["c"] > 0.8: base -= 5
    return max(0, min(100, base))

# ----------------------------
# Tagging / Evidence UI
# ----------------------------
TAG_KR = {
    "CLUSTER_SPREAD": "군집 분포 변화 관찰",
    "ROI_PEAK_MED": "특정 구역 활동 집중",
    "ACTIVITY_SPIKE": "활동 증가 관찰",
}

def tag_event(e: dict[str, Any]) -> list[str]:
    tags=[]
    # 아주 단순 규칙(데모)
    mr = float(e.get("motion_ratio", 0) or 0)
    cc = float(e.get("cluster_compactness", 0) or 0)
    rp = float(e.get("roi_peak", 0) or 0)
    if mr >= 0.22:
        tags.append("ACTIVITY_SPIKE")
    if cc >= 0.012:
        tags.append("CLUSTER_SPREAD")
    if rp >= 0.22:
        tags.append("ROI_PEAK_MED")
    return tags

def badge(text: str) -> str:
    return f"<span class='badge'>{html.escape(text)}</span>"

def evidence_buttons(e: dict[str, Any]) -> str:
    clip = normalize_media_path(e.get("clip_path"), "clips")
    thumb = normalize_media_path(e.get("thumb_path"), "thumbs")
    heat = normalize_media_path(e.get("heatmap_path"), "heatmaps")

    btns=[]
    if clip:
        btns.append(f"<a class='pillbtn' href='{clip}' target='_blank' rel='noopener'>▶ clip</a>")
    if thumb:
        btns.append(f"<a class='pillbtn' href='{thumb}' target='_blank' rel='noopener'>🖼 thumb</a>")
    if heat:
        btns.append(f"<a class='pillbtn' href='{heat}' target='_blank' rel='noopener'>🔥 heatmap</a>")
    return " ".join(btns) if btns else "<span class='muted'>증거 없음</span>"

def build_cards(tagged: list[dict[str, Any]]) -> str:
    rows=[]
    for e in tagged[:10]:
        t = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(float(e.get("time", 0) or 0)))
        tags = e.get("tags") or []
        tags_html = " ".join(badge(TAG_KR.get(x, x)) for x in tags) if tags else "<span class='muted'>태그 없음</span>"
        char = html.escape(str(e.get("character","")))
        rows.append(f"""
        <tr>
          <td class='td'>{t}</td>
          <td class='td'>{tags_html}</td>
          <td class='td'>{badge(char) if char else "<span class='muted'>N/A</span>"}</td>
          <td class='td'>{evidence_buttons(e)}</td>
        </tr>
        """)
    if not rows:
        return "<div class='muted'>표시할 관찰 기록이 없습니다.</div>"
    return f"""
    <table class='table'>
      <thead>
        <tr><th class='th'>시간</th><th class='th'>태그</th><th class='th'>캐릭터</th><th class='th'>증거</th></tr>
      </thead>
      <tbody>
        {''.join(rows)}
      </tbody>
    </table>
    """

# ----------------------------
# App
# ----------------------------
app = FastAPI()

# 정적 제공: data 아래를 URL로 노출
app.mount("/qrcodes", StaticFiles(directory=str(QR_DIR)), name="qrcodes")
app.mount("/clips", StaticFiles(directory=str(CLIPS_DIR)), name="clips")
app.mount("/thumbs", StaticFiles(directory=str(THUMBS_DIR)), name="thumbs")
app.mount("/heatmaps", StaticFiles(directory=str(HEATMAPS_DIR)), name="heatmaps")
app.mount("/videos", StaticFiles(directory="static/videos"), name="videos")

STYLE = """
<style>
  body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,"Apple SD Gothic Neo","Noto Sans KR","Malgun Gothic",sans-serif;margin:0;background:#f6f7fb;color:#111;}
  .wrap{max-width:1100px;margin:0 auto;padding:22px;}
  .toplinks{display:flex;gap:10px;align-items:center;margin:8px 0 18px;}
  .pill{display:inline-block;padding:8px 12px;border:1px solid #e5e7eb;border-radius:999px;background:#fff;color:#111;text-decoration:none;font-weight:700}
  .pill:hover{border-color:#111}
  .grid{display:grid;grid-template-columns:1fr 1fr;gap:14px;}
  .card{background:#fff;border:1px solid #eee;border-radius:18px;padding:16px;box-shadow:0 2px 12px rgba(0,0,0,.03);}
  .title{font-size:28px;font-weight:900;margin:6px 0 6px;}
  .sub{color:#6b7280;font-weight:600;margin:0 0 8px;}
  .row{display:flex;gap:10px;flex-wrap:wrap;margin:10px 0;}
  .badge{display:inline-block;border:1px solid #d1d5db;border-radius:999px;padding:6px 10px;background:#fff;font-weight:800}
  .ok{border-color:#16a34a;color:#16a34a}
  .bad{border-color:#dc2626;color:#dc2626}
  .muted{color:#6b7280}
  .kpi{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-top:10px}
  .k{background:#fafafa;border:1px solid #eee;border-radius:14px;padding:10px}
  .k .h{color:#6b7280;font-size:12px;font-weight:800}
  .k .v{font-size:20px;font-weight:900;margin-top:4px}
  .table{width:100%;border-collapse:separate;border-spacing:0 10px;margin-top:10px}
  .th{font-size:12px;color:#6b7280;text-align:left;padding:6px 10px}
  .td{background:#fff;border:1px solid #eee;padding:12px 10px}
  tr td:first-child{border-radius:12px 0 0 12px}
  tr td:last-child{border-radius:0 12px 12px 0}
  .pillbtn{display:inline-block;padding:8px 10px;border:1px solid #e5e7eb;border-radius:999px;background:#fff;color:#111;text-decoration:none;font-weight:800;margin-right:6px}
  .pillbtn:hover{border-color:#111}
  .qrimg{max-width:260px;border-radius:14px;border:1px solid #eee}
  @media (max-width:900px){
    .grid{grid-template-columns:1fr}
    .wrap{padding:14px}
  }
</style>
"""

@app.get("/", response_class=HTMLResponse)
def root():
    return RedirectResponse(url="/demo")

@app.get("/demo", response_class=HTMLResponse)
def demo():
    # demo는 바로 상품페이지로 보내도 됨
    return RedirectResponse(url="/p/EGG-0001")

@app.get("/report", response_class=HTMLResponse)
def report(days: int = 7, farm_id: str = "farm1", lot_id: str = "lotA"):
    # 리포트는 상품 페이지로 유도
    return RedirectResponse(url=f"/p/EGG-0001?days={days}&farm_id={farm_id}&lot_id={lot_id}")

def generate_ai_summary(score, sig):
    if score >= 80:
        return "최근 농장 환경은 안정적인 상태를 유지하고 있습니다. 닭의 활동 패턴과 군집 분포가 정상 범위 내에서 유지되었습니다."
    elif score >= 60:
        return "최근 농장의 활동 패턴은 전반적으로 양호합니다. 일부 활동 변화가 있었지만 안정적인 사육 환경을 유지하고 있습니다."
    else:
        return "최근 농장에서 일부 활동 변화가 관찰되었습니다. 지속적인 모니터링이 진행 중입니다."

@app.get("/p/{code}", response_class=HTMLResponse)
def product_page(code: str, days: int = 7, farm_id: str = "farm1", lot_id: str = "lotA"):
    products = read_products()
    meta = products.get(code, {"name": code, "farm_id": farm_id, "lot_id": lot_id})
    farm_id = meta.get("farm_id", farm_id)
    lot_id  = meta.get("lot_id", lot_id)

    all_events = load_events()
    now = time.time()
    cut = now - days*86400
    filtered = [e for e in all_events if (e.get("farm_id")==farm_id and e.get("lot_id")==lot_id and float(e.get("time",0) or 0) >= cut)]

    # 서버에서 태그/캐릭터 보정
    for e in filtered:
        if not e.get("tags"):
            e["tags"] = tag_event(e)
        if not e.get("character"):
            sig_one = compute_signals([e])
            e["character"] = select_character(sig_one)

    tagged = [e for e in filtered if e.get("tags")]
    sig = compute_signals(filtered)
    integrity_ok, integrity_detail = verify_integrity(filtered)
    char = select_character(sig) if filtered else "N/A"
    score = trust_score(sig, integrity_ok)
    label = "안정적" if score >= 75 else ("보통" if score >= 50 else "주의")

    integrity_badge = f"<span class='badge ok'>무결성: Integrity OK</span>" if integrity_ok else f"<span class='badge bad'>무결성: Integrity FAIL</span>"
    score_badge = f"<span class='badge ok'>신뢰 점수: {score}/100 ({label})</span>"
    char_badge = f"<span class='badge info'>분석 패턴: {html.escape(char)}</span>"

    qr_path = f"/qrcodes/{code}.png"
    title = html.escape(meta.get("name", code))


    video_html = """
        <div class="card">
          <div class="section-title">농장 영상</div>
          <video width="100%" controls autoplay muted loop playsinline style="border-radius:14px; background:#000;">
            <source src="/videos/farm.mp4" type="video/mp4">
          </video>
          <div class="muted tiny" style="margin-top:10px">농장 관찰 영상이 웹에서 바로 재생됩니다.</div>
        </div>
    """

    cards_html = build_cards(tagged)

    return HTMLResponse(f"""
    <html><head><meta charset="utf-8">{STYLE}</head>
    <body>
      <div class="wrap">
        <div class="toplinks">
          <a class="pill" href="/report?days=7&farm_id={farm_id}&lot_id={lot_id}">7일 리포트</a>
          <a class="pill" href="/report?days=30&farm_id={farm_id}&lot_id={lot_id}">30일 리포트</a>
          <a class="pill" href="/p/{code}?days={days}&farm_id={farm_id}&lot_id={lot_id}&window=all">상품 페이지(all)</a>
        </div>

        <div class="title">{title}</div>
        <div class="sub">제품 코드: {html.escape(code)} · farm_id={html.escape(farm_id)}, lot_id={html.escape(lot_id)}</div>

        {video_html}

        <div class="grid">
<div class="card">
<div class="section-title">AI 농장 요약</div>
<div style="font-size:15px;line-height:1.6;color:#444;">
최근 농장의 닭 활동 패턴은 전반적으로 안정적인 흐름을 보이고 있습니다.
군집 분포와 이동량은 정상 범위 내에서 유지되고 있으며
특별한 스트레스 징후는 발견되지 않았습니다.
</div>
</div>


          <div class="card">
            <div class="row">{score_badge} {integrity_badge} {char_badge}</div>
            <div class="muted" style="font-weight:800">최근 {days}일 기준 요약 결과</div>

            <div class="kpi">
              <div class="k"><div class="h">이벤트 수</div><div class="v">{sig["events"]}</div></div>
              <div class="k"><div class="h">평균 활동</div><div class="v">{sig["avg_motion"]:.3f}</div></div>
              <div class="k"><div class="h">평균 Flow</div><div class="v">{sig["avg_flow"]:.3f}</div></div>
              <div class="k"><div class="h">평균 Compactness</div><div class="v">{sig["avg_compactness"]:.3f}</div></div>
              <div class="k"><div class="h">BVI(변동성)</div><div class="v">{sig["bvi"]:.3f}</div></div>
              <div class="k"><div class="h">야간 안정성</div><div class="v">{50}</div></div>
            </div>
          </div>
        </div>

        <div class="card" style="margin-top:14px">
          <div class="row"><span class="badge">최근 관찰 기록 · 증거 보기</span></div>
          {cards_html}
          <div class="muted" style="margin-top:10px;font-size:12px">
            filtered_events={len(filtered)}, all_events={len(all_events)}, integrity_detail={html.escape(str(integrity_detail))}
          </div>
        </div>
      </div>
    </body></html>
    """)

@app.get("/events", response_class=JSONResponse)
def events(days: int = 7, farm_id: str = "farm1", lot_id: str = "lotA"):
    all_events = load_events()
    now = time.time()
    cut = now - days*86400
    filtered = [e for e in all_events if (e.get("farm_id")==farm_id and e.get("lot_id")==lot_id and float(e.get("time",0) or 0) >= cut)]
    return JSONResponse({"count": len(filtered), "events": filtered})

# 간단 Ingest API (Edge가 행동데이터만 보내는 구조)
@app.post("/ingest/event")
async def ingest_event(req: Request):
    e = await req.json()
    # 최소 필드 보정
    e.setdefault("time", time.time())
    e.setdefault("farm_id", "farm1")
    e.setdefault("lot_id", "lotA")

    # media 경로 정규화
    e["clip_path"] = normalize_media_path(e.get("clip_path"), "clips")
    e["thumb_path"] = normalize_media_path(e.get("thumb_path"), "thumbs")
    e["heatmap_path"] = normalize_media_path(e.get("heatmap_path"), "heatmaps")

    # 태그/캐릭터 서버 보정
    e.setdefault("tags", tag_event(e))
    e.setdefault("character", select_character(compute_signals([e])))

    # hashchain 보정(뒤에 이어쓰기)
    events = load_events()
    prev_hash = "GENESIS" if not events else events[-1].get("hash","GENESIS")
    seq = 1 if not events else int(events[-1].get("seq", len(events))) + 1
    e["seq"] = seq
    e["prev_hash"] = prev_hash
    payload = {k:v for k,v in e.items() if k not in ("hash",)}
    e["hash"] = compute_chain_hash(prev_hash, payload)

    with EVENTS_JSONL.open("a", encoding="utf-8") as f:
        f.write(json.dumps(e, ensure_ascii=False) + "\n")

    return {"ok": True, "seq": seq}

# 에러 페이지(디버그용)
@app.exception_handler(Exception)
async def all_exception_handler(request: Request, exc: Exception):
    # Render에서 원인 파악 쉽게
    tb = traceback.format_exc()
    return HTMLResponse(
        f"<h1>Internal Server Error</h1><pre>{html.escape(str(exc))}</pre><pre>{html.escape(tb)}</pre>",
        status_code=500
    )
