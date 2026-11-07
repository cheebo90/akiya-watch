"""Why isn't a listing in the app? Reads the live page and the archive entry (only for the given URLs)."""
from __future__ import annotations
import json, os, re, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from bs4 import BeautifulSoup  # noqa: E402
from scraper import store  # noqa: E402
from scraper.common import Http  # noqa: E402

urls = json.loads((ROOT / "trigger/inspect.json").read_text())["urls"]
state = store.load_state(ROOT / "data/state.enc", os.environ["AKIYA_PASSPHRASE"])
http = Http(delay=2.0, max_requests=10, timeout=30, retries=1)
for u in urls:
    nc = re.search(r"nc_(\d+)", u)
    hits = [l for l in state["listings"].values() if u.rstrip("/") in l.get("url", "") or (nc and nc.group(1) in l.get("url", ""))]
    lines = [u]
    for l in hits:
        lines.append("ARCHIVIO: " + json.dumps({k: l.get(k) for k in ("key", "source", "type", "price_yen", "address", "latlng",
                     "active", "first_seen", "last_seen", "building_m2", "land_m2")}, ensure_ascii=False))
    if not hits:
        lines.append("ARCHIVIO: non presente")
    html = http.get(u) or ""
    soup = BeautifulSoup(html, "lxml")
    txt = re.sub(r"\s+", " ", soup.get_text(" "))
    for lab in ("価格", "所在地", "土地面積", "建物面積", "間取り", "完成時期", "沿線・駅", "情報提供日", "次回更新"):
        m = re.search(lab + r"[^ ]{0,6} (.{1,60}?)(?= [^ ]{2,8}(?:\[|：| ヒント))", txt)
        if m:
            lines.append(f"{lab}: {m.group(1)}")
    lines.append("pagina: " + (txt[txt.find("価格"):txt.find("価格") + 300] if "価格" in txt else txt[:300]))
    print("::notice::" + " %0A".join(lines))
