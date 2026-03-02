import argparse, json
from pathlib import Path
from statistics import mean, pstdev

def load_events(p: Path):
    if not p.exists():
        return []
    txt = p.read_text(encoding="utf-8").strip()
    if not txt:
        return []
    return [json.loads(l) for l in txt.splitlines()]

def save_events(p: Path, events):
    p.write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in events) + "\n", encoding="utf-8")

def tag_one(e, base):
    """
    base: baseline dict
    tags rule (MVP):
    - motion spike
    - flow spike
    - compactness spread
    - roi peak high
    """
    tags = []

    motion = float(e.get("motion_ratio", 0) or 0)
    flow = e.get("flow_mean_mag")
    flow = float(flow) if flow is not None else None
    comp = e.get("cluster_compactness")
    comp = float(comp) if comp is not None else None
    roi_peak = float(e.get("roi_peak", 0) or 0)

    # baseline stats
    m_mu, m_sd = base["motion_mu"], base["motion_sd"]
    f_mu, f_sd = base["flow_mu"], base["flow_sd"]
    c_mu = base["comp_mu"]

    # motion spike: z-score
    if m_sd > 1e-9:
        z = (motion - m_mu) / m_sd
        if z >= 2.5:
            tags.append("MOTION_SPIKE_HIGH")
        elif z >= 1.8:
            tags.append("MOTION_SPIKE")

    # flow spike
    if flow is not None and f_sd > 1e-9:
        zf = (flow - f_mu) / f_sd
        if zf >= 2.5:
            tags.append("FLOW_SPIKE_HIGH")
        elif zf >= 1.8:
            tags.append("FLOW_SPIKE")

    # compactness very low => spread
    if comp is not None:
        if comp < 0.10:
            tags.append("CLUSTER_SPREAD")
        elif comp < 0.30:
            tags.append("CLUSTER_MIXED")

    # roi peak high (simple)
    if roi_peak >= 0.60:
        tags.append("ROI_PEAK_HIGH")
    elif roi_peak >= 0.45:
        tags.append("ROI_PEAK_MED")

    # severity heuristic
    sev = "low"
    if any(t.endswith("_HIGH") for t in tags) or "ROI_PEAK_HIGH" in tags:
        sev = "high"
    elif any(t in ("MOTION_SPIKE","FLOW_SPIKE","CLUSTER_SPREAD","ROI_PEAK_MED") for t in tags):
        sev = "mid"

    return tags, sev

def build_baseline(events):
    motions = [float(e.get("motion_ratio", 0) or 0) for e in events]
    flows = [float(e.get("flow_mean_mag", 0) or 0) for e in events if e.get("flow_mean_mag") is not None]
    comps = [float(e.get("cluster_compactness", 0) or 0) for e in events if e.get("cluster_compactness") is not None]

    motion_mu = mean(motions) if motions else 0.0
    motion_sd = pstdev(motions) if len(motions) >= 2 else 0.0

    flow_mu = mean(flows) if flows else 0.0
    flow_sd = pstdev(flows) if len(flows) >= 2 else 0.0

    comp_mu = mean(comps) if comps else 0.0

    return {
        "motion_mu": motion_mu, "motion_sd": motion_sd,
        "flow_mu": flow_mu, "flow_sd": flow_sd,
        "comp_mu": comp_mu,
    }

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--path", default="data/events.jsonl")
    ap.add_argument("--farm_id", default=None)
    ap.add_argument("--lot_id", default=None)
    ap.add_argument("--overwrite", action="store_true", help="overwrite existing tags")
    args = ap.parse_args()

    p = Path(args.path)
    events = load_events(p)
    if not events:
        print("[INFO] no events")
        return 0

    # filter for baseline (same subset as tagging)
    subset = events
    if args.farm_id:
        subset = [e for e in subset if e.get("farm_id") == args.farm_id]
    if args.lot_id:
        subset = [e for e in subset if e.get("lot_id") == args.lot_id]

    base = build_baseline(subset)
    changed = 0

    for e in events:
        if args.farm_id and e.get("farm_id") != args.farm_id:
            continue
        if args.lot_id and e.get("lot_id") != args.lot_id:
            continue

        if (not args.overwrite) and ("tags" in e or "severity" in e):
            continue

        tags, sev = tag_one(e, base)
        e["tags"] = tags
        e["severity"] = sev
        changed += 1

    save_events(p, events)
    print(f"[OK] tagged {changed} events")
    print("[NOTE] events.jsonl changed -> re-seal hashchain is required")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
PYcat > tools/tag_events.py <<'PY'
import argparse, json
from pathlib import Path
from statistics import mean, pstdev

def load_events(p: Path):
    if not p.exists():
        return []
    txt = p.read_text(encoding="utf-8").strip()
    if not txt:
        return []
    return [json.loads(l) for l in txt.splitlines()]

def save_events(p: Path, events):
    p.write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in events) + "\n", encoding="utf-8")

def tag_one(e, base):
    """
    base: baseline dict
    tags rule (MVP):
    - motion spike
    - flow spike
    - compactness spread
    - roi peak high
    """
    tags = []

    motion = float(e.get("motion_ratio", 0) or 0)
    flow = e.get("flow_mean_mag")
    flow = float(flow) if flow is not None else None
    comp = e.get("cluster_compactness")
    comp = float(comp) if comp is not None else None
    roi_peak = float(e.get("roi_peak", 0) or 0)

    # baseline stats
    m_mu, m_sd = base["motion_mu"], base["motion_sd"]
    f_mu, f_sd = base["flow_mu"], base["flow_sd"]
    c_mu = base["comp_mu"]

    # motion spike: z-score
    if m_sd > 1e-9:
        z = (motion - m_mu) / m_sd
        if z >= 2.5:
            tags.append("MOTION_SPIKE_HIGH")
        elif z >= 1.8:
            tags.append("MOTION_SPIKE")

    # flow spike
    if flow is not None and f_sd > 1e-9:
        zf = (flow - f_mu) / f_sd
        if zf >= 2.5:
            tags.append("FLOW_SPIKE_HIGH")
        elif zf >= 1.8:
            tags.append("FLOW_SPIKE")

    # compactness very low => spread
    if comp is not None:
        if comp < 0.10:
            tags.append("CLUSTER_SPREAD")
        elif comp < 0.30:
            tags.append("CLUSTER_MIXED")

    # roi peak high (simple)
    if roi_peak >= 0.60:
        tags.append("ROI_PEAK_HIGH")
    elif roi_peak >= 0.45:
        tags.append("ROI_PEAK_MED")

    # severity heuristic
    sev = "low"
    if any(t.endswith("_HIGH") for t in tags) or "ROI_PEAK_HIGH" in tags:
        sev = "high"
    elif any(t in ("MOTION_SPIKE","FLOW_SPIKE","CLUSTER_SPREAD","ROI_PEAK_MED") for t in tags):
        sev = "mid"

    return tags, sev

def build_baseline(events):
    motions = [float(e.get("motion_ratio", 0) or 0) for e in events]
    flows = [float(e.get("flow_mean_mag", 0) or 0) for e in events if e.get("flow_mean_mag") is not None]
    comps = [float(e.get("cluster_compactness", 0) or 0) for e in events if e.get("cluster_compactness") is not None]

    motion_mu = mean(motions) if motions else 0.0
    motion_sd = pstdev(motions) if len(motions) >= 2 else 0.0

    flow_mu = mean(flows) if flows else 0.0
    flow_sd = pstdev(flows) if len(flows) >= 2 else 0.0

    comp_mu = mean(comps) if comps else 0.0

    return {
        "motion_mu": motion_mu, "motion_sd": motion_sd,
        "flow_mu": flow_mu, "flow_sd": flow_sd,
        "comp_mu": comp_mu,
    }

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--path", default="data/events.jsonl")
    ap.add_argument("--farm_id", default=None)
    ap.add_argument("--lot_id", default=None)
    ap.add_argument("--overwrite", action="store_true", help="overwrite existing tags")
    args = ap.parse_args()

    p = Path(args.path)
    events = load_events(p)
    if not events:
        print("[INFO] no events")
        return 0

    # filter for baseline (same subset as tagging)
    subset = events
    if args.farm_id:
        subset = [e for e in subset if e.get("farm_id") == args.farm_id]
    if args.lot_id:
        subset = [e for e in subset if e.get("lot_id") == args.lot_id]

    base = build_baseline(subset)
    changed = 0

    for e in events:
        if args.farm_id and e.get("farm_id") != args.farm_id:
            continue
        if args.lot_id and e.get("lot_id") != args.lot_id:
            continue

        if (not args.overwrite) and ("tags" in e or "severity" in e):
            continue

        tags, sev = tag_one(e, base)
        e["tags"] = tags
        e["severity"] = sev
        changed += 1

    save_events(p, events)
    print(f"[OK] tagged {changed} events")
    print("[NOTE] events.jsonl changed -> re-seal hashchain is required")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
