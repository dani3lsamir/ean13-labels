"""EAN-13 maths and symbol encoding. Pure Python, no dependencies."""

from __future__ import annotations

import re

__all__ = ["EAN13Error", "check_digit", "validate", "normalize", "encode", "decode_modules"]


class EAN13Error(ValueError):
    """Invalid EAN-13 data (bad code, bad module string, failed verification)."""


# Left-hand encodings. L = odd parity, G = even parity; R is the bitwise complement of L.
_L = ["0001101", "0011001", "0010011", "0111101", "0100011",
      "0110001", "0101111", "0111011", "0110111", "0001011"]
_G = ["0100111", "0110011", "0011011", "0100001", "0011101",
      "0111001", "0000101", "0010001", "0001001", "0010111"]
_R = ["".join("1" if b == "0" else "0" for b in s) for s in _L]

# Parity of the six left digits, selected by the first digit.
_PARITY = ["LLLLLL", "LLGLGG", "LLGGLG", "LLGGGL", "LGLLGG",
           "LGGLLG", "LGGGLL", "LGLGLG", "LGLGGL", "LGGLGL"]

START = "101"
CENTRE = "01010"
END = "101"
MODULES = 95


def check_digit(d12: str) -> int:
    """Check digit for the first 12 digits (weights 1,3,1,3,... from the left)."""
    if not re.fullmatch(r"\d{12}", d12):
        raise EAN13Error("expected exactly 12 digits, got %r" % (d12,))
    total = sum(int(c) * (3 if i % 2 else 1) for i, c in enumerate(d12))
    return (10 - total % 10) % 10


def validate(code: str) -> bool:
    """True if ``code`` is 13 digits with a correct check digit."""
    return bool(re.fullmatch(r"\d{13}", code)) and check_digit(code[:12]) == int(code[12])


def normalize(value: str) -> str:
    """Return the 13-digit code for ``value``.

    Accepts 12 digits (check digit is appended) or 13 digits (check digit is verified),
    with optional spaces or dashes. Raises :class:`EAN13Error` otherwise.
    """
    if not isinstance(value, str):
        value = str(value)
    digits = re.sub(r"[\s-]", "", value)
    if not re.fullmatch(r"\d+", digits):
        raise EAN13Error("%r contains characters other than digits, spaces and dashes" % value)
    if len(digits) == 12:
        return digits + str(check_digit(digits))
    if len(digits) == 13:
        expected = check_digit(digits[:12])
        if int(digits[12]) != expected:
            raise EAN13Error("bad check digit in %s: expected %d, got %s" % (digits, expected, digits[12]))
        return digits
    raise EAN13Error("expected 12 or 13 digits, got %d" % len(digits))


def encode(code: str) -> str:
    """95-module string ('1' = bar, '0' = space) for a valid 12/13-digit code."""
    code = normalize(code)
    parity = _PARITY[int(code[0])]
    left = "".join((_L if p == "L" else _G)[int(d)] for p, d in zip(parity, code[1:7]))
    right = "".join(_R[int(d)] for d in code[7:])
    return START + left + CENTRE + right + END


def decode_modules(bits: str) -> str:
    """Inverse of :func:`encode`. Returns the 13 digits; raises on any inconsistency."""
    if len(bits) != MODULES or set(bits) - {"0", "1"}:
        raise EAN13Error("expected %d modules of 0/1, got %d" % (MODULES, len(bits)))
    if bits[:3] != START or bits[45:50] != CENTRE or bits[92:] != END:
        raise EAN13Error("guard patterns not found")
    first, left = "", ""
    for i in range(6):
        group = bits[3 + 7 * i: 10 + 7 * i]
        if group in _L:
            first, left = first + "L", left + str(_L.index(group))
        elif group in _G:
            first, left = first + "G", left + str(_G.index(group))
        else:
            raise EAN13Error("invalid left digit pattern %s" % group)
    if first not in _PARITY:
        raise EAN13Error("invalid parity pattern %s" % first)
    right = ""
    for i in range(6):
        group = bits[50 + 7 * i: 57 + 7 * i]
        if group not in _R:
            raise EAN13Error("invalid right digit pattern %s" % group)
        right += str(_R.index(group))
    code = str(_PARITY.index(first)) + left + right
    if not validate(code):
        raise EAN13Error("decoded %s has a bad check digit" % code)
    return code
