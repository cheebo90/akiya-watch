"""Alerts: match new listings against the filters in config.yml, then push (ntfy) and/or email digest."""
from __future__ import annotations

import os
import smtplib
from email.mime.text import MIMEText
from html import escape

import requests

from .common import log
from .prefectures import BY_SLUG

TYPE_IT = {"house": "Casa", "apartment": "Appartamento", "land": "Terreno", "akiya": "Akiya",
           "building": "Edificio intero", "commercial": "Commerciale"}


def matches(l: dict, f: dict, aud_per_jpy: float) -> bool:
    if not l.get("price_yen"):
        return False
    aud = l["price_yen"] * aud_per_jpy
    if f.get("max_price_aud") and aud > f["max_price_aud"]:
        return False
    if f.get("min_price_aud") and aud < f["min_price_aud"]:
        return False
    types = f.get("types") or []
    ltype = "house" if l["type"] == "akiya" else l["type"]
    if types and ltype not in types and l["type"] not in types:
        return False
    if f.get("prefectures") and l.get("prefecture") not in f["prefectures"]:
        return False
    if f.get("min_building_m2") and (l.get("building_m2") or 0) < f["min_building_m2"]:
        return False
    if f.get("min_land_m2") and (l.get("land_m2") or 0) < f["min_land_m2"]:
        return False
    if f.get("max_walk_min") and (l.get("walk_min") is None or l["walk_min"] > f["max_walk_min"]):
        return False
    if f.get("built_after") and (l.get("year_built") or 0) < f["built_after"]:
        return False
    if f.get("min_yield_pct") and (l.get("yield_pct") or 0) < f["min_yield_pct"]:
        return False
    if f.get("new_build") is not None and bool(l.get("new_build")) != bool(f["new_build"]):
        return False
    return True


def describe(l: dict, aud_per_jpy: float) -> str:
    pref = BY_SLUG.get(l.get("prefecture"), (None, l.get("prefecture", "")))[1]
    bits = [f"A${l['price_yen'] * aud_per_jpy:,.0f} (¥{l['price_yen']:,})", TYPE_IT.get(l["type"], l["type"]), pref]
    if l.get("building_m2"):
        bits.append(f"{l['building_m2']:.0f} m² casa")
    if l.get("land_m2"):
        bits.append(f"{l['land_m2']:.0f} m² terreno")
    if l.get("year_built"):
        bits.append(f"anno {l['year_built']}")
    if l.get("walk_min") is not None:
        bits.append(f"{l['walk_min']} min a piedi dalla stazione")
    if l.get("yield_pct"):
        bits.append(f"rendimento dichiarato {l['yield_pct']:.1f}%")
    if l.get("new_build"):
        bits.append("nuova costruzione")
    return " · ".join(bits)


def ntfy(topic: str, title: str, body: str, click: str | None = None, server: str = "https://ntfy.sh"):
    headers = {"Title": title.encode("utf-8"), "Tags": "house"}
    if click:
        headers["Click"] = click
    try:
        requests.post(f"{server}/{topic}", data=body.encode("utf-8"), headers=headers, timeout=20)
    except requests.RequestException as e:
        log.warning("ntfy failed: %s", e)


def email(subject: str, html: str):
    user, pw, to = os.getenv("SMTP_USER"), os.getenv("SMTP_PASS"), os.getenv("EMAIL_TO")
    if not (user and pw and to):
        return False
    msg = MIMEText(html, "html", "utf-8")
    msg["Subject"], msg["From"], msg["To"] = subject, user, to
    host = os.getenv("SMTP_HOST", "smtp.gmail.com")
    with smtplib.SMTP_SSL(host, int(os.getenv("SMTP_PORT", "465"))) as s:
        s.login(user, pw)
        s.send_message(msg)
    return True


def send(new: list[dict], cfg: dict, aud_per_jpy: float, app_url: str | None, warnings: list[str]):
    topic = os.getenv("NTFY_TOPIC")
    alerts = cfg.get("alerts") or []
    max_push = int(cfg.get("max_push_per_run", 15))
    hits: list[tuple[str, dict]] = []
    for l in new:
        for f in alerts:
            if matches(l, f, aud_per_jpy):
                hits.append((f.get("name", "Avviso"), l))
                break
    log.info("%d new listings, %d match alert filters", len(new), len(hits))

    if topic:
        for name, l in hits[:max_push]:
            link = f"{app_url}#/p/{l['key']}" if app_url else l["url"]
            ntfy(topic, f"🏠 {name}", describe(l, aud_per_jpy) + "\n" + (l.get("address") or ""), click=link)
        if len(hits) > max_push:
            ntfy(topic, "Altri annunci nuovi", f"+{len(hits) - max_push} annunci che rispettano i tuoi filtri. Aprili nell'app.",
                 click=app_url)
        for w in warnings:
            ntfy(topic, "⚠️ akiya-watch", w)

    if hits and cfg.get("email_digest", True):
        rows = "".join(
            f"<tr><td style='padding:8px 0;border-bottom:1px solid #eee'><b>{escape(n)}</b><br>"
            f"{escape(describe(l, aud_per_jpy))}<br><span style='color:#666'>{escape(l.get('address',''))}</span><br>"
            f"<a href='{escape(l['url'])}'>Annuncio originale ({l['source']})</a></td></tr>"
            for n, l in hits)
        extra = "".join(f"<p style='color:#a00'>⚠️ {escape(w)}</p>" for w in warnings)
        app = f"<p><a href='{escape(app_url)}'>Apri l'app</a></p>" if app_url else ""
        html = f"<h2>{len(hits)} nuovi annunci per te</h2>{app}{extra}<table>{rows}</table>"
        if email(f"akiya-watch: {len(hits)} nuovi annunci", html):
            log.info("email digest sent")
    return hits
