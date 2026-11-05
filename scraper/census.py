"""Monthly census of municipal akiya-bank websites.

1. Collects the municipal akiya-bank links listed per prefecture on akiya-portal.net (a public link directory).
2. Visits each site once, politely: robots.txt, then the page, then at most a few candidate listing pages.
3. If the generic reader recognises real listings, the site is marked `ok` and the daily run starts reading it.

Output: census.yml (only URLs and statuses, no listing data), committed to the repo.

  python -m scraper.census                 # whole country
  python -m scraper.census --pref oita     # one prefecture
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import logging
import re
from pathlib import Path
from urllib.parse import urljoin, urlparse

import yaml
from bs4 import BeautifulSoup

from .common import Blocked, Http, log, norm
from .prefectures import SLUGS
from .sources import akiyabank as ab

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "census.yml"
DIRECTORY = "https://akiya-portal.net/link_{slug}/"
DIR_SLUG = {"ibaraki": "ibaragi", "shizuoka": "sizuoka", "hyogo": "hyougo", "kochi": "kouchi", "oita": "ooita"}
LIST_WORDS = re.compile(r"(物件一覧|物件情報|登録物件|物件を探す|物件検索|空き家情報|空家情報|売買物件|一覧を見る|物件紹介)")
SOCIAL = re.compile(r"(twitter|x\.com|facebook|instagram|line\.me|google|youtube|amazon|rakuten|akiya-portal\.net)")


def harvest(http: Http, prefs: list[str]) -> list[dict]:
    seeds = []
    for pref in prefs:
        html = http.get(DIRECTORY.format(slug=DIR_SLUG.get(pref, pref)))
        if not html:
            log.warning("directory page missing for %s", pref)
            continue
        soup = BeautifulSoup(html, "lxml")
        seen = set()
        for a in soup.find_all("a", href=True):
            u = a["href"].strip()
            if not u.startswith("http") or SOCIAL.search(u) or u in seen:
                continue
            seen.add(u)
            seeds.append({"prefecture": pref, "name": norm(a.get_text())[:60], "url": u})
    return seeds


def detail_regex(urls: list[str]) -> str | None:
    """Generalise successful listing URLs into one regex (digits -> \\d+), if they share a shape."""
    shapes = set()
    for u in urls:
        pu = urlparse(u)
        shape = pu.path + ("?" + pu.query if pu.query else "")
        shapes.add(re.sub(r"\d+", r"\\d+", re.escape(shape)) + "$")
    return shapes.pop() if len(shapes) == 1 else None


def probe(http: Http, robots: ab.Robots, seed: dict) -> dict:
    url = seed["url"]
    host = urlparse(url).netloc
    sid = f"{seed['prefecture']}-{re.sub(r'[^a-z0-9]+', '-', host.lower()).strip('-')[:40]}-{hashlib.sha1(url.encode()).hexdigest()[:6]}"
    entry = {"id": sid, "prefecture": seed["prefecture"], "name": seed["name"], "list": url}
    if any(h in host for h in ab.PLATFORM_HOSTS):
        return {**entry, "status": "delegated", "note": "ospitato da LIFULL/At Home"}
    if url.lower().endswith(".pdf"):
        return {**entry, "status": "pdf"}
    if not robots.allowed(url):
        return {**entry, "status": "robots"}
    html = http.get(url)
    if not html:
        return {**entry, "status": "unreachable"}
    soup = BeautifulSoup(html, "lxml")
    if soup.find("a", href=re.compile(r"(homes\.co\.jp/akiyabank|akiya-athome\.jp)")) and not ab.detail_links(html, url, {"list": url}):
        return {**entry, "status": "delegated", "note": "rimanda a LIFULL/At Home"}

    pages = [(url, html)]
    # one level down: the page that actually lists the properties
    for a in soup.find_all("a", href=True):
        if len(pages) >= 3:
            break
        u = urljoin(url, a["href"]).split("#")[0]
        if urlparse(u).netloc == host and u != url and LIST_WORDS.search(a.get_text()) and not ab.SKIP_EXT.search(u):
            if robots.allowed(u):
                h = http.get(u)
                if h:
                    pages.append((u, h))

    pdfs = 0
    for list_url, page_html in pages:
        cands = ab.detail_links(page_html, list_url, {"list": list_url})
        pdfs += len(re.findall(r"href=[\"'][^\"']+\.pdf", page_html, re.I))
        good = []
        for c in cands[:4]:
            if not robots.allowed(c):
                continue
            h = http.get(c)
            l = ab.parse_detail(h, c, {**entry, "list": list_url}) if h else None
            if l and (l.price_yen or l.building_m2 or l.land_m2):
                good.append(c)
            if len(good) >= 2:
                break
        if good:
            out = {**entry, "list": list_url, "status": "ok", "found": len(cands)}
            rx = detail_regex(good)
            if rx:
                out["detail"] = rx
            return out
    if pdfs:
        return {**entry, "status": "pdf", "note": f"{pdfs} PDF"}
    return {**entry, "status": "todo", "note": "schede non riconosciute automaticamente"}


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--pref", action="append")
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    prefs = a.pref or SLUGS
    http = Http(delay=1.5, max_requests=12000, timeout=20)
    robots = ab.Robots(http)
    manual = yaml.safe_load((ROOT / "akiyabanks.yml").read_text(encoding="utf-8"))["sites"]
    manual_hosts = {urlparse(u).netloc for s in manual for u in ab.as_list(s["list"])}
    old = {e["list"]: e for e in (yaml.safe_load(OUT.read_text(encoding="utf-8")) or {}).get("sites", [])} if OUT.exists() else {}

    seeds = harvest(http, prefs)
    if a.limit:
        seeds = seeds[: a.limit]
    log.info("%d seed links", len(seeds))
    results = [e for e in old.values() if e["prefecture"] not in prefs]
    for i, seed in enumerate(seeds, 1):
        if urlparse(seed["url"]).netloc in manual_hosts:
            continue
        try:
            r = probe(http, robots, seed)
        except Blocked:
            r = {"id": seed["url"], "prefecture": seed["prefecture"], "name": seed["name"], "list": seed["url"],
                 "status": "blocked"}
        except Exception as e:  # noqa: BLE001
            r = {"id": seed["url"], "prefecture": seed["prefecture"], "name": seed["name"], "list": seed["url"],
                 "status": "error", "note": str(e)[:80]}
        http.blocked = 0
        results.append(r)
        if i % 25 == 0:
            log.info("%d/%d probed", i, len(seeds))
    # de-duplicate by list page, keep the best status
    rank = {"ok": 0, "todo": 1, "pdf": 2, "delegated": 3, "robots": 4, "blocked": 5, "unreachable": 6, "error": 7}
    best: dict[str, dict] = {}
    for r in results:
        k = r["list"]
        if k not in best or rank.get(r["status"], 9) < rank.get(best[k]["status"], 9):
            best[k] = r
    sites = sorted(best.values(), key=lambda r: (SLUGS.index(r["prefecture"]), rank.get(r["status"], 9), r["name"]))
    summary = {}
    for r in sites:
        summary.setdefault(r["prefecture"], {}).setdefault(r["status"], 0)
        summary[r["prefecture"]][r["status"]] += 1
    OUT.write_text(
        "# Generato da `python -m scraper.census` — non modificare a mano: per correggere un sito copialo in akiyabanks.yml\n"
        + yaml.safe_dump({"updated": dt.date.today().isoformat(), "summary": summary, "sites": sites},
                         allow_unicode=True, sort_keys=False, width=200),
        encoding="utf-8")
    tot = {}
    for r in sites:
        tot[r["status"]] = tot.get(r["status"], 0) + 1
    log.info("census done: %s", tot)


if __name__ == "__main__":
    main()
