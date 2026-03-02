import argparse, json
from pathlib import Path

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--farm_id", default="farm1")
    ap.add_argument("--lot_id", default="lotA")
    ap.add_argument("--path", default="data/events.jsonl")
    args = ap.parse_args()

    p = Path(args.path)
    if not p.exists():
        print(f"[ERR] not found: {p}")
        return 1

    lines = p.read_text(encoding="utf-8").splitlines()
    if not lines:
        print("[INFO] events.jsonl is empty")
        return 0

    out = []
    changed = 0
    for line in lines:
        if not line.strip():
            continue
        e = json.loads(line)
        if "farm_id" not in e:
            e["farm_id"] = args.farm_id
            changed += 1
        if "lot_id" not in e:
            e["lot_id"] = args.lot_id
            changed += 1
        out.append(json.dumps(e, ensure_ascii=False))

    tmp = p.with_suffix(".jsonl.tmp")
    tmp.write_text("\n".join(out) + "\n", encoding="utf-8")
    tmp.replace(p)

    print(f"[OK] updated {p} (fields added: {changed})")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
