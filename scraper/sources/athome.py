"""athome.co.jp — general portal; used detached houses (kodate/chuko) and used apartments (mansion/chuko).

List page: /{cat}/{pref}/list/[pageN/]?PRICETO=kp1xx   (30 cards, price ascending)
Card: <athome-csite-pc-part-bukken-card-*> with .property-price and
      .property-detail-table__block (strong = label, span = value)
"""
from __future__ import annotations

import re
from typing import Iterator
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..common import (Http, Listing, log, norm, parse_area_m2, parse_layout,
                      parse_price_yen, parse_walk_min, parse_year)
from ..prefectures import ja_name

BASE = "https://www.athome.co.jp"
NAME = "athome"
CATEGORIES = {"kodate/chuko": "house", "mansion/chuko": "apartment"}

# PRICETO select values on athome (万円 -> code)
_PRICE_CODES = [(500, "kp101"), (1000, "kp102"), (1500, "kp103"), (2000, "kp104"), (2500, "kp105"),
                (3000, "kp106"), (3500, "kp107"), (4000, "kp108"), (4500, "kp109"), (5000, "kp110")]


def price_code(max_man: int) -> str:
    for man, code in _PRICE_CODES:
        if max_man <= man:
            return code
    return "kp120"  # no limit


def list_url(cat: str, pref: str, page: int, max_man: int) -> str:
    p = "" if page == 1 else f"page{page}/"
    return f"{BASE}/{cat}/{pref}/list/{p}?PRICETO={price_code(max_man)}"


def _cards(soup):
    return [el for el in soup.find_all(True) if el.name.startswith("athome-csite-pc-part-bukken-card")]


def parse_list(html: str, cat: str, pref: str) -> list[Listing]:
    soup = BeautifulSoup(html, "lxml")
    out = []
    for card in _cards(soup):
        a = card.find("a", href=re.compile(r"/(?:kodate|mansion)/\d{6,}/"))
        if not a:
            continue
        sid = re.search(r"/(\d{6,})/", a["href"]).group(1)
        fields = {}
        for block in card.select(".property-detail-table__block"):
            k, v = block.find("strong"), block.find("span")
            if k and v:
                fields[norm(k.get_text())] = norm(v.get_text())
        price_el = card.select_one(".property-price")
        title_el = card.select_one(".title-wrap__title-text")
        imgs = []
        for img in card.select("img"):
            src = img.get("data-src") or img.get("src") or ""
            if "/image_files/" in src:
                imgs.append(urljoin(BASE, src))
        ltype = CATEGORIES[cat]
        area = fields.get("建物面積") or fields.get("専有面積")
        address = fields.get("所在地", "")
        if address and not address.startswith(ja_name(pref)):
            address = ja_name(pref) + address
        out.append(Listing(
            source=NAME,
            source_id=sid,
            url=f"{BASE}/{cat.split('/')[0]}/{sid}/",
            type=ltype,
            price_yen=parse_price_yen(price_el.get_text() if price_el else ""),
            address=address,
            prefecture=pref,
            title=norm(title_el.get_text()) if title_el else "",
            land_m2=parse_area_m2(fields.get("土地面積")),
            building_m2=parse_area_m2(area),
            layout=parse_layout(fields.get("間取り")),
            year_built=parse_year(fields.get("築年月")),
            access=fields.get("交通", ""),
            walk_min=parse_walk_min(fields.get("交通")),
            images=list(dict.fromkeys(imgs))[:6],
        ))
    return out


def has_next(html: str, page: int) -> bool:
    return f"/list/page{page + 1}/" in html


def scrape(http: Http, prefs: list[str], categories: list[str], max_man: int,
           max_pages: int = 40) -> Iterator[Listing]:
    for cat in categories:
        for pref in prefs:
            page = 1
            while page <= max_pages:
                html = http.get(list_url(cat, pref, page, max_man))
                if not html:
                    break
                items = parse_list(html, cat, pref)
                if not items:
                    break
                yield from items
                if not has_next(html, page):
                    break
                page += 1
            log.info("athome %s %s: %d pages", cat, pref, page)
