"""LIFULL HOME'S Akiya Bank (homes.co.jp/akiyabank) — municipal akiya-bank listings.

List page:   /akiyabank/{region}/{pref}/?page=N   (30 cards, div.wrap-bukken)
Detail page: /akiyabank/b-{id}/                   (th/td spec table)
"""
from __future__ import annotations

import re
from typing import Iterator
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..common import (Http, Listing, log, norm, parse_area_m2, parse_layout,
                      parse_price_yen, parse_walk_min, parse_year)
from ..prefectures import BY_SLUG, slug_from_address

BASE = "https://www.homes.co.jp"
NAME = "lifull"


def list_url(pref: str, page: int) -> str:
    region = BY_SLUG[pref][3]
    u = f"{BASE}/akiyabank/{region}/{pref}/"
    return u if page == 1 else f"{u}?page={page}"


def parse_list(html: str, pref: str) -> list[Listing]:
    soup = BeautifulSoup(html, "lxml")
    out = []
    for card in soup.select("div.wrap-bukken"):
        a = card.find("a", href=re.compile(r"/akiyabank/b-\d+"))
        if not a:
            continue
        sid = re.search(r"b-(\d+)", a["href"]).group(1)
        fields = {}
        for dt in card.select("dt"):
            dd = dt.find_next_sibling("dd")
            if dd:
                fields[norm(dt.get_text()).lstrip("・·").strip()] = norm(dd.get_text())
        imgs = []
        for img in card.select("img"):
            src = img.get("data-src") or img.get("src") or ""
            if "akiyabank-image" in src:
                imgs.append(src.replace("259x190", "562x418"))
        point = card.select_one(".pointText")
        address = fields.get("所在地", "")
        out.append(Listing(
            source=NAME,
            source_id=sid,
            url=urljoin(BASE, f"/akiyabank/b-{sid}/"),
            type="akiya",
            price_yen=parse_price_yen(fields.get("価格")),
            address=address,
            prefecture=slug_from_address(address) or pref,
            title=norm(point.get_text()).removeprefix("Point").strip() if point else "",
            land_m2=parse_area_m2(fields.get("土地面積")),
            images=list(dict.fromkeys(imgs)),
        ))
    return out


def has_next(html: str, page: int) -> bool:
    return f"page={page + 1}" in html


def parse_detail(html: str, listing: Listing) -> Listing:
    soup = BeautifulSoup(html, "lxml")
    table = {}
    for th in soup.select("th"):
        td = th.find_next_sibling("td")
        if td:
            k = norm(th.get_text())
            table.setdefault(k, norm(td.get_text()))
    get = lambda prefix: next((v for k, v in table.items() if k.startswith(prefix)), "")
    listing.price_yen = parse_price_yen(get("価格")) or listing.price_yen
    listing.building_m2 = parse_area_m2(get("建物面積"))
    listing.land_m2 = parse_area_m2(get("土地面積")) or listing.land_m2
    listing.layout = parse_layout(get("間取り"))
    listing.year_built = parse_year(get("築年月")) or parse_year(get("備考"))
    listing.access = get("交通")
    listing.walk_min = parse_walk_min(listing.access)
    if get("物件名"):
        listing.extra["物件名"] = get("物件名")
    for k in ("地目", "都市計画", "現況", "引き渡し状況", "備考", "小学校", "中学校"):
        if get(k):
            listing.extra[k] = get(k)[:300]
    h1 = norm(soup.select_one("h1").get_text()) if soup.select_one("h1") else ""
    if "賃貸" in h1 and "売買" not in h1:
        listing.extra["rent"] = True
    if listing.building_m2 is None and not listing.layout:
        listing.type = "land"
    imgs = re.findall(r"https://akiyabank-image\.akiyabank\.homes\.co\.jp/resized-bukken-1124x836-[0-9a-f]+\.jpg", html)
    if imgs:
        listing.images = list(dict.fromkeys(imgs))[:12]
    return listing


def scrape(http: Http, prefs: list[str], known: set[str], max_pages: int = 60,
           max_details: int = 400) -> Iterator[Listing]:
    details = 0
    for pref in prefs:
        page = 1
        while page <= max_pages:
            html = http.get(list_url(pref, page))
            if not html:
                break
            items = parse_list(html, pref)
            if not items:
                break
            for it in items:
                if it.key not in known and details < max_details:
                    d = http.get(it.url)
                    details += 1
                    if d:
                        it = parse_detail(d, it)
                    it.extra["_detail"] = bool(d)
                if it.extra.get("rent"):
                    continue
                yield it
            if not has_next(html, page):
                break
            page += 1
        log.info("lifull %s: %d pages", pref, page)
