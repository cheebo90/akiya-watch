"""Run the real akiya-bank reader on a few PDF sites (max 3 PDFs each) and print GitHub annotations."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("AKIYA_PASSPHRASE", "test-only")
from scraper import photos  # noqa: E402
from scraper.common import Http  # noqa: E402
from scraper.sources import akiyabank  # noqa: E402

sites = [s for s in yaml.safe_load((ROOT / "akiyabanks.yml").read_text(encoding="utf-8"))["sites"] if s.get("pdf")]
pick = [s for s in sites if any(k in s["id"] for k in ("tonosho", "saijo", "kasagi", "tendo", "city-awara", "takizawa"))]
http = Http(delay=1.5, max_requests=400, timeout=30, retries=1)
for s in pick:
    s = {**s, "max_details": 3}
    out = list(akiyabank.scrape(http, [s], [s["prefecture"]], set()))
    lines = [f"{s['id']}: {len(out)} letti"]
    for l in out:
        lines.append(f"¥{l.price_yen} b={l.building_m2} t={l.land_m2} foto={len(l.images)} | {l.title[:25]} | {(l.address or '')[:25]}")
    print("::notice::" + " %0A".join(lines))
print("::notice::foto salvate: " + str(len(list(photos.OUT.glob('*.bin'))) if photos.OUT.exists() else 0))
