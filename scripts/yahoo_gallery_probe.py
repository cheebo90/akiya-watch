"""Look at 2 Yahoo! 不動産 listing pages: is the page allowed by robots.txt, and how are its photos linked?
Prints GitHub annotations only (URL shapes and counts, no listing data)."""
from __future__ import annotations

import re
import sys
from collections import Counter
from pathlib import Path
from urllib import robotparser

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from bs4 import BeautifulSoup  # noqa: E402

from scraper.common import Http  # noqa: E402
from scraper.sources import yahoo  # noqa: E402

http = Http(delay=3)
rp = robotparser.RobotFileParser()
rp.parse(http.s.get(yahoo.BASE + "/robots.txt", timeout=20).text.splitlines())
for cat in ("used/house", "used/mansion"):
    items = yahoo.parse_list(http.get(yahoo.list_url(cat, 1)) or "", cat)
    for l in items[:2]:
        allowed = rp.can_fetch("*", l.url)
        msg = [f"{cat} robots_allowed={allowed} list_imgs={len(l.images)} list_img_shape={re.sub(r'[0-9a-f]{8,}', 'H', l.images[0]) if l.images else ''}"]
        if allowed:
            html = http.get(l.url) or ""
            soup = BeautifulSoup(html, "lxml")
            srcs = []
            for el in soup.select("img, source"):
                for attr in ("src", "data-src", "srcset", "data-srcset"):
                    v = el.get(attr)
                    if v and "yimg" in v:
                        srcs += [x.strip().split(" ")[0] for x in v.split(",")]
            raw = re.findall(r"https?:\\?/\\?/[^\"' ]*yimg\.jp[^\"' ]*", html)
            shapes = Counter(re.sub(r"[0-9a-f]{8,}", "H", re.sub(r"\d+", "N", s.split("?")[0])) for s in srcs)
            qs = Counter(re.sub(r"\d+", "N", s.split("?")[1]) for s in srcs if "?" in s)
            msg.append(f"page_len={len(html)} img_tags={len(srcs)} unique={len(set(srcs))} raw_in_html={len(set(raw))}")
            msg += [f"{c}x {s}" for s, c in shapes.most_common(8)]
            msg += [f"query {c}x {s}" for s, c in qs.most_common(4)]
            msg.append("sample: " + re.sub(r"[0-9a-f]{12,}", "H", (srcs or raw or [""])[0]))
        print("::notice::" + " %0A".join(msg))
