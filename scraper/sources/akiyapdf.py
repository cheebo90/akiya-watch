"""Akiya banks that publish each property as a PDF sheet (物件情報 / 物件概要).

The PDF's text is turned into simple HTML (table rows -> th/td, 'ラベル 値' lines -> 'ラベル：値') and read
by the same label reader as the web pages (akiyabank.parse_detail). Scanned PDFs (images only, no text)
are skipped: we report them but don't OCR.
"""
from __future__ import annotations

import io
import re
from html import escape
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from ..common import log, norm

PROPISH = re.compile(r"(物件|No\.?\s*\d|番号|売買|売却|空き家|空家|戸建|住宅|土地|万円|\d{2,}号)")
NOT_PROP = re.compile(r"(申込|申請|様式|要綱|規則|要領|カード|チラシ|案内|パンフ|補助金|助成|制度|手引|一覧表?$|同意書|誓約|媒介|"
                      r"記載例|事例|台帳(?!登録物件)|成約|協力業者|Q&A|しくみ|計画|について|届出|^\(?(写真|画像|間取|位置図|地図|平面図|案内図)|写真\s*[\(（\[])")
LABELISH = re.compile(r"^[■●・◆□○]?([^\d\s：:]{2,10})$")
MAX_BYTES = 6_000_000


def pdf_links(html: str, base: str) -> list[tuple[str, str]]:
    soup = BeautifulSoup(html, "lxml")
    out = []
    for a in soup.find_all("a", href=True):
        u = urljoin(base, a["href"]).split("#")[0]
        if not re.search(r"\.pdf($|\?)", u, re.I):
            continue
        t = norm(a.get_text(" ") or a.get("title", ""))
        ctx = norm((a.find_parent(["li", "tr", "p", "td"]) or a).get_text(" "))[:120]
        if NOT_PROP.search(t):
            continue
        if PROPISH.search(t + " " + ctx):
            out.append((u, t[:60]))
    return list(dict.fromkeys(out))


def pdf_text(data: bytes) -> tuple[str, list[list[list[str]]]]:
    import pdfplumber
    text, tables = [], []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page in pdf.pages[:4]:
            text.append(page.extract_text() or "")
            try:
                tables += [[[norm(c or "") for c in row] for row in t] for t in page.extract_tables()]
            except Exception:  # noqa: BLE001
                pass
    return "\n".join(text), tables


def to_html(text: str, tables) -> str:
    rows = []
    for t in tables:
        for row in t:
            cells = [c for c in row if c]
            # label, value, label, value ... on one row
            for i in range(0, len(cells) - 1, 2):
                if LABELISH.match(cells[i].replace(" ", "")):
                    rows.append(f"<tr><th>{escape(cells[i])}</th><td>{escape(cells[i + 1])}</td></tr>")
    lines = []
    for ln in text.splitlines():
        ln = norm(ln)
        m = re.match(r"^([■●・◆□○]?[^\d\s：:]{2,10})[\s：:]+(.+)$", ln)
        if m and "：" not in ln and ":" not in ln:
            lines.append(f"{m.group(1)}：{m.group(2)}")
        else:
            lines.append(ln)
    title = next((l for l in lines if 3 <= len(l) <= 40), "")
    body = "\n".join(escape(l) for l in lines)
    return f"<html><body><h1>{escape(title)}</h1><table>{''.join(rows)}</table><div>{body.replace(chr(10), '<br>' + chr(10))}</div></body></html>"


def parse_pdf(data: bytes, url: str, site: dict):
    """Listing from a PDF sheet, or (None, reason)."""
    if len(data) > MAX_BYTES:
        return None, "too big"
    try:
        text, tables = pdf_text(data)
    except Exception as e:  # noqa: BLE001
        return None, f"unreadable {type(e).__name__}"
    if len(re.sub(r"\s", "", text)) < 30:
        return None, "scanned"
    html = to_html(text, tables)
    # pages are <br>-joined lines: give pairs() real line breaks
    soup_html = html.replace("<br>", "\n")
    from . import akiyabank as ab
    l = ab.parse_detail(soup_html, url, site)
    if l:
        l.extra["pdf"] = True
        l.images = []
        return l, "ok"
    return None, "no fields"
