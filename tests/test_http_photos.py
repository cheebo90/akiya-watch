import io
from PIL import Image
from scraper import photos


class FakeHttp:
    def __init__(self, files):
        self.files = files

    def get(self, u, raw=False, **kw):
        return self.files.get(u)


def jpg(w, h):
    b = io.BytesIO()
    Image.new("RGB", (w, h), (120, 90, 60)).save(b, "JPEG")
    return b.getvalue()


def test_from_urls_dedupes_sizes_and_skips_icons():
    base = "http://sousei.town.kunitomi.miyazaki.jp/houselist/assets_c/2023/08/"
    files = {base + "IMG_7-thumb-560xauto-7075.jpg": jpg(560, 420), base + "IMG_7-thumb-173xauto-7075.jpg": jpg(173, 130),
             base + "IMG_8-thumb-560xauto-7076.jpg": jpg(560, 420), "http://x/btn.png": jpg(60, 20)}
    out = photos.from_urls(FakeHttp(files), list(files))
    assert len(out) == 2 and all(o[:4] == b"RIFF" for o in out)
