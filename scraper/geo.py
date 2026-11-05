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
        if res:
            lng, lat = res[0]["geometry"]["coordinates"]
            return [round(lat, 5), round(lng, 5)]
    return None


def fill(http, listings: dict, cache: dict, limit: int = 25000) -> int:
    done = 0
    for l in listings.values():
        if l.get("latlng") or not l.get("address"):
            continue
        a = clean_address(l["address"])
        if a not in cache:
            if done >= limit:
                continue
            cache[a] = geocode(http, a)
            done += 1
        l["latlng"] = cache[a]
    return done
