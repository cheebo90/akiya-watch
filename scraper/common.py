"""Shared helpers: polite HTTP session, Japanese number parsing, the Listing schema."""
from __future__ import annotations

import logging
import random
import re
import time
import unicodedata
from dataclasses import dataclass, field, asdict
from typing import Optional

import requests

log = logging.getLogger("akiya")

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0 Safari/537.36 akiya-watch/1.0 (personal use)"
)


class Http:
    """Single session with a fixed delay between requests, retries and a request budget."""

    def __init__(self, delay: float = 2.0, max_requests: int = 5000, timeout: int = 30, retries: int = 3):
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "ja,en;q=0.8"})
        self.delay = delay
        self.max_requests = max_requests
        self.timeout = timeout
        self.retries = retries
        self.count = 0
        self.errors = 0
        self.blocked = 0
        self._last = 0.0

    def get(self, url: str, **kw) -> Optional[str]:
        if self.count >= self.max_requests:
            raise BudgetExceeded(url)
        for attempt in range(self.retries):
            wait = self.delay + random.uniform(0, self.delay / 2) - (time.time() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.time()
            self.count += 1
            try:
                r = self.s.get(url, timeout=self.timeout, **kw)
            except requests.RequestException as e:
                msg = str(e)
                if any(x in msg for x in ("NameResolution", "getaddrinfo", "Name or service not known",
                                          "nodename nor servname", "SSLError", "CERTIFICATE")):
                    log.warning("GET %s: site does not exist / bad certificate, skipped", url)
                    break  # dead domain or broken TLS: retrying won't help
                log.warning("GET %s failed (%s), attempt %d", url, e.__class__.__name__, attempt + 1)
                if attempt + 1 < self.retries:
                    time.sleep(5 * (attempt + 1))
                continue
            if r.status_code == 200:
                r.encoding = r.apparent_encoding if r.encoding in (None, "ISO-8859-1") else r.encoding
                return r.text
            if r.status_code == 404:
                return None
            # 202 = AWS WAF challenge page, 403 = refused: the site doesn't want automated access -> stop.
            if r.status_code in (202, 403) or "awswaf" in r.text[:5000].lower():
                self.blocked += 1
                log.warning("GET %s -> %d: bot protection, stopping this source", url, r.status_code)
                if self.blocked >= 2:
                    raise Blocked(f"{r.status_code} su {url}")
                return None
            if r.status_code in (429, 503):
                log.warning("GET %s -> %d (blocked/throttled), attempt %d", url, r.status_code, attempt + 1)
                time.sleep(20 * (attempt + 1))
                continue
            log.warning("GET %s -> %d", url, r.status_code)
            return None
        self.errors += 1
        return None

    def get_json(self, url: str, **kw):
        self.count += 1
        r = self.s.get(url, timeout=self.timeout, **kw)
        r.raise_for_status()
        return r.json()


class BudgetExceeded(Exception):
    pass


class Blocked(Exception):
    """The site answered with a bot-protection challenge or refusal; we stop instead of insisting."""


# ---------------------------------------------------------------- parsing helpers

def norm(s: Optional[str]) -> str:
    """NFKC-normalise (full-width -> half-width), collapse whitespace."""
    if not s:
        return ""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", s)).strip()


def parse_price_yen(s: Optional[str]) -> Optional[int]:
    """'8万円' -> 80000, '1,450万円' -> 14500000, '17,800,000円' -> 17800000, '1億2000万円' -> 120000000."""
    s = norm(s).replace(",", "")
    if not s:
        return None
    m = re.search(r"(?:(\d+(?:\.\d+)?)億)?\s*(?:(\d+(?:\.\d+)?)万)?\s*(\d+)?\s*円", s)
    if m and any(m.groups()):
        oku, man, yen = m.groups()
        total = 0.0
        if oku:
            total += float(oku) * 1e8
        if man:
            total += float(man) * 1e4
        if yen and not man and not oku:
            total += float(yen)
        return int(round(total)) or None
    m = re.search(r"(\d+(?:\.\d+)?)\s*万", s)
    if m:
        return int(float(m.group(1)) * 1e4)
    return None


def parse_area_m2(s: Optional[str]) -> Optional[float]:
    """'359.10m²' / '241.59m2（73.08坪）' / '3,221㎡-' -> float m²."""
    s = norm(s).replace(",", "")
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:m2|m²|㎡|平米)", s)
    if m:
        return float(m.group(1))
    m = re.search(r"(\d+(?:\.\d+)?)\s*坪", s)
    if m:
        return round(float(m.group(1)) * 3.30579, 2)
    return None


_ERAS = {"明治": 1867, "大正": 1911, "昭和": 1925, "平成": 1988, "令和": 2018}


def parse_year(s: Optional[str]) -> Optional[int]:
    """'1967年1月（築59年）' -> 1967, '平成2年築' -> 1990, '昭和元年' -> 1926."""
    s = norm(s)
    m = re.search(r"(19\d{2}|20\d{2})\s*年", s)
    if m:
        return int(m.group(1))
    m = re.search(r"(明治|大正|昭和|平成|令和)\s*(\d+|元)\s*年", s)
    if m:
        n = 1 if m.group(2) == "元" else int(m.group(2))
        return _ERAS[m.group(1)] + n
    m = re.fullmatch(r"\s*(19\d{2}|20\d{2})\s*", s)  # bare year, e.g. '1985'
    if m:
        return int(m.group(1))
    return None


def parse_walk_min(s: Optional[str]) -> Optional[int]:
    """Smallest '徒歩N分' in the access text."""
    vals = [int(x) for x in re.findall(r"徒歩\s*(\d+)\s*分", norm(s))]
    return min(vals) if vals else None


def parse_layout(s: Optional[str]) -> str:
    s = norm(s).upper()
    m = re.search(r"\d+\s*(?:S?LDK|S?DK|S?K|R)", s)
    return m.group(0).replace(" ", "") if m else ""


# ---------------------------------------------------------------- schema

TYPES = ("house", "apartment", "land", "akiya", "building", "commercial")


def parse_yield(s: Optional[str]) -> Optional[float]:
    """'利回り 22.00%' / '表面利回り：8.5％' -> 22.0 / 8.5"""
    m = re.search(r"利回り\D{0,8}?(\d{1,2}(?:\.\d+)?)\s*%", norm(s))
    return float(m.group(1)) if m else None


def type_from_kind(kind: str, default: str = "commercial") -> str:
    """Japanese property kind (種目) -> our type."""
    k = norm(kind)
    if re.search(r"一棟|ビル|アパート|寮|社宅", k):
        return "building"
    if re.search(r"マンション", k):
        return "apartment"
    if re.search(r"一戸建|住宅(?!付き店舗)|戸建", k) and not re.search(r"店舗|事務所", k.replace("店舗付き住宅", "")):
        return "house"
    if re.search(r"土地|地$", k):
        return "land"
    return default


@dataclass
class Listing:
    source: str                 # lifull | athome | suumo
    source_id: str
    url: str
    type: str                   # house | apartment | land | akiya
    price_yen: Optional[int]
    address: str                # Japanese, normalised
    prefecture: str             # romaji slug, e.g. "chiba"
    title: str = ""
    land_m2: Optional[float] = None
    building_m2: Optional[float] = None
    layout: str = ""
    year_built: Optional[int] = None
    access: str = ""
    walk_min: Optional[int] = None
    images: list = field(default_factory=list)
    yield_pct: Optional[float] = None   # gross yield declared by the seller (表面利回り)
    new_build: bool = False
    subtype: str = ""                   # Japanese kind as listed, e.g. 売店舗, 一棟売アパート
    extra: dict = field(default_factory=dict)   # raw label -> value (Japanese)

    @property
    def key(self) -> str:
        return f"{self.source}:{self.source_id}"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["key"] = self.key
        return d
