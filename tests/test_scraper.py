from pathlib import Path

import pytest

from scraper import notify, store
from scraper.common import parse_area_m2, parse_price_yen, parse_walk_min, parse_year
from scraper.run import max_man
from scraper.sources import athome, lifull, suumo

FX = Path(__file__).parent / "fixtures"
read = lambda n: (FX / n).read_text(encoding="utf-8")


@pytest.mark.parametrize("s,v", [("8万円", 80_000), ("1,450万円", 14_500_000), ("17,800,000円", 17_800_000),
                                 ("1億2000万円", 120_000_000), ("1450万円", 14_500_000), ("", None)])
def test_price(s, v):
    assert parse_price_yen(s) == v


@pytest.mark.parametrize("s,v", [("359.10m²", 359.10), ("241.59m2（73.08坪）（登記）", 241.59), ("3,221㎡-", 3221.0),
                                 ("142.73㎡ (-)", 142.73), ("-", None)])
def test_area(s, v):
    assert parse_area_m2(s) == v


@pytest.mark.parametrize("s,v", [("1967年1月（築59年11ヶ月）", 1967), ("・平成2年築", 1990), ("昭和元年", 1926), ("-", None)])
def test_year(s, v):
    assert parse_year(s) == v


def test_walk():
    assert parse_walk_min("いすみ鉄道 西畑駅 徒歩 24分 いすみ鉄道 総元駅 徒歩 32分") == 24
    assert parse_walk_min("ＪＲ成田線 「笹川」駅 徒歩21分") == 21


def test_lifull():
    items = lifull.parse_list(read("lifull_list.html"), "chiba")
    assert [i.source_id for i in items] == ["45116", "43804"]
    a, b = items
    assert a.price_yen == 17_800_000 and a.land_m2 == 3221 and a.prefecture == "chiba"
    assert a.images[0].endswith(".jpg") and "562x418" in a.images[0]
    assert b.images == [] and b.title.startswith("田舎暮らし")
    assert lifull.has_next(read("lifull_list.html"), 2)
    d = lifull.parse_detail(read("lifull_detail.html"), a)
    assert d.building_m2 == 142.73 and d.layout == "2LDK" and d.year_built == 1990 and d.walk_min == 24
    assert d.type == "akiya" and d.extra["現況"] == "空家" and len(d.images) == 2


def test_athome():
    html = read("athome_list.html")
    [l] = athome.parse_list(html, "kodate/chuko", "chiba")
    assert l.source_id == "6991831954" and l.url == "https://www.athome.co.jp/kodate/6991831954/"
    assert l.price_yen == 80_000 and l.type == "house"
    assert l.address == "千葉県香取郡東庄町笹川ろ" and l.layout == "2DK"
    assert l.land_m2 == 359.10 and l.building_m2 == 52.06 and l.year_built == 1967 and l.walk_min == 21
    assert l.images and "/image_files/" in l.images[0]
    assert athome.has_next(html, 1) and not athome.has_next(html, 2)
    assert athome.price_code(1000) == "kp102" and athome.price_code(800) == "kp102" and athome.price_code(99999) == "kp120"


def test_suumo():
    assert suumo.parse_city_index(read("suumo_city.html"), "chukoikkodate", "chiba") == ["sc_chibashichuo", "sc_katori"]
    html = read("suumo_list.html")
    [l] = suumo.parse_list(html, "chukoikkodate", "chiba")
    assert l.source_id == "21643383" and l.price_yen == 14_500_000
    assert l.building_m2 == 111.37 and l.land_m2 == 241.59 and l.layout == "4LDK" and l.year_built == 1981
    assert l.walk_min == 20 and l.images[0].startswith("https://img01.suumo.com/")
    assert suumo.has_next(html, 1)


def test_budget_rounding():
    assert max_man({"budget_aud": 80000}, 100.0) == 1000
    assert max_man({"budget_aud": 80000}, 110.0) == 1000
    assert max_man({"budget_aud": 80000}, 130.0) == 1500
    assert max_man({"budget_aud": 80000, "max_price_yen": 13_500_000}, 111.0) == 1500
    assert max_man({"budget_aud": 80000, "max_price_yen": 10_000_000}, 111.0) == 1000


def test_encrypt_roundtrip():
    blob = store.encrypt({"a": "空き家", "n": [1, 2]}, "segreto")
    assert store.decrypt(blob, "segreto") == {"a": "空き家", "n": [1, 2]}
    with pytest.raises(Exception):
        store.decrypt(blob, "sbagliato")


def _l(source, sid, **kw):
    d = dict(source=source, source_id=sid, key=f"{source}:{sid}", url=f"https://x/{sid}", type="house",
             price_yen=5_000_000, address="千葉県香取市岩ケ崎台1-2", prefecture="chiba", building_m2=80.0,
             land_m2=None, images=[], extra={})
    d.update(kw)
    return d


def test_merge_dedupe_export():
    st = {"listings": {}, "geocache": {}, "runs": []}
    new = store.merge(st, [_l("athome", "1"), _l("suumo", "9", address="千葉県香取市岩ケ崎台", building_m2=81.0,
                                                     layout="3DK")])
    assert len(new) == 2
    # second run: price drop on athome, suumo disappears
    new2 = store.merge(st, [_l("athome", "1", price_yen=4_500_000)])
    assert new2 == [] and st["listings"]["athome:1"]["price_history"][0][1] == 5_000_000
    store.mark_inactive(st, "suumo", set(), completed=True)
    assert st["listings"]["suumo:9"]["active"] is False
    # back to same price -> grouped as one property with two links
    store.merge(st, [_l("athome", "1"), _l("suumo", "9", address="千葉県香取市岩ケ崎台", building_m2=81.0, layout="3DK")])
    exp = store.export(st, 1 / 100)
    assert exp["count"] == 1
    p = exp["properties"][0]
    assert {x["source"] for x in p["links"]} == {"athome", "suumo"} and p["layout"] == "3DK" and p["price_aud"] == 50000


def test_alert_filters():
    l = _l("athome", "1", price_yen=7_000_000, walk_min=10, year_built=1990)
    rate = 1 / 100
    assert notify.matches(l, {"max_price_aud": 80000, "types": ["house"]}, rate)
    assert not notify.matches(l, {"max_price_aud": 60000}, rate)
    assert not notify.matches(l, {"types": ["apartment"]}, rate)
    assert notify.matches(dict(l, type="akiya"), {"types": ["house"]}, rate)
    assert not notify.matches(l, {"prefectures": ["kagoshima"]}, rate)
    assert not notify.matches(l, {"max_walk_min": 5}, rate)
    assert not notify.matches(l, {"min_building_m2": 100}, rate)


def test_http_stops_on_bot_protection(monkeypatch):
    from scraper.common import Blocked, Http

    class R:
        status_code, text, encoding = 202, "<script src='x.awswaf.com/challenge.js'>", "utf-8"

    h = Http(delay=0)
    monkeypatch.setattr(h.s, "get", lambda *a, **k: R())
    assert h.get("https://example.jp/1") is None
    with pytest.raises(Blocked):
        h.get("https://example.jp/2")


def test_athome_diagnose_empty_page():
    d = athome.diagnose("<html><head><title>アクセス制限</title></head><body>しばらくお待ちください</body></html>")
    assert "アクセス" in d and "title=" in d


def test_athome_ownerchange_yield():
    [l] = athome.parse_list(read("athome_ownerchange.html"), "mansion/ownerchange", "oita")
    assert l.price_yen == 1_200_000 and l.yield_pct == 22.0 and l.type == "apartment"
    assert l.building_m2 == 18.5 and l.address == "大分県別府市北浜2丁目" and l.url.endswith("/mansion/1153941731/")


def test_athome_business_cards():
    shop, block = athome.parse_list(read("athome_business.html"), "buy_store", "oita")
    assert shop.type == "commercial" and shop.subtype == "売住宅付き店舗" and shop.price_yen == 3_490_000
    assert shop.building_m2 == 134.76 and shop.land_m2 == 61.37 and shop.year_built == 1973
    assert shop.address == "大分県臼杵市大字臼杵" and shop.walk_min == 13 and shop.yield_pct is None
    assert shop.url == "https://www.athome.co.jp/buy_store/6981234567/"
    assert block.type == "building" and block.price_yen == 12_800_000 and block.yield_pct == 11.2


def test_suumo_new_houses_skip_land():
    html = read("suumo_list.html").replace("/chukoikkodate/chiba/sc_katori/nc_21643383/", "/ikkodate/chiba/sc_katori/nc_1/")
    html += html.replace("/ikkodate/chiba/sc_katori/nc_1/", "/tochi/chiba/sc_katori/nc_2/")
    [l] = suumo.parse_list(html, "ikkodate", "chiba")
    assert l.new_build and l.type == "house" and l.source_id == "1"


def test_athome_challenge_page():
    page = "<html><head><title>【アットホーム】認証中</title></head><body>認証にご協力ください。</body></html>"
    assert athome.is_challenge(page) and not athome.is_challenge(read("athome_list.html"))


def test_suumo_hokkaido_slug():
    assert suumo.city_index_url("chukoikkodate", "hokkaido").endswith("/chukoikkodate/hokkaido_/city/")
    html = '<a href="/chukoikkodate/hokkaido_/sc_sapporoshichuo/">札幌市中央区</a>'
    assert suumo.parse_city_index(html, "chukoikkodate", "hokkaido") == ["sc_sapporoshichuo"]
    assert "/hokkaido_/sc_x/" in suumo.list_url("chukoikkodate", "hokkaido", "sc_x", 1, 1500)
