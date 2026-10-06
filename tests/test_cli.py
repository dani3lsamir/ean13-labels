import io

import pytest
from PIL import Image

from ean13_tools.cli import main

A, B = "4006381333931", "5901234123457"


def run(capsys, *argv):
    rc = main(list(argv))
    cap = capsys.readouterr()
    return rc, cap.out, cap.err


def test_check_and_validate(capsys):
    assert run(capsys, "check", "400638133393") == (0, A + "\n", "")
    assert run(capsys, "check", "400-6381 33393")[1] == A + "\n"
    assert run(capsys, "validate", A)[0] == 0
    rc, _, err = run(capsys, "validate", "4006381333932")
    assert rc == 1 and "check digit" in err
    assert run(capsys, "validate", "400638133393")[0] == 1
    assert run(capsys, "validate", "abc")[0] == 1
    assert run(capsys, "check", "123")[0] == 1


def test_label_formats(capsys, tmp_path):
    for fmt, magic in (("svg", b"<?xml"), ("png", b"\x89PNG"), ("pdf", b"%PDF")):
        out = tmp_path / ("x." + fmt)
        rc, stdout, _ = run(capsys, "label", A, "--top", "SKU", "--bottom", "Lot 7", "--bold", "--out", str(out))
        assert rc == 0 and out.read_bytes().startswith(magic) and A in stdout


def test_label_format_flag_and_default_name(capsys, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert run(capsys, "label", "400638133393", "--format", "png", "--dpi", "300")[0] == 0
    assert (tmp_path / (A + ".png")).exists()
    assert run(capsys, "label", A)[0] == 0 and (tmp_path / (A + ".svg")).exists()
    assert run(capsys, "label", A, "--out", "noext")[0] == 1


def test_label_errors_and_warnings(capsys, tmp_path):
    assert run(capsys, "label", "4006381333932", "--out", str(tmp_path / "a.svg"))[0] == 1
    assert run(capsys, "label", A, "--scale", "3", "--out", str(tmp_path / "a.svg"))[0] == 1
    rc, _, err = run(capsys, "label", A, "--module-mm", "0.9", "--out", str(tmp_path / "a.svg"))
    assert rc == 0 and "warning" in err and "GS1" in err
    assert run(capsys, "label", A, "--out", str(tmp_path / "missing" / "a.svg"))[0] == 3
    with pytest.raises(SystemExit) as exc:
        main(["label", A, "--scale", "1", "--module-mm", "0.33"])
    assert exc.value.code == 2


def test_sheet(capsys, tmp_path):
    csv_path = tmp_path / "c.csv"
    csv_path.write_text("ean,top,copies\n%s,A,2\n%s,B,\n" % (A, B))
    out = tmp_path / "s.pdf"
    assert run(capsys, "sheet", str(csv_path), "--layout", "a4-3x8", "--cut-marks", "--out", str(out))[0] == 0
    assert out.read_bytes().startswith(b"%PDF")
    csv_path.write_text("ean\n1\n%s\n2\n" % A)
    out2 = tmp_path / "t.pdf"
    rc, _, err = run(capsys, "sheet", str(csv_path), "--out", str(out2))
    assert rc == 1 and "line 2" in err and "line 4" in err and not out2.exists()
    assert run(capsys, "sheet", str(tmp_path / "nope.csv"))[0] == 3


def test_verify(capsys, tmp_path):
    pytest.importorskip("zxingcpp")
    png = tmp_path / "a.png"
    assert run(capsys, "label", A, "--top", "T", "--out", str(png))[0] == 0
    rc, out, _ = run(capsys, "verify", str(png), "--expect", A)
    assert rc == 0 and A in out
    assert run(capsys, "verify", str(png), "--expect", B)[0] == 1
    blank = tmp_path / "b.png"
    Image.new("L", (200, 100), 255).save(blank)
    assert run(capsys, "verify", str(blank))[0] == 1


def test_verify_without_zxing(capsys, tmp_path, monkeypatch):
    monkeypatch.setitem(__import__("sys").modules, "zxingcpp", None)
    rc, _, err = run(capsys, "verify", str(tmp_path / "x.png"))
    assert rc == 3 and "ean13-labels[scan]" in err
