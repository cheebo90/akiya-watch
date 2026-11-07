"""Show where images live in a few detail pages (img tags, lazy attrs, css backgrounds, links to jpg)."""
from __future__ import annotations
import json, re, sys
from pathlib import Path
from bs4 import BeautifulSoup
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from scraper.common import Http  # noqa: E402

http = Http(delay=1.5, max_requests=20, timeout=30, retries=1)
for u in json.loads((ROOT / "trigger/inspect.json").read_text())["urls"]:
    html = http.get(u) or ""
    soup = BeautifulSoup(html, "lxml")
    lines = [f"{u} ({len(html)} chars)"]
    for img in soup.select("img")[:40]:
        lines.append("IMG " + " ".join(f"{k}={str(v)[:90]}" for k, v in img.attrs.items() if k in ("src", "data-src", "data-original", "data-lazy", "srcset", "alt", "class")))
    for a in soup.select("a[href]"):
        if re.search(r"\.(jpe?g|png|webp)", a["href"], re.I):
            lines.append("A " + a["href"][:120])
    for m in re.findall(r"url\(([^)]+\.(?:jpe?g|png|webp)[^)]*)\)", html, re.I)[:10]:
        lines.append("CSS " + m[:120])
    for m in re.findall(r"[\"']([^\"'\s]+\.(?:jpe?g|JPG|png|webp))[\"']", html)[:25]:
        lines.append("STR " + m[:120])
    print("::notice::" + " %0A".join(dict.fromkeys(lines)))
