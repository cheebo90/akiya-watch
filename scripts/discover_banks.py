"""Teach the census 'todo' akiya banks automatically.

For each todo site: open the list page and up to 6 linked pages that look like the property list; group
their links by shape (digits -> N); try the shapes whose link text looks like a property first. A shape is
accepted when 3 of 4 sample pages read as sale listings (price, or area plus address). The accepted
entry (list page + detail regex) is written to discovered-{part}.yml for review before going live.

  python scripts/discover_banks.py --part 1/4 [--exclude-pref fukuoka ...]
"""
from __future__ import annotations

import argparse
import logging
import re
import sys
from collections import defaultdict
from pathlib import Path
from urllib.parse import urljoin, urlparse

import yaml
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from scraper.census import AKIYA_LINK, LIST_WORDS, terms_ban  # noqa: E402
from scraper.common import Http, norm  # noqa: E402
from scraper.sources import akiyabank as ab  # noqa: E402

MORE = re.compile(r"(物件|売買|一覧|バンク|空き家|空家|住まい|すまい|売)")
PROPISH = re.compile(r"(万円|㎡|平米|m2|m²|坪|LDK|DK|\dK|No\.?\s*\d|番号|物件|戸建|住宅|空き家|空家|売)")
NAV = re.compile(r"(/category/|/tag/|/news|/event|sitemap|/topics|/soshiki/|/kurashi/|/faq|/contact|/inquiry|/blog|/page/N)")


def shape(u: str) -> str:
    pu = urlparse(u)
    q = "&".join(sorted(k.split("=")[0] + "=" for k in pu.query.split("&") if k)) if pu.query else ""
    return pu.netloc + re.sub(r"\d+", "N", pu.path) + ("?" + q if q else "")


def regex_from(sample: str) -> str:
    pu = urlparse(sample)
    rx = re.sub(r"\d+", r"\\d+", re.escape(pu.netloc + pu.path))
    if pu.query:
        keys = [k.split("=")[0] for k in pu.query.split("&") if k]
        id_key = next((k for k in reversed(keys) if re.search(r"\d", dict(x.split("=", 1) if "=" in x else (x, "") for x in pu.query.split("&")).get(k, ""))), None)
        return rx + r"\?" + (rf".*\b{re.escape(id_key)}=\d+" if id_key else "")
    return rx + r"(\?|$)"


def links(html: str, base: str):
    soup = BeautifulSoup(html, "lxml")
    out = []
    for a in soup.find_all("a", href=True):
        u = urljoin(base, a["href"]).split("#")[0]
        if u.startswith("http") and not ab.SKIP_EXT.search(u):
            ctx = a.find_parent(["li", "tr", "article", "dl"]) or a
            out.append((u, norm(a.get_text())[:40], norm(ctx.get_text(" "))[:200]))
    return soup, out


def good(l) -> bool:
    return bool(l) and (l.price_yen is not None or ((l.building_m2 or l.land_m2) and l.address))


def discover(http: Http, robots: ab.Robots, site: dict) -> dict:
    url = site["list"]
    rep = {"id": site["id"], "name": site["name"], "prefecture": site["prefecture"], "census_list": url}
    if not robots.allowed(url):
        return {**rep, "result": "robots"}
    html = http.get(url)
    if not html:
        return {**rep, "result": "unreachable"}
    host = urlparse(url).netloc
    soup, ls = links(html, url)
    ban = terms_ban(http, robots, soup, url)
    if ban:
        return {**rep, "result": "terms", "terms": ban[:200]}
    pages = [(url, ls)]
    for u, t, _ in ls:
        if len(pages) >= 7:
            break
        if urlparse(u).netloc == host and u not in [p[0] for p in pages] and (LIST_WORDS.search(t) or AKIYA_LINK.search(t) or MORE.search(t)) \
                and robots.allowed(u):
            h = http.get(u)
            if h:
                pages.append((u, links(h, u)[1]))
    # candidate shapes across pages, best first
    cands = []
    for pu, pl in pages:
        groups = defaultdict(list)
        for u, t, ctx in pl:
            if u != pu and urlparse(u).netloc not in ab.PLATFORM_HOSTS and not any(h in u for h in ab.PLATFORM_HOSTS):
                groups[shape(u)].append((u, t, ctx))
        for s, v in groups.items():
            uniq = list(dict.fromkeys(x[0] for x in v))
            if len(uniq) < 2 or NAV.search(s):
                continue
            score = sum(bool(PROPISH.search(x[1] + " " + x[2])) for x in v) / len(v) + min(len(uniq), 30) / 30
            cands.append((score, pu, s, uniq))
    cands.sort(key=lambda c: -c[0])
    tried = set()
    rep["tried"] = []
    for score, pu, s, uniq in cands:
        if s in tried or len(tried) >= 6:
            continue
        tried.add(s)
        reads = []
        for u in uniq[:4]:
            if not robots.allowed(u):
                continue
            h = http.get(u)
            reads.append(ab.parse_detail(h, u, {**site, "list": pu}) if h else None)
            if len(reads) == 1 and not good(reads[0]):
                break  # first sample isn't a listing: next shape
        ok = [l for l in reads if good(l)]
        rep["tried"].append({"shape": s, "n": len(uniq), "ok": f"{len(ok)}/{len(reads)}"})
        if len(reads) >= 3 and len(ok) >= 3 or (len(reads) == len(uniq) == 2 and len(ok) == 2):
            if not any(l.price_yen for l in ok):
                continue
            entry = {"id": site["id"], "name": site["name"], "prefecture": site["prefecture"], "list": pu,
                     "detail": regex_from(uniq[0]), "status": "ok"}
            rep.update(result="ok", entry=entry, links=len(uniq),
                       samples=[{"url": l.url, "price": l.price_yen, "building_m2": l.building_m2, "land_m2": l.land_m2,
                                 "title": l.title[:30], "address": (l.address or "")[:30]} for l in ok])
            return rep
    return {**rep, "result": "no listings found"}


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--part", default="1/1")
    ap.add_argument("--exclude-pref", action="append", default=[])
    a = ap.parse_args()
    i, n = map(int, a.part.split("/"))
    census = yaml.safe_load((ROOT / "census.yml").read_text(encoding="utf-8"))["sites"]
    manual = {s["id"] for s in yaml.safe_load((ROOT / "akiyabanks.yml").read_text(encoding="utf-8"))["sites"]}
    todo = [s for s in census if s["status"] == "todo" and s["prefecture"] not in a.exclude_pref and s["id"] not in manual]
    todo = todo[i - 1::n]
    http = Http(delay=1.5, max_requests=6000, timeout=15, retries=1)
    robots = ab.Robots(http)
    out = []
    for k, s in enumerate(todo, 1):
        try:
            out.append(discover(http, robots, s))
        except Exception as e:  # noqa: BLE001
            out.append({"id": s["id"], "prefecture": s["prefecture"], "result": f"error {e}"[:120]})
        http.blocked = 0
        logging.info("%d/%d %s -> %s", k, len(todo), s["id"], out[-1].get("result"))
    (ROOT / f"discovered-{i}.yml").write_text(yaml.safe_dump({"sites": out}, allow_unicode=True, sort_keys=False, width=200),
                                             encoding="utf-8")


if __name__ == "__main__":
    main()
