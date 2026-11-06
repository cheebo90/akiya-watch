"""Generic reader for municipal / prefectural akiya-bank websites.

Every site is different, so each one is described by a small entry in akiyabanks.yml:

  - id: niigata-pref                 # unique, stable
    name: 新潟県 空き家情報検索システム
    prefecture: niigata
    list: https://niigatakurashi.com/akiya-search/        # one or more list pages
    detail: "/akiya-search/detail/\\d+"                     # optional regex for listing links
    pages: "?page={n}"                                      # optional pagination suffix
    status: ok | pdf | delegated | blocked | todo           # census status, only "ok" is read

From each list page we collect links to listing pages (by the `detail` regex, or heuristically),
open the ones we haven't seen yet and extract the usual fields from label/value pairs.
Sites are checked against robots.txt; disallowed pages are skipped.
"""
from __future__ import annotations

import hashlib
import re
from typing import Iterator
from urllib import robotparser
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from ..common import (Http, Listing, log, norm, parse_area_m2, parse_layout,
                      parse_price_yen, parse_walk_min, parse_year)
from ..prefectures import ja_name

NAME = "akiyabank"

LABELS = {
    "price": ("売買価格", "販売価格", "売却価格", "希望価格", "価格", "金額"),
    "rent": ("賃料", "家賃", "月額"),
    "address": ("物件所在地", "所在地", "住所", "所在"),
    "land": ("土地面積", "敷地面積", "土地", "敷地"),
    "building": ("延床面積", "延べ床面積", "建物面積", "床面積", "延面積", "建物"),
    "layout": ("間取り", "間取"),
    "year": ("建築年月", "築年月", "建築年", "築年数", "築年", "建築時期", "建築年次"),
    "access": ("交通", "最寄り", "最寄駅", "アクセス"),
    "kind": ("物件種別", "種別", "取引形態", "取引区分", "取引の態様", "区分", "契約形態", "種類"),
    "name": ("物件名", "物件名称"),
}
# a key containing one of these is never the sale price
_NOT_PRICE = ("賃", "敷", "礼", "管理", "修繕", "保険", "共益", "固定資産", "税")
DETAIL_HINTS = re.compile(r"(detail|bukken|akiya|property|house|estate|info|id=|\d{2,})", re.I)
SKIP_EXT = re.compile(r"\.(pdf|jpe?g|png|gif|zip|docx?|xlsx?)($|\?)", re.I)
# Hosts that are national platforms: covered (or blocked) elsewhere, never read here.
PLATFORM_HOSTS = ("homes.co.jp", "akiya-athome.jp", "athome.co.jp", "suumo.jp")


# ------------------------------------------------------------------ parsing

def pairs(soup) -> dict[str, str]:
    """All label -> value pairs on a page: th/td, dt/dd, and 'ラベル：値' lines."""
    out: dict[str, str] = {}
    for th in soup.select("th"):
        td = th.find_next_sibling(["td", "th"])
        if td:
            out.setdefault(norm(th.get_text()), norm(td.get_text(" ")))
    for dt in soup.select("dt"):
        dd = dt.find_next_sibling("dd")
        if dd:
            out.setdefault(norm(dt.get_text()), norm(dd.get_text(" ")))
    text = soup.get_text("\n")
    for m in re.finditer(r"^\s*[■●・◆]?\s*([^\s：:]{2,8})\s*[：:]\s*(.{1,80})$", text, re.M):
        out.setdefault(norm(m.group(1)), norm(m.group(2)))
    return out


def _empty(v: str) -> bool:
    return not v or v.strip("-－‐ー—･・/ ") == ""


def pick(p: dict[str, str], field: str) -> str:
    """First value whose label contains one of the field's labels (in priority order)."""
    for label in LABELS[field]:
        for k, v in p.items():
            if label not in k or _empty(v) or len(k) > 20:
                continue
            if field == "price" and any(x in k for x in _NOT_PRICE):
                continue
            if field == "building" and "構造" in k:
                continue
            if field == "land" and ("地目" in k or "用途" in k):
                continue
            return v
    if field == "price":
        # combined labels used by many banks: 価格・賃料 / 賃料・価格 / 販売価格/家賃 -> the value says which it is
        for k, v in p.items():
            if "価格" in k and "賃" in k and len(k) <= 20 and not _empty(v) and not re.search(r"(月|賃料|家賃)", v) \
                    and re.search(r"\d", v):
                return v
    return ""


def parse_detail(html: str, url: str, site: dict) -> Listing | None:
    soup = BeautifulSoup(html, "lxml")
    for bad in soup.select("script, style, nav, header, footer"):
        bad.decompose()
    p = pairs(soup)
    price_s, rent_s, kind = pick(p, "price"), pick(p, "rent"), pick(p, "kind")
    if price_s and rent_s == price_s:
        rent_s = ""  # the same combined 価格・賃料 field, holding a sale price
    if not price_s and (rent_s or "賃貸" in kind):
        return None  # rental only
    price = parse_price_yen(price_s)
    if price_s and any(w in price_s for w in ("無償", "0円", "譲渡", "応相談")) and not price:
        price = 0 if ("無償" in price_s or "0円" in price_s) else None
    address = pick(p, "address")
    pref = site["prefecture"]
    if address and not address.startswith(ja_name(pref)):
        address = ja_name(pref) + (site.get("city") or "") + address if site.get("city") and site["city"] not in address \
            else ja_name(pref) + address
    building = parse_area_m2(pick(p, "building"))
    land = parse_area_m2(pick(p, "land"))
    if not (price_s or building or land):
        return None  # not a listing page
    title_el = soup.select_one("h1") or soup.select_one("h2") or soup.title
    name = pick(p, "name")
    imgs = []
    for img in soup.select("img"):
        src = img.get("data-src") or img.get("src") or ""
        if not src or src.startswith("data:") or re.search(r"(logo|icon|btn|banner|common|spacer|arrow)", src, re.I):
            continue
        imgs.append(urljoin(url, src))
    ltype = "akiya"
    if building is None and not pick(p, "layout"):
        ltype = "land"
    extra = {k: v[:200] for k, v in p.items() if k in ("現況", "構造", "備考", "設備", "物件番号", "登録番号")}
    extra["bank"] = site.get("name", site["id"])
    if price_s and price is None:
        extra["価格"] = price_s[:60]
    return Listing(
        source=NAME,
        source_id=f"{site['id']}-{hashlib.sha1(url.encode()).hexdigest()[:10]}",
        url=url,
        type=ltype,
        price_yen=price,
        address=address,
        prefecture=pref,
        title=(name or (norm(title_el.get_text()) if title_el else ""))[:120],
        land_m2=land,
        building_m2=building,
        layout=parse_layout(pick(p, "layout")),
        year_built=parse_year(pick(p, "year")),
        access=pick(p, "access")[:200],
        walk_min=parse_walk_min(pick(p, "access")),
        images=list(dict.fromkeys(imgs))[:8],
        extra=extra,
    )


def detail_links(html: str, base: str, site: dict) -> list[str]:
    soup = BeautifulSoup(html, "lxml")
    host = urlparse(base).netloc
    rx = re.compile(site["detail"]) if site.get("detail") else None
    lists = set(as_list(site["list"]))
    out = []
    for a in soup.find_all("a", href=True):
        u = urljoin(base, a["href"]).split("#")[0]
        if SKIP_EXT.search(u) or u in lists or not u.startswith("http"):
            continue
        if rx:
            if rx.search(u):
                out.append(u)
            continue
        # heuristic: same host, looks like a detail page, and the link sits in a block mentioning price/area
        if urlparse(u).netloc != host or not DETAIL_HINTS.search(urlparse(u).path + "?" + urlparse(u).query):
            continue
        ctx = a.find_parent(["li", "tr", "article", "div"]) or a
        t = ctx.get_text(" ")
        if re.search(r"(万円|円|㎡|m2|m²|坪|LDK|DK|物件)", t):
            out.append(u)
    return list(dict.fromkeys(out))


def as_list(v) -> list[str]:
    return v if isinstance(v, list) else [v]


# ------------------------------------------------------------------ robots

class Robots:
    def __init__(self, http: Http):
        self.http, self.cache = http, {}

    def allowed(self, url: str) -> bool:
        pu = urlparse(url)
        root = f"{pu.scheme}://{pu.netloc}"
        if root not in self.cache:
            rp = robotparser.RobotFileParser()
            try:
                r = self.http.s.get(root + "/robots.txt", timeout=15)
                rp.parse(r.text.splitlines() if r.status_code == 200 else [])
            except Exception:  # noqa: BLE001
                rp.parse([])
            self.cache[root] = rp
        return self.cache[root].can_fetch("*", url)


# ------------------------------------------------------------------ scrape

def scrape(http: Http, sites: list[dict], prefs: list[str], known_urls: set[str],
           max_details_per_site: int = 150) -> Iterator[Listing]:
    robots = Robots(http)
    for site in sites:
        if site.get("status", "ok") != "ok" or site["prefecture"] not in prefs:
            continue
        found, details = 0, 0
        try:
            links: list[str] = []
            for list_url in as_list(site["list"]):
                for n in range(1, int(site.get("max_pages", 10)) + 1):
                    u = list_url if n == 1 else list_url + site["pages"].format(n=n) if site.get("pages") else None
                    if not u:
                        break
                    if any(h in urlparse(u).netloc for h in PLATFORM_HOSTS) or not robots.allowed(u):
                        log.info("akiyabank %s: %s not allowed/skipped", site["id"], u)
                        break
                    html = http.get(u)
                    if not html:
                        break
                    new = [l for l in detail_links(html, u, site) if l not in links]
                    if not new:
                        break
                    links += new
            for link in links:
                if any(h in urlparse(link).netloc for h in PLATFORM_HOSTS) or not robots.allowed(link):
                    continue
                if link in known_urls:
                    # already stored: re-yield a minimal record so it stays "active"
                    yield Listing(source=NAME, source_id=f"{site['id']}-{hashlib.sha1(link.encode()).hexdigest()[:10]}",
                                  url=link, type="akiya", price_yen=None, address="", prefecture=site["prefecture"],
                                  extra={"_seen_only": True})
                    found += 1
                    continue
                if details >= int(site.get("max_details", max_details_per_site)):
                    continue
                details += 1
                html = http.get(link)
                if not html:
                    continue
                l = parse_detail(html, link, site)
                if l:
                    found += 1
                    yield l
        except Exception as e:  # noqa: BLE001  one broken or protected site must not stop the others
            if e.__class__.__name__ == "BudgetExceeded":
                raise
            log.warning("akiyabank %s stopped: %s", site["id"], e)
        http.blocked = 0
        log.info("akiyabank %s: %d listings (%d detail pages read)", site["id"], found, details)
