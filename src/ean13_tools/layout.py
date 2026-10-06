"""EAN-13 geometry in millimetres (GS1 General Specifications, section 5.2.3).

Everything is expressed in a small :class:`Drawing` (rectangles + centred texts, y pointing
down, origin top-left) that the SVG, PNG and PDF back ends draw one-to-one.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field

from .core import EAN13Error, MODULES, encode, normalize
from .fonts import Font, digit_metrics, resolve_font, text_width_mm

NOMINAL_MODULE_MM = 0.33      # X dimension at 100 % magnification
MIN_SCALE, MAX_SCALE = 0.8, 2.0
QUIET_LEFT, QUIET_RIGHT = 11, 7   # modules
BAR_HEIGHT_MM = 22.85         # nominal height of the normal bars
GUARD_EXTENSION = 5           # modules the guard bars extend below the normal bars
DIGIT_HEIGHT_MM = 2.75        # nominal height of the human-readable digits
SYMBOL_HEIGHT_MM = 25.93      # nominal bars + digits
CAPTION_GAP_MM = 0.8
_ASCENT, _DESCENT = 0.905, 0.212   # em, used to reserve room for caption lines

# Module indices of the extended guard bars (start, centre, end).
_GUARD_BARS = {0, 2, 46, 48, 92, 94}


class GS1Warning(UserWarning):
    """A requested size is outside the range recommended by GS1."""


@dataclass(frozen=True)
class Rect:
    x: float
    y: float
    w: float
    h: float


@dataclass(frozen=True)
class Text:
    x: float          # horizontal centre
    y: float          # baseline
    text: str
    size: float       # em size in mm
    bold: bool = False


@dataclass
class Drawing:
    width: float
    height: float
    module: float
    code: str
    font: Font
    rects: list = field(default_factory=list)
    texts: list = field(default_factory=list)
    symbol_x: float = 0.0   # left edge of the start guard


def resolve_module(scale: float | None = None, module_mm: float | None = None) -> float:
    """Module width in mm from a magnification (0.8-2.0) or an explicit module width."""
    if scale is not None and module_mm is not None:
        raise EAN13Error("use either scale or module_mm, not both")
    if module_mm is not None:
        if not module_mm > 0:
            raise EAN13Error("module_mm must be positive")
        mag = module_mm / NOMINAL_MODULE_MM
        if not MIN_SCALE - 1e-9 <= mag <= MAX_SCALE + 1e-9:
            warnings.warn("module width %.3f mm is %.0f%% magnification, outside the GS1 range "
                          "of %d-%d%%" % (module_mm, mag * 100, MIN_SCALE * 100, MAX_SCALE * 100),
                          GS1Warning, stacklevel=3)
        return module_mm
    scale = 1.0 if scale is None else scale
    if not MIN_SCALE - 1e-9 <= scale <= MAX_SCALE + 1e-9:
        raise EAN13Error("scale %.2f is outside the GS1 range %.1f-%.1f" % (scale, MIN_SCALE, MAX_SCALE))
    return NOMINAL_MODULE_MM * scale


def build_drawing(code: str, *, module_mm: float = NOMINAL_MODULE_MM, no_digits: bool = False,
                  top: str | None = None, bottom: str | None = None, bold: bool = False,
                  font_size: float = 8.0, font: str | None = None) -> Drawing:
    """Lay out one symbol (quiet zones included) with optional digits and captions.

    ``font_size`` is in points. Captions are centred on the bars and never shrink the
    quiet zones; a caption wider than the symbol widens the drawing.
    """
    code = normalize(code)
    bits = encode(code)
    fnt = resolve_font(font)
    if bold and fnt.bold == fnt.regular:
        warnings.warn("bold is ignored with a custom font (it has a single weight)", UserWarning, stacklevel=2)
        bold = False
    m = module_mm
    s = m / NOMINAL_MODULE_MM
    cap_size = font_size * 25.4 / 72
    if cap_size <= 0:
        raise EAN13Error("font_size must be positive")

    y_bars = 0.0
    if top:
        y_bars = cap_size * (_ASCENT + _DESCENT) + CAPTION_GAP_MM
    bar_h = BAR_HEIGHT_MM * s
    guard_h = bar_h + GUARD_EXTENSION * m
    # digits get half a module of room below the baseline for the overshoot of round glyphs
    symbol_h = guard_h if no_digits else SYMBOL_HEIGHT_MM * s + 0.5 * m
    total_w = (QUIET_LEFT + MODULES + QUIET_RIGHT) * m
    d = Drawing(width=total_w, height=y_bars + symbol_h, module=m, code=code, font=fnt,
                symbol_x=QUIET_LEFT * m)

    # Bars: merge neighbouring modules, but keep guard bars separate (they are taller).
    i = 0
    while i < MODULES:
        if bits[i] == "0":
            i += 1
            continue
        guard = i in _GUARD_BARS
        j = i + 1
        while j < MODULES and bits[j] == "1" and not guard and j not in _GUARD_BARS:
            j += 1
        d.rects.append(Rect((QUIET_LEFT + i) * m, y_bars, (j - i) * m, guard_h if guard else bar_h))
        i = j

    if not no_digits:
        height_em, width_em = digit_metrics(fnt.regular)
        size = min(DIGIT_HEIGHT_MM * s / height_em, 0.92 * 7 * m / width_em)
        base = y_bars + SYMBOL_HEIGHT_MM * s
        d.texts.append(Text((QUIET_LEFT - 4.5) * m, base, code[0], size))
        for k in range(6):
            d.texts.append(Text((QUIET_LEFT + 3 + 7 * k + 3.5) * m, base, code[1 + k], size))
            d.texts.append(Text((QUIET_LEFT + 50 + 7 * k + 3.5) * m, base, code[7 + k], size))

    cx = (QUIET_LEFT + MODULES / 2) * m
    captions = []
    if top:
        captions.append(Text(cx, cap_size * _ASCENT, top, cap_size, bold))
    if bottom:
        base = y_bars + symbol_h + CAPTION_GAP_MM + cap_size * _ASCENT
        captions.append(Text(cx, base, bottom, cap_size, bold))
        d.height = base + cap_size * _DESCENT
    d.texts.extend(captions)

    # A caption wider than the quiet-zone-to-quiet-zone drawing extends it; re-centre if needed.
    lo, hi = 0.0, total_w
    for t in captions:
        half = text_width_mm(fnt.path(t.bold), t.text, t.size) / 2
        lo, hi = min(lo, t.x - half), max(hi, t.x + half)
    if lo < 0 or hi > total_w:
        d.rects = [Rect(r.x - lo, r.y, r.w, r.h) for r in d.rects]
        d.texts = [Text(t.x - lo, t.y, t.text, t.size, t.bold) for t in d.texts]
        d.symbol_x -= lo
        d.width = hi - lo
    return d
