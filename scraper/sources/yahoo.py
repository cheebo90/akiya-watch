"""Yahoo! 不動産 (realestate.yahoo.co.jp) — national lists of used houses, new houses and used apartments.

List page: /{cat}/search/[?page=N]   (30 cards li.ListBukken2__list__item)
robots.txt allows these list pages with ?page=; it disallows path-style filters (/search/_...) and the
old /search/*_start_ pagination, which we never use. Nationwide lists have no server-side price filter we
are allowed to use, so the price ceiling is applied locally.
Parts: part i of n reads pages i, i+n, i+2n, ... of every category.
"""
from __future__ import annotations

import re
from typing import Iterator

from bs4 import BeautifulSoup

from ..common import (condition_flags, Http, Listing, log, norm, parse_layout, parse_price_yen, parse_walk_min, parse_year)
from ..prefectures import slug_from_address

BASE = "https://realestate.yahoo.co.jp"
NAME = "yahoo"
# category -> (type, new_build)
CATEGORIES = {"used/house": ("house", False), "new/house": ("house", True), "used/mansion": ("apartment", False)}
_ID = re.compile(r"/(used/house|new/house|used/mansion)/detail_corp/([a-z0-9]+)/")


def list_url(cat: str, page: int) -> str:
    u = f"{BASE}/{cat}/search/"
    return u if page == 1 else f"{u}?page={page}"


def _area(text: str, label: str):
    m = re.search(label + r"\s*([\d,]+(?:\.\d+)?)\s*m", text.replace(",", ""))
    return float(m.group(1)) if m else None


def parse_list(html: str, cat: str) -> list[Listing]:
    soup = BeautifulSoup(html, "lxml")
    out = []
    ltype, new = CATEGORIES[cat]
    for card in soup.select("li.ListBukken2__list__item"):
        a = card.find("a", href=_ID)
        if not a:
            continue
        sid = _ID.search(a["href"]).group(2)
        info = [norm(x.get_text(" ")) for x in card.select(".ListCassette2__info__dtl")]
        access = next((x for x in info if "駅" in x or "徒歩" in x or "バス" in x), "")
        address = next((x for x in info if x != access and slug_from_address(x)), "")
        year_s = next((x for x in info if re.search(r"(19|20)\d{2}年", x)), "")
        layout_s = next((x for x in info if re.search(r"\d\s*(S?LDK|S?DK|K|R)", x)), "")
        areas_s = next((x for x in info if re.search(r"(土地|建物|専有).*?\d\s*(m|㎡)", x)), "")
        price_el = card.select_one(".ListCassette2__info__price")
        title_el = card.select_one(".ListCassette2__ttl__txt")
        imgs = []
        for el in card.select("source, img"):
            src = (el.get("srcset") or el.get("data-src") or el.get("src") or "").split(" ")[0]
            if "yimg.jp" in src and "realestate" in src:
                imgs.append(src)
        out.append(Listing(
            source=NAME, source_id=sid, url=f"{BASE}/{cat}/detail_corp/{sid}/", type=ltype, new_build=new,
            price_yen=parse_price_yen(price_el.get_text() if price_el else ""),
            address=address, prefecture=slug_from_address(address),
            title=norm(title_el.get_text()) if title_el else "",
            land_m2=_area(areas_s, "土地"), building_m2=_area(areas_s, "建物") or _area(areas_s, "専有"),
            layout=parse_layout(layout_s), year_built=parse_year(year_s),
            access=access, walk_min=parse_walk_min(access),
            images=list(dict.fromkeys(imgs))[:6],
            extra=condition_flags(card.get_text(" ")),
        ))
    return out


def scrape(http: Http, categories: list[str], prefs: list[str], part: tuple[int, int] = (1, 1),
           max_pages: int = 2500) -> Iterator[Listing]:
    i, n = part
    wanted = set(prefs)
    for cat in categories:
        page, read, empty = i, 0, 0
        while page <= max_pages:
            html = http.get(list_url(cat, page))
            items = parse_list(html, cat) if html else []
            if not items:
                empty += 1
                if empty >= 2:  # two empty pages in a row: past the end of the list
                    break
            else:
                empty = 0
                read += 1
                yield from (l for l in items if l.prefecture in wanted)
            page += n
        log.info("yahoo %s part %d/%d: %d pages with listings", cat, i, n, read)


_BLD = re.compile(r"https://realestate-pctr\.c\.yimg\.jp/ds/realestate-buy-image/bld_image/[^\"'\s,?]+\.jpe?g")


def parse_detail_images(html: str, known: list[str]) -> list[str]:
    """Photos of this listing on its Yahoo page. The page also shows other properties, so keep only the
    image folders already seen on the listing's card (bld_image/00/2474/6123/0001/...)."""
    dirs = {m.group(0).rsplit("/", 1)[0] + "/" for u in known for m in [_BLD.search(u)] if m}
    if not dirs:
        return []
    out = []
    for m in _BLD.finditer(html.replace("\\/", "/")):
        u = m.group(0)
        if u.rsplit("/", 1)[0] + "/" in dirs:
            out.append(u)
    return [u + "?w=1024&h=768&fmt=webp" for u in dict.fromkeys(out)][:40]
