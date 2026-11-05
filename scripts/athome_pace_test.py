"""One-off test: does athome still show its verification page at a much slower pace?

  python scripts/athome_pace_test.py --delay 60 --pages 12

Reads at most --pages list pages (used houses, Kyushu prefectures), one every --delay seconds, and stops at the
first verification page. Prints the result as a GitHub annotation so it is visible without the log. Saves nothing.
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scraper.common import Http  # noqa: E402
from scraper.sources import athome  # noqa: E402

PREFS = ["oita", "kumamoto", "miyazaki", "kagoshima", "fukuoka", "nagasaki", "saga"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--delay", type=float, required=True)
    ap.add_argument("--pages", type=int, default=10)
    a = ap.parse_args()
    http = Http(delay=a.delay, max_requests=a.pages, retries=1)
    http.delay = a.delay
    urls = [athome.list_url("kodate/chuko", p, n, 1500) for p in PREFS for n in (1, 2)][: a.pages]
    got, t0 = 0, time.time()
    for i, u in enumerate(urls, 1):
        html = http.get(u)
        if html is None:
            print(f"::notice::athome {a.delay:.0f}s: pagina {i} senza risposta (status non 200)")
            break
        if athome.is_challenge(html):
            print(f"::notice::athome {a.delay:.0f}s: BLOCCATA alla pagina {i} dopo {(time.time()-t0)/60:.0f} min "
                  f"({got} annunci letti prima)")
            return
        n = len(athome.parse_list(html, "kodate/chuko", u.split("/")[5]))
        got += n
        print(f"pagina {i}: {n} annunci", flush=True)
    print(f"::notice::athome {a.delay:.0f}s: NESSUN BLOCCO su {len(urls)} pagine in {(time.time()-t0)/60:.0f} min "
          f"({got} annunci)")


if __name__ == "__main__":
    main()
