"""Font handling. Liberation Sans (SIL OFL 1.1) is bundled so no system fonts are needed."""

from __future__ import annotations

import functools
from dataclasses import dataclass
from pathlib import Path

from PIL import ImageFont

from .core import EAN13Error

FONT_DIR = Path(__file__).parent / "fonts"
_REF = 1000  # reference pixel size used for measuring


@dataclass(frozen=True)
class Font:
    regular: str
    bold: str

    def path(self, bold: bool = False) -> str:
        return self.bold if bold else self.regular


def resolve_font(font: str | Path | None = None) -> Font:
    """``font`` (a TTF/OTF path) is used for both weights; otherwise the bundled one."""
    if font is None:
        return Font(str(FONT_DIR / "LiberationSans-Regular.ttf"), str(FONT_DIR / "LiberationSans-Bold.ttf"))
    path = Path(font)
    if not path.is_file():
        raise EAN13Error("font file not found: %s" % font)
    try:
        _load(str(path))
    except OSError as exc:
        raise EAN13Error("cannot read font %s: %s" % (font, exc)) from exc
    return Font(str(path), str(path))


@functools.lru_cache(maxsize=16)
def _load(path: str) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, _REF)


def family(path: str) -> str:
    return _load(path).getname()[0]


def text_width_mm(path: str, text: str, size_mm: float) -> float:
    return _load(path).getlength(text) / _REF * size_mm


def digit_metrics(path: str) -> tuple[float, float]:
    """(height of a digit, widest digit advance), both in em."""
    f = _load(path)
    height = max(-f.getbbox(d, anchor="ls")[1] for d in "0123456789") / _REF
    width = max(f.getlength(d) for d in "0123456789") / _REF
    return height, width
