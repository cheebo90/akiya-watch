"""Print the text the PDF reader extracts from a few PDFs (URLs in trigger/inspect.json 'urls')."""
from __future__ import annotations
import json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from scraper.common import Http  # noqa: E402
from scraper.sources import akiyapdf  # noqa: E402

http = Http(delay=1.5, max_requests=20, timeout=30, retries=1)
for u in json.loads((ROOT / "trigger/inspect.json").read_text())["urls"]:
    data = http.get(u, raw=True)
    text, tables = akiyapdf.pdf_text(data)
    rows = [" | ".join(c or "" for c in r) for t in tables for r in t]
    body = (text[:1500] + " %0A--tabelle-- %0A" + " %0A".join(rows[:40])).replace("\n", " %0A")
    print(f"::notice::{u.rsplit('/',1)[-1]} %0A{body}")
