"""Look closer at akiya-bank sites the census could not read on its own ("todo").

For each site: robots.txt, the list page, then up to 6 linked pages that look like the property list.
On every page the links are grouped by shape (digits -> N); for the most repeated shapes one sample
page is opened and run through the generic reader, to see whether price/area come out.
Writes inspect.yml (URLs, link shapes and which fields were recognised: no listing data).

  python scripts/inspect_todo.py --pref fukuoka --pref saga ...
"""
from __future__ import annotations

import argparse
import logging
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urljoin, urlparse

import yaml
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from scraper.census import AKIYA_LINK, LIST_WORDS  # noqa: E402
from scraper.common import Http, norm  # noqa: E402
from scraper.sources import akiyabank as ab  # noqa: E402

MORE = re.compile(r"(物件|売買|賃貸|一覧|バンク|空き家|空家|住まい|すまい)")


def shape(u: str) -> str:
    pu = urlparse(u)
    q = "&".join(sorted(k.split("=")[0] + "=" for k in pu.query.split("&") if k)) if pu.query else ""
    return pu.netloc + re.sub(r"\d+", "N", pu.path) + ("?" + re.sub(r"\d+", "N", q) if q else "")


def links(html: str, base: str):
    soup = BeautifulSoup(html, "lxml")
    out = []
    for a in soup.find_all("a", href=True):
        u = urljoin(base, a["href"]).split("#")[0]
        if u.startswith("http") and not ab.SKIP_EXT.search(u):
            out.append((u, norm(a.get_text())[:30]))
    return soup, out


def inspect(http: Http, robots: ab.Robots, site: dict) -> dict:
    url = site["list"]
    rep = {"id": site["id"], "name": site["name"], "list": url}
    if not robots.allowed(url):
        return {**rep, "result": "robots"}
    html = http.get(url)
    if not html:
        return {**rep, "result": "unreachable"}
    host = urlparse(url).netloc
    soup, ls = links(html, url)
    rep["pdf"] = len(re.findall(r"href=[\"'][^\"']+\.pdf", html, re.I))
    rep["iframes"] = [urljoin(url, f["src"]) for f in soup.find_all("iframe", src=True)][:3]
    rep["external"] = sorted({urlparse(u).netloc for u, t in ls if urlparse(u).netloc != host and AKIYA_LINK.search(t)})[:5]
    pages = [(url, html)]
    for u, t in ls:
        if len(pages) >= 7:
            break
        if urlparse(u).netloc == host and u not in dict(pages) and (LIST_WORDS.search(t) or AKIYA_LINK.search(t) or MORE.search(t)):
            if robots.allowed(u):
                h = http.get(u)
                if h:
                    pages.append((u, h))
    rep["pages"] = []
    for pu, ph in pages:
        _, pl = links(ph, pu)
        groups = defaultdict(list)
        for u, t in pl:
            if u != pu:
                groups[shape(u)].append((u, t))
        top = sorted(groups.items(), key=lambda kv: -len(set(x[0] for x in kv[1])))
        top = [(s, v) for s, v in top if len(set(x[0] for x in v)) >= 3][:6]
        page = {"url": pu, "pdf": len(re.findall(r"href=[\"'][^\"']+\.pdf", ph, re.I)), "shapes": []}
        for s, v in top:
            uniq = list(dict.fromkeys(x[0] for x in v))
            entry = {"shape": s, "n": len(uniq), "samples": [f"{x[0]}  «{x[1]}»" for x in v[:2]]}
            page["shapes"].append(entry)
        # open one sample for the 3 biggest same-host shapes that look like detail pages
        tried = 0
        for e in page["shapes"]:
            if tried >= 3:
                break
            u = e["samples"][0].split("  «")[0]
            if not robots.allowed(u):
                continue
            tried += 1
            h = http.get(u)
            l = ab.parse_detail(h, u, {**site, "list": pu}) if h else None
            if l:
                e["read"] = {k: v for k, v in {"price": l.price_yen, "building_m2": l.building_m2, "land_m2": l.land_m2,
                                                "address": l.address[:30] if l.address else None,
                                                "images": len(l.images or [])}.items() if v}
        rep["pages"].append(page)
    return rep


def try_site(http: Http, robots: ab.Robots, site: dict) -> dict:
    """Run a hand-written site entry: list -> detail links -> read up to 4 detail pages."""
    from scraper.census import terms_ban
    rep = {"id": site["id"], "lists": []}
    links = []
    for lu in ab.as_list(site["list"]):
        if not robots.allowed(lu):
            rep["lists"].append({lu: "robots"})
            continue
        h = http.get(lu)
        if not h:
            rep["lists"].append({lu: "unreachable"})
            continue
        found = ab.detail_links(h, lu, site)
        rep["lists"].append({lu: len(found)})
        ban = terms_ban(http, robots, BeautifulSoup(h, "lxml"), lu)
        if ban:
            rep["terms"] = ban[:160]
        if site.get("pages"):
            h2 = http.get(lu + site["pages"].format(n=2))
            rep["page2"] = len(ab.detail_links(h2, lu, site)) if h2 else 0
        links += [l for l in found if l not in links]
    rep["reads"] = []
    hosts_checked = {urlparse(lu).netloc for lu in ab.as_list(site["list"])}
    for u in links[:4]:
        host = urlparse(u).netloc
        if not robots.allowed(u):
            rep["reads"].append({"url": u, "result": "robots"})
            continue
        h = http.get(u)
        if not h:
            rep["reads"].append({"url": u, "result": "unreachable"})
            continue
        if host not in hosts_checked:
            hosts_checked.add(host)
            ban = terms_ban(http, robots, BeautifulSoup(h, "lxml"), u)
            if ban:
                rep["terms"] = ban[:160]
        l = ab.parse_detail(h, u, site)
        if l:
            rep["reads"].append({"url": u, "price": l.price_yen, "building_m2": l.building_m2, "land_m2": l.land_m2,
                                 "layout": l.layout, "year": l.year_built, "address": l.address, "title": l.title[:40],
                                 "images": len(l.images), "type": l.type})
        else:
            soup = BeautifulSoup(h, "lxml")
            rep["reads"].append({"url": u, "result": "not read", "labels": list(ab.pairs(soup))[:25],
                                 "text": norm(soup.get_text(" "))[:600]})
    return rep


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--pref", action="append")
    ap.add_argument("--try", dest="try_file")
    ap.add_argument("--status", default="todo")
    a = ap.parse_args()
    if a.try_file:
        sites = yaml.safe_load((ROOT / a.try_file).read_text(encoding="utf-8"))["sites"]
        http = Http(delay=1.5, max_requests=2000, timeout=15, retries=1)
        robots = ab.Robots(http)
        out = []
        for s in sites:
            try:
                out.append(try_site(http, robots, s))
            except Exception as e:  # noqa: BLE001
                out.append({"id": s["id"], "error": str(e)[:120]})
            http.blocked = 0
            logging.info("tried %s", s["id"])
        (ROOT / "inspect-try.yml").write_text(yaml.safe_dump({"sites": out}, allow_unicode=True, sort_keys=False, width=200),
                                              encoding="utf-8")
        return
    census = yaml.safe_load((ROOT / "census.yml").read_text(encoding="utf-8"))["sites"]
    todo = [s for s in census if s["prefecture"] in a.pref and s["status"] == a.status]
    http = Http(delay=1.5, max_requests=3000, timeout=15, retries=1)
    robots = ab.Robots(http)
    out = []
    for i, s in enumerate(todo, 1):
        try:
            out.append({"prefecture": s["prefecture"], **inspect(http, robots, s)})
        except Exception as e:  # noqa: BLE001
            out.append({"prefecture": s["prefecture"], "id": s["id"], "list": s["list"], "result": f"error {e}"[:100]})
        http.blocked = 0
        logging.info("%d/%d %s", i, len(todo), s["list"])
    (ROOT / "inspect.yml").write_text(yaml.safe_dump({"sites": out}, allow_unicode=True, sort_keys=False, width=200),
                                      encoding="utf-8")


if __name__ == "__main__":
    main()
