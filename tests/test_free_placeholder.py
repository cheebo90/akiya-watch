from scraper.sources.akiyabank import parse_detail

SITE = {"id": "niigata-pref", "prefecture": "niigata", "name": "x"}


def page(price, area, img="https://b97.yahoo.co.jp/pagead/conversion/1/?guid=ON"):
    return f"""<html><h1>【柏崎市】物件情報はこちら!</h1><img src="{img}"><img src="/up/house1.jpg">
    <table><tr><th>価格</th><td>{price}</td></tr><tr><th>建物面積</th><td>{area}</td></tr>
    <tr><th>所在地</th><td>柏崎市</td></tr></table></html>"""


def test_zero_yen_placeholder_dropped():
    assert parse_detail(page("0円", "0㎡"), "https://niigatakurashi.com/akiya/1/", SITE) is None
    assert parse_detail(page("0円", "1㎡"), "https://niigatakurashi.com/akiya/1/", SITE) is None


def test_real_free_house_kept_and_tracker_skipped():
    l = parse_detail(page("無償譲渡", "85.2㎡"), "https://niigatakurashi.com/akiya/2/", SITE)
    assert l and l.price_yen == 0 and l.building_m2 == 85.2
    assert all("pagead" not in u for u in l.images) and any("house1" in u for u in l.images)


def test_export_hides_stored_placeholders():
    import inspect
    from scraper import store
    src = inspect.getsource(store)
    assert "not (p.get(\"building_m2\") or p.get(\"land_m2\"))" in src and "TRACKER.search" in src


def test_export_drops_images_shared_by_many_properties():
    from scraper import store
    banner = "https://www.town.nankan.lg.jp/akiya/img/kau.png"
    L = {k: {"key": k, "source": "akiyabank", "url": "u" + k, "type": "akiya", "price_yen": 1_000_000,
             "address": f"熊本県南関町{k}{i}", "prefecture": "kumamoto", "first_seen": "2026-11-07", "building_m2": 80.0 + i,
             "images": [banner, f"https://x/{k}.jpg"]} for i, k in enumerate("abc")}
    out = store.export({"listings": L}, 0.01)
    assert out["properties"] and all(p["images"] == [f"https://x/{p['keys'][0]}.jpg"] for p in out["properties"])


def test_ad_banners_skipped():
    html = """<html><h1>物件</h1>
    <a href="https://jutaku-ryutsu.example.com/"><img src="/img/ad1.jpg"></a>
    <img src="/img/anim.gif"><img src="/img/wide.jpg" width="600" height="100"><img src="/img/pr.jpg" alt="広告">
    <a href="/up/big1.jpg"><img src="/up/house1.jpg"></a>
    <table><tr><th>価格</th><td>500万円</td></tr><tr><th>建物面積</th><td>90㎡</td></tr></table></html>"""
    l = parse_detail(html, "https://www.example-akiya.jp/bukken/1", SITE)
    assert [u.rsplit("/", 1)[-1] for u in l.images] == ["house1.jpg"]


def test_full_gallery_survives_daily_scrape():
    from scraper import store
    st = {"listings": {"suumo:1": {"key": "suumo:1", "source": "suumo", "url": "u", "type": "house", "price_yen": 5_000_000,
                                   "address": "大阪府松原市一津屋5", "prefecture": "osaka", "first_seen": "2026-11-06",
                                   "images": ["a", "b", "c"], "gallery": [f"g{i}" for i in range(12)]}}}
    store.merge(st, [{"key": "suumo:1", "source": "suumo", "url": "u", "type": "house", "price_yen": 5_000_000,
                      "address": "大阪府松原市一津屋5", "prefecture": "osaka", "images": ["a", "b", "c"]}])
    out = store.export(st, 0.01)
    assert len(out["properties"][0]["images"]) == 12 and "gallery" not in out["properties"][0]


def test_export_respects_lowered_ceiling():
    from scraper import store
    L = {k: {"key": k, "source": "suumo", "url": "u" + k, "type": "house", "price_yen": v, "address": f"東京都板橋区{k}",
             "prefecture": "tokyo", "first_seen": "2026-11-07", "building_m2": 60.0 + i}
         for i, (k, v) in enumerate({"a": 12_900_000, "b": 13_400_000}.items())}
    out = store.export({"listings": L}, 0.01, 13_000_000)
    assert [p["keys"] for p in out["properties"]] == [["a"]]


def test_condition_flags():
    from scraper.common import condition_flags as c
    assert c("この物件は賃貸中のため、原則ご自身でお住まいいただくことができません") == {"tenant": True}
    assert c("オーナーチェンジ 表面利回り 8.03%")["tenant"]
    assert c("※再建築不可") == {"no_rebuild": True}
    assert c("即入居可") == {} and c("居住中（引渡し時空室）") == {}


def test_export_carries_flags():
    from scraper import store
    L = {"y": {"key": "y", "source": "yahoo", "url": "u", "type": "house", "price_yen": 11_800_000, "address": "東京都板橋区西台2",
               "prefecture": "tokyo", "first_seen": "2026-11-07", "building_m2": 49.6, "extra": {"tenant": True}},
         "s": {"key": "s", "source": "suumo", "url": "v", "type": "house", "price_yen": 13_000_000, "address": "東京都板橋区x",
               "prefecture": "tokyo", "first_seen": "2026-11-07", "building_m2": 59.5, "extra": {"no_rebuild": True}}}
    out = {p["keys"][0]: p for p in store.export({"listings": L}, 0.01)["properties"]}
    assert out["y"]["tenant"] and not out["y"]["no_rebuild"] and out["s"]["no_rebuild"] and not out["s"]["tenant"]
