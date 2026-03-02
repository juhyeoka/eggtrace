import json, time
from pathlib import Path

def score_label(score:int):
    if score >= 80: return "안정적"
    if score >= 60: return "보통"
    return "주의"

def signals_from_event(e: dict):
    # 이벤트 자체에서 신호 추출 (특허의 "상황 특징")
    roi_peak = float(e.get("roi_peak", 0) or 0)
    flow = e.get("flow_mean_mag")
    flow = float(flow) if flow is not None else 0.0
    motion = float(e.get("motion_ratio", 0) or 0)

    # 간단 정규화(0~1)
    sig_cluster = min(1.0, roi_peak / 0.60)          # ROI 집중/군집 신호
    sig_flow    = min(1.0, flow / 12.0)              # 이동 신호
    sig_motion  = min(1.0, motion / 0.45)            # 활동량 신호(보조)

    return {
        "roi_peak": round(roi_peak, 3),
        "flow_mean_mag": round(flow, 3),
        "motion_ratio": round(motion, 3),
        "signal_cluster": round(sig_cluster, 3),
        "signal_flow": round(sig_flow, 3),
        "signal_motion": round(sig_motion, 3),
    }

def choose_character(sig: dict):
    c = sig["signal_cluster"]
    f = sig["signal_flow"]
    m = sig["signal_motion"]

    # 특허의 "캐릭터 선택(라우팅)" - MVP 게이팅
    if f >= 0.65 and f >= c:
        return "FLOW"
    if c >= 0.65:
        return "CLUSTER"
    if m >= 0.75 and m > max(c, f):
        return "VARIANCE"  # 여기서는 motion 기반으로 변동 캐릭터 대체(이벤트 단위라 BVI가 없음)
    return "BALANCED"

def classify(character: str, sig: dict):
    # 선택된 캐릭터가 최종 점수 산출(특허의 "선택 캐릭터가 분류")
    score = 100
    rationale = [f"[{character}] 캐릭터가 이벤트를 평가했습니다."]

    if character == "CLUSTER":
        if sig["roi_peak"] >= 0.60:
            score -= 18; rationale.append("ROI 피크가 매우 큼(특정 구역 집중) → 감점.")
        elif sig["roi_peak"] >= 0.45:
            score -= 10; rationale.append("ROI 피크가 큼(집중 경향) → 소폭 감점.")
        else:
            rationale.append("ROI 집중이 크지 않음(분산).")

    elif character == "FLOW":
        if sig["flow_mean_mag"] >= 12:
            score -= 20; rationale.append("이동 흐름 강도가 매우 큼 → 감점.")
        elif sig["flow_mean_mag"] >= 8:
            score -= 12; rationale.append("이동 흐름 강도가 큼 → 소폭 감점.")
        else:
            rationale.append("이동 흐름이 정상 범위.")

    elif character == "VARIANCE":
        if sig["motion_ratio"] >= 0.40:
            score -= 18; rationale.append("활동량 급증(변동성) → 감점.")
        elif sig["motion_ratio"] >= 0.30:
            score -= 10; rationale.append("활동량 증가 → 소폭 감점.")
        else:
            rationale.append("활동량 안정.")

    else:  # BALANCED
        if sig["roi_peak"] >= 0.60: score -= 8; rationale.append("ROI 피크 큼 → 감점.")
        if sig["flow_mean_mag"] >= 12: score -= 8; rationale.append("Flow 큼 → 감점.")
        if sig["motion_ratio"] >= 0.40: score -= 8; rationale.append("Motion 큼 → 감점.")

    score = max(0, min(100, int(score)))
    return score, score_label(score), rationale

def main():
    path = Path("data/events.jsonl")
    if not path.exists():
        print("[ERR] data/events.jsonl not found")
        return 1

    lines = path.read_text(encoding="utf-8").strip().splitlines()
    if not lines:
        print("[INFO] empty events.jsonl")
        return 0

    out = []
    changed = 0

    for line in lines:
        e = json.loads(line)
        # 이미 있으면 덮어쓰기 안 함(원하면 지우고 다시 돌리면 됨)
        if "character" in e and "character_signals" in e:
            out.append(json.dumps(e, ensure_ascii=False))
            continue

        sig = signals_from_event(e)
        ch = choose_character(sig)
        score, label, rationale = classify(ch, sig)

        e["character"] = ch
        e["character_signals"] = sig
        e["character_score"] = score
        e["character_label"] = label
        e["character_rationale"] = rationale
        e["character_saved_at"] = int(time.time())

        out.append(json.dumps(e, ensure_ascii=False))
        changed += 1

    path.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"[OK] assigned character to {changed} events")
    print("[NOTE] events.jsonl changed -> re-seal hashchain required")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
