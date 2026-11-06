"""SUUMO — used detached houses (chukoikkodate) and used apartments (ms/chuko).

SUUMO's robots.txt disallows its search-result endpoints (/jj/bukken/ichiran/...), so this module
only reads the public per-city pages, which are allowed:
  City index: /{cat}/{pref}/city/
  City list:  /{cat}/{pref}/sc_{city}/?kt={max 万円}&pc=100&page=N   (div.property_unit, dl/dt/dd)
"""
from __future__ import annotations

import re
from typing import Iterator
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..common import (Http, Listing, log, norm, parse_area_m2, parse_layout,
                      parse_price_yen, parse_walk_min, parse_year)

BASE = "https://suumo.jp"
NAME = "suumo"
# SUUMO's URL slug differs from ours for Hokkaido only
SLUG = {"hokkaido": "hokkaido_"}


def slug(pref: str) -> str:
    return SLUG.get(pref, pref)


CATEGORIES = {"chukoikkodate": "house", "ms/chuko": "apartment", "ikkodate": "house"}  # ikkodate = new houses


def city_index_url(cat: str, pref: str) -> str:
    return f"{BASE}/{cat}/{slug(pref)}/city/"


def parse_city_index(html: str, cat: str, pref: str) -> list[str]:
    pat = re.compile(rf"^/{re.escape(cat)}/{re.escape(slug(pref))}/(sc_[a-z0-9_]+)/$")
    soup = BeautifulSoup(html, "lxml")
    cities = []
    for a in soup.find_all("a", href=True):
        m = pat.match(a["href"].split("?")[0])
        if m:
            cities.append(m.group(1))
    return list(dict.fromkeys(cities))


def list_url(cat: str, pref: str, city: str, page: int, max_man: int) -> str:
    u = f"{BASE}/{cat}/{slug(pref)}/{city}/?kt={max_man}&pc=100"
    return u if page == 1 else f"{u}&page={page}"


def parse_list(html: str, cat: str, pref: str) -> list[Listing]:
    soup = BeautifulSoup(html, "lxml")
    out = []
    for unit in soup.select("div.property_unit"):
        a = unit.find("a", href=re.compile(r"/nc_\d+/"))
        if not a:
            continue
        href = a["href"].split("?")[0]
        if href.startswith("/tochi/"):
            continue  # land lots shown among new-house results: not requested
        sid = re.search(r"nc_(\d+)", href).group(1)
        fields = {}
        for dl in unit.select("dl"):
            dt, dd = dl.find("dt"), dl.find("dd")
            if dt and dd:
                fields[norm(dt.get_text())] = norm(dd.get_text())
        title_el = unit.select_one(".property_unit-title a") or unit.select_one("h2 a")
        imgs = []
        for img in unit.select("img"):
            src = img.get("rel") or img.get("data-src") or img.get("src") or ""
            if isinstance(src, list):
                src = src[0]
            if src.startswith("http") and "suumo" in src:
                imgs.append(src)
        area = fields.get("建物面積") or fields.get("専有面積")
        out.append(Listing(
            source=NAME,
            source_id=sid,
            url=urljoin(BASE, href),
            type=CATEGORIES[cat],
            new_build=cat == "ikkodate",
            price_yen=parse_price_yen(fields.get("販売価格") or fields.get("価格")),
            address=fields.get("所在地", ""),
            prefecture=pref,
            title=norm(title_el.get_text()) if title_el else fields.get("物件名", ""),
            land_m2=parse_area_m2(fields.get("土地面積")),
            building_m2=parse_area_m2(area),
            layout=parse_layout(fields.get("間取り")),
            year_built=parse_year(fields.get("築年月")),
            access=fields.get("沿線・駅", ""),
            walk_min=parse_walk_min(fields.get("沿線・駅")),
            images=list(dict.fromkeys(imgs))[:6],
            extra={"物件名": fields["物件名"]} if fields.get("物件名") else {},
        ))
    return out


def has_next(html: str, page: int) -> bool:
    return re.search(rf"[?&]page={page + 1}\b", html) is not None


def scrape(http: Http, prefs: list[str], categories: list[str], max_man: int,
           max_pages: int = 20) -> Iterator[Listing]:
    for cat in categories:
        for pref in prefs:
            idx = http.get(city_index_url(cat, pref))
            cities = parse_city_index(idx, cat, pref) if idx else []
            if not cities:
                log.warning("suumo %s %s: no cities found", cat, pref)
            for city in cities:
                page = 1
                while page <= max_pages:
                    html = http.get(list_url(cat, pref, city, page, max_man))
                    if not html:
                        break
                    items = parse_list(html, cat, pref)
                    yield from items
                    if not items or not has_next(html, page):
                        break
                    page += 1
            log.info("suumo %s %s: %d cities", cat, pref, len(cities))


def parse_detail_images(html: str) -> list[str]:
    """All gallery photos on a SUUMO listing page (resizer URLs; the app asks for the size it needs)."""
    soup = BeautifulSoup(html, "lxml")
    out = []
    for img in soup.select("img"):
        src = img.get("rel") or img.get("data-src") or img.get("src") or ""
        if isinstance(src, list):
            src = src[0]
        if "resizeImage" in src and "gazo" in src:
            out.append(urljoin("https://img01.suumo.com/", src))
    seen, uniq = set(), []
    for u in out:  # same photo appears in several sizes: keep one per file
        key = re.search(r"src=([^&]+)", u)
        k = key.group(1) if key else u
        if k not in seen:
            seen.add(k)
            uniq.append(u)
    return uniq[:40]
