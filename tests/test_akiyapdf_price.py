from scraper.sources.akiyapdf import sheet_price, NOT_PROP


def test_sheet_price_ticked_box():
    assert sheet_price("所有者の意向\n■売却希望 希望価格 ９０ 万円") == 900_000
    assert sheet_price("□売却希望 希望価格 万円") is None


def test_daicho_listing_allowed():
    assert not NOT_PROP.search("空き家台帳登録物件情報 空き家番号55")
    assert NOT_PROP.search("空き家台帳")
