from pathlib import Path
import json
import qrcode

BASE = Path(__file__).resolve().parents[1]
PRODUCTS = BASE / "configs" / "products.json"
OUTDIR = BASE / "data" / "qrcodes"
OUTDIR.mkdir(parents=True, exist_ok=True)

if not PRODUCTS.exists():
    print("products.json not found")
    exit(1)

products = json.loads(PRODUCTS.read_text(encoding="utf-8"))

BASE_URL = "http://192.168.45.37:8000/p"

for code in products.keys():
    url = f"{BASE_URL}/{code}"
    img = qrcode.make(url)
    out = OUTDIR / f"{code}.png"
    img.save(out)
    print("saved:", out, "->", url)
