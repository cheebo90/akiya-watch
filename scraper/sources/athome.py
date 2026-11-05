"""athome.co.jp — general portal.

Residential  /{cat}/{pref}/list/[pageN/]?PRICETO=kp1xx   cards <athome-csite-pc-part-bukken-card-*>
  kodate/chuko (used houses), mansion/chuko (used apartments), kodate/shinchiku (new houses),
  mansion/ownerchange (apartments sold with a tenant; the card shows the gross yield)
Business     /{cat}/{pref}/list/[pageN/]?PRICETO=kp1xx   cards <athome-csite-pc-part-rent-business-other-bukken-card>
  buy_store (shops), buy_office (offices), buy_other (buildings, whole apartment blocks, other)
"""
from __future__ import annotations

import re
from typing import Iterator
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..common import (Blocked, Http, Listing, log, norm, parse_area_m2, parse_layout, parse_price_yen,
                      parse_walk_min, parse_year, parse_yield, type_from_kind)
from ..prefectures import ja_name

BASE = "https://www.athome.co.jp"
NAME = "athome"
# category -> (type, new_build); type None = decided per card from its kind (種目)
CATEGORIES = {
    "kodate/chuko": ("house", False),
    "mansion/chuko": ("apartment", False),
    "kodate/shinchiku": ("house", True),
    "mansion/ownerchange": ("apartment", False),
    "buy_store": ("commercial", False),
    "buy_office": ("commercial", False),
    "buy_other": (None, False),
}
# categories where a whole prefecture with zero results is implausible -> empty pages mean trouble
_CORE = ("kodate/chuko", "mansion/chuko")
_ID = re.compile(r"/(kodate|mansion|buy_store|buy_office|buy_other)/(\d{6,})/")

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


def _with_pref(address: str, pref: str) -> str:
    address = norm(address)
    return ja_name(pref) + address if address and not address.startswith(ja_name(pref)) else address


def _images(card) -> list[str]:
    imgs = []
    for img in card.select("img"):
        src = img.get("data-src") or img.get("src") or ""
        if "/image_files/" in src:
            imgs.append(urljoin(BASE, src))
    return list(dict.fromkeys(imgs))[:6]


def _residential(card, cat: str, pref: str) -> Listing | None:
    a = card.find("a", href=_ID)
    if not a:
        return None
    prefix, sid = _ID.search(a["href"]).groups()
    fields = {}
    for block in card.select(".property-detail-table__block"):
        k, v = block.find("strong"), block.find("span")
        if k and v:
            fields[norm(k.get_text())] = norm(v.get_text())
    price_el = card.select_one(".property-price")
    price_txt = price_el.get_text(" ") if price_el else ""
    title_el = card.select_one(".title-wrap__title-text")
    kind_el = card.select_one(".square-icon")
    ltype, new = CATEGORIES[cat]
    return Listing(
        source=NAME, source_id=sid, url=f"{BASE}/{prefix}/{sid}/", type=ltype, new_build=new,
        price_yen=parse_price_yen(price_txt.split("利回り")[0]),
        yield_pct=parse_yield(price_txt) or parse_yield(card.get_text(" ")),
        address=_with_pref(fields.get("所在地", ""), pref),
        prefecture=pref,
        title=norm(title_el.get_text()) if title_el else "",
        subtype=norm(kind_el.get_text()) if kind_el else "",
        land_m2=parse_area_m2(fields.get("土地面積")),
        building_m2=parse_area_m2(fields.get("建物面積") or fields.get("専有面積")),
        layout=parse_layout(fields.get("間取り")),
        year_built=parse_year(fields.get("築年月") or fields.get("完成時期")),
        access=fields.get("交通", ""),
        walk_min=parse_walk_min(fields.get("交通")),
        images=_images(card),
    )


def _business(card, cat: str, pref: str) -> Listing | None:
    a = card.find("a", href=_ID)
    if not a:
        return None
    prefix, sid = _ID.search(a["href"]).groups()
    kind = norm(card.select_one(".area-title__syumoku").get_text()) if card.select_one(".area-title__syumoku") else ""
    title = norm(card.select_one(".area-title__text").get_text()) if card.select_one(".area-title__text") else ""
    tds = card.select("tr.tr-top td")
    cell = lambda i: norm(tds[i].get_text(" ")) if len(tds) > i else ""
    spans = [norm(s.get_text()) for s in tds[0].find_all("span") if norm(s.get_text())] if tds else []
    access, address = (spans[0], spans[-1]) if len(spans) >= 2 else (cell(0), "")
    areas = re.findall(r"(\d[\d,]*(?:\.\d+)?)\s*m", cell(2).replace(",", ""))
    ltype, _ = CATEGORIES[cat]
    if ltype is None or kind:
        ltype = type_from_kind(kind, default=ltype or "commercial")
    return Listing(
        source=NAME, source_id=sid, url=f"{BASE}/{prefix}/{sid}/", type=ltype, subtype=kind,
        price_yen=parse_price_yen(cell(1).split("利回り")[0] + ("" if "円" in cell(1) else "万円")),
        yield_pct=parse_yield(card.get_text(" ")),
        address=_with_pref(address, pref), prefecture=pref, title=title,
        building_m2=float(areas[0]) if areas else None,
        land_m2=float(areas[1]) if len(areas) > 1 else None,
        year_built=parse_year(cell(4)),
        access=access, walk_min=parse_walk_min(access),
        images=_images(card),
        extra={"用途地域・構造": cell(3)} if cell(3) else {},
    )


def parse_list(html: str, cat: str, pref: str) -> list[Listing]:
    soup = BeautifulSoup(html, "lxml")
    out = []
    for el in soup.find_all(True):
        if el.name.startswith("athome-csite-pc-part-bukken-card"):
            l = _residential(el, cat, pref)
        elif el.name == "athome-csite-pc-part-rent-business-other-bukken-card":
            l = _business(el, cat, pref)
        else:
            continue
        if l:
            out.append(l)
    return out


def has_next(html: str, page: int) -> bool:
    return f"/list/page{page + 1}/" in html


def scrape(http: Http, prefs: list[str], categories: list[str], max_man: int,
           max_pages: int = 40) -> Iterator[Listing]:
    empty_streak = 0
    for cat in categories:
        for pref in prefs:
            page = 1
            while page <= max_pages:
                http.s.cookies.clear()  # each page as a fresh visit, no session state carried over
                html = http.get(list_url(cat, pref, page, max_man))
                if not html:
                    break
                if is_challenge(html):
                    log.warning("athome %s %s: verification page. %s", cat, pref, diagnose(html))
                    raise Blocked("athome: pagina di verifica anti-bot (認証中)")
                items = parse_list(html, cat, pref)
                if not items:
                    if page == 1 and cat in _CORE:
                        empty_streak += 1
                        log.warning("athome %s %s: empty page. %s", cat, pref, diagnose(html))
                        if empty_streak >= 4:
                            raise Blocked("athome: pagine senza annunci in serie (probabile blocco silenzioso)")
                    break
                if cat in _CORE:
                    empty_streak = 0
                yield from items
                if not has_next(html, page):
                    break
                page += 1
            log.info("athome %s %s: %d pages", cat, pref, page)


def is_challenge(html: str) -> bool:
    """athome's bot check: '【アットホーム】認証中' — 'please help us verify'."""
    head = html[:3000]
    return "認証中" in head or "認証にご協力ください" in html[:8000]


def diagnose(html: str) -> str:
    """Short, log-safe description of a page that has no listing cards."""
    soup = BeautifulSoup(html, "lxml")
    title = norm(soup.title.get_text()) if soup.title else ""
    text = norm(soup.body.get_text(" ")) if soup.body else ""
    flags = [w for w in ("captcha", "challenge", "robot", "アクセス", "制限", "ブロック", "混み合", "該当する物件")
             if w in html.lower() or w in text]
    tags = sorted({el.name for el in soup.find_all(True) if el.name.startswith("athome-")})[:5]
    return f"len={len(html)} title={title[:80]!r} flags={flags} components={tags} text={text[:160]!r}"
