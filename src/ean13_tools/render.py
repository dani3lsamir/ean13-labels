"""SVG, PNG and PDF back ends. Every render is decoded again before it is returned."""

from __future__ import annotations

import hashlib
import io
from pathlib import Path
from xml.sax.saxutils import escape

from PIL import Image, ImageDraw, ImageFont

from . import verify
from .fonts import family
from .layout import Drawing, build_drawing, resolve_module

PT_PER_MM = 72 / 25.4
SVG_FALLBACK = "Arial, Helvetica, sans-serif"


def _num(v: float) -> str:
    return ("%.4f" % v).rstrip("0").rstrip(".") or "0"


def _drawing(code, scale, module_mm, **kw) -> Drawing:
    return build_drawing(code, module_mm=resolve_module(scale, module_mm), **kw)


def _write(out, data) -> None:
    if out is not None:
        mode = "w" if isinstance(data, str) else "wb"
        with open(out, mode, **({"encoding": "utf-8"} if mode == "w" else {})) as fh:
            fh.write(data)


def svg_markup(d: Drawing) -> str:
    w, h = _num(d.width), _num(d.height)
    parts = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<svg xmlns="http://www.w3.org/2000/svg" width="%smm" height="%smm" viewBox="0 0 %s %s">' % (w, h, w, h),
             '<title>EAN-13 %s</title>' % d.code,
             '<rect x="0" y="0" width="%s" height="%s" fill="#fff"/>' % (w, h),
             '<g id="bars" fill="#000" shape-rendering="crispEdges">']
    parts += ['<rect x="%s" y="%s" width="%s" height="%s"/>' % tuple(_num(v) for v in (r.x, r.y, r.w, r.h))
              for r in d.rects]
    parts.append("</g>")
    parts.append('<g id="text" fill="#000" text-anchor="middle">')
    for t in d.texts:
        fam = family(d.font.path(t.bold))
        parts.append('<text x="%s" y="%s" font-size="%s" font-family="%s, %s"%s>%s</text>' % (
            _num(t.x), _num(t.y), _num(t.size), escape(fam), SVG_FALLBACK,
            ' font-weight="bold"' if t.bold else "", escape(t.text)))
    parts += ["</g>", "</svg>", ""]
    return "\n".join(parts)


def render_svg(code, out=None, *, scale=None, module_mm=None, no_digits=False, top=None, bottom=None,
               bold=False, font_size=8.0, font=None, verify_output=True) -> str:
    """EAN-13 as SVG text (user units = mm). Written to ``out`` if given."""
    d = _drawing(code, scale, module_mm, no_digits=no_digits, top=top, bottom=bottom,
                 bold=bold, font_size=font_size, font=font)
    svg = svg_markup(d)
    if verify_output:
        verify.check_svg(svg, d.code)
    _write(out, svg)
    return svg


def png_image(d: Drawing, dpi: int) -> Image.Image:
    k = dpi / 25.4
    img = Image.new("L", (max(1, round(d.width * k)), max(1, round(d.height * k))), 255)
    draw = ImageDraw.Draw(img)
    for r in d.rects:
        x0, y0 = round(r.x * k), round(r.y * k)
        draw.rectangle([x0, y0, max(x0, round((r.x + r.w) * k) - 1), max(y0, round((r.y + r.h) * k) - 1)], fill=0)
    for t in d.texts:
        f = ImageFont.truetype(d.font.path(t.bold), max(1, round(t.size * k)))
        draw.text((t.x * k, t.y * k), t.text, font=f, fill=0, anchor="ms")
    return img


def render_png(code, out=None, *, dpi=600, scale=None, module_mm=None, no_digits=False, top=None, bottom=None,
               bold=False, font_size=8.0, font=None, verify_output=True) -> bytes:
    """EAN-13 as PNG bytes (greyscale, ``dpi`` stored in the file). Written to ``out`` if given."""
    d = _drawing(code, scale, module_mm, no_digits=no_digits, top=top, bottom=bottom,
                 bold=bold, font_size=font_size, font=font)
    img = png_image(d, dpi)
    if verify_output:
        verify.check_png(img, d.code)
    buf = io.BytesIO()
    img.save(buf, "PNG", dpi=(dpi, dpi))
    _write(out, buf.getvalue())
    return buf.getvalue()


_registered: dict[str, str] = {}


def pdf_font_name(path: str) -> str:
    """Register a TTF with reportlab (once) and return its internal name."""
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    if path not in _registered:
        name = "ean13-" + hashlib.sha1(path.encode()).hexdigest()[:10]
        pdfmetrics.registerFont(TTFont(name, path))
        _registered[path] = name
    return _registered[path]


def draw_on_canvas(c, d: Drawing, x_mm: float, y_mm: float, page_h_mm: float) -> None:
    """Draw ``d`` with its top-left corner at (x_mm, y_mm), measured from the page's top-left."""
    c.setFillColorRGB(0, 0, 0)
    for r in d.rects:
        c.rect((x_mm + r.x) * PT_PER_MM, (page_h_mm - y_mm - r.y - r.h) * PT_PER_MM,
               r.w * PT_PER_MM, r.h * PT_PER_MM, stroke=0, fill=1)
    for t in d.texts:
        c.setFont(pdf_font_name(d.font.path(t.bold)), t.size * PT_PER_MM)
        c.drawCentredString((x_mm + t.x) * PT_PER_MM, (page_h_mm - y_mm - t.y) * PT_PER_MM, t.text)


def new_canvas(buf, w_mm: float, h_mm: float):
    from reportlab.pdfgen import canvas

    # Uncompressed page content and invariant=1 keep the output reproducible and re-readable.
    return canvas.Canvas(buf, pagesize=(w_mm * PT_PER_MM, h_mm * PT_PER_MM), pageCompression=0, invariant=1)


def render_pdf(code, out=None, *, scale=None, module_mm=None, no_digits=False, top=None, bottom=None,
               bold=False, font_size=8.0, font=None, verify_output=True) -> bytes:
    """EAN-13 as a one-page PDF cut exactly to the symbol (quiet zones included)."""
    d = _drawing(code, scale, module_mm, no_digits=no_digits, top=top, bottom=bottom,
                 bold=bold, font_size=font_size, font=font)
    buf = io.BytesIO()
    c = new_canvas(buf, d.width, d.height)
    draw_on_canvas(c, d, 0, 0, d.height)
    c.showPage()
    c.save()
    data = buf.getvalue()
    if verify_output:
        verify.check_pdf(data, d.code)
    _write(out, data)
    return data
