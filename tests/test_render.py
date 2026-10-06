import io
import random
import re
import warnings

import pytest
from PIL import Image

from ean13_tools import (EAN13Error, GS1Warning, VerificationError, check_digit, decode_modules, encode,
                         render_pdf, render_png, render_svg)
from ean13_tools import verify
from ean13_tools.layout import NOMINAL_MODULE_MM, build_drawing

PUBLIC = ["4006381333931", "5901234123457", "9780201379624"]


def random_codes(n, seed=7):
    rng = random.Random(seed)
    for _ in range(n):
        d12 = "".join(rng.choice("0123456789") for _ in range(12))
        yield d12 + str(check_digit(d12))


def svg_rects(svg):
    return [tuple(float(v) for v in m) for m in
            re.findall(r'<rect x="([\d.]+)" y="([\d.]+)" width="([\d.]+)" height="([\d.]+)"/>', svg)]


def test_svg_exact_millimetres():
    svg = render_svg("5901234123457")
    assert 'width="37.29mm"' in svg
    rects = svg_rects(svg)
    assert min(w for _, _, w, _ in rects) == pytest.approx(0.33)
    # first bar starts after an 11-module quiet zone; the symbol is 95 modules wide
    x0 = min(x for x, *_ in rects)
    x1 = max(x + w for x, _, w, _ in rects)
    assert x0 == pytest.approx(11 * 0.33)
    assert x1 - x0 == pytest.approx(95 * 0.33, abs=1e-3)
    assert 37.29 - x1 == pytest.approx(7 * 0.33, abs=1e-3)


def test_guard_bars_are_longer():
    rects = svg_rects(render_svg("5901234123457", no_digits=True))
    heights = sorted({round(h, 3) for *_, h in rects})
    assert heights == [22.85, 24.5]
    tall = [x for x, _, _, h in rects if round(h, 3) == 24.5]
    assert len(tall) == 6  # start, centre and end guards: two bars each


def test_scale_and_module_mm():
    d1 = build_drawing("5901234123457")
    svg2 = render_svg("5901234123457", scale=2.0)
    assert 'width="74.58mm"' in svg2
    assert d1.module == NOMINAL_MODULE_MM
    with pytest.raises(EAN13Error):
        render_svg("5901234123457", scale=0.5)
    with pytest.raises(EAN13Error):
        render_svg("5901234123457", scale=3)
    with pytest.raises(EAN13Error):
        render_svg("5901234123457", scale=1.0, module_mm=0.33)
    with pytest.warns(GS1Warning):
        render_svg("5901234123457", module_mm=0.8)
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        render_svg("5901234123457", module_mm=0.4)


def test_digits_and_captions_in_svg():
    svg = render_svg("5901234123457", top="SKU-1 <A&B>", bottom="low", bold=True)
    assert svg.count("<text") == 13 + 2
    assert "SKU-1 &lt;A&amp;B&gt;" in svg and 'font-weight="bold"' in svg
    assert render_svg("5901234123457", no_digits=True).count("<text") == 0


def test_no_caption_by_default():
    assert render_svg("5901234123457").count("<text") == 13


def test_caption_never_eats_quiet_zone():
    svg = render_svg("5901234123457", top="A" * 60, no_digits=True)
    rects = svg_rects(svg)
    w = float(re.search(r'width="([\d.]+)mm"', svg).group(1))
    x0 = min(x for x, *_ in rects)
    x1 = max(x + wd for x, _, wd, _ in rects)
    assert x0 >= 11 * 0.33 - 1e-3 and w - x1 >= 7 * 0.33 - 1e-3


@pytest.mark.parametrize("code", PUBLIC)
def test_all_formats_for_public_codes(code):
    render_svg(code, top="TOP", bottom="BOTTOM")
    render_png(code, dpi=300, top="TOP", bottom="BOTTOM", bold=True)
    render_pdf(code, top="TOP", bottom="BOTTOM")


def test_random_roundtrip_all_formats():
    for code in random_codes(25):
        svg = render_svg(code)
        verify.check_svg(svg, code)  # independent second decode of the returned text
        png = render_png(code, dpi=300)
        verify.check_png(Image.open(io.BytesIO(png)), code)
        verify.check_pdf(render_pdf(code), code)


def test_png_dpi_and_size():
    data = render_png("5901234123457", dpi=600, no_digits=True)
    img = Image.open(io.BytesIO(data))
    assert img.info["dpi"][0] == pytest.approx(600, abs=0.5)
    assert img.width == pytest.approx(37.29 / 25.4 * 600, abs=1)


def test_png_dpi_too_low_fails_verification():
    with pytest.raises(VerificationError):
        render_png("5901234123457", dpi=40)


def test_verification_catches_wrong_digits():
    svg = render_svg("5901234123457")
    with pytest.raises(VerificationError):
        verify.check_svg(svg, "4006381333931")


def test_files_written(tmp_path):
    render_svg("5901234123457", out=tmp_path / "a.svg")
    render_png("5901234123457", out=tmp_path / "a.png")
    render_pdf("5901234123457", out=tmp_path / "a.pdf")
    assert (tmp_path / "a.svg").read_text(encoding="utf-8").startswith("<?xml")
    assert (tmp_path / "a.png").read_bytes()[:4] == b"\x89PNG"
    assert (tmp_path / "a.pdf").read_bytes()[:5] == b"%PDF-"


def test_custom_font_and_bold_warning():
    import ean13_tools
    font = str(__import__("pathlib").Path(ean13_tools.__file__).parent / "fonts" / "LiberationSans-Regular.ttf")
    render_png("5901234123457", dpi=300, top="x", font=font)
    with pytest.warns(UserWarning):
        render_svg("5901234123457", top="x", font=font, bold=True)
    with pytest.raises(EAN13Error):
        render_svg("5901234123457", top="x", font="/nonexistent.ttf")


def test_invalid_code_rejected():
    with pytest.raises(EAN13Error):
        render_svg("5901234123450")
