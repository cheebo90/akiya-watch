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
from .sources import athome, lifull, suumo

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
STATE = DATA / "state.enc"
SOURCES = ("lifull", "athome", "suumo")


def load_cfg() -> dict:
    return yaml.safe_load((ROOT / "config.yml").read_text(encoding="utf-8"))


def passphrase() -> str:
    p = os.getenv("AKIYA_PASSPHRASE")
    if not p:
        sys.exit("AKIYA_PASSPHRASE non impostata")
    return p


def max_man(cfg: dict, rate_jpy_per_aud: float) -> int:
    """Budget in 万円, rounded up to the next 500万 step used by the portals' price filters."""
    yen = cfg["budget_aud"] * rate_jpy_per_aud
    man = int(yen // 10_000) + 1
    return ((man + 499) // 500) * 500


def cmd_scrape(source: str, cfg: dict, pw: str):
    scfg = cfg["sources"][source]
    out = DATA / f"raw-{source}.enc"
    if not scfg.get("enabled", True):
        log.info("%s disabled", source)
        store.save_encrypted({"source": source, "completed": False, "listings": [], "skipped": True}, out, pw)
        return
    http = Http(delay=float(cfg.get("request_delay_sec", 2.0)), max_requests=int(cfg.get("max_requests_per_run", 9000)))
    state = store.load_state(STATE, pw)
    rate = fx.aud_to_jpy(http, state.get("fx_aud_jpy"))
    mm = max_man(cfg, rate)
    prefs = select(cfg.get("prefectures"))
    known = {k for k in state["listings"] if k.startswith(source + ":")}
    log.info("%s: %d prefectures, max %d万円", source, len(prefs), mm)

    if source == "lifull":
        gen = lifull.scrape(http, prefs, known)
    elif source == "athome":
        gen = athome.scrape(http, prefs, scfg.get("categories", list(athome.CATEGORIES)), mm)
    else:
        gen = suumo.scrape(http, prefs, scfg.get("categories", list(suumo.CATEGORIES)), mm)

    listings, completed, blocked, t0 = {}, True, None, time.time()
    try:
        for l in gen:
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
    store.save_encrypted({"source": source, "completed": completed, "listings": list(listings.values()),
                          "requests": http.count, "errors": http.errors, "rate": rate,
                          "blocked": blocked}, out, pw)


def cmd_merge(cfg: dict, pw: str):
    state = store.load_state(STATE, pw)
    http = Http(delay=0.0)
    rate = fx.aud_to_jpy(http, state.get("fx_aud_jpy"))
    state["fx_aud_jpy"] = rate
    aud_per_jpy = 1 / rate
    prev_counts = {s: sum(1 for l in state["listings"].values() if l["source"] == s and l.get("active", True))
                   for s in SOURCES}
    warnings, new_keys, summary = [], [], {}
    for s in SOURCES:
        f = DATA / f"raw-{s}.enc"
        if not f.exists():
            warnings.append(f"Nessun dato da {s} in questo giro.")
            continue
        raw = store.decrypt(json.loads(f.read_text()), pw)
        if raw.get("skipped"):
            continue
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
        new_keys += store.merge(state, items)
        store.mark_inactive(state, s, {i["key"] for i in items}, bool(raw.get("completed")))
        f.unlink()

    first_run = not state.get("runs")
    geocoded = geo.fill(http, state["listings"], state["geocache"])
    new = [state["listings"][k] for k in new_keys]
    if first_run:
        log.info("first run: %d listings stored, alerts skipped (everything would be 'new')", len(new))
        if os.getenv("NTFY_TOPIC"):
            notify.ntfy(os.environ["NTFY_TOPIC"], "akiya-watch è attivo",
                        f"Primo giro completato: {len(state['listings'])} annunci in archivio. "
                        "Da domani ti avviso solo per quelli nuovi.", click=os.getenv("APP_URL"))
    else:
        notify.send(new, cfg, aud_per_jpy, os.getenv("APP_URL"), warnings)

    state["runs"] = (state.get("runs") or [])[-60:] + [{
        "at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes"),
        "new": len(new), "geocoded": geocoded, "sources": summary, "warnings": warnings}]
    store.save_encrypted(state, STATE, pw)
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
    sub.add_parser("merge")
    sub.add_parser("all")
    a = ap.parse_args()
    cfg, pw = load_cfg(), passphrase()
    if a.cmd == "scrape":
        cmd_scrape(a.source, cfg, pw)
    elif a.cmd == "merge":
        cmd_merge(cfg, pw)
    else:
        for s in SOURCES:
            cmd_scrape(s, cfg, pw)
        cmd_merge(cfg, pw)


if __name__ == "__main__":
    main()
