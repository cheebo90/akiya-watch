"""State (all listings ever seen + caches), merging, de-duplication, export and encryption.

Everything written to the repository / website is AES-256-GCM encrypted with a key derived from
the AKIYA_PASSPHRASE secret, so the public GitHub repo and Pages site never expose listing data.
"""
from __future__ import annotations

from .sources.akiyabank import TRACKER
import base64
import datetime as dt
import gzip
import hashlib
import json
import os
import re
import unicodedata
from pathlib import Path

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

ITERATIONS = 250_000
DROP_INACTIVE_AFTER_DAYS = 45


# ------------------------------------------------------------------ crypto

def _key(passphrase: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=ITERATIONS)
    return kdf.derive(passphrase.encode())


def encrypt(obj, passphrase: str) -> dict:
    salt, iv = os.urandom(16), os.urandom(12)
    raw = gzip.compress(json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode())
    ct = AESGCM(_key(passphrase, salt)).encrypt(iv, raw, None)
    b64 = lambda b: base64.b64encode(b).decode()
    return {"v": 1, "kdf": "PBKDF2-SHA256", "iter": ITERATIONS, "salt": b64(salt), "iv": b64(iv), "ct": b64(ct)}


def decrypt(blob: dict, passphrase: str):
    d = lambda k: base64.b64decode(blob[k])
    raw = AESGCM(_key(passphrase, d("salt"))).decrypt(d("iv"), d("ct"), None)
    return json.loads(gzip.decompress(raw))


def load_state(path: Path, passphrase: str) -> dict:
    if path.exists():
        return decrypt(json.loads(path.read_text()), passphrase)
    return {"listings": {}, "geocache": {}, "fx_aud_jpy": None, "runs": []}


def save_encrypted(obj, path: Path, passphrase: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(encrypt(obj, passphrase)))


# ------------------------------------------------------------------ merge

def today() -> str:
    return dt.date.today().isoformat()


def merge(state: dict, scraped: list[dict]) -> list[str]:
    """Insert/update listings; returns keys of listings never seen before."""
    new_keys = []
    now = today()
    L = state["listings"]
    for d in scraped:
        k = d["key"]
        old = L.get(k)
        if d.get("extra", {}).get("_seen_only"):
            if old is not None:
                old["last_seen"], old["active"] = now, True
            continue
        if old is None:
            d["first_seen"] = now
            new_keys.append(k)
            old = d
        else:
            if d.get("price_yen") and old.get("price_yen") and d["price_yen"] != old["price_yen"]:
                hist = old.setdefault("price_history", [])
                hist.append([now, old["price_yen"]])
            for f, v in d.items():
                if f == "extra":
                    old.setdefault("extra", {}).update({ek: ev for ek, ev in v.items() if ev not in (None, "")})
                elif v not in (None, "", []):
                    if f == "address" and v != old.get("address"):
                        old.pop("latlng", None)
                    old[f] = v
        old["last_seen"] = now
        old["active"] = True
        L[k] = old
    return new_keys


def mark_inactive(state: dict, source: str, seen: set[str], completed: bool):
    """Listings of a source that completed its run but weren't seen are marked inactive (sold/removed)."""
    if not completed:
        return
    cutoff = (dt.date.today() - dt.timedelta(days=DROP_INACTIVE_AFTER_DAYS)).isoformat()
    L = state["listings"]
    for k in list(L):
        l = L[k]
        if l["source"] != source or k in seen:
            continue
        l["active"] = False
        if l.get("last_seen", "") < cutoff:
            del L[k]


# ------------------------------------------------------------------ de-duplication

def _addr_key(a: str) -> str:
    a = unicodedata.normalize("NFKC", a or "").replace(" ", "")
    a = re.sub(r"[（(].*?[)）]", "", a)
    a = re.sub(r"(\d|[一二三四五六七八九十]+丁目|番地).*$", "", a)  # cut house numbers -> town level
    return a


def dedupe_groups(listings: dict) -> dict[str, str]:
    """Map listing key -> group id. Same town + same price + similar area => same property."""
    groups, gid_of = {}, {}
    for k, l in listings.items():
        if not l.get("active", True):
            gid_of[k] = k  # removed listings stay visible (e.g. in favourites), never grouped
            continue
        area = l.get("building_m2") or l.get("land_m2") or 0
        sig = (l.get("prefecture"), _addr_key(l.get("address", "")), l.get("price_yen"), round(area / 5))
        if not l.get("price_yen") or not sig[1]:
            gid_of[k] = k
            continue
        gid = groups.setdefault(sig, hashlib.sha1(repr(sig).encode()).hexdigest()[:12])
        gid_of[k] = gid
    return gid_of


# ------------------------------------------------------------------ export for the web app

_COMPLETENESS = ("building_m2", "land_m2", "layout", "year_built", "access", "images", "latlng")


def _fix_generic_titles(L: dict):
    """Akiya-bank pages whose heading is site navigation: the same title on many listings of one bank."""
    from .sources.akiyabank import fallback_title, is_generic_title
    count: dict = {}
    for l in L.values():
        if l["source"] == "akiyabank":
            k = ((l.get("extra") or {}).get("bank"), l.get("title"))
            count[k] = count.get(k, 0) + 1
    for l in L.values():
        if l["source"] != "akiyabank":
            continue
        ex = l.get("extra") or {}
        if count.get((ex.get("bank"), l.get("title")), 0) >= 3 or is_generic_title(l.get("title"), ex.get("bank", "")):
            l["title"] = fallback_title(l.get("address", ""), l.get("prefecture", ""),
                                        ex.get("物件番号") or ex.get("登録番号") or "")


def export(state: dict, aud_per_jpy: float, max_yen: int | None = None) -> dict:
    L = state["listings"]
    _fix_generic_titles(L)
    gid_of = dedupe_groups(L)
    groups: dict[str, list] = {}
    for k, g in gid_of.items():
        groups.setdefault(g, []).append(L[k])
    # an akiya-bank image on 3+ different properties is site chrome (banners, "no photo", buy/rent buttons), not a photo
    seen: dict[str, int] = {}
    for members in groups.values():
        for u in {u for m in members if m.get("source") == "akiyabank" for u in (m.get("images") or [])}:
            seen[u] = seen.get(u, 0) + 1
    shared = {u for u, n in seen.items() if n >= 3 and not u.startswith("enc:")}
    props = []
    for gid, members in groups.items():
        members.sort(key=lambda l: -sum(bool(l.get(f)) for f in _COMPLETENESS))
        p = dict(members[0])
        for m in members[1:]:  # fill gaps from the other sources
            for f in _COMPLETENESS + ("title",):
                if not p.get(f) and m.get(f):
                    p[f] = m[f]
        richest = max((g for m in members for g in (m.get("gallery") or [], m.get("images") or [])), key=len)
        if len(richest) > len(p.get("images") or []):
            p["images"] = richest  # e.g. the full SUUMO gallery
        p.pop("gallery", None)
        if p.get("price_yen") is None:
            # no price, or "da trattare" (応相談): not shown. Kept in the archive so the page isn't re-read daily.
            prices = [m["price_yen"] for m in members if m.get("price_yen") is not None]
            if not prices:
                continue
            p["price_yen"] = prices[0]
        for f in ("building_m2", "land_m2"):
            if p.get(f) is not None and p[f] < 5:
                p[f] = None  # '0㎡'/'1㎡' placeholders
        if p["price_yen"] == 0 and not (p.get("building_m2") or p.get("land_m2")):
            continue  # '0円' on a portal/link page, not a real free house
        p["images"] = [u for u in (p.get("images") or []) if not TRACKER.search(u) and u not in shared]
        if max_yen and p["price_yen"] > max_yen:
            continue  # above the archive ceiling (it may have been lowered after the listing was stored)
        ex = [m.get("extra") or {} for m in members]
        p["tenant"] = any(e.get("tenant") for e in ex) or bool(p.get("yield_pct"))
        p["no_rebuild"] = any(e.get("no_rebuild") for e in ex)
        p["id"] = gid
        p["links"] = [{"source": m["source"], "url": m["url"]} for m in members]
        p["keys"] = [m["key"] for m in members]
        p["first_seen"] = min(m.get("first_seen", today()) for m in members)
        p["price_aud"] = round(p["price_yen"] * aud_per_jpy) if p.get("price_yen") is not None else None
        p["active"] = any(m.get("active", True) for m in members)
        for drop in ("key", "source_id", "last_seen"):
            p.pop(drop, None)
        props.append(p)
    props.sort(key=lambda p: p["first_seen"], reverse=True)
    return {
        "generated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes"),
        "aud_per_jpy": aud_per_jpy,
        "count": len(props),
        "properties": props,
    }
