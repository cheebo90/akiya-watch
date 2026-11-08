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
print("::notice::" + " %0A".join(lines))
