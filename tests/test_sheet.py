import pytest

from ean13_tools import EAN13Error, build_sheet
from ean13_tools.sheet import LayoutError, SheetError, read_rows, resolve_layout, PRESETS
from ean13_tools.verify import pdf_page_rects

A, B, C = "4006381333931", "5901234123457", "9780201379624"


def write(tmp_path, text, name="codes.csv", encoding="utf-8"):
    p = tmp_path / name
    p.write_bytes(text.encode(encoding))
    return p


def test_bad_rows_reported_with_line_numbers_and_nothing_generated(tmp_path):
    csv_path = write(tmp_path, "ean,top,bottom,copies\n"
                               "4006381333931,ok,,\n"
                               "4006381333932,wrong check digit,,\n"      # line 3
                               "\n"
                               "12345,too short,,\n"                      # line 5
                               "5901234123457,,,0\n"                      # line 6
                               "5901234123457,,,abc\n"                    # line 7
                               ",empty,,\n"                               # line 8
                               "9780201379624,fine,,2\n")
    out = tmp_path / "out.pdf"
    with pytest.raises(SheetError) as exc:
        build_sheet(csv_path, out)
    assert [line for line, _ in exc.value.errors] == [3, 5, 6, 7, 8]
    assert "line 3" in str(exc.value) and "check digit" in str(exc.value)
    assert not out.exists()


def test_missing_ean_column_and_empty_file(tmp_path):
    with pytest.raises(SheetError, match="missing required column 'ean'"):
        read_rows(write(tmp_path, "code,top\n1,2\n"))
    with pytest.raises(SheetError):
        read_rows(write(tmp_path, "ean\n"))
    with pytest.raises(SheetError):
        read_rows(write(tmp_path, ""))


def test_csv_dialects(tmp_path):
    p = write(tmp_path, "ean;top;copies\n400-6381 33393 1;Ñandú;2\n590123412345;;\n", encoding="utf-8-sig")
    rows = read_rows(p)
    assert [(lab.code, lab.top, n) for lab, n in rows] == [(A, "Ñandú", 2), (B, None, 1)]
    assert [lab.line for lab, _ in rows] == [2, 3]


def test_page_count_and_copies(tmp_path):
    p = write(tmp_path, "ean,copies\n%s,20\n%s,\n%s,4\n" % (A, B, C))  # 25 labels, 24 per page
    pdf = build_sheet(p, layout="a4-3x8")
    pages = pdf_page_rects(pdf)
    assert len(pages) == 2
    assert [len(r) for _, _, r in pages][1] == 1 * len(pages[1][2]) and len(pages[1][2]) < len(pages[0][2])
    assert pages[0][0] == pytest.approx(210, abs=0.01) and pages[0][1] == pytest.approx(297, abs=0.01)


def test_roll_layout_one_label_per_page():
    pdf = build_sheet([{"ean": A, "copies": "3"}, {"ean": B}], layout="roll-50x30")
    pages = pdf_page_rects(pdf)
    assert len(pages) == 4
    assert pages[0][0] == pytest.approx(50, abs=0.01) and pages[0][1] == pytest.approx(30, abs=0.01)


def test_quiet_zones_preserved_on_sheet():
    rows = [{"ean": A, "top": "SKU"}, {"ean": B}, {"ean": C, "bottom": "x"}]
    lay = PRESETS["a4-4x10"]
    pdf = build_sheet(rows, layout="a4-4x10", font_size=6)
    (_, _, rects), = pdf_page_rects(pdf)
    for idx in range(3):
        x, y = lay.cell(idx)
        mine = [r for r in rects if x <= r.x <= x + lay.label[0] and y <= r.y <= y + lay.label[1]]
        module = min(r.w for r in mine)
        left = min(r.x for r in mine) - x
        right = x + lay.label[0] - max(r.x + r.w for r in mine)
        assert left >= 11 * module - 1e-3
        assert right >= 7 * module - 1e-3
        # centred in the cell (the 11 + 95 + 7 module box)
        assert left - right == pytest.approx(4 * module, abs=1e-2)


def test_default_is_100_percent_and_shrinks_only_to_fit():
    big = pdf_page_rects(build_sheet([{"ean": A}], layout="a4-3x8"))[0][2]
    assert min(r.w for r in big) == pytest.approx(0.33, abs=1e-3)
    # 40x25 mm is a hair too short for 100 %: shrunk, but not below 80 %
    small = pdf_page_rects(build_sheet([{"ean": A}], layout="roll-40x25"))[0][2]
    m = min(r.w for r in small)
    assert 0.8 * 0.33 <= m < 0.33


def test_minimum_magnification_enforced():
    with pytest.raises(LayoutError, match="80%"):
        build_sheet([{"ean": A}], page="30x20", label="30x20", cols=1, rows=1)
    # a caption that needs more room than 80 % leaves also fails instead of shrinking further
    with pytest.raises(LayoutError, match="80%"):
        build_sheet([{"ean": A, "top": "T", "bottom": "B"}], layout="a4-4x10", font_size=12)
    with pytest.raises(LayoutError):
        build_sheet([{"ean": A}], layout="roll-50x30", scale=0.7)
    with pytest.raises(LayoutError, match="too small"):
        build_sheet([{"ean": A}], layout="roll-40x25", scale=1.0)


def test_explicit_scale_used_exactly():
    rects = pdf_page_rects(build_sheet([{"ean": A}], layout="a4-3x8", scale=0.9))[0][2]
    assert min(r.w for r in rects) == pytest.approx(0.33 * 0.9, abs=1e-3)


def test_custom_layout_and_margins():
    pdf = build_sheet([{"ean": A, "copies": "7"}], page="A4", label="45x25", cols=4, rows=10,
                      margins="10,5", gap="2")
    assert len(pdf_page_rects(pdf)) == 1
    lay = resolve_layout(page="100x100", label="40x40", cols=2, rows=2, margins="5,6,7,8", gap="1,2")
    assert lay.margins == (5, 6, 7, 8) and lay.gap == (1, 2)
    assert lay.cell(3) == (8 + 41, 5 + 42)
    with pytest.raises(LayoutError):
        resolve_layout(page="100x100", label="60x40", cols=2, rows=2)       # does not fit the page
    with pytest.raises(LayoutError):
        resolve_layout(page="100x100", label="40x40")                       # incomplete custom layout
    with pytest.raises(LayoutError):
        resolve_layout("nope")


def test_cut_marks():
    plain = build_sheet([{"ean": A}], layout="a4-3x8")
    marked = build_sheet([{"ean": A}], layout="a4-3x8", cut_marks=True)
    assert len(marked) > len(plain)
    assert pdf_page_rects(marked)[0][2] == pdf_page_rects(plain)[0][2]   # marks are lines, bars untouched
    with pytest.raises(LayoutError, match="cut marks"):
        build_sheet([{"ean": A}], layout="roll-50x30", cut_marks=True)


def test_output_file_written(tmp_path):
    out = tmp_path / "labels.pdf"
    build_sheet([{"ean": A}], out, layout="a4-3x8")
    assert out.read_bytes().startswith(b"%PDF-")


def test_invalid_row_in_dict_source():
    with pytest.raises(EAN13Error):
        build_sheet([{"ean": "123"}])
