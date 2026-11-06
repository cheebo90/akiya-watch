"""Entry point.

  python -m scraper.run scrape --source athome     # read one source -> data/raw-athome.enc
  python -m scraper.run merge                      # merge raw files into state, geocode, alert, export
  python -m scraper.run all                        # both, sequentially (for running on your own computer)

Needs the AKIYA_PASSPHRASE environment variable (and optionally NTFY_TOPIC, SMTP_*, EMAIL_TO, APP_URL).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import os
import sys
import time
from pathlib import Path

import yaml

from . import fx, geo, notify, store
from .common import Blocked, BudgetExceeded, Http, log
from .prefectures import select
from . import photos
from .sources import akiyabank, athome, lifull, suumo, yahoo

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
STATE = DATA / "state.enc"
SOURCES = ("lifull", "athome", "suumo", "akiyabank", "yahoo")


def load_cfg() -> dict:
    return yaml.safe_load((ROOT / "config.yml").read_text(encoding="utf-8"))


def load_sites(jp: bool = False) -> list[dict]:
    """Hand-curated sites (akiyabanks.yml) first, then the ones the monthly census found working."""
    sites = [] if jp else yaml.safe_load((ROOT / "akiyabanks.yml").read_text(encoding="utf-8"))["sites"]
    census = ROOT / "census.yml"
    if census.exists():
        known = {u for s in sites for u in akiyabank.as_list(s["list"])}
        for e in (yaml.safe_load(census.read_text(encoding="utf-8")) or {}).get("sites", []):
            if e.get("status") == "ok" and e["list"] not in known and bool(e.get("needs_jp")) == jp:
                sites.append({**e, "max_pages": 1})
    return sites


def passphrase() -> str:
    p = os.getenv("AKIYA_PASSPHRASE")
    if not p:
        sys.exit("AKIYA_PASSPHRASE non impostata")
    return p


def max_price_yen(cfg: dict, rate_jpy_per_aud: float) -> int:
    """Archive ceiling: `max_price_yen` if set, otherwise the AUD budget converted."""
    return int(cfg.get("max_price_yen") or cfg["budget_aud"] * rate_jpy_per_aud)


def max_man(cfg: dict, rate_jpy_per_aud: float) -> int:
    """Archive ceiling in 万円, rounded up to the next 500万 step used by the portals' price filters."""
    man = max_price_yen(cfg, rate_jpy_per_aud) // 10_000 + (1 if max_price_yen(cfg, rate_jpy_per_aud) % 10_000 else 0)
    return ((man + 499) // 500) * 500


def cmd_scrape(source: str, cfg: dict, pw: str, part: str = "1/1"):
    scfg = cfg["sources"][source]
    i, n = (int(x) for x in part.split("/"))
    out = DATA / f"raw-{source}-{i}.enc"
    if not scfg.get("enabled", True):
        log.info("%s disabled", source)
        store.save_encrypted({"source": source, "completed": False, "listings": [], "skipped": True}, out, pw)
        return
    http = Http(delay=float(scfg.get("request_delay_sec", cfg.get("request_delay_sec", 2.0))),
                max_requests=int(cfg.get("max_requests_per_run", 9000)))
    state = store.load_state(STATE, pw)
    rate = fx.aud_to_jpy(http, state.get("fx_aud_jpy"))
    mm = max_man(cfg, rate)
    cap = max_price_yen(cfg, rate)
    all_prefs = select(cfg.get("prefectures"))
    prefs = all_prefs[i - 1::n]  # a part = every n-th prefecture (yahoo: every n-th page instead)
    known = {k for k in state["listings"] if k.startswith(source + ":")}
    log.info("%s: %d prefectures, max %d万円", source, len(prefs), mm)

    if source == "lifull":
        gen = lifull.scrape(http, prefs, known)
    elif source == "athome":
        gen = athome.scrape(http, prefs, scfg.get("categories", list(athome.CATEGORIES)), mm)
    elif source == "yahoo":
        gen = yahoo.scrape(http, scfg.get("categories", list(yahoo.CATEGORIES)), all_prefs, (i, n))
    elif source == "suumo":
        gen = suumo.scrape(http, prefs, scfg.get("categories", list(suumo.CATEGORIES)), mm)
    else:
        sites = load_sites()
        urls = {l["url"] for l in state["listings"].values() if l["source"] == "akiyabank"}
        gen = akiyabank.scrape(http, sites, prefs, urls)

    listings, completed, blocked, t0 = {}, True, None, time.time()
    try:
        for l in gen:
            if l.price_yen and l.price_yen > cap:
                continue  # portals round the price filter up (and some show "related" listings): enforce the ceiling
            listings[l.key] = l.to_dict()
    except BudgetExceeded:
        completed = False
        log.warning("%s: request budget reached, run incomplete", source)
    except Blocked as e:
        completed = False
        blocked = str(e)
        log.warning("%s: blocked by the site's bot protection (%s); stopped", source, e)
    log.info("%s: %d listings, %d requests, %d errors, %.0f min",
             source, len(listings), http.count, http.errors, (time.time() - t0) / 60)
    # A run with many failed requests is treated as incomplete so nothing gets marked as sold.
    if http.count and http.errors / http.count > 0.2:
        completed = False
    if source == "akiyabank":
        completed = False  # many small sites: a listing goes inactive only after a week unseen (see merge)
    store.save_encrypted({"source": source, "completed": completed, "listings": list(listings.values()),
                          "requests": http.count, "errors": http.errors, "rate": rate,
                          "blocked": blocked}, out, pw)


def full_gallery(http: Http, targets: list[dict], listings: dict, limit: int):
    """Open the listing page (SUUMO or Yahoo) of listings that triggered an alert and keep their whole photo gallery."""
    done = 0
    page = Http(delay=2.0, max_requests=limit, retries=2)
    for l in targets:
        if done >= limit:
            break
        if l["source"] not in ("suumo", "yahoo"):
            continue
        try:
            html = page.get(l["url"])
        except Exception:  # noqa: BLE001  budget reached / blocked: stop quietly
            break
        done += 1
        if not html:
            continue
        imgs = suumo.parse_detail_images(html) if l["source"] == "suumo" else \
            yahoo.parse_detail_images(html, l.get("images") or [])
        if len(imgs) > len(l.get("images") or []):
            l["images"] = imgs
            listings[l["key"]]["images"] = imgs
    log.info("full gallery fetched for %d alert listings", done)


def cmd_merge(cfg: dict, pw: str):
    state = store.load_state(STATE, pw)
    http = Http(delay=0.0)
    rate = fx.aud_to_jpy(http, state.get("fx_aud_jpy"))
    state["fx_aud_jpy"] = rate
    aud_per_jpy = 1 / rate
    prev_counts = {s: sum(1 for l in state["listings"].values() if l["source"] == s and l.get("active", True))
                   for s in SOURCES}
    warnings, new_keys, summary, quiet = [], [], {}, set()
    for s in SOURCES:
        files = sorted(DATA.glob(f"raw-{s}-*.enc")) + sorted(DATA.glob(f"raw-{s}.enc"))  # also the old single-file name
        if not files:
            expected = [x for x in os.getenv("EXPECT_SOURCES", "").split(",") if x]
            if s in expected and cfg["sources"].get(s, {}).get("enabled", False):
                warnings.append(f"Nessun dato da {s} in questo giro.")
            continue
        parts = [store.decrypt(json.loads(f.read_text()), pw) for f in files]
        for f in files:
            f.unlink()
        if all(p.get("skipped") for p in parts):
            continue
        raw = {"listings": [l for p in parts for l in p.get("listings", [])],
               "requests": sum(p.get("requests") or 0 for p in parts),
               "errors": sum(p.get("errors") or 0 for p in parts),
               "completed": all(p.get("completed") for p in parts),
               "blocked": "; ".join(p["blocked"] for p in parts if p.get("blocked")) or None}
        items = raw["listings"]
        summary[s] = {"found": len(items), "requests": raw.get("requests"), "errors": raw.get("errors"),
                      "completed": raw.get("completed"), "blocked": raw.get("blocked")}
        if raw.get("blocked"):
            warnings.append(f"{s}: il sito ha attivato la protezione anti-bot, lettura interrotta "
                            f"({len(items)} annunci letti prima del blocco).")
        # Sudden collapse => probably blocked; don't touch existing data.
        if prev_counts[s] > 50 and len(items) < prev_counts[s] * 0.3:
            warnings.append(f"{s}: trovati solo {len(items)} annunci (prima {prev_counts[s]}). "
                            f"Forse il sito blocca lo script: i dati vecchi sono stati mantenuti.")
            raw["completed"] = False
        added = store.merge(state, items)
        new_keys += added
        if prev_counts.get(s, 0) == 0 and added:
            quiet |= set(added)  # first time we read this source: everything is "new", don't alert
        store.mark_inactive(state, s, {i["key"] for i in items}, bool(raw.get("completed")))

    # sources switched off in config.yml: their leftover listings are hidden (kept only in favourites)
    off = {s for s in SOURCES if not cfg["sources"].get(s, {}).get("enabled", True)}
    for l in state["listings"].values():
        if l["source"] in off:
            l["active"] = False
    week_ago = (dt.date.today() - dt.timedelta(days=7)).isoformat()
    for l in state["listings"].values():
        if l["source"] == "akiyabank" and l.get("last_seen", "") < week_ago:
            l["active"] = False

    first_run = not state.get("runs")
    try:
        geocoded = geo.fill(http, state["listings"], state["geocache"])
    except Exception:  # noqa: BLE001  never lose a merge because of the map
        log.exception("geocoding failed, continuing without it")
        geocoded = 0
    new = [state["listings"][k] for k in new_keys if k not in quiet]
    if first_run:
        log.info("first run: %d listings stored, alerts skipped (everything would be 'new')", len(new))
        if os.getenv("NTFY_TOPIC"):
            notify.ntfy(os.environ["NTFY_TOPIC"], "akiya-watch è attivo",
                        f"Primo giro completato: {len(state['listings'])} annunci in archivio. "
                        "Da domani ti avviso solo per quelli nuovi.", click=os.getenv("APP_URL"))
    else:
        try:
            hits = notify.select(new, cfg, aud_per_jpy)
            full_gallery(http, [l for _, l in hits], state["listings"], int(cfg.get("full_gallery_per_run", 80)))
            notify.send(new, cfg, aud_per_jpy, os.getenv("APP_URL"), warnings, hits=hits)
        except Exception:  # noqa: BLE001
            log.exception("alerts failed, continuing")

    state["runs"] = (state.get("runs") or [])[-60:] + [{
        "at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes"),
        "new": len(new), "geocoded": geocoded, "sources": summary, "warnings": warnings}]
    store.save_encrypted(state, STATE, pw)
    # photos cut from PDFs still used by stored listings: the workflow deletes the others
    (DATA / "photos-keep.txt").write_text("\n".join(sorted(photos.referenced(state["listings"].values()))))
    exp = store.export(state, aud_per_jpy)
    exp["runs"] = state["runs"][-10:]
    exp["new_keys"] = new_keys
    out = ROOT / "web" / "data.enc"
    store.save_encrypted(exp, out, pw)
    log.info("exported %d properties (%d listings) -> %s", exp["count"], len(state["listings"]), out)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sc = sub.add_parser("scrape")
    sc.add_argument("--source", choices=SOURCES, required=True)
    sc.add_argument("--part", default="1/1", help="i/n: read every n-th prefecture starting from the i-th")
    sub.add_parser("merge")
    sub.add_parser("all")
    a = ap.parse_args()
    cfg, pw = load_cfg(), passphrase()
    if a.cmd == "scrape":
        cmd_scrape(a.source, cfg, pw, a.part)
    elif a.cmd == "merge":
        cmd_merge(cfg, pw)
    else:
        for s in SOURCES:
            cmd_scrape(s, cfg, pw)
        cmd_merge(cfg, pw)


if __name__ == "__main__":
    main()
