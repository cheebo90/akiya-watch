"""Check Mapbox geocoding with the app token (Referer = the site)."""
import re
import requests
from pathlib import Path
tok = re.search(r'MAPBOX_TOKEN = "([^"]+)"', (Path(__file__).resolve().parent.parent / "web/app.js").read_text()).group(1)
for q in ("Beppu", "別府市", "Shibuya", "南関町"):
    r = requests.get(f"https://api.mapbox.com/geocoding/v5/mapbox.places/{q}.json?country=jp&language=en,ja"
                     f"&types=region,district,place,locality,neighborhood,poi&limit=3&access_token={tok}",
                     headers={"Referer": "https://cheebo90.github.io/akiya-watch/"}, timeout=30)
    feats = r.json().get("features", []) if r.ok else []
    print(f"::notice::{q}: HTTP {r.status_code} " + " | ".join(f"{f.get('text_en')}/{f.get('text_ja')} {f.get('place_name_en')} {f.get('center')} bbox={bool(f.get('bbox'))}" for f in feats) + (r.text[:200] if not r.ok else ""))
