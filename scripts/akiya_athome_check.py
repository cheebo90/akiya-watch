"""One-off check of the national akiya bank run by At Home (akiya-athome.jp): robots.txt, terms, anti-bot.
Writes inspect-athome.yml (status codes, robots rules, terms clauses: no listing data)."""
from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import urljoin

import requests
import yaml
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from scraper.census import TERMS_BAN, TERMS_LINK  # noqa: E402
from scraper.common import norm  # noqa: E402

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36",
      "Accept-Language": "ja,en;q=0.8"}
s = requests.Session(); s.headers.update(UA)
out = {}


def get(u):
    try:
        r = s.get(u, timeout=20)
        txt = r.text
        return {"status": r.status_code, "len": len(txt), "final": r.url,
                "challenge": bool(re.search(r"(awswaf|challenge|captcha|認証中|Just a moment)", txt[:5000], re.I)),
                "title": norm(BeautifulSoup(txt, "lxml").title.get_text()) if "<title" in txt else ""}, txt
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)[:120]}, ""


for name, u in [("robots", "https://www.akiya-athome.jp/robots.txt"),
                ("robots_amami", "https://amami-c46222.akiya-athome.jp/robots.txt")]:
    info, txt = get(u)
    info["text"] = txt[:1500]
    out[name] = info
import time
for name, u in [("top", "https://www.akiya-athome.jp/"),
                ("amami_list", "https://amami-c46222.akiya-athome.jp/bukken/search/list/?search_type=area&br_kbn=buy"),
                ("amami_home", "https://amami-c46222.akiya-athome.jp/")]:
    time.sleep(8)
    info, txt = get(u)
    if txt:
        soup = BeautifulSoup(txt, "lxml")
        info["links_sample"] = sorted({re.sub(r"\d+", "N", urljoin(u, a["href"]).split("?")[0]) for a in soup.find_all("a", href=True)})[:60]
        if name == "top":
            terms = [urljoin(u, a["href"]) for a in soup.find_all("a", href=True) if TERMS_LINK.search(a.get_text()) or "規約" in a.get_text()]
            info["terms_links"] = terms[:6]
            for t in terms[:3]:
                time.sleep(8)
                ti, tt = get(t)
                text = norm(BeautifulSoup(tt, "lxml").get_text(" ")) if tt else ""
                ti["ban"] = [text[max(0, m.start() - 80): m.end() + 80] for m in TERMS_BAN.finditer(text)][:3]
                ti["mentions"] = [text[max(0, m.start() - 80): m.end() + 120] for m in
                                  re.finditer(r"(複製|転載|転用|二次利用|収集|ロボット|クローラ|スクレイピング)", text)][:8]
                out[f"terms {t}"] = ti
    out[name] = info
(ROOT / "inspect-athome.yml").write_text(yaml.safe_dump(out, allow_unicode=True, sort_keys=False, width=200), encoding="utf-8")
