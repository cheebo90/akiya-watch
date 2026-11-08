"""Find archived listings by place/price and save their first photos (artifact) to compare by eye."""
from __future__ import annotations
import json, os, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from scraper import store  # noqa: E402
from scraper.common import Http  # noqa: E402
from scraper.photos import decrypt_bytes  # noqa: E402

q = json.loads((ROOT / "trigger/inspect.json").read_text())
state = store.load_state(ROOT / "data/state.enc", os.environ["AKIYA_PASSPHRASE"])
hits = [l for l in state["listings"].values()
        if q["place"] in (l.get("address") or "") and q["min_yen"] <= (l.get("price_yen") or -1) <= q["max_yen"]
        and l.get("type") in q.get("types", [l.get("type")])]
hits.sort(key=lambda l: l["price_yen"])
out = ROOT / "out"; out.mkdir(exist_ok=True)
http = Http(delay=1.0, max_requests=400, timeout=30, retries=1)
lines = [f"{len(hits)} annunci"]
for i, l in enumerate(hits[:60]):
    imgs = (l.get("gallery") or l.get("images") or [])[:2]
    for j, u in enumerate(imgs):
        try:
            if u.startswith("enc:"):
                data = decrypt_bytes((ROOT / "web" / u[4:]).read_bytes(), os.environ["AKIYA_PASSPHRASE"]) if (ROOT / "web" / u[4:]).exists() else None
            else:
                data = http.get(u, raw=True)
            if data:
                (out / f"{i:02d}_{j}.jpg").write_bytes(data)
        except Exception:  # noqa: BLE001
            pass
    lines.append(f"{i:02d} ¥{l['price_yen']:,} {l.get('type')} b={l.get('building_m2')} t={l.get('land_m2')} {l.get('year_built')} "
                 f"{'attivo' if l.get('active', True) else 'NON attivo'} {l['source']} {l.get('address')} {l['url']}")
# one contact sheet, numbered like the list
from PIL import Image, ImageDraw  # noqa: E402
import io  # noqa: E402
tiles = []
for f in sorted(out.glob("*.jpg")):
    try:
        im = Image.open(io.BytesIO(f.read_bytes())).convert("RGB"); im.thumbnail((320, 240)); tiles.append((f.stem, im))
    except Exception:  # noqa: BLE001
        pass
if tiles:
    W = 4; rows = (len(tiles) + W - 1) // W
    sheet = Image.new("RGB", (W * 320, rows * 260), (30, 30, 30)); d = ImageDraw.Draw(sheet)
    for k, (name, im) in enumerate(tiles):
        x, y = (k % W) * 320, (k // W) * 260
        sheet.paste(im, (x, y)); d.text((x + 6, y + 242), name, fill=(255, 220, 0))
    sheet.save(out / "sheet.jpg", quality=80)
print("::notice::" + " %0A".join(lines))
