from pathlib import Path
import qrcode

BASE_URL = "http://192.168.0.6:8000/demo"  # 현재 IP 기준

out = Path("data/qrcodes")
out.mkdir(parents=True, exist_ok=True)

img = qrcode.make(BASE_URL)
fn = out / "EGG-0001.png"
img.save(fn)

print("saved:", fn, "->", BASE_URL)
