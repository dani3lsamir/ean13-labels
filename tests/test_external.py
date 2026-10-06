"""Independent check: decode the rendered PNGs with zxing-cpp (a third-party reader)."""

import io
import random
import shutil
import subprocess

import pytest
from PIL import Image

from ean13_tools import build_sheet, check_digit, render_png

zxingcpp = pytest.importorskip("zxingcpp")

PUBLIC = ["4006381333931", "5901234123457", "9780201379624"]


def read(img):
    found = zxingcpp.read_barcodes(img)
    assert len(found) == 1
    return str(found[0].format), found[0].text


def decode_png(data):
    return read(Image.open(io.BytesIO(data)))


@pytest.mark.parametrize("code", PUBLIC)
@pytest.mark.parametrize("kw", [
    {},
    {"top": "SKU-123", "bold": True},
    {"top": "TOP", "bottom": "BOTTOM", "no_digits": True},
    {"scale": 0.8, "dpi": 400},
    {"scale": 2.0, "dpi": 300},
    {"module_mm": 0.3, "dpi": 600},
])
def test_zxing_reads_public_codes(code, kw):
    assert decode_png(render_png(code, **kw)) == ("EAN-13", code)


def test_zxing_reads_random_codes():
    rng = random.Random(99)
    for _ in range(30):
        d12 = "".join(rng.choice("0123456789") for _ in range(12))
        code = d12 + str(check_digit(d12))
        assert decode_png(render_png(code, dpi=300, top="x")) == ("EAN-13", code)


@pytest.mark.skipif(not shutil.which("pdftoppm"), reason="poppler not installed")
def test_zxing_reads_rasterised_sheet(tmp_path):
    rows = [{"ean": c, "top": "L%d" % i} for i, c in enumerate(PUBLIC)]
    pdf = tmp_path / "s.pdf"
    build_sheet(rows, pdf, layout="a4-3x8")
    subprocess.run(["pdftoppm", "-r", "300", "-png", str(pdf), str(tmp_path / "p")], check=True)
    img = Image.open(next(tmp_path.glob("p*.png")))
    assert sorted(r.text for r in zxingcpp.read_barcodes(img)) == sorted(PUBLIC)
