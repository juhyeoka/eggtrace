from dataclasses import dataclass
from typing import Dict, Tuple, List

@dataclass
class CharacterResult:
    character: str
    score: int
    label: str
    rationale: List[str]
    context: Dict

def _clamp(x: int, lo=0, hi=100) -> int:
    return max(lo, min(hi, int(x)))

def _label(score: int) -> str:
    if score >= 80: return "안정적"
    if score >= 60: return "보통"
    return "주의"

def extract_context(metrics: Dict) -> Dict:
    """
    '상황 특징(Feature)' 추출 단계 (특허의 상황 분석에 해당)
    """
    avg_motion = metrics.get("avg_motion", 0.0) or 0.0
    bvi = metrics.get("behavior_variance_index", 0.0) or 0.0
    avg_flow = metrics.get("avg_flow", None)
    avg_comp = metrics.get("avg_compactness", None)
    roi_peak_avg = metrics.get("roi_peak_avg", None)

    # 신호(0~1-ish)로 정규화 느낌만 주기 (MVP라 단순화)
    flow_sig = 0.0 if avg_flow is None else min(1.0, avg_flow / 12.0)
    var_sig  = min(1.0, bvi / 0.16) if bvi is not None else 0.0
    cluster_sig = 0.0
    if roi_peak_avg is not None:
        cluster_sig = min(1.0, roi_peak_avg / 0.6)
    elif avg_comp is not None:
        # compactness가 낮으면 spread 경향 → cluster_sig 낮게
        cluster_sig = max(0.0, min(1.0, (avg_comp - 0.1) / 0.5))

    return {
        "avg_motion": avg_motion,
        "bvi": bvi,
        "avg_flow": avg_flow,
        "avg_compactness": avg_comp,
        "roi_peak_avg": roi_peak_avg,
        "signal_flow": round(flow_sig, 3),
        "signal_variance": round(var_sig, 3),
        "signal_cluster": round(cluster_sig, 3),
    }

# ----------------------------
# 머신 캐릭터들 (특허의 "복수 캐릭터")
# ----------------------------
def character_cluster(ctx: Dict, metrics: Dict) -> CharacterResult:
    # 군집/공간 특화: spread(응집도 낮음)일 때 강하게 패널티
    score = 100
    comp = ctx.get("avg_compactness")
    roi_peak = ctx.get("roi_peak_avg")

    rationale = ["[Cluster 캐릭터] 군집(공간) 패턴을 중심으로 평가합니다."]

    if comp is not None:
        if comp < 0.10:
            score -= 25; rationale.append("군집이 크게 퍼지는(spread) 경향 → 감점.")
        elif comp < 0.30:
            score -= 12; rationale.append("군집이 혼합(mixed) 양상 → 소폭 감점.")
        else:
            rationale.append("군집 응집도가 양호합니다.")

    if roi_peak is not None:
        if roi_peak >= 0.60:
            score -= 8; rationale.append("ROI 피크가 큼(특정 구역 집중) → 주의.")
        elif roi_peak >= 0.45:
            score -= 4; rationale.append("ROI 피크가 다소 큼 → 참고.")

    score = _clamp(score)
    return CharacterResult("CLUSTER", score, _label(score), rationale, ctx)

def character_flow(ctx: Dict, metrics: Dict) -> CharacterResult:
    # 이동/방향 특화: flow가 높은데 불안정하면 경고
    score = 100
    avg_flow = ctx.get("avg_flow")
    bvi = ctx.get("bvi", 0.0)

    rationale = ["[Flow 캐릭터] 이동 흐름(Flow) 패턴을 중심으로 평가합니다."]

    if avg_flow is None:
        score -= 10
        rationale.append("Flow 데이터가 부족 → 감점.")
    else:
        if avg_flow >= 12:
            score -= 18; rationale.append("이동 흐름 강도가 매우 큼 → 감점.")
        elif avg_flow >= 8:
            score -= 10; rationale.append("이동 흐름 강도가 큼 → 소폭 감점.")
        elif avg_flow <= 3:
            score -= 6; rationale.append("이동 흐름이 너무 낮음(비활동 가능성) → 참고.")
        else:
            rationale.append("이동 흐름이 정상 범위입니다.")

    if bvi >= 0.12:
        score -= 10; rationale.append("변동성(BVI)이 높음 → 추가 감점(흐름 불안정 가능).")

    score = _clamp(score)
    return CharacterResult("FLOW", score, _label(score), rationale, ctx)

def character_variance(ctx: Dict, metrics: Dict) -> CharacterResult:
    # 시간/변동성 특화: BVI 중심
    score = 100
    bvi = ctx.get("bvi", 0.0)

    rationale = ["[Variance 캐릭터] 시간 변동성(BVI)과 리듬 안정성을 중심으로 평가합니다."]

    if bvi >= 0.14:
        score -= 30; rationale.append("BVI 매우 높음 → 강한 감점.")
    elif bvi >= 0.12:
        score -= 20; rationale.append("BVI 높음 → 감점.")
    elif bvi >= 0.08:
        score -= 10; rationale.append("BVI 보통 → 소폭 감점.")
    else:
        rationale.append("BVI 낮음(안정)")

    score = _clamp(score)
    return CharacterResult("VARIANCE", score, _label(score), rationale, ctx)

def character_balanced(ctx: Dict, metrics: Dict) -> CharacterResult:
    # 기본 캐릭터(안전망)
    score = 100
    bvi = ctx.get("bvi", 0.0)
    comp = ctx.get("avg_compactness")
    rationale = ["[Balanced 캐릭터] 기본 규칙 기반으로 종합 평가합니다."]

    if bvi > 0.12: score -= 20; rationale.append("BVI 높음 → 감점.")
    elif bvi > 0.08: score -= 10; rationale.append("BVI 보통 → 소폭 감점.")

    if comp is not None and comp < 0.10: score -= 10; rationale.append("군집 spread → 감점.")

    score = _clamp(score)
    return CharacterResult("BALANCED", score, _label(score), rationale, ctx)

# ----------------------------
# 캐릭터 선택기 (특허의 "상황별 캐릭터 선택")
# ----------------------------
def select_character(metrics: Dict) -> CharacterResult:
    ctx = extract_context(metrics)

    flow_sig = ctx["signal_flow"]
    var_sig  = ctx["signal_variance"]
    clu_sig  = ctx["signal_cluster"]

    # MVP용 간단한 게이팅(= 상황 분류 → 캐릭터 라우팅)
    # 1) Flow가 가장 강하면 FLOW
    if flow_sig >= 0.65 and flow_sig >= var_sig and flow_sig >= clu_sig:
        return character_flow(ctx, metrics)

    # 2) Cluster(ROI 집중/공간) 신호가 강하면 CLUSTER
    if clu_sig >= 0.65 and clu_sig >= var_sig:
        return character_cluster(ctx, metrics)

    # 3) Variance가 강하면 VARIANCE
    if var_sig >= 0.60:
        return character_variance(ctx, metrics)

    # 4) 그 외는 BALANCED
    return character_balanced(ctx, metrics)
