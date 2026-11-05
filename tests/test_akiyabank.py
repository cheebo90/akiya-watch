"""Generic akiya-bank reader, against page structures observed on 2026-11-05 (reconstructed)."""
from scraper.sources import akiyabank as ab

NIIGATA = """<html><body><h2>【小千谷市】 小千谷市船岡（売買戸建て物件）</h2><table>
<tr><th>所在地</th><td>小千谷市船岡３－１１－１７</td></tr><tr><th>種類</th><td>一戸建て</td></tr>
<tr><th>間取り</th><td>5K以上</td></tr><tr><th>価格</th><td>90万円</td></tr><tr><th>築年月</th><td>1995年</td></tr>
<tr><th>建物（占有）面積</th><td>149.86㎡</td></tr><tr><th>構造・規模</th><td>木造・鉄筋コンクリート造3階建て</td></tr>
<tr><th>最寄り公共交通機関と所要時間</th><td>ＪＲ上越線 小千谷駅 / 車2.7km</td></tr>
<tr><th>物件名</th><td>【小千谷市】 小千谷市船岡（売買戸建て物件）【Ｎｏ．２３１】</td></tr></table>
<img src="/wp-content/uploads/2026/11/4023f48dfe.jpg"><img src="/img/logo.png"></body></html>"""

HOKKAIDO = """<html><body><table>
<tr><th>登録番号</th><td>03129</td></tr><tr><th>物件分類</th><td>空き家(居住用)</td></tr><tr><th>区分</th><td>売買</td></tr>
<tr><th>希望価格</th><td>5,100,000円／売却価格</td></tr><tr><th>敷金</th><td>---</td></tr><tr><th>礼金</th><td>---</td></tr>
<tr><th>住所</th><td>帯広市 西21条南2丁目3番134</td></tr><tr><th>間取り</th><td>---</td></tr>
<tr><th>土地面積</th><td>186.29㎡(56.4坪)</td></tr><tr><th>建物面積</th><td></td></tr><tr><th>構造</th><td>---</td></tr>
<tr><th>建築年</th><td>---</td></tr></table></body></html>"""

HOKKAIDO_RENT = HOKKAIDO.replace("売買", "賃貸").replace("5,100,000円／売却価格", "---").replace("<th>敷金</th><td>---", "<th>賃料</th><td>30,000円")

IBARAKI = """<html><body><dl><dt>希望価格</dt><dd>4,800,000円</dd><dt>所在地</dt><dd>下妻市見田</dd>
<dt>敷地面積</dt><dd>563.40㎡</dd><dt>建築年</dt><dd>1985</dd><dt>用途</dt><dd>住宅</dd><dt>構造</dt><dd>木造</dd>
<dt>延べ床面積</dt><dd>73.94㎡</dd><dt>間取り</dt><dd>4DK</dd></dl></body></html>"""

MIE = """<html><body><dl><dt>取引区分</dt><dd>売買</dd><dt>売買希望価格</dt><dd>5,000,000円</dd>
<dt>賃貸希望価格</dt><dd>-</dd><dt>所在地</dt><dd>伊賀市島ヶ原</dd><dt>土地面積</dt><dd>400㎡</dd><dt>建物面積</dt><dd>98㎡</dd>
<dt>間取り</dt><dd>-</dd><dt>建築時期</dt><dd>1983年</dd></dl></body></html>"""

NOT_A_LISTING = "<html><body><h1>空き家バンク制度について</h1><p>登録方法の説明です。</p></body></html>"


def site(pref, **kw):
    return {"id": f"t-{pref}", "name": "test", "prefecture": pref, "list": "https://x.jp/list/", **kw}


def test_niigata():
    l = ab.parse_detail(NIIGATA, "https://niigatakurashi.com/akiya/123628/", site("niigata"))
    assert l.price_yen == 900_000 and l.building_m2 == 149.86 and l.year_built == 1995
    assert l.address == "新潟県小千谷市船岡3-11-17" and "小千谷市船岡" in l.title
    assert l.images == ["https://niigatakurashi.com/wp-content/uploads/2026/11/4023f48dfe.jpg"]


def test_hokkaido_sale_and_rent():
    l = ab.parse_detail(HOKKAIDO, "https://www.hokkaido-akiya.com/detail?id=3129", site("hokkaido"))
    assert l.price_yen == 5_100_000 and l.land_m2 == 186.29 and l.building_m2 is None
    assert l.address.startswith("北海道帯広市") and l.type == "land" and l.year_built is None
    assert ab.parse_detail(HOKKAIDO_RENT, "https://www.hokkaido-akiya.com/detail?id=1", site("hokkaido")) is None


def test_ibaraki_and_mie():
    l = ab.parse_detail(IBARAKI, "https://iju-ibaraki.jp/residence/akiya/35089.html", site("ibaraki"))
    assert (l.price_yen, l.land_m2, l.building_m2, l.year_built, l.layout) == (4_800_000, 563.40, 73.94, 1985, "4DK")
    m = ab.parse_detail(MIE, "https://www.ijyu.pref.mie.lg.jp/bank/16675/", site("mie"))
    assert m.price_yen == 5_000_000 and m.year_built == 1983 and m.building_m2 == 98


def test_not_a_listing():
    assert ab.parse_detail(NOT_A_LISTING, "https://x.jp/about", site("chiba")) is None


def test_detail_links_regex_and_heuristic():
    html = """<ul><li><a href="/akiya/123/">船岡 90万円 149㎡</a></li><li><a href="/akiya/124/">見田 480万円</a></li>
    <li><a href="/about/">制度について</a></li><li><a href="/files/a.pdf">物件一覧 PDF 万円</a></li>
    <li><a href="https://www.homes.co.jp/akiyabank/b-1/">LIFULL 100万円</a></li></ul>"""
    s = site("niigata", detail=r"/akiya/\d+/$")
    assert ab.detail_links(html, "https://n.jp/list/", s) == ["https://n.jp/akiya/123/", "https://n.jp/akiya/124/"]
    heur = ab.detail_links(html, "https://n.jp/list/", site("niigata"))
    assert "https://n.jp/akiya/123/" in heur and not any(u.endswith(".pdf") or "homes.co.jp" in u for u in heur)


def test_census_terms_detection():
    from scraper import census
    assert census.TERMS_BAN.search("当サイトの情報を自動的に収集する行為は禁止します")
    assert census.TERMS_BAN.search("スクレイピング行為を禁止します")
    assert not census.TERMS_BAN.search("当サイトへのリンクは自由です。著作権は市に帰属します。")
