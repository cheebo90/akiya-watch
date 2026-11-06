"""How many 'pdf' akiya banks publish readable (text) property sheets? Writes pdfprobe-{part}.yml."""
from __future__ import annotations

import argparse
import logging
import sys
from collections import Counter
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from scraper.common import Http  # noqa: E402
from scraper.sources import akiyabank as ab, akiyapdf  # noqa: E402


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--part", default="1/1")
    a = ap.parse_args()
    i, n = map(int, a.part.split("/"))
    census = yaml.safe_load((ROOT / "census.yml").read_text(encoding="utf-8"))["sites"]
    sites = [s for s in census if s["status"] in ("pdf", "todo")][i - 1::n]
    http = Http(delay=1.5, max_requests=8000, timeout=20, retries=1)
    robots = ab.Robots(http)
    out = []
    for k, s in enumerate(sites, 1):
        rep = {"id": s["id"], "prefecture": s["prefecture"], "status": s["status"], "list": s["list"]}
        try:
            if not robots.allowed(s["list"]):
                rep["result"] = "robots"
            else:
                html = http.get(s["list"])
                links = akiyapdf.pdf_links(html, s["list"]) if html else []
                rep["pdfs"] = len(links)
                reads = []
                for u, t in links[:3]:
                    if not robots.allowed(u):
                        continue
                    r = http.s.get(u, timeout=30)
                    if r.status_code != 200 or not r.content.startswith(b"%PDF"):
                        reads.append({"url": u, "result": f"http {r.status_code}"})
                        continue
                    l, why = akiyapdf.parse_pdf(r.content, u, s)
                    d = {"url": u, "text": t, "result": why}
                    if l:
                        d.update(price=l.price_yen, building_m2=l.building_m2, land_m2=l.land_m2,
                                 address=(l.address or "")[:30], title=l.title[:30])
                    reads.append(d)
                rep["reads"] = reads
                c = Counter(r["result"] for r in reads)
                rep["result"] = "ok" if c["ok"] >= 2 or (c["ok"] == 1 and len(reads) == 1) else \
                    ("scanned" if c["scanned"] >= 2 else ("no pdf" if not links else "partial" if c["ok"] else "no fields"))
        except Exception as e:  # noqa: BLE001
            rep["result"] = f"error {e}"[:100]
        http.blocked = 0
        out.append(rep)
        logging.info("%d/%d %s -> %s", k, len(sites), s["id"], rep.get("result"))
    (ROOT / f"pdfprobe-{i}.yml").write_text(yaml.safe_dump({"sites": out}, allow_unicode=True, sort_keys=False, width=200),
                                           encoding="utf-8")


if __name__ == "__main__":
    main()
