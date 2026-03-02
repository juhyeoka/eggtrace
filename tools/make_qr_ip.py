from pathlib import Path
import qrcode

BASE_URL = "http://192.168.0.40:8000/p"  # ✅ 지금 IP로 업데이트

out = Path("data/qrcodes")
out.mkdir(parents=True, exist_ok=True)

code = "EGG-0001"
url = f"{BASE_URL}/{code}"
img = qrcode.make(url)
fn = out / f"{code}.png"
img.save(fn)
print("saved:", fn, "->", url)
