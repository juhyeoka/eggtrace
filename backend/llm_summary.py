"""
LLM Summary Adapter (Optional)

- 기본: rule-based summary (항상 동작)
- 선택: Ollama 로컬 LLM이 있으면 더 자연스러운 문장 생성
  - 환경변수로 켜기:
      export OLLAMA_MODEL="llama3.1:8b"   # 예시
  - Ollama 서버 기본: http://127.0.0.1:11434

※ Ollama가 없어도 프로젝트는 그대로 돌아감.
"""
import json
import os
import urllib.request
from typing import Dict, List, Tuple

def _post_json(url: str, payload: dict, timeout: float = 8.0) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))

def rule_based_summary(title: str, score: int, label: str, metrics: Dict) -> Tuple[str, List[str]]:
    bvi = metrics.get("behavior_variance_index")
    night = metrics.get("night_stability_score")
    avg_flow = metrics.get("avg_flow")
    avg_comp = metrics.get("avg_compactness")

    def level_bvi(x):
        if x is None: return "N/A"
        if x <= 0.06: return "낮음(안정)"
        if x <= 0.12: return "보통"
        return "높음(변동 큼)"

    def level_score100(x):
        if x is None: return "N/A"
        if x >= 80: return "좋음"
        if x >= 60: return "보통"
        return "주의"

    def describe_flow(x):
        if x is None: return "이동 흐름(Flow) 데이터가 부족합니다."
        if x >= 10: return "이동 흐름(Flow) 강도가 높은 편입니다."
        if x >= 6:  return "이동 흐름(Flow) 강도가 보통 수준입니다."
        return "이동 흐름(Flow) 강도가 낮은 편입니다."

    def describe_comp(x):
        if x is None: return "군집 응집도 데이터가 부족합니다."
        if x >= 0.55: return "닭들이 비교적 한 곳에 모여(응집) 활동하는 경향입니다."
        if x >= 0.30: return "군집이 일부는 모이고 일부는 퍼지는(mixed) 양상입니다."
        return "군집이 넓게 퍼지는(spread) 경향이 있습니다."

    # 변화율(있을 때만)
    def delta_line(name, d):
        if d is None:
            return None
        sign = "증가" if d > 0 else "감소"
        return f"최근 구간에서 {name}이 {abs(d):.1f}% {sign}했습니다."

    bullets = [
        f"종합 평가는 **{label}({score}/100)** 입니다.",
        f"패턴 변동성(BVI)은 **{bvi}** 로, 변동 수준은 **{level_bvi(bvi)}** 입니다.",
        f"야간 안정성은 **{night}/100({level_score100(night)})** 입니다.",
        describe_flow(avg_flow),
        describe_comp(avg_comp),
    ]
    for s in [
        delta_line("평균 활동량", metrics.get("delta_avg_motion_pct")),
        delta_line("이동 흐름(Flow)", metrics.get("delta_avg_flow_pct")),
        delta_line("응집도(Compactness)", metrics.get("delta_avg_comp_pct")),
    ]:
        if s:
            bullets.append(s)

    headline = f"{title}: 최근 기록을 기반으로 활동 리듬과 군집/이동 패턴을 요약했습니다."
    return headline, bullets

def llm_summary_with_ollama(title: str, score: int, label: str, metrics: Dict) -> Tuple[str, List[str]]:
    model = os.getenv("OLLAMA_MODEL")
    if not model:
        raise RuntimeError("OLLAMA_MODEL is not set")

    base_head, base_bullets = rule_based_summary(title, score, label, metrics)

    # LLM에는 '사실(지표)'만 주고, 과장/추측 금지 지시
    facts = {
        "title": title,
        "score": score,
        "label": label,
        "metrics": metrics,
        "rule_based_headline": base_head,
        "rule_based_bullets": base_bullets,
    }

    prompt = f"""
너는 소비자용 리포트 작성 AI다.
아래 FACTS의 수치/문구를 벗어나서 추측하지 말고, 과장하지 말고, 짧고 명확하게 한국어로 요약해라.
출력은 JSON만. 형식:
{{"headline":"...", "bullets":["...","...","..."]}}
- bullets는 4~6개
- 수치(점수, BVI, 야간점수, Flow, Compactness)는 가능하면 포함
- 건강/질병 같은 민감 추정 금지

FACTS:
{json.dumps(facts, ensure_ascii=False)}
""".strip()

    url = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434/api/generate")
    payload = {"model": model, "prompt": prompt, "stream": False, "format": "json"}

    out = _post_json(url, payload, timeout=12.0)
    # Ollama는 {"response": "..."} 형태를 주는 경우가 많아서 대응
    raw = out.get("response") if isinstance(out, dict) else None
    if not raw:
        raise RuntimeError(f"Unexpected ollama response: {out}")

    parsed = json.loads(raw)
    headline = parsed.get("headline") or base_head
    bullets = parsed.get("bullets") or base_bullets
    bullets = [str(b) for b in bullets][:6]
    return headline, bullets

def generate_summary(title: str, score: int, label: str, metrics: Dict) -> Tuple[str, List[str]]:
    # 1) Ollama 있으면 사용
    try:
        if os.getenv("OLLAMA_MODEL"):
            return llm_summary_with_ollama(title, score, label, metrics)
    except Exception:
        # LLM 실패해도 서비스는 살아야 함
        pass
    # 2) fallback
    return rule_based_summary(title, score, label, metrics)
