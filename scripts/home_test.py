"""Quick test from a home connection: can athome and LIFULL be read at a gentle pace?

  python scripts/home_test.py

Reads at most 10 list pages per site (athome: one every ~15 s, LIFULL: one every ~5 s) and stops at the
first verification / bot-protection page. Prints a summary; saves nothing.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scraper.common import Blocked, Http  # noqa: E402
from scraper.sources import athome, lifull  # noqa: E402

PREFS = ["oita", "kumamoto", "miyazaki", "kagoshima", "fukuoka"]


def test_athome():
    http = Http(delay=15.0, max_requests=10)
    got, pages = 0, 0
    try:
        for pref in PREFS:
            for page in (1, 2):
                html = http.get(athome.list_url("kodate/chuko", pref, page, 1500))
                pages += 1
                if not html:
                    print(f"  athome {pref} p{page}: nessuna risposta")
                    continue
                if athome.is_challenge(html):
                    raise Blocked("pagina di verifica 認証中")
                n = len(athome.parse_list(html, "kodate/chuko", pref))
                got += n
                print(f"  athome {pref} p{page}: {n} annunci")
    except Blocked as e:
        print(f"  athome BLOCCATA dopo {pages} pagine: {e}")
        return False
    except Exception as e:  # noqa: BLE001
        print(f"  athome: fine anticipata ({e.__class__.__name__})")
    print(f"  athome OK: {got} annunci in {pages} pagine")
    return True


def test_lifull():
    http = Http(delay=5.0, max_requests=10)
    got, pages = 0, 0
    try:
        for pref in PREFS:
            for page in (1, 2):
                html = http.get(lifull.list_url(pref, page))
                pages += 1
                if not html:
                    print(f"  lifull {pref} p{page}: nessuna risposta o fine elenco")
                    break
                n = len(lifull.parse_list(html, pref))
                got += n
                print(f"  lifull {pref} p{page}: {n} annunci")
    except Blocked as e:
        print(f"  LIFULL BLOCCATA dopo {pages} pagine: {e}")
        return False
    except Exception as e:  # noqa: BLE001
        print(f"  lifull: fine anticipata ({e.__class__.__name__})")
    print(f"  LIFULL OK: {got} annunci in {pages} pagine")
    return True


if __name__ == "__main__":
    t0 = time.time()
    print("Test athome (una pagina ogni ~15 s)…")
    a = test_athome()
    print("Test LIFULL (una pagina ogni ~5 s)…")
    l = test_lifull()
    print(f"\nRisultato: athome {'OK' if a else 'bloccata'}, LIFULL {'OK' if l else 'bloccata'} "
          f"({(time.time() - t0) / 60:.1f} min)")
