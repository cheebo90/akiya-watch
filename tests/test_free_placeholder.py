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
