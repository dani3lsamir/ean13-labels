"""Command line interface: ``ean13 check|validate|label|sheet|verify``.

Exit codes: 0 success, 1 invalid input or failed verification, 2 usage error, 3 I/O or missing dependency.
"""

from __future__ import annotations

import argparse
import sys
import warnings
from pathlib import Path

from . import __version__
from .core import EAN13Error, normalize, validate
from .render import render_pdf, render_png, render_svg
from .sheet import PRESETS, build_sheet

OK, FAIL, USAGE, IO_ERROR = 0, 1, 2, 3


def _style(p: argparse.ArgumentParser) -> None:
    p.add_argument("--no-digits", action="store_true", help="omit the human-readable digits")
    p.add_argument("--bold", action=argparse.BooleanOptionalAction, default=False, help="bold captions")
    p.add_argument("--font-size", type=float, default=8.0, metavar="PT", help="caption size in points (default 8)")
    p.add_argument("--font", metavar="PATH", help="TTF/OTF font for digits and captions (default: bundled Liberation Sans)")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ean13", description="Generate correct EAN-13 barcodes (SVG, PNG, PDF).")
    p.add_argument("--version", action="version", version="ean13-labels " + __version__)
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("check", help="print the full 13-digit code for 12 digits")
    s.add_argument("code")

    s = sub.add_parser("validate", help="exit 0 if the 13-digit code has a correct check digit")
    s.add_argument("code")

    s = sub.add_parser("label", help="render one barcode")
    s.add_argument("code", help="12 or 13 digits (spaces and dashes allowed)")
    s.add_argument("--top", metavar="TEXT", help="caption above the barcode")
    s.add_argument("--bottom", metavar="TEXT", help="caption below the barcode")
    s.add_argument("--format", choices=["svg", "png", "pdf"], help="default: from --out, else svg")
    s.add_argument("--out", metavar="FILE", help="default: <code>.<format>")
    size = s.add_mutually_exclusive_group()
    size.add_argument("--scale", type=float, help="magnification 0.8-2.0 (1.0 = module 0.33 mm)")
    size.add_argument("--module-mm", type=float, help="module width in mm (warns outside the GS1 range)")
    s.add_argument("--dpi", type=int, default=600, help="PNG resolution (default 600)")
    _style(s)

    s = sub.add_parser("sheet", help="PDF label sheet from a CSV (ean, top, bottom, copies)")
    s.add_argument("csv")
    s.add_argument("--layout", default="a4-3x8", choices=sorted(PRESETS), help="preset (default a4-3x8)")
    s.add_argument("--page", help='custom page: "A4", "letter" or "WxH" mm')
    s.add_argument("--label", metavar="WxH", help="custom label size in mm")
    s.add_argument("--cols", type=int)
    s.add_argument("--rows", type=int)
    s.add_argument("--margins", help='mm: "all", "vertical,horizontal" or "top,right,bottom,left"')
    s.add_argument("--gap", help='mm between labels: "g" or "horizontal,vertical"')
    s.add_argument("--cut-marks", action="store_true", help="print crop marks in the page margins")
    s.add_argument("--scale", type=float, help="fixed magnification 0.8-2.0 (default: 1.0, shrunk to fit but never below 0.8)")
    s.add_argument("--out", default="labels.pdf", metavar="FILE")
    _style(s)

    s = sub.add_parser("verify", help="decode an image with zxing-cpp (needs the [scan] extra)")
    s.add_argument("image")
    s.add_argument("--expect", metavar="CODE", help="fail unless the barcode reads as this code")
    return p


def _cmd_label(a) -> int:
    code = normalize(a.code)
    fmt = a.format or (Path(a.out).suffix.lstrip(".").lower() if a.out else "svg")
    if fmt not in ("svg", "png", "pdf"):
        raise EAN13Error("cannot tell the format from %r; use --format svg|png|pdf" % a.out)
    out = a.out or "%s.%s" % (code, fmt)
    kw = dict(scale=a.scale, module_mm=a.module_mm, no_digits=a.no_digits, top=a.top, bottom=a.bottom,
              bold=a.bold, font_size=a.font_size, font=a.font)
    if fmt == "svg":
        render_svg(code, out, **kw)
    elif fmt == "png":
        render_png(code, out, dpi=a.dpi, **kw)
    else:
        render_pdf(code, out, **kw)
    print("wrote %s (EAN-13 %s, verified)" % (out, code))
    return OK


def _cmd_sheet(a) -> int:
    build_sheet(a.csv, a.out, layout=a.layout, page=a.page, label=a.label, cols=a.cols, rows=a.rows,
                margins=a.margins, gap=a.gap, cut_marks=a.cut_marks, scale=a.scale, no_digits=a.no_digits,
                bold=a.bold, font_size=a.font_size, font=a.font)
    print("wrote %s (all labels verified)" % a.out)
    return OK


def _cmd_verify(a) -> int:
    try:
        import zxingcpp
    except ImportError:
        print("error: 'verify' needs zxing-cpp. Install it with: pip install \"ean13-labels[scan]\"", file=sys.stderr)
        return IO_ERROR
    from PIL import Image

    with Image.open(a.image) as img:
        found = [r for r in zxingcpp.read_barcodes(img) if "EAN" in str(r.format).upper()]
    if not found:
        print("error: no EAN barcode found in %s" % a.image, file=sys.stderr)
        return FAIL
    got = found[0].text
    print("%s %s" % (found[0].format, got))
    if a.expect and got != normalize(a.expect):
        print("error: expected %s" % normalize(a.expect), file=sys.stderr)
        return FAIL
    return OK


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            try:
                if args.command == "check":
                    print(normalize(args.code))
                    return OK
                if args.command == "validate":
                    code = args.code.strip()
                    if validate(code):
                        print("OK %s" % code)
                        return OK
                    if len(code) == 12:
                        raise EAN13Error("only 12 digits; 'ean13 check' adds the check digit")
                    normalize(code)  # raises with the precise reason
                    raise EAN13Error("%r is not a plain 13-digit code" % code)
                rc = {"label": _cmd_label, "sheet": _cmd_sheet, "verify": _cmd_verify}[args.command](args)
            finally:
                for w in caught:
                    print("warning: %s" % w.message, file=sys.stderr)
        return rc
    except EAN13Error as exc:
        print("error: %s" % exc, file=sys.stderr)
        return FAIL
    except OSError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return IO_ERROR


if __name__ == "__main__":
    sys.exit(main())
