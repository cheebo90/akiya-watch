"""Check the Mapbox token as the app uses it (Referer = the GitHub Pages site)."""
import re
import requests
from pathlib import Path

tok = re.search(r'MAPBOX_TOKEN = "([^"]+)"', (Path(__file__).resolve().parent.parent / "web/app.js").read_text()).group(1)
for ref in ("https://cheebo90.github.io/akiya-watch/", None):
    for style in ("streets-v12", "satellite-streets-v12"):
        r = requests.get(f"https://api.mapbox.com/styles/v1/mapbox/{style}/tiles/512/10/909/403@2x?access_token={tok}",
                         headers={"Referer": ref} if ref else {}, timeout=30)
        print(f"::notice::{style} referer={ref}: HTTP {r.status_code} {r.headers.get('content-type')} {len(r.content)}B {r.text[:150] if not r.ok else ''}")
