"""Japanese -> romaji for the app's previews (addresses, stations, titles). Simplified Hepburn: Tokyo, Kyushu, Ito."""
from __future__ import annotations

import re
from functools import lru_cache

from .prefectures import PREFECTURES

try:
    import pykakasi
    _K = pykakasi.kakasi()
except ImportError:  # pragma: no cover  (romaji is a nice-to-have: never break a run for it)
    _K = None

_PREF = sorted(((ja, en) for _, en, ja, _ in PREFECTURES), key=lambda x: -len(x[0]))
_SUF = {"郡": "gun", "市": "shi", "区": "ku", "町": "machi", "村": "mura"}
_UNIT = re.compile(r"(.+?郡|.+?市|.+?区|.+?町|.+?村)")
_JA = re.compile(r"[぀-ヿ㐀-鿿]")


@lru_cache(maxsize=50000)
def plain(t: str) -> str:
    if not t or not _K or not _JA.search(t):
        return t or ""
    s = " ".join(x["hepburn"] for x in _K.convert(t))
    s = s.replace("ou", "o").replace("uu", "u").replace("oo", "o")
    s = re.sub(r"\s+([,.)」』])", r"\1", s)
    return re.sub(r"\s+", " ", s).strip()


def _word(t: str) -> str:
    return plain(t).replace(" ", "").replace("-", "").capitalize()


@lru_cache(maxsize=50000)
def address(a: str) -> str:
    """'静岡県伊東市川奈' -> 'Shizuoka, Ito-shi, Kawana'."""
    if not a or not _JA.search(a):
        return a or ""
    out, rest = [], a.strip()
    for ja, en in _PREF:
        if rest.startswith(ja):
            out.append(en)
            rest = rest[len(ja):]
            break
    while rest:
        m = _UNIT.match(rest)
        if m and len(m.group(0)) <= 6:
            u = m.group(0)
            rest = rest[len(u):]
            out.append(_word(u[:-1]) + "-" + _SUF[u[-1]])
            continue
        tail = re.sub(r"^(大字|字)", "", rest)
        tail = re.sub(r"(\d+)丁目", r" \1-chome ", tail)
        tail = re.sub(r"(\d+)番(地)?", r" \1-", tail)
        tail = re.sub(r"(\d+)号", r"\1", tail)
        out.append(" ".join(w if not _JA.search(w) else _word(w) for w in re.split(r"(\d[\d\-]*-?|\s+)", tail) if w and w.strip()).strip(" -"))
        break
    res = ", ".join(x for x in out if x)
    return re.sub(r"(\d)-\s+chome", r"\1-chome", res)


@lru_cache(maxsize=50000)
def access(a: str) -> str:
    """'伊豆急行「川奈」徒歩10分' -> 'Izukyuko "Kawana" 10′ a piedi'."""
    if not a or not _JA.search(a):
        return a or ""
    s = re.sub(r"「([^」]+)」", lambda m: f' "{_word(m.group(1))}" ', a)
    s = re.sub(r"徒歩\s*(\d+)\s*分", r" \1′ a piedi ", s)
    s = re.sub(r"(車|自動車)\s*(\d+)\s*分", r" \2′ in auto ", s)
    s = re.sub(r"バス\s*(\d+)\s*分", r" bus \1′ ", s)
    s = s.replace("駅", " ")
    parts = re.split(r'("[^"]*"|\d+′ [a-z ]+|bus \d+′)', s)
    out = " ".join(p.strip() if (p.startswith('"') or "′" in p) else " ".join(w.capitalize() if w.islower() else w for w in plain(p).split()) for p in parts if p.strip())
    return re.sub(r"\s+", " ", out).strip()


@lru_cache(maxsize=50000)
def title(t: str) -> str:
    r = plain(t)
    return r[:1].upper() + r[1:] if r else r
