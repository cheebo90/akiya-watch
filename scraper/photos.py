"""Photos that have no web address of their own (cut out of akiya-bank PDF sheets).

They are stored next to the app, encrypted like the data (AES-256-GCM, key from AKIYA_PASSPHRASE with a
fixed salt, so the app derives it once): file = 12-byte IV + ciphertext of a WebP image.
Listings reference them as "enc:p/<name>.bin"; the app fetches and decrypts them on display.
"""
from __future__ import annotations

import hashlib
import io
import os
from functools import lru_cache
from pathlib import Path

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from .common import log

SALT = b"akiya-watch-photos-v1"
ITER = 250_000
OUT = Path(__file__).resolve().parent.parent / "data" / "photos"
MAX_PHOTOS = 4
MAX_SIDE = 1280


@lru_cache(maxsize=2)
def _key(passphrase: str) -> bytes:
    return PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=SALT, iterations=ITER).derive(passphrase.encode())


def encrypt_bytes(data: bytes, passphrase: str) -> bytes:
    iv = os.urandom(12)
    return iv + AESGCM(_key(passphrase)).encrypt(iv, data, None)


def decrypt_bytes(blob: bytes, passphrase: str) -> bytes:
    return AESGCM(_key(passphrase)).decrypt(blob[:12], blob[12:], None)


def _webp(img) -> bytes:
    img = img.convert("RGB")
    img.thumbnail((MAX_SIDE, MAX_SIDE))
    buf = io.BytesIO()
    img.save(buf, "WEBP", quality=70, method=4)
    return buf.getvalue()


def from_pdf(data: bytes) -> list[bytes]:
    """Photos in a PDF sheet (embedded images, cut from the rendered page); if none, a preview of page 1."""
    import pdfplumber
    import pypdfium2 as pdfium

    out, scale = [], 2.0
    try:
        doc = pdfium.PdfDocument(data)
        with pdfplumber.open(io.BytesIO(data)) as pl:
            for pno, page in enumerate(pl.pages[:3]):
                boxes = []
                for im in page.images:
                    x0, top, x1, bottom = im["x0"], im["top"], im["x1"], im["bottom"]
                    w, h = x1 - x0, bottom - top
                    if w < 90 or h < 70 or w * h < 12000 or not (0.4 < w / h < 2.6):
                        continue  # logos, icons, stamps, thin banners
                    if any(abs(x0 - b[0]) < 5 and abs(top - b[1]) < 5 for b in boxes):
                        continue
                    boxes.append((x0, top, x1, bottom))
                if not boxes:
                    continue
                bmp = doc[pno].render(scale=scale).to_pil()
                for x0, top, x1, bottom in boxes:
                    if len(out) >= MAX_PHOTOS:
                        break
                    crop = bmp.crop((max(0, int(x0 * scale)), max(0, int(top * scale)),
                                     int(x1 * scale), int(bottom * scale)))
                    out.append(_webp(crop))
        if not out and len(doc):
            out.append(_webp(doc[0].render(scale=1.6).to_pil()))  # the sheet itself as a preview
    except Exception as e:  # noqa: BLE001
        log.warning("pdf photos failed: %s", e)
    return out[:MAX_PHOTOS]


def save(images: list[bytes], key: str, passphrase: str) -> list[str]:
    """Encrypt and write images; returns the references to put in listing.images."""
    OUT.mkdir(parents=True, exist_ok=True)
    refs = []
    for i, data in enumerate(images):
        name = hashlib.sha1(f"{key}#{i}".encode()).hexdigest()[:16]
        (OUT / f"{name}.bin").write_bytes(encrypt_bytes(data, passphrase))
        refs.append(f"enc:p/{name}.bin")
    return refs


def referenced(listings) -> set[str]:
    """File names (x.bin) still used by stored listings."""
    return {u.split("/")[-1] for l in listings for u in (l.get("images") or []) if u.startswith("enc:")}
