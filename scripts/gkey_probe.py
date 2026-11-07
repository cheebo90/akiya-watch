"""Check the Google Map Tiles key as the app uses it (Referer = the GitHub Pages site)."""
import json
import re
import requests
from pathlib import Path

key = re.search(r'GOOGLE_KEY = "([^"]+)"', (Path(__file__).resolve().parent.parent / "web/app.js").read_text()).group(1)
for ref in ("https://cheebo90.github.io/akiya-watch/", None):
    h = {"Content-Type": "application/json", **({"Referer": ref} if ref else {})}
    r = requests.post(f"https://tile.googleapis.com/v1/createSession?key={key}", headers=h,
                      data=json.dumps({"mapType": "roadmap", "language": "en-US", "region": "JP"}), timeout=30)
    msg = f"referer={ref}: HTTP {r.status_code} {r.text[:400]}"
    if r.ok:
        s = r.json()["session"]
        t = requests.get(f"https://tile.googleapis.com/v1/2dtiles/5/28/12?session={s}&key={key}", headers=h, timeout=30)
        msg += f" | tile HTTP {t.status_code} {t.headers.get('content-type')} {len(t.content)}B"
    print("::notice::" + msg.replace("\n", " "))
