"""Show where ¥0 akiya-bank listings come from (raw price text, area, images). Sites from trigger 'keys'."""
from __future__ import annotations
import json, os, sys
from pathlib import Path
import yaml
from bs4 import BeautifulSoup
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("AKIYA_PASSPHRASE", "test-only")
from scraper.common import Http  # noqa: E402
from scraper.sources import akiyabank as ab  # noqa: E402

keys = json.loads((ROOT / "trigger/inspect.json").read_text())["keys"].split(",")
from scraper.run import load_sites  # noqa: E402
sites = [s for s in load_sites() if any(k in s["id"] for k in keys)]
http = Http(delay=1.2, max_requests=900, timeout=30, retries=1)
for s in sites:
    s = {**s, "max_pages": min(int(s.get("max_pages", 10)), 6), "max_details": 80}
    out = list(ab.scrape(http, [s], [s["prefecture"]], set()))
    zero = [l for l in out if l.price_yen == 0]
    lines = [f"{s['id']}: {len(out)} letti, {len(zero)} a ¥0"]
    for l in zero[:12]:
        html = http.get(l.url) or ""
        raw = ab.pick(ab.pairs(BeautifulSoup(html, "lxml")), "price") if html else "?"
        lines.append(f"raw='{raw[:40]}' b={l.building_m2} t={l.land_m2} img={len(l.images)} {l.images[:1]} | {l.title[:30]} | {l.url}")
    print("::notice::" + " %0A".join(lines))
