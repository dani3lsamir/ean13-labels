import random

import pytest

from ean13_tools import EAN13Error, check_digit, decode_modules, encode, normalize, validate

# GS1 General Specifications tables, written independently of the implementation:
# each digit as (L pattern, G pattern, R pattern) given as integers of 7 bits.
GS1 = {
    0: (0b0001101, 0b0100111, 0b1110010),
    1: (0b0011001, 0b0110011, 0b1100110),
    2: (0b0010011, 0b0011011, 0b1101100),
    3: (0b0111101, 0b0100001, 0b1000010),
    4: (0b0100011, 0b0011101, 0b1011100),
    5: (0b0110001, 0b0111001, 0b1001110),
    6: (0b0101111, 0b0000101, 0b1010000),
    7: (0b0111011, 0b0010001, 0b1000100),
    8: (0b0110111, 0b0001001, 0b1001000),
    9: (0b0001011, 0b0010111, 0b1110100),
}
# first digit -> which of the six left digits use G (1) instead of L (0)
GS1_PARITY = {0: 0b000000, 1: 0b001011, 2: 0b001101, 3: 0b001110, 4: 0b010011,
              5: 0b011001, 6: 0b011100, 7: 0b010101, 8: 0b010110, 9: 0b011010}


def reference_modules(code):
    digits = [int(c) for c in code]
    out = "101"
    for i, d in enumerate(digits[1:7]):
        g = (GS1_PARITY[digits[0]] >> (5 - i)) & 1
        out += format(GS1[d][g], "07b")
    out += "01010"
    for d in digits[7:]:
        out += format(GS1[d][2], "07b")
    return out + "101"


PUBLIC = ["4006381333931", "5901234123457", "9780201379624"]


@pytest.mark.parametrize("code", PUBLIC)
def test_known_codes(code):
    assert validate(code)
    assert check_digit(code[:12]) == int(code[12])
    assert encode(code) == reference_modules(code)
    assert len(encode(code)) == 95
    assert decode_modules(encode(code)) == code


def test_known_module_string():
    # 4 -> parity LGLLGG; left digits 0 0 6 3 8 1; right digits 3 3 3 9 3 1
    expected = ("101"
                "0001101" "0100111" "0101111" "0111101" "0001001" "0110011"
                "01010"
                "1000010" "1000010" "1000010" "1110100" "1000010" "1100110"
                "101")
    assert encode("4006381333931") == expected


def test_normalize():
    assert normalize("400638133393") == "4006381333931"
    assert normalize("4006381333931") == "4006381333931"
    assert normalize("400-6381 33393 1") == "4006381333931"
    for bad in ["4006381333932", "40063813339", "40063813339311", "40063a133393", ""]:
        with pytest.raises(EAN13Error):
            normalize(bad)


def test_validate():
    assert validate("5901234123457")
    assert not validate("5901234123458")
    assert not validate("590123412345")
    assert not validate("59012341234x7")


def test_random_roundtrip():
    rng = random.Random(20240601)
    for _ in range(500):
        d12 = "".join(rng.choice("0123456789") for _ in range(12))
        code = d12 + str(check_digit(d12))
        bits = encode(code)
        assert bits == reference_modules(code)
        assert decode_modules(bits) == code


def test_decode_rejects_garbage():
    bits = encode(PUBLIC[0])
    with pytest.raises(EAN13Error):
        decode_modules(bits[:-1])
    with pytest.raises(EAN13Error):
        decode_modules("0" + bits[1:])
    flipped = bits[:10] + ("1" if bits[10] == "0" else "0") + bits[11:]
    with pytest.raises(EAN13Error):
        decode_modules(flipped)
