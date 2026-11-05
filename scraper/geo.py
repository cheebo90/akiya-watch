"""Geocoding via the Geospatial Information Authority of Japan (GSI) address search — free, no key.
Results are town-level (chome/aza), cached by address so each one is looked up once."""
from __future__ import annotations

import re
import time
from urllib.parse import quote

from .common import log, norm

GSI = "https://msearch.gsi.go.jp/address-search/AddressSearch?q="


def clean_address(addr: str) -> str:
    a = norm(addr).replace(" ", "")
    a = re.sub(r"[（(].*?[)）]", "", a)
    return a


def geocode(http, address: str):
    """Return [lat, lng] or None. Falls back to shorter prefixes of the address."""
    a = clean_address(address)
    tries = [a]
    while len(a) > 4:
        a = a[:-2]
        tries.append(a)
    for q in tries[:4]:
        try:
            res = http.get_json(GSI + quote(q))
        except Exception as e:  # noqa: BLE001
            log.warning("geocode %s failed: %s", q, e)
            return None
        finally:
            time.sleep(0.1)
        try:
            if isinstance(res, list) and res:
                lng, lat = res[0]["geometry"]["coordinates"][:2]
                return [round(float(lat), 5), round(float(lng), 5)]
        except (KeyError, TypeError, ValueError, IndexError) as e:
            log.warning("geocode %s: unexpected answer (%s)", q, e)
            return None
    return None


def fill(http, listings: dict, cache: dict, limit: int = 25000, minutes: float = 75) -> int:
    """Geocode listings without coordinates, round-robin across prefectures so every region
    progresses, within a time budget (the rest continues on the next run)."""
    deadline = time.time() + minutes * 60
    by_pref: dict[str, list] = {}
    for l in listings.values():
        if not l.get("latlng") and l.get("address"):
            by_pref.setdefault(l.get("prefecture") or "", []).append(l)
    queues = list(by_pref.values())
    done = 0
    while queues and done < limit and time.time() < deadline:
        nxt = []
        for q in queues:
            l = q.pop()
            a = clean_address(l["address"])
            if a not in cache:
                cache[a] = geocode(http, a)
                done += 1
            l["latlng"] = cache[a]
            if q:
                nxt.append(q)
            if done >= limit or time.time() >= deadline:
                break
        queues = nxt
    log.info("geocoded %d new addresses", done)
    return done
