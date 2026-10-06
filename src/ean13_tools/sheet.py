"""PDF label sheets from a CSV: layouts, validation, placement."""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from pathlib import Path

from . import verify
from .core import EAN13Error, normalize
from .layout import MAX_SCALE, MIN_SCALE, NOMINAL_MODULE_MM, build_drawing
from .render import PT_PER_MM, draw_on_canvas, new_canvas, _write

MAX_COPIES = 10000
MARK_OFFSET_MM, MARK_LENGTH_MM = 0.5, 2.0
PAGES = {"a3": (297, 420), "a4": (210, 297), "a5": (148, 210), "a6": (105, 148),
         "letter": (215.9, 279.4), "legal": (215.9, 355.6)}


class SheetError(EAN13Error):
    """CSV rows are invalid. ``errors`` is a list of (line number, reason)."""

    def __init__(self, errors):
        self.errors = errors
        super().__init__("\n".join("line %d: %s" % e for e in errors))


class LayoutError(EAN13Error):
    """The requested layout cannot hold the labels without breaking GS1 limits."""


@dataclass(frozen=True)
class Label:
    line: int
    code: str
    top: str | None = None
    bottom: str | None = None


@dataclass(frozen=True)
class Layout:
    page: tuple          # (w, h) mm
    label: tuple         # (w, h) mm
    cols: int
    rows: int
    margins: tuple       # top, right, bottom, left (mm)
    gap: tuple           # horizontal, vertical (mm)

    @property
    def per_page(self) -> int:
        return self.cols * self.rows

    def cell(self, index: int) -> tuple[float, float]:
        """Top-left corner (mm) of cell ``index`` (row-major) on a page."""
        col, row = index % self.cols, index // self.cols
        return (self.margins[3] + col * (self.label[0] + self.gap[0]),
                self.margins[0] + row * (self.label[1] + self.gap[1]))


def _preset(page, label, cols, rows, gap):
    lw, lh = label
    mx = (page[0] - cols * lw - (cols - 1) * gap) / 2
    my = (page[1] - rows * lh - (rows - 1) * gap) / 2
    return Layout(page, label, cols, rows, (my, mx, my, mx), (gap, gap))


PRESETS = {
    "a4-3x8": _preset((210, 297), (63.5, 33.9), 3, 8, 2.5),
    "a4-4x10": _preset((210, 297), (48.5, 25.4), 4, 10, 2.5),
    "roll-50x30": _preset((50, 30), (50, 30), 1, 1, 0),
    "roll-40x25": _preset((40, 25), (40, 25), 1, 1, 0),
}


def _pair(value, what):
    if isinstance(value, str):
        parts = [p for p in re.split(r"[x,;\s]+", value.strip().lower()) if p]
    else:
        parts = list(value)
    try:
        nums = tuple(float(p) for p in parts)
    except ValueError:
        raise LayoutError("invalid %s %r" % (what, value)) from None
    if len(nums) != 2 or min(nums) <= 0:
        raise LayoutError("%s must be two positive numbers (W x H), got %r" % (what, value))
    return nums


def _margins(value):
    parts = re.split(r"[,;\s]+", value.strip()) if isinstance(value, str) else (
        [value] if isinstance(value, (int, float)) else list(value))
    try:
        n = tuple(float(p) for p in parts if p != "")
    except ValueError:
        raise LayoutError("invalid margins %r" % (value,)) from None
    if len(n) not in (1, 2, 4) or min(n) < 0:
        raise LayoutError("margins must be 1, 2 (vertical, horizontal) or 4 (top, right, bottom, left) "
                          "non-negative numbers, got %r" % (value,))
    return {1: n * 4, 2: (n[0], n[1], n[0], n[1]), 4: n}[len(n)]


def _gap(value):
    parts = re.split(r"[,;\s]+", value.strip()) if isinstance(value, str) else (
        [value] if isinstance(value, (int, float)) else list(value))
    try:
        n = tuple(float(p) for p in parts if p != "")
    except ValueError:
        raise LayoutError("invalid gap %r" % (value,)) from None
    if len(n) not in (1, 2) or min(n) < 0:
        raise LayoutError("gap must be one or two (horizontal, vertical) non-negative numbers")
    return n * 2 if len(n) == 1 else n


def resolve_layout(layout="a4-3x8", *, page=None, label=None, cols=None, rows=None, margins=None, gap=None) -> Layout:
    """A preset name, or a custom grid (``page``, ``label``, ``cols`` and ``rows`` all given)."""
    custom = [x is not None for x in (page, label, cols, rows)]
    if any(custom):
        if not all(custom):
            raise LayoutError("a custom layout needs page, label, cols and rows together")
        if isinstance(page, str) and page.strip().lower() in PAGES:
            page = PAGES[page.strip().lower()]
        page, label = _pair(page, "page"), _pair(label, "label")
        gp = _gap(gap if gap is not None else 0)
        if int(cols) < 1 or int(rows) < 1:
            raise LayoutError("cols and rows must be at least 1")
        mx = (page[0] - int(cols) * label[0] - (int(cols) - 1) * gp[0]) / 2
        my = (page[1] - int(rows) * label[1] - (int(rows) - 1) * gp[1]) / 2
        lay = Layout(page, label, int(cols), int(rows), (my, mx, my, mx), gp)  # centred unless margins given
    else:
        if layout not in PRESETS:
            raise LayoutError("unknown layout %r (choose from %s)" % (layout, ", ".join(PRESETS)))
        lay = PRESETS[layout]
        if gap is not None:
            lay = Layout(lay.page, lay.label, lay.cols, lay.rows, lay.margins, _gap(gap))
    if margins is not None:
        lay = Layout(lay.page, lay.label, lay.cols, lay.rows, _margins(margins), lay.gap)
    t, r, b, l = lay.margins
    width = l + r + lay.cols * lay.label[0] + (lay.cols - 1) * lay.gap[0]
    height = t + b + lay.rows * lay.label[1] + (lay.rows - 1) * lay.gap[1]
    if width > lay.page[0] + 1e-6 or height > lay.page[1] + 1e-6:
        raise LayoutError("the %dx%d grid of %gx%g mm labels needs %.1fx%.1f mm but the page is %gx%g mm"
                          % (lay.cols, lay.rows, *lay.label, width, height, *lay.page))
    return lay


def read_rows(source) -> list[tuple[Label, int]]:
    """Parse and validate every row. Returns (label, copies) pairs, or raises :class:`SheetError`.

    ``source`` is a CSV path/text stream with columns ean (required), top, bottom, copies,
    or an iterable of dicts with the same keys (line numbers then count from 1).
    """
    if isinstance(source, (str, Path)):
        try:
            with open(source, newline="", encoding="utf-8-sig") as fh:
                text = fh.read()
        except UnicodeDecodeError as exc:
            raise SheetError([(1, "file is not valid UTF-8 (%s)" % exc.reason)]) from None
        lines = _csv_records(text)
    elif hasattr(source, "read"):
        lines = _csv_records(source.read())
    else:
        lines = [(i, {str(k).strip().lower(): ("" if v is None else str(v)) for k, v in row.items()})
                 for i, row in enumerate(source, 1)]
    errors, out = [], []
    for line, row in lines:
        if line == 0:  # header problem reported by _csv_records
            errors.append((1, row))
            continue
        try:
            code = normalize(row.get("ean", ""))
        except EAN13Error as exc:
            errors.append((line, "ean: %s" % exc if row.get("ean", "").strip() else "ean is empty"))
            code = None
        raw = row.get("copies", "").strip()
        copies = 1
        if raw:
            if not re.fullmatch(r"\d+", raw) or not 1 <= int(raw) <= MAX_COPIES:
                errors.append((line, "copies must be a whole number from 1 to %d, got %r" % (MAX_COPIES, raw)))
            else:
                copies = int(raw)
        if code:
            out.append((Label(line, code, row.get("top", "").strip() or None,
                              row.get("bottom", "").strip() or None), copies))
    if errors:
        raise SheetError(sorted(errors, key=lambda e: e[0]))
    if not out:
        raise SheetError([(1, "no label rows found")])
    return out


def _csv_records(text: str):
    first = text.split("\n", 1)[0]
    delim = ";" if first.count(";") > first.count(",") else ","
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delim)
    try:
        header = [h.strip().lower() for h in next(reader)]
    except StopIteration:
        return [(0, "file is empty")]
    if "ean" not in header:
        return [(0, "missing required column 'ean' (found: %s)" % ", ".join(header))]
    recs = []
    for row in reader:
        if not any(c.strip() for c in row):
            continue
        recs.append((reader.line_num, {h: (row[i] if i < len(row) else "") for i, h in enumerate(header)}))
    return recs


def choose_scale(labels, lay: Layout, scale, **style) -> float:
    """Common magnification for the whole sheet: ``scale`` if given, else 100 % shrunk (never below 80 %) to fit."""
    lw, lh = lay.label
    cache = {}

    def worst(s):
        """(width, height, line) of the biggest drawing among the labels at magnification s."""
        res = (0.0, 0.0, 0)
        for lab in labels:
            key = (lab.top, lab.bottom)
            if key not in cache or cache[key][0] != s:
                d = build_drawing(lab.code, module_mm=NOMINAL_MODULE_MM * s, top=lab.top, bottom=lab.bottom, **style)
                cache[key] = (s, d.width, d.height)
            _, w, h = cache[key]
            if w > res[0] + 1e-9 or h > res[1] + 1e-9:
                res = (max(w, res[0]), max(h, res[1]), lab.line)
        return res

    def fits(s):
        w, h, _ = worst(s)
        return w <= lw + 1e-6 and h <= lh + 1e-6

    if scale is not None:
        if not MIN_SCALE - 1e-9 <= scale <= MAX_SCALE + 1e-9:
            raise LayoutError("scale %.2f is outside the GS1 range %.1f-%.1f" % (scale, MIN_SCALE, MAX_SCALE))
        lo = scale
    else:
        lo = 1.0
        if not fits(1.0):
            lo = MIN_SCALE
    if not fits(lo):
        w, h, line = worst(lo)
        raise LayoutError("labels of %gx%g mm are too small: the symbol with its captions needs %.1fx%.1f mm at "
                          "%d%% magnification (line %d); GS1 allows no less than %d%%"
                          % (lw, lh, w, h, round(lo * 100), line, round(MIN_SCALE * 100)))
    if scale is not None or lo == 1.0:
        return lo
    hi = 1.0
    for _ in range(40):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if fits(mid) else (lo, mid)
    return lo


def _cut_marks(c, lay: Layout, page_h: float) -> None:
    t, r, b, l = lay.margins
    need = MARK_OFFSET_MM + MARK_LENGTH_MM
    if min(t, r, b, l) < need - 1e-9:
        raise LayoutError("cut marks need page margins of at least %g mm on every side" % need)
    c.setLineWidth(0.25)
    c.setStrokeColorRGB(0, 0, 0)
    xs = {round(lay.cell(i)[0] + dx, 4) for i in range(lay.cols) for dx in (0, lay.label[0])}
    ys = {round(lay.cell(j * lay.cols)[1] + dy, 4) for j in range(lay.rows) for dy in (0, lay.label[1])}
    top, bottom = t, lay.page[1] - b
    left, right = l, lay.page[0] - r

    def line(x1, y1, x2, y2):
        c.line(x1 * PT_PER_MM, (page_h - y1) * PT_PER_MM, x2 * PT_PER_MM, (page_h - y2) * PT_PER_MM)

    for x in xs:
        line(x, top - MARK_OFFSET_MM, x, top - need)
        line(x, bottom + MARK_OFFSET_MM, x, bottom + need)
    for y in ys:
        line(left - MARK_OFFSET_MM, y, left - need, y)
        line(right + MARK_OFFSET_MM, y, right + need, y)


def build_sheet(source, out=None, *, layout="a4-3x8", page=None, label=None, cols=None, rows=None,
                margins=None, gap=None, cut_marks=False, scale=None, no_digits=False, bold=False,
                font_size=8.0, font=None, verify_output=True) -> bytes:
    """Build a PDF label sheet. Nothing is produced (or written) unless every row is valid.

    ``page``/``label`` are "WxH" strings or (w, h) tuples in mm (``page`` may also be a name such as
    "A4"); ``margins`` is one number, "V,H" or "top,right,bottom,left" in mm; ``gap`` is mm.
    """
    lay = resolve_layout(layout, page=page, label=label, cols=cols, rows=rows, margins=margins, gap=gap)
    entries = read_rows(source)
    style = dict(no_digits=no_digits, bold=bold, font_size=font_size, font=font)
    s = choose_scale([lab for lab, _ in entries], lay, scale, **style)
    module = NOMINAL_MODULE_MM * s

    expanded = [lab for lab, n in entries for _ in range(n)]
    drawings = {}
    pw, ph = lay.page
    buf = io.BytesIO()
    c = new_canvas(buf, pw, ph)
    for start in range(0, len(expanded), lay.per_page):
        for idx, lab in enumerate(expanded[start:start + lay.per_page]):
            d = drawings.get((lab.code, lab.top, lab.bottom))
            if d is None:
                d = drawings[(lab.code, lab.top, lab.bottom)] = build_drawing(
                    lab.code, module_mm=module, top=lab.top, bottom=lab.bottom, **style)
            cx, cy = lay.cell(idx)
            draw_on_canvas(c, d, cx + (lay.label[0] - d.width) / 2, cy + (lay.label[1] - d.height) / 2, ph)
        if cut_marks:
            _cut_marks(c, lay, ph)
        c.showPage()
    c.save()
    data = buf.getvalue()
    if verify_output:
        _verify(data, expanded, lay)
    _write(out, data)
    return data


def _verify(pdf: bytes, expanded: list[Label], lay: Layout) -> None:
    pages = verify.pdf_page_rects(pdf)
    expected_pages = -(-len(expanded) // lay.per_page)
    if len(pages) != expected_pages:
        raise verify.VerificationError("PDF has %d pages, expected %d" % (len(pages), expected_pages))
    lw, lh = lay.label
    for p, (_, _, rects) in enumerate(pages):
        labels = expanded[p * lay.per_page:(p + 1) * lay.per_page]
        unassigned = list(rects)
        for idx, lab in enumerate(labels):
            x, y = lay.cell(idx)
            mine = [r for r in unassigned if x <= r.x + r.w / 2 <= x + lw and y <= r.y + r.h / 2 <= y + lh]
            unassigned = [r for r in unassigned if r not in mine]
            verify.check_rects(mine, lab.code, x, x + lw, "page %d, label %d (line %d)" % (p + 1, idx + 1, lab.line))
        if unassigned:
            raise verify.VerificationError("page %d has bars outside the label cells" % (p + 1))
