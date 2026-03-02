#!/usr/bin/env bash
set -euo pipefail

echo "[1] clean old data"
rm -f data/events.jsonl || true
rm -rf data/clips data/thumbs data/heatmaps || true
mkdir -p data/clips data/thumbs data/heatmaps

echo "[2] generate fresh events"
# 중요: backend import 경로 문제 방지
.venv/bin/python -m vision.run_video

echo "[3] force farm_id/lot_id for demo stability"
.venv/bin/python - <<'PY'
import json
from pathlib import Path

farm_id="farm1"
lot_id="lotA"

p=Path("data/events.jsonl")
lines=p.read_text().strip().splitlines()
events=[json.loads(l) for l in lines]
for e in events:
    e["farm_id"]=e.get("farm_id") or farm_id
    e["lot_id"]=e.get("lot_id") or lot_id
p.write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in events) + "\n", encoding="utf-8")
print("[OK] injected farm_id/lot_id into events")
PY

echo "[4] seal hashchain"
.venv/bin/python tools/hashchain.py seal --path data/events.jsonl
.venv/bin/python tools/hashchain.py verify --path data/events.jsonl

echo "[DONE] demo reset complete"
