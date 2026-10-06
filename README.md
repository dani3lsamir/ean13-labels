# ean13-labels

A small, well-tested Python library and command line tool that generates **correct EAN-13 barcodes**
as SVG, PNG and print-ready PDF label sheets, following the GS1 size and quiet-zone rules.

* Pure-Python core (check digit, encoding, decoding) with no dependencies.
* Sizes are real millimetres: SVG is exact vector, PNG carries its DPI, PDF is cut to size.
* **Every rendering is decoded again before it is returned**: SVG/PDF from the drawn geometry, PNG from
  the pixels. If the result does not read back as the same 13 digits, nothing is written and the command fails.
* CSV label sheets (A4 3x8, A4 4x10, 50x30 and 40x25 mm rolls, or a custom grid) with optional cut marks.
* No web server, no GUI.

> **A valid barcode needs a licensed GS1 company prefix.** This tool only draws the symbol for a number you
> already own; it does **not** allocate numbers. Printing a code you were not assigned can collide with
> someone else's product. Get your prefix from your national GS1 member organisation (https://www.gs1.org).

## Install

```bash
pip install .            # or: pip install -e ".[dev]" for the test suite
pip install ".[scan]"    # optional: enables `ean13 verify` (zxing-cpp)
```

Python >= 3.10 on Windows, macOS and Linux. A sans font (Liberation Sans, SIL OFL 1.1) is bundled, so no
system fonts are needed.

### Why Pillow and ReportLab

* **Pillow** draws the PNG and measures text, the one job a raster library is needed for.
* **ReportLab** writes the PDF: it embeds TrueType subsets, gives exact vector rectangles in points, can write
  uncompressed page content (so the PDF geometry can be parsed back for verification) and has a
  byte-reproducible mode. `fpdf2` would also work but pulls in more transitive dependencies (fontTools,
  defusedxml) and compresses content by default.

## CLI

```bash
ean13 check 400638133393                 # -> 4006381333931  (adds the check digit)
ean13 validate 4006381333931             # exit 0 if valid, 1 if not

# one label, no caption (SVG by default; file is named after the code)
ean13 label 5901234123457

# with captions, bold, as PNG at 600 dpi (default) or as PDF
ean13 label 4006381333931 --top "SKU-1234" --bottom "Lot 7" --bold --out label.png
ean13 label 4006381333931 --format pdf --out label.pdf

# size: magnification 0.8-2.0 (1.0 = 0.33 mm module) or an explicit module width
ean13 label 9780201379624 --scale 1.5
ean13 label 9780201379624 --module-mm 0.4
ean13 label 9780201379624 --no-digits --font ./OCRB.ttf --font-size 9

# sheets
ean13 sheet codes.csv --layout a4-3x8 --cut-marks --out labels.pdf
ean13 sheet codes.csv --page A4 --label 45x25 --cols 4 --rows 10 --margins 10,5 --gap 2 --out custom.pdf

# optional: decode an image with an independent reader (needs the [scan] extra)
ean13 verify label.png --expect 4006381333931
```

Options of `label`: `--top`, `--bottom`, `--bold/--no-bold`, `--font-size PT` (default 8), `--font PATH`,
`--scale`, `--module-mm` (mutually exclusive), `--no-digits`, `--dpi`, `--format`, `--out`.
There is no caption unless you ask for one.

Exit codes: `0` success, `1` invalid input / failed verification / label does not fit, `2` usage error,
`3` I/O error or `verify` without zxing-cpp installed. Warnings (for example a module width outside the GS1
range) go to stderr.

### Sheets

`codes.csv` columns: `ean` (required, 12 or 13 digits, spaces/dashes allowed), `top`, `bottom`, `copies`
(optional, empty means 1). Comma or semicolon separated, UTF-8 (BOM accepted).

```csv
ean,top,bottom,copies
4006381333931,SKU-0001,Sample A,6
5901234123457,SKU-0002,,
```

All rows are validated first. Every bad row is reported with its line number and nothing is generated:

```
error: line 3: ean: bad check digit in 4006381333932: expected 1, got 2
line 5: copies must be a whole number from 1 to 10000, got 'abc'
```

| Preset       | Page      | Label (mm)  | Grid  | Notes                              |
|--------------|-----------|-------------|-------|------------------------------------|
| `a4-3x8`     | A4        | 63.5 x 33.9 | 3 x 8 | 24 labels, 2.5 mm gaps |
| `a4-4x10`    | A4        | 48.5 x 25.4 | 4 x 10| 40 labels, 2.5 mm gaps             |
| `roll-50x30` | 50 x 30   | 50 x 30     | 1 x 1 | one label per page                 |
| `roll-40x25` | 40 x 25   | 40 x 25     | 1 x 1 | one label per page                 |

Custom: `--page A4|A3|A5|A6|letter|legal|WxH`, `--label WxH`, `--cols`, `--rows`, `--margins` (`all`,
`vertical,horizontal` or `top,right,bottom,left`; default: grid centred), `--gap` (`g` or `horizontal,vertical`).
`--cut-marks` prints crop marks in the page margins (which need at least 2.5 mm; presets for rolls have none).

Each barcode, **including its quiet zones**, is centred in its cell. The default magnification is 100 %; if a
symbol with its captions does not fit it is shrunk uniformly for the whole sheet, but **never below 80 %**: the
command fails with an explanation instead. `--scale` fixes the magnification (0.8-2.0).

## Library

```python
from ean13_tools import render_svg, render_png, render_pdf, build_sheet, check_digit, encode

svg = render_svg("4006381333931", out="a.svg", top="SKU-1234", bold=True)        # str
png = render_png("4006381333931", out="a.png", dpi=600, scale=1.5, bottom="Lot 7")  # bytes
pdf = render_pdf("4006381333931", out="a.pdf", no_digits=True)                   # bytes

build_sheet("codes.csv", "labels.pdf", layout="a4-3x8", cut_marks=True)
build_sheet([{"ean": "5901234123457", "copies": "3"}], "roll.pdf", layout="roll-50x30", font_size=7)

check_digit("400638133393")   # 1
encode("4006381333931")       # 95-character module string, '1' = bar
```

Keyword arguments mirror the CLI: `scale`, `module_mm`, `no_digits`, `top`, `bottom`, `bold`, `font_size`, `font`,
`dpi` (PNG) and, for sheets, `layout`, `page`, `label`, `cols`, `rows`, `margins`, `gap`, `cut_marks`.
Errors derive from `EAN13Error` (`SheetError` carries `.errors` as `(line, reason)` pairs, `LayoutError`,
`VerificationError`). Out-of-range module widths raise a `GS1Warning`.

## GS1 rules implemented

| Item | Value |
|------|-------|
| Module (X dimension) at 100 % | 0.33 mm |
| Magnification | 80 % - 200 % (`--scale`); `--module-mm` outside it only warns |
| Symbol | 95 modules: 101 + 6 digits + 01010 + 6 digits + 101; parity of the left half from the first digit |
| Quiet zones | 11 modules left, 7 modules right (always kept, also on sheets) |
| Bars at 100 % | 22.85 mm high; guard bars extend 5 modules (1.65 mm) lower |
| Human-readable digits | first digit left of the symbol, then 6 + 6 under the halves; 2.75 mm high at 100 % |
| Size at 100 % | 37.29 x 25.93 mm including quiet zones and digits (files add 0.17 mm below the digits so round glyphs are not clipped) |

Heights scale with the magnification. Captions are not part of the GS1 symbol: they are placed outside the bars,
centred on them, and never reduce the quiet zones.

Notes:

* The digits use the bundled Liberation Sans, **not OCR-B**, which GS1 specifies for human-readable digits. Pass
  `--font` with an OCR-B font if you need strict conformance.
* SVG text is plain `<text>` using the font family name, so viewers need that font (or fall back to Arial/Helvetica);
  PNG and PDF always use the bundled font. The bars are exact either way.
* Print at 100 % ("actual size"), without scaling, and test with a real scanner.

## Development

```bash
pip install -e ".[dev]"
pytest
```

The suite compares check digits and complete module strings of public example codes with GS1 tables written
independently in the tests, round-trips random codes through SVG/PNG/PDF, and decodes rendered PNGs (and a
rasterised sheet, when `pdftoppm` is available) with zxing-cpp.

The files in `examples/` use only public example codes (4006381333931, 5901234123457, 9780201379624).

## Licence

MIT, see `LICENSE`. The bundled Liberation Sans fonts are under the SIL Open Font License 1.1
(`src/ean13_tools/fonts/LICENSE-LiberationSans.txt`).

## Uso rápido

```bash
pip install .
ean13 check 400638133393                       # calcula el dígito de control -> 4006381333931
ean13 label 4006381333931 --top "SKU-1234" --bold --out etiqueta.png
ean13 sheet codigos.csv --layout a4-3x8 --cut-marks --out etiquetas.pdf
```

El CSV lleva las columnas `ean` (obligatoria), `top`, `bottom` y `copies` (opcional; vacío = 1). Si alguna fila es
inválida se informa de todas con su número de línea y no se genera nada. El tamaño nominal es 100 % (módulo de
0,33 mm); nunca se reduce por debajo del 80 %, y las zonas en blanco (11 módulos a la izquierda, 7 a la derecha) se
respetan siempre. Imprima al 100 % sin ajustar a la página. **Un código de barras válido requiere un prefijo de
empresa GS1 con licencia**: esta herramienta no asigna números.
