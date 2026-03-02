import argparse, json, hashlib, time
from pathlib import Path

HASH_FIELDS = {"hash", "prev_hash", "seq", "sealed_at"}

def canonical_json(obj: dict) -> str:
    clean = {k: v for k, v in obj.items() if k not in HASH_FIELDS}
    return json.dumps(clean, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

def sha256_hex(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

def seal(path: Path, genesis: str = "GENESIS"):
    if not path.exists():
        print(f"[ERR] not found: {path}")
        return 1
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines:
        print("[INFO] empty file")
        return 0

    out = []
    prev = genesis
    sealed_at = int(time.time())
    n = 0

    for i, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        e = json.loads(line)
        payload = canonical_json(e)
        h = sha256_hex(prev + "|" + payload)

        e["seq"] = i
        e["prev_hash"] = prev
        e["hash"] = h
        e["sealed_at"] = sealed_at

        out.append(json.dumps(e, ensure_ascii=False))
        prev = h
        n += 1

    tmp = path.with_suffix(".jsonl.tmp")
    tmp.write_text("\n".join(out) + "\n", encoding="utf-8")
    tmp.replace(path)

    print(f"[OK] sealed: {path} (records={n})")
    print(f"[OK] last_hash: {prev}")
    return 0

def verify(path: Path, genesis: str = "GENESIS"):
    if not path.exists():
        print(f"[ERR] not found: {path}")
        return 2
    txt = path.read_text(encoding="utf-8").strip()
    if not txt:
        print("[OK] verified (empty)")
        return 0

    prev = genesis
    last_hash = None

    for idx, line in enumerate(txt.splitlines(), start=1):
        e = json.loads(line)
        payload = canonical_json(e)
        expected = sha256_hex(prev + "|" + payload)

        if e.get("seq") != idx:
            print(f"[FAIL] seq mismatch at line {idx}: got {e.get('seq')}")
            return 1
        if e.get("prev_hash") != prev:
            print(f"[FAIL] prev_hash mismatch at line {idx}")
            return 1
        if e.get("hash") != expected:
            print(f"[FAIL] hash mismatch at line {idx}")
            return 1

        prev = expected
        last_hash = expected

    print("[OK] verified")
    print(f"[OK] last_hash: {last_hash}")
    return 0

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["seal", "verify"])
    ap.add_argument("--path", default="data/events.jsonl")
    ap.add_argument("--genesis", default="GENESIS")
    args = ap.parse_args()
    p = Path(args.path)

    if args.cmd == "seal":
        return seal(p, args.genesis)
    return verify(p, args.genesis)

if __name__ == "__main__":
    raise SystemExit(main())
