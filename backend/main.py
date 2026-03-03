from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fastapi import FastAPI, HTTPException

from pathlib import Path as _Path

def _file_exists(path: str | None) -> bool:
    if not path:
        return False
    try:
        # 절대경로(/Users/...)도 들어올 수 있으니 그대로 검사
        return _Path(path).exists()
    except Exception:
        return False

def _to_public_path(path: str | None) -> str | None:
    # 배포에서 절대경로는 의미 없으니 data/... 상대경로만 공개용으로 변환 시도
    if not path:
        return None
    p = str(path)
    if "/data/" in p:
        return "data/" + p.split("/data/", 1)[1]
    if p.startswith("data/"):
        return p
    return p
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse, RedirectResponse

app = FastAPI()

# --- Paths
ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
EVENTS_PATH = DATA_DIR / "events.jsonl"
CLIPS_DIR = DATA_DIR / "clips"
THUMBS_DIR = DATA_DIR / "thumbs"
HEATMAPS_DIR = DATA_DIR / "heatmaps"
QRCODES_DIR = DATA_DIR / "qrcodes"

# --- Labels (Korean)
SEV_LABELS = {"low": "경미", "mid": "주의", "high": "위험"}
SEV_COLOR = {"low": "#16a34a", "mid": "#d97706", "high": "#dc2626"}

TAG_LABELS = {
    "HIGH_ACTIVITY": "활동량 급증",
    "MOVE_FLOW": "이동 흐름 증가",
    "CLUSTER_SPREAD": "군집 분산 확대",
    "ROI_PEAK": "특정 구역 집중 활동",
    "MID_ACTIVITY": "중간 수준 활동",
    # 이미 한글로 저장된 태그도 그대로 표시
}

CHAR_LABELS = {
    "BALANCED": "균형",
    "FLOW": "이동",
    "SPREAD": "분산",
    "ACTIVE": "활동",
    "N/A": "N/A",
}

# --- Demo Products (촬영/데모용)
PRODUCTS: Dict[str, Dict[str, str]] = {
    "EGG-0001": {"title": "J Crova 달걀 10구 (IoT A)", "farm_id": "farm1", "lot_id": "lotA"},
    "EGG-0002": {"title": "J Crova 달걀 10구 (IoT B)", "farm_id": "farm1", "lot_id": "lotA"},
}

# ---------- Utils ----------
def _safe_join(base: Path, rel: str) -> Path:
    # disallow absolute, .., etc
    p = (base / rel).resolve()
    if not str(p).startswith(str(base.resolve())):
        raise HTTPException(status_code=400, detail="Invalid path")
    return p

def _fmt_num(v, digits=3):
    try:
        x = float(v)
    except Exception:
        return "N/A"
    # 0에 가까운 값은 조금 더 보여주기
    if abs(x) < 0.01:
        return f"{x:.4f}"
    return f"{x:.{digits}f}"

def _fmt_ts(ts: Any) -> str:
    try:
        t = float(ts)
    except Exception:
        return "-"
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t))

def _now() -> float:
    return time.time()

def load_events() -> List[Dict[str, Any]]:
    if not EVENTS_PATH.exists():
        return []
    lines = EVENTS_PATH.read_text(encoding="utf-8").splitlines()
    out: List[Dict[str, Any]] = []
    for l in lines:
        l = l.strip()
        if not l:
            continue
        try:
            out.append(json.loads(l))
        except Exception:
            # ignore broken line
            continue
    return out

def filter_events(
    events: List[Dict[str, Any]],
    days: int = 30,
    farm_id: Optional[str] = None,
    lot_id: Optional[str] = None,
    code: Optional[str] = None,
) -> List[Dict[str, Any]]:
    cut = _now() - float(days) * 86400.0
    out = []
    for e in events:
        t = float(e.get("time", 0) or 0)
        if t < cut:
            continue
        if farm_id and e.get("farm_id") != farm_id:
            continue
        if lot_id and e.get("lot_id") != lot_id:
            continue
        if code and e.get("code") != code:
            # code 필드가 없으면 무시(기존 데이터 호환)
            pass
        out.append(e)
    out.sort(key=lambda x: float(x.get("time", 0) or 0), reverse=True)
    return out

def integrity_status(events: List[Dict[str, Any]]) -> Tuple[bool, str]:
    """
    해시체인 전체 검증을 완벽히 하진 않고,
    촬영/데모용으로 "봉인(seal) 흔적이 있는가"를 빠르게 확인.
    - hash/prev_hash/seq가 일정 개수 이상 있으면 OK
    """
    if not events:
        return True, "no events"
    has = sum(1 for e in events if "hash" in e and "prev_hash" in e and "seq" in e)
    if has == len(events):
        return True, "sealed"
    if has == 0:
        return False, "not sealed"
    return False, f"partial sealed ({has}/{len(events)})"

def tag_badge(e: Dict[str, Any]) -> str:
    tags = e.get("tags") or []
    sev = (e.get("severity") or "mid").lower()
    sev_txt = SEV_LABELS.get(sev, "주의")
    color = SEV_COLOR.get(sev, "#111827")

    if not tags:
        return "<span class='muted'>-</span>"

    tag_txt = ", ".join(TAG_LABELS.get(t, t) for t in tags)
    icon = "🚨" if sev == "high" else ("⚠️" if sev == "mid" else "✅")
    return (
        f"<span class='badge' style='border-color:{color};color:{color}'>"
        f"{icon} {sev_txt}: {tag_txt}"
        f"</span>"
    )

def evidence_buttons(e: Dict[str, Any]) -> str:
    def btn(label: str, href: str) -> str:
        return f"<a class='btn' href='{href}' target='_blank'>▶ {label}</a>"

    parts = []
    clip = _evidence_buttons(e)
    heat = e.get("heatmap_path")
    if clip:
        parts.append(btn("clip", f"/file/{clip}"))
    if thumb:
        parts.append(btn("thumb", f"/file/{thumb}"))
    if heat:
        parts.append(btn("heatmap", f"/file/{heat}"))
    if not parts:
        return "<span class='muted'>증거 없음</span>"
    return "<div class='actions'>" + "".join(parts) + "</div>"

def build_cards(events: List[Dict[str, Any]]) -> str:
    cards = []
    for e in events:
        char = e.get("character", "N/A")
        char_k = CHAR_LABELS.get(char, char)
        cards.append(
            f"""
            <div class="card">
              <div class="card-top">
                <div class="card-time">{_fmt_ts(e.get("time"))}</div>
                <span class="chip">{char_k}</span>
              </div>
              <div class="card-mid">
                <div class="label">태그</div>
                {tag_badge(e)}
              </div>
              <div class="card-line">
                <div class="label">증거</div>
                {evidence_buttons(e)}
              </div>
            </div>
            """
        )
    return "".join(cards) if cards else "<div class='muted'>태그된 이벤트가 없습니다.</div>"

def calc_metrics(events: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not events:
        return {
            "count": 0,
            "avg_motion": None,
            "avg_flow": None,
            "avg_compact": None,
            "avg_roi_peak": None,
            "bvi": None,
            "night_score": None,
        }

    def avg(key: str) -> Optional[float]:
        vals = []
        for e in events:
            v = e.get(key)
            try:
                v = float(v)
            except Exception:
                continue
            vals.append(v)
        return (sum(vals) / len(vals)) if vals else None

    avg_motion = avg("motion_ratio")
    avg_flow = avg("flow_mean_mag")
    avg_compact = avg("cluster_compactness")
    avg_roi_peak = avg("roi_peak")

    # 변동성(BVI) = motion_ratio 표준편차(아주 단순)
    vals = []
    for e in events:
        try:
            vals.append(float(e.get("motion_ratio", 0) or 0))
        except Exception:
            pass
    if len(vals) >= 2:
        m = sum(vals) / len(vals)
        var = sum((x - m) ** 2 for x in vals) / (len(vals) - 1)
        bvi = var ** 0.5
    else:
        bvi = None

    # 야간 안정성(데모): 0~100, 이벤트 수가 적으면 50
    night_score = 50
    return {
        "count": len(events),
        "avg_motion": avg_motion,
        "avg_flow": avg_flow,
        "avg_compact": avg_compact,
        "avg_roi_peak": avg_roi_peak,
        "bvi": bvi,
        "night_score": night_score,
    }

def trust_score(metrics: Dict[str, Any], integrity_ok: bool) -> Tuple[int, str]:
    # 촬영/데모용 간단 점수: 데이터/무결성/변동성 기반
    base = 60
    if not integrity_ok:
        base -= 20
    cnt = metrics.get("count") or 0
    if cnt < 3:
        base -= 10
    elif cnt >= 10:
        base += 10

    bvi = metrics.get("bvi")
    if isinstance(bvi, (int, float)):
        if bvi > 0.25:
            base -= 10
        elif bvi < 0.10:
            base += 5

    base = max(0, min(100, int(round(base))))
    label = "안정적" if base >= 75 else ("보통" if base >= 55 else "주의")
    return base, label

# ---------- HTML ----------
STYLE = """
<style>
  :root { --bg:#f5f7fb; --card:#fff; --muted:#6b7280; --line:#e5e7eb; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Apple SD Gothic Neo', 'Noto Sans KR', Segoe UI, Roboto, Helvetica, Arial, sans-serif;
         margin:0; background:var(--bg); color:#111827; }
  a { color: inherit; }
  .wrap { max-width: 1060px; margin: 0 auto; padding: 22px; }
  .topnav { display:flex; gap:10px; margin-bottom: 14px; flex-wrap: wrap; }
  .tab { padding:8px 12px; border:1px solid var(--line); border-radius:999px; background:#fff; text-decoration:none; font-weight:800; font-size:13px; }
  .title { font-size: 26px; font-weight: 900; margin: 6px 0 12px; }
  .sub { color: var(--muted); font-weight: 700; margin-bottom: 14px; }

  .hero { display:flex; gap: 14px; align-items: stretch; flex-wrap: wrap; }
  .panel { background: var(--card); border:1px solid var(--line); border-radius: 18px; padding: 16px; flex:1; min-width: 280px; }
  .panel h3 { margin:0 0 10px; font-size: 15px; letter-spacing: -0.2px; }
  .kpi { display:flex; gap:10px; flex-wrap: wrap; }
  .k { background:#fff; border:1px solid var(--line); border-radius: 14px; padding: 12px; min-width: 140px; flex: 1; }
  .k .lab { color:var(--muted); font-weight:800; font-size:12px; }
  .k .val { font-size: 20px; font-weight: 900; margin-top: 4px; }

  .scorewrap{ display:flex; gap:14px; align-items:center; justify-content: space-between; flex-wrap: wrap; }
  .ring { width: 86px; height: 86px; border-radius: 999px; border: 10px solid #e5e7eb; position: relative; }
  .ring > .fill { position:absolute; inset: -10px; border-radius: 999px; border: 10px solid #dc2626; clip-path: polygon(50% 50%, 50% 0, 100% 0, 100% 100%, 0 100%, 0 0); }
  .ring .num { position:absolute; inset:0; display:flex; align-items:center; justify-content:center; font-weight:900; }
  .badges { display:flex; gap:10px; flex-wrap: wrap; align-items:center; }
  .pill { padding:8px 12px; border-radius: 999px; border:1px solid var(--line); background:#fff; font-weight:900; }
  .ok { color:#16a34a; font-weight:900; }
  .fail { color:#dc2626; font-weight:900; }

  table { width: 100%; border-collapse: collapse; background:#fff; border:1px solid var(--line); border-radius: 18px; overflow:hidden; }
  th, td { padding: 12px; border-bottom: 1px solid var(--line); text-align: left; vertical-align: top; }
  th { background:#f8fafc; font-size: 13px; color:#334155; }
  tr:last-child td { border-bottom: none; }

  .badge { display:inline-block; padding: 8px 12px; border: 2px solid; border-radius: 999px;
           font-weight: 900; max-width: 100%; white-space: normal; line-height: 1.2; }
  .muted { color: var(--muted); font-weight: 700; }

  .btn { display:inline-block; padding: 8px 12px; border-radius: 12px; border:1px solid var(--line);
         background:#fff; font-weight: 900; text-decoration:none; }
  .actions { display:flex; gap:8px; flex-wrap: wrap; }

  /* mobile cards */
  .cards { display:none; margin-top: 12px; }
  .card { background:#fff; border:1px solid var(--line); border-radius: 18px; padding: 14px; margin-bottom: 10px; }
  .card-top { display:flex; justify-content: space-between; align-items:center; gap:10px; flex-wrap: wrap; }
  .card-time { font-weight: 900; }
  .chip { display:inline-block; padding:6px 10px; border:1px solid var(--line); border-radius: 999px; background:#f8fafc; font-weight: 900; font-size: 12px; }
  .label { margin-top: 10px; color: var(--muted); font-weight: 900; font-size: 12px; }

  @media (max-width: 760px){
    table { display:none; }
    .cards { display:block; }
    .wrap { padding: 16px; }
    .title { font-size: 22px; }
  }
</style>
"""

def page_shell(title: str, body: str) -> str:
    return f"""
    <html>
      <head>
        <meta charset="utf-8"/>
        <meta name="viewport" content="width=device-width, initial-scale=1"/>
        <title>{title}</title>
        {STYLE}
      </head>
      <body>
        <div class="wrap">
          {body}
        </div>
      </body>
    </html>
    """

# ---------- Routes ----------
@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url="/demo")

@app.get("/demo", response_class=HTMLResponse, include_in_schema=False)
def demo():
    # 촬영용: 바로 상품페이지로
    return RedirectResponse(url="/p/EGG-0001")

@app.get("/events", response_class=JSONResponse)
def api_events(days: int = 30, farm_id: str = "farm1", lot_id: str = "lotA"):
    events = filter_events(load_events(), days=days, farm_id=farm_id, lot_id=lot_id)
    return {"count": len(events), "events": events}

@app.get("/file/{path:path}", include_in_schema=False)
def file_any(path: str):
    # allow absolute path from old logs OR relative under project
    p = Path(path)
    if p.is_absolute():
        if not p.exists():
            raise HTTPException(status_code=404, detail="Not Found")
        return FileResponse(str(p))
    # relative: interpret from project root
    abs_p = (ROOT / p).resolve()
    if not abs_p.exists():
        raise HTTPException(status_code=404, detail="Not Found")
    return FileResponse(str(abs_p))

@app.get("/qrcodes/{name}", include_in_schema=False)
def qrcode(name: str):
    # name can be "EGG-0001.png"
    target = _safe_join(QRCODES_DIR, name)
    if not target.exists():
        raise HTTPException(status_code=404, detail="Not Found")
    return FileResponse(str(target))

@app.get("/p/{code}", response_class=HTMLResponse)
def product_page(code: str, window: str = "7"):
    meta = PRODUCTS.get(code) or {"title": f"제품 {code}", "farm_id": "farm1", "lot_id": "lotA"}
    days = 30 if window == "all" else 7
    farm_id = meta.get("farm_id", "farm1")
    lot_id = meta.get("lot_id", "lotA")

    events_all = filter_events(load_events(), days=30, farm_id=farm_id, lot_id=lot_id)
    events = filter_events(load_events(), days=days, farm_id=farm_id, lot_id=lot_id)

    ok, why = integrity_status(events_all)
    metrics = calc_metrics(events)
    score, label = trust_score(metrics, ok)

    # "이상치"는 tags가 있는 이벤트만
    tagged = [e for e in events if (e.get("tags") or [])]
    cards_html = build_cards(tagged[:10])

    # table rows
    rows = ""
    for e in tagged[:10]:
        char = e.get("character", "N/A")
        char_k = CHAR_LABELS.get(char, char)
        rows += f"""
        <tr>
          <td>{_fmt_ts(e.get("time"))}</td>
          <td>{tag_badge(e)}</td>
          <td><span class="chip">{char_k}</span></td>
          <td>{evidence_buttons(e)}</td>
        </tr>
        """
    if not rows:
        rows = "<tr><td colspan='4' class='muted'>태그된 이벤트가 없습니다. (tag 생성/필터 확인)</td></tr>"

    qr_hint = f"/qrcodes/{code}.png"
    body = f"""
    <div class="topnav">
      <a class="tab" href="/report?days=7&farm_id={farm_id}&lot_id={lot_id}">7일 리포트</a>
      <a class="tab" href="/report?days=30&farm_id={farm_id}&lot_id={lot_id}">30일 리포트</a>
      <a class="tab" href="/p/{code}?window=all">상품 페이지(all)</a>
    </div>

    <div class="title">{meta.get("title","상품")}</div>
    <div class="sub">제품 코드: <b>{code}</b> · farm_id={farm_id}, lot_id={lot_id}</div>

    <div class="hero">
      <div class="panel" style="max-width:340px">
        <h3>QR</h3>
        <div class="sub">촬영용: 아래 QR 이미지를 폰으로 찍으면 이 페이지로 연결됩니다.</div>
        <div style="display:flex;gap:12px;align-items:center;flex-wrap:wrap">
          <img src="{qr_hint}" alt="qr" style="width:160px;height:160px;border-radius:12px;border:1px solid #e5e7eb;background:white"/>
          <div class="muted" style="font-size:12px;line-height:1.5">
            · QR 이미지: <a href="{qr_hint}" target="_blank">{qr_hint}</a><br/>
            · 촬영 팁: 폰에서 /p/{code} 화면을 먼저 보여주고, 아래 “증거” 버튼 클릭까지 이어가면 MVP 느낌이 확 살아납니다.
          </div>
        </div>
      </div>

      <div class="panel">
        <div class="scorewrap">
          <div>
            <h3>농장 신뢰 리포트</h3>
            <div class="badges">
              <span class="pill">신뢰 점수: <b>{score}/100</b> ({label})</span>
              <span class="pill">무결성: {"<span class='ok'>Integrity OK</span>" if ok else "<span class='fail'>Integrity FAIL</span>"}</span>
              <span class="pill">선택 캐릭터: <b>{CHAR_LABELS.get((tagged[0].get("character") if tagged else "N/A"), (tagged[0].get("character") if tagged else "N/A"))}</b></span>
            </div>
            <div class="muted" style="margin-top:8px">integrity={why} · events(기간 {days}일)={metrics["count"]}</div>
          </div>

          <div class="ring" title="점수">
            <div class="fill" style="border-color:{'#dc2626' if score<55 else ('#d97706' if score<75 else '#16a34a')};"></div>
            <div class="num">{score}</div>
          </div>
        </div>

        <div class="kpi" style="margin-top:12px">
          <div class="k"><div class="lab">이벤트 수</div><div class="val">{metrics["count"]}</div></div>
          <div class="k"><div class="lab">평균 활동</div><div class="val">{_fmt_num(metrics["avg_motion"])}</div></div>
          <div class="k"><div class="lab">평균 Flow</div><div class="val">{_fmt_num(metrics["avg_flow"])}</div></div>
          <div class="k"><div class="lab">평균 Compactness</div><div class="val">{_fmt_num(metrics["avg_compact"])}</div></div>
          <div class="k"><div class="lab">BVI(변동성)</div><div class="val">{_fmt_num(metrics["bvi"])}</div></div>
          <div class="k"><div class="lab">야간 안정성</div><div class="val">{_fmt_num(metrics["night_score"], digits=0)}</div></div>
        </div>
      </div>
    </div>

    <div class="panel" style="margin-top:14px">
      <h3>이상치 이벤트 (태그) · 증거 클릭</h3>
      <div class="cards">{cards_html}</div>
      <table>
        <thead>
          <tr><th style="width:190px">시간</th><th>태그</th><th style="width:90px">캐릭터</th><th style="width:240px">증거</th></tr>
        </thead>
        <tbody>
          {rows}
        </tbody>
      </table>
      <div class="muted" style="margin-top:10px">
        · 개발자용 JSON: <a href="/events?days={days}&farm_id={farm_id}&lot_id={lot_id}" target="_blank">/events</a>
      </div>
    </div>
    """
    return page_shell(meta.get("title", "Product"), body)

@app.get("/report", response_class=HTMLResponse)
def report(days: int = 7, farm_id: str = "farm1", lot_id: str = "lotA"):
    events_all = filter_events(load_events(), days=30, farm_id=farm_id, lot_id=lot_id)
    events = filter_events(load_events(), days=days, farm_id=farm_id, lot_id=lot_id)

    ok, why = integrity_status(events_all)
    metrics = calc_metrics(events)
    score, label = trust_score(metrics, ok)

    tagged = [e for e in events if (e.get("tags") or [])]
    cards_html = build_cards(tagged[:30])

    rows = ""
    for e in tagged[:30]:
        char = e.get("character", "N/A")
        char_k = CHAR_LABELS.get(char, char)
        rows += f"""
        <tr>
          <td>{_fmt_ts(e.get("time"))}</td>
          <td>{tag_badge(e)}</td>
          <td><span class="chip">{char_k}</span></td>
          <td>{evidence_buttons(e)}</td>
        </tr>
        """
    if not rows:
        rows = "<tr><td colspan='4' class='muted'>태그된 이벤트가 없습니다.</td></tr>"

    body = f"""
    <div class="topnav">
      <a class="tab" href="/report?days=7&farm_id={farm_id}&lot_id={lot_id}">7일</a>
      <a class="tab" href="/report?days=30&farm_id={farm_id}&lot_id={lot_id}">30일</a>
      <a class="tab" href="/p/EGG-0001?window=all">상품 페이지</a>
    </div>

    <div class="title">리포트 ({days}일) — {farm_id} / {lot_id}</div>
    <div class="sub">영상 기반 이벤트 로그를 통계로 요약하고, 이상치 이벤트는 증거(클립/썸네일/히트맵)로 확인합니다.</div>

    <div class="panel">
      <div class="badges">
        <span class="pill">신뢰 점수: <b>{score}/100</b> ({label})</span>
        <span class="pill">무결성: {"<span class='ok'>Integrity OK</span>" if ok else "<span class='fail'>Integrity FAIL</span>"}</span>
        <span class="pill">integrity={why}</span>
      </div>

      <div class="kpi" style="margin-top:12px">
        <div class="k"><div class="lab">이벤트 수</div><div class="val">{metrics["count"]}</div></div>
        <div class="k"><div class="lab">평균 활동</div><div class="val">{_fmt_num(metrics["avg_motion"])}</div></div>
        <div class="k"><div class="lab">평균 Flow</div><div class="val">{_fmt_num(metrics["avg_flow"])}</div></div>
        <div class="k"><div class="lab">평균 Compactness</div><div class="val">{_fmt_num(metrics["avg_compact"])}</div></div>
        <div class="k"><div class="lab">ROI 피크 평균</div><div class="val">{_fmt_num(metrics["avg_roi_peak"])}</div></div>
        <div class="k"><div class="lab">BVI(변동성)</div><div class="val">{_fmt_num(metrics["bvi"])}</div></div>
      </div>
    </div>

    <div class="panel" style="margin-top:14px">
      <h3>이상치 이벤트(태그) — 클릭해서 증거 보기</h3>
      <div class="cards">{cards_html}</div>
      <table>
        <thead>
          <tr><th style="width:190px">시간</th><th>태그</th><th style="width:90px">캐릭터</th><th style="width:240px">증거</th></tr>
        </thead>
        <tbody>
          {rows}
        </tbody>
      </table>

      <div class="muted" style="margin-top:10px">
        · 개발자용 JSON: <a href="/events?days={days}&farm_id={farm_id}&lot_id={lot_id}" target="_blank">/events</a>
      </div>
    </div>
    """
    return page_shell("Report", body)



def _evidence_buttons(e: dict) -> str:
    clip = _evidence_buttons(e)
    heat = e.get("heatmap_path")

    # 파일이 실제로 존재하는 경우에만 노출 (배포 서버에서 404 폭탄 방지)
    btns = []
    if clip and _file_exists(clip):
        btns.append(f"<a class='btn' href='/file/{clip}' target='_blank'>▶ clip</a>")
    if thumb and _file_exists(thumb):
        btns.append(f"<a class='btn' href='/file/{thumb}' target='_blank'>🖼 thumb</a>")
    if heat and _file_exists(heat):
        btns.append(f"<a class='btn' href='/file/{heat}' target='_blank'>🔥 heatmap</a>")

    if not btns:
        # 데모에서도 '멈춘 느낌' 안나게
        return "<span class='muted'>증거 파일 없음(데모)</span>"
    return " ".join(btns)

