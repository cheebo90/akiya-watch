"""The 47 prefectures: slug (used in athome/SUUMO/LIFULL URLs), English, Japanese, LIFULL region."""

# slug, english, japanese, lifull_region
PREFECTURES = [
    ("hokkaido", "Hokkaido", "北海道", "tohoku"),
    ("aomori", "Aomori", "青森県", "tohoku"),
    ("iwate", "Iwate", "岩手県", "tohoku"),
    ("miyagi", "Miyagi", "宮城県", "tohoku"),
    ("akita", "Akita", "秋田県", "tohoku"),
    ("yamagata", "Yamagata", "山形県", "tohoku"),
    ("fukushima", "Fukushima", "福島県", "tohoku"),
    ("ibaraki", "Ibaraki", "茨城県", "kanto"),
    ("tochigi", "Tochigi", "栃木県", "kanto"),
    ("gunma", "Gunma", "群馬県", "kanto"),
    ("saitama", "Saitama", "埼玉県", "kanto"),
    ("chiba", "Chiba", "千葉県", "kanto"),
    ("tokyo", "Tokyo", "東京都", "kanto"),
    ("kanagawa", "Kanagawa", "神奈川県", "kanto"),
    ("niigata", "Niigata", "新潟県", "hokuriku"),
    ("toyama", "Toyama", "富山県", "hokuriku"),
    ("ishikawa", "Ishikawa", "石川県", "hokuriku"),
    ("fukui", "Fukui", "福井県", "hokuriku"),
    ("yamanashi", "Yamanashi", "山梨県", "hokuriku"),
    ("nagano", "Nagano", "長野県", "hokuriku"),
    ("gifu", "Gifu", "岐阜県", "tokai"),
    ("shizuoka", "Shizuoka", "静岡県", "tokai"),
    ("aichi", "Aichi", "愛知県", "tokai"),
    ("mie", "Mie", "三重県", "tokai"),
    ("shiga", "Shiga", "滋賀県", "kinki"),
    ("kyoto", "Kyoto", "京都府", "kinki"),
    ("osaka", "Osaka", "大阪府", "kinki"),
    ("hyogo", "Hyogo", "兵庫県", "kinki"),
    ("nara", "Nara", "奈良県", "kinki"),
    ("wakayama", "Wakayama", "和歌山県", "kinki"),
    ("tottori", "Tottori", "鳥取県", "chugoku"),
    ("shimane", "Shimane", "島根県", "chugoku"),
    ("okayama", "Okayama", "岡山県", "chugoku"),
    ("hiroshima", "Hiroshima", "広島県", "chugoku"),
    ("yamaguchi", "Yamaguchi", "山口県", "chugoku"),
    ("tokushima", "Tokushima", "徳島県", "chugoku"),
    ("kagawa", "Kagawa", "香川県", "chugoku"),
    ("ehime", "Ehime", "愛媛県", "chugoku"),
    ("kochi", "Kochi", "高知県", "chugoku"),
    ("fukuoka", "Fukuoka", "福岡県", "kyushu"),
    ("saga", "Saga", "佐賀県", "kyushu"),
    ("nagasaki", "Nagasaki", "長崎県", "kyushu"),
    ("kumamoto", "Kumamoto", "熊本県", "kyushu"),
    ("oita", "Oita", "大分県", "kyushu"),
    ("miyazaki", "Miyazaki", "宮崎県", "kyushu"),
    ("kagoshima", "Kagoshima", "鹿児島県", "kyushu"),
    ("okinawa", "Okinawa", "沖縄県", "kyushu"),
]

BY_SLUG = {p[0]: p for p in PREFECTURES}
SLUGS = [p[0] for p in PREFECTURES]


def slug_from_address(address: str) -> str:
    for slug, _en, ja, _r in PREFECTURES:
        if address.startswith(ja) or address.startswith(ja.rstrip("県府都")):
            return slug
    return ""


def ja_name(slug: str) -> str:
    return BY_SLUG[slug][2] if slug in BY_SLUG else ""


def select(cfg_value) -> list[str]:
    """Config 'prefectures': 'all' or a list of slugs."""
    if cfg_value in (None, "all", "*", []):
        return list(SLUGS)
    bad = [s for s in cfg_value if s not in BY_SLUG]
    if bad:
        raise ValueError(f"Prefetture sconosciute in config.yml: {bad}")
    return list(cfg_value)
