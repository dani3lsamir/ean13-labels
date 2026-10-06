"""Re-derive the modules from what was actually drawn (vector geometry or pixels)."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from .core import EAN13Error, MODULES, decode_modules
from .layout import QUIET_LEFT, QUIET_RIGHT, Rect

PT_MM = 25.4 / 72


class VerificationError(EAN13Error):
    """The rendered symbol does not decode to the requested digits."""


def _expect(got: str, code: str, what: str) -> None:
    if got != code:
        raise VerificationError("%s decodes to %s, expected %s" % (what, got, code))


def check_rects(rects: list[Rect], code: str, left: float, right: float, what: str = "drawing") -> None:
    """Decode bar rectangles (mm) and check quiet zones against the container ``left``/``right`` edges."""
    if not rects:
        raise VerificationError("%s contains no bars" % what)
    top = min(r.y for r in rects)
    bars = [r for r in rects if abs(r.y - top) < 1e-3]
    m = min(r.w for r in rects)
    x0 = min(r.x for r in rects)
    x1 = max(r.x + r.w for r in rects)
    if abs((x1 - x0) / m - MODULES) > 0.05:
        raise VerificationError("%s: bars span %.2f modules, expected %d" % (what, (x1 - x0) / m, MODULES))
    bits = "".join(
        "1" if any(r.x <= x0 + (i + 0.5) * m <= r.x + r.w for r in bars) else "0" for i in range(MODULES))
    try:
        got = decode_modules(bits)
    except EAN13Error as exc:
        raise VerificationError("%s does not decode: %s" % (what, exc)) from exc
    _expect(got, code, what)
    eps = 1e-3
    if x0 - left < QUIET_LEFT * m - eps or right - x1 < QUIET_RIGHT * m - eps:
        raise VerificationError("%s: quiet zones smaller than %d/%d modules" % (what, QUIET_LEFT, QUIET_RIGHT))


def check_svg(svg: str, code: str) -> None:
    root = ET.fromstring(svg)
    ns = {"s": "http://www.w3.org/2000/svg"}
    vb = [float(v) for v in root.get("viewBox").split()]
    rects = [Rect(float(r.get("x")), float(r.get("y")), float(r.get("width")), float(r.get("height")))
             for r in root.findall(".//s:g[@id='bars']/s:rect", ns)]
    check_rects(rects, code, vb[0], vb[0] + vb[2], "SVG")


def check_png(img, code: str) -> None:
    """Decode a PIL image by sampling the longest run of identical rows that holds the bars."""
    g = img.convert("L")
    w, h = g.size
    data = g.tobytes()
    rows = [data[y * w:(y + 1) * w] for y in range(h)]
    best, start = None, 0
    for y in range(1, h + 1):
        if y == h or rows[y] != rows[start]:
            row = rows[start]
            edges = sum(1 for i in range(1, w) if (row[i] < 128) != (row[i - 1] < 128))
            if edges >= 56 and (best is None or y - start > best[1] - best[0]):
                best = (start, y)
            start = y
    if best is None:
        raise VerificationError("PNG: no bar rows found")
    row = rows[best[0]]
    dark = [i for i, v in enumerate(row) if v < 128]
    x0, x1 = dark[0], dark[-1] + 1
    m = (x1 - x0) / MODULES
    if m < 1.5:
        raise VerificationError("PNG: module is %.2f px wide; use a higher dpi" % m)
    bits = "".join("1" if row[int(x0 + (i + 0.5) * m)] < 128 else "0" for i in range(MODULES))
    try:
        got = decode_modules(bits)
    except EAN13Error as exc:
        raise VerificationError("PNG does not decode: %s (try a higher dpi)" % exc) from exc
    _expect(got, code, "PNG")
    if x0 < QUIET_LEFT * m - 1.5 or w - x1 < QUIET_RIGHT * m - 1.5:
        raise VerificationError("PNG: quiet zones smaller than %d/%d modules" % (QUIET_LEFT, QUIET_RIGHT))


_PAGE = re.compile(rb"/Contents (\d+) 0 R /MediaBox \[ 0 0 ([\d.]+) ([\d.]+) \]")
_RECT = re.compile(r"^n ([-\d.]+) ([-\d.]+) ([-\d.]+) ([-\d.]+) re f\*?$", re.M)


def pdf_page_rects(pdf: bytes) -> list[tuple[float, float, list[Rect]]]:
    """Per page: (width mm, height mm, filled rectangles in mm with y pointing down).

    Only understands the uncompressed content streams written by this package.
    """
    streams = {int(n): body for n, body in re.findall(rb"(\d+) 0 obj\s*<<[^>]*>>\s*stream\r?\n(.*?)endstream", pdf, re.S)}
    pages = []
    for num, pw, ph in _PAGE.findall(pdf):
        pw, ph = float(pw), float(ph)
        body = streams.get(int(num))
        if body is None:
            raise VerificationError("PDF page content stream not found")
        rects = [Rect(float(x) * PT_MM, (ph - float(y) - float(hh)) * PT_MM, float(ww) * PT_MM, float(hh) * PT_MM)
                 for x, y, ww, hh in _RECT.findall(body.decode("latin-1"))]
        pages.append((pw * PT_MM, ph * PT_MM, rects))
    if not pages:
        raise VerificationError("PDF has no pages")
    return pages


def check_pdf(pdf: bytes, code: str) -> None:
    (pw, _ph, rects), = pdf_page_rects(pdf)
    check_rects(rects, code, 0.0, pw, "PDF")
