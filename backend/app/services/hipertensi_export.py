"""Render the Hipertensi (blood-pressure) export workbook from dashboard data.

Loads the committed template ``app/data/hipertensi_template.xlsx`` (built by
``app.data.build_hipertensi_template``), fills the ``Hipertensi - Puskesmas``
sheet's data columns (A..AD) from row 4 down, and patches the formula ranges to
the real row count. The Terkendali columns (AE..BG) and the ``Hipertensi - Rekap``
recap sheet stay as *formulas* — Excel computes them on open — so the exported
file behaves exactly like the master template.

Two formula shapes coexist on the Puskesmas sheet:

- ``AF4:AU4`` — spilling dynamic-array (``MAP``/``LAMBDA``) formulas whose range
  bounds are the literal ``1003`` (the template's last row). We rewrite that
  literal to the export's last data row in both the formula text and its ``ref``
  (same technique ``app.services.gdp_export`` uses for ``33766``).
- ``AV4:BG4`` — per-row plain formulas (``Status Jan..Des``). openpyxl does not
  fill-down, so each data row needs its own row-shifted copy.

Generation strategy (fast path): openpyxl builds the *base* workbook — the
template with row 4 (the first NIK) filled and the array formulas resized — so
all the fiddly parts (styles.xml, the Rekap sheet, namespaces, the row-4
formulas) are produced by the tested library. Rows 5+ are then appended as raw
``<row>`` XML spliced into the saved sheet. This avoids openpyxl's per-cell
object model and ``save()`` over tens of thousands of formula cells, which is
~12x faster at large NIK counts (5k NIKs: ~6.2s → ~0.5s) while producing a
byte-equivalent file. The per-row ``Status`` formulas are pre-tokenized once
(see ``_status_formula_templates``) instead of re-translated per row.
"""

from __future__ import annotations

import re
import zipfile
from datetime import date
from io import BytesIO
from pathlib import Path
from typing import TypedDict

import openpyxl
from openpyxl.formula.tokenizer import Token, Tokenizer
from openpyxl.utils import column_index_from_string, get_column_letter
from openpyxl.worksheet.formula import ArrayFormula

_TEMPLATE_PATH = (
    Path(__file__).resolve().parents[1] / "data" / "hipertensi_template.xlsx"
)

# Hipertensi - Puskesmas sheet layout (1-based columns).
_SHEET = "Hipertensi - Puskesmas"
# The Puskesmas sheet is the workbook's first sheet → openpyxl writes it as
# ``sheet1.xml``. The raw-XML splice targets that part directly.
_SHEET_PART = "xl/worksheets/sheet1.xml"
_DATA_START_ROW = 4
_COL_NAMA_PUSKESMAS = 1  # A
_COL_TAHUN = 2  # B
_COL_NAMA = 3  # C
_COL_DIAGNOSIS = 4  # D
_COL_OBAT = 5  # E
_COL_EDUKASI = 6  # F
_COL_SIS_JAN = 7  # G — month m: sistolik = 7+(m-1)*2, diastolik = 8+(m-1)*2
_LAST_DATA_COL = 30  # AD
_ARRAY_FORMULA_COLS = range(32, 48)  # AF..AU (spilling MAP formulas)
_STATUS_FORMULA_COLS = range(48, 60)  # AV..BG (per-row plain formulas)
_LAST_FORMULA_COL = 59  # BG
# The literal last-row bound baked into the template's array formulas / refs.
_TEMPLATE_LAST_ROW = "1003"

# Excel's 1900 date system epoch, offset by the historical 1900-leap-year bug
# the same way openpyxl serializes dates: serial = (d - _EXCEL_EPOCH).days.
_EXCEL_EPOCH = date(1899, 12, 30)

# Placeholder marking the per-row number inside a pre-tokenized Status formula.
# A NUL byte can never appear in formula text, so ``.replace`` is unambiguous.
_ROW_PH = "\x00"
# The row part of a single cell reference (``$D4`` / ``G4`` / ``AA4``). Applied
# ONLY to an OPERAND/RANGE token's text — never to raw formula text — so number
# literals like ``1+1`` or ``<140`` are structurally out of reach. Matches the
# template's data-start row.
_RANGE_ROW_RE = re.compile(rf"(\$?[A-Z]{{1,3}}\$?){_DATA_START_ROW}(?![0-9])")


class HipertensiExportRow(TypedDict):
    nama: str
    tanggal_diagnosis: date | None
    tertatalaksana_obat: bool
    tertatalaksana_edukasi: bool
    sistolik_by_month: dict[int, float | None]
    diastolik_by_month: dict[int, float | None]


def build_hipertensi_workbook(
    pk_name: str, year: int, rows: list[HipertensiExportRow]
) -> bytes:
    """Return the .xlsx bytes for the given puskesmas/year and per-NIK rows."""
    wb = openpyxl.load_workbook(_TEMPLATE_PATH, data_only=False)
    ws = wb[_SHEET]
    last_row = (
        _DATA_START_ROW + len(rows) - 1 if rows else _DATA_START_ROW
    )

    # openpyxl owns row 4 (the first NIK) and the spilling array formulas so the
    # committed template's structure/styles/Rekap sheet are reproduced exactly;
    # rows 5+ are appended as raw XML below.
    if rows:
        _fill_data_row(ws, _DATA_START_ROW, pk_name, year, rows[0])
    templates = _status_formula_templates(ws)
    _resize_array_formulas(ws, str(last_row))

    buf = BytesIO()
    wb.save(buf)
    return _splice_rows(buf.getvalue(), pk_name, year, rows, templates, last_row)


_FORMULA_TRIGGERS = ("=", "+", "-", "@", "\t", "\r")


def _formula_safe(value: str) -> str:
    """Neutralize spreadsheet formula injection for the openpyxl path: openpyxl
    turns a leading ``=`` into a live formula, and ``nama`` / ``pk_name`` come
    from scraped data. Prefix a leading trigger with ``'`` so it stays text.
    (The raw-XML row path uses ``t="inlineStr"``, which Excel never evaluates.)
    """
    if value and value[0] in _FORMULA_TRIGGERS:
        return "'" + value
    return value


def _fill_data_row(
    ws, r: int, pk_name: str, year: int, row: HipertensiExportRow
) -> None:
    """Write one NIK's data columns (A..AD) into ``ws`` via openpyxl."""
    ws.cell(row=r, column=_COL_NAMA_PUSKESMAS).value = _formula_safe(pk_name)
    ws.cell(row=r, column=_COL_TAHUN).value = year
    ws.cell(row=r, column=_COL_NAMA).value = _formula_safe(row["nama"])
    ws.cell(row=r, column=_COL_DIAGNOSIS).value = row["tanggal_diagnosis"]
    # "Ya"/"Tidak" reads clearer than TRUE/FALSE in Excel.
    ws.cell(row=r, column=_COL_OBAT).value = (
        "Ya" if row["tertatalaksana_obat"] else "Tidak"
    )
    ws.cell(row=r, column=_COL_EDUKASI).value = (
        "Ya" if row["tertatalaksana_edukasi"] else "Tidak"
    )
    sis = row["sistolik_by_month"]
    dia = row["diastolik_by_month"]
    for m in range(1, 13):
        sv = sis.get(m)
        dv = dia.get(m)
        if sv is not None:
            ws.cell(row=r, column=_COL_SIS_JAN + (m - 1) * 2).value = sv
        if dv is not None:
            ws.cell(row=r, column=_COL_SIS_JAN + 1 + (m - 1) * 2).value = dv


def _resize_array_formulas(ws, last_row: str) -> None:
    """Shrink/extend the spilling array formulas (AF4:AU4) to the real last data
    row so the spill covers exactly the filled rows (not the template's 1003)."""
    for col in _ARRAY_FORMULA_COLS:
        cell = ws.cell(row=_DATA_START_ROW, column=col)
        formula = cell.value
        if not isinstance(formula, ArrayFormula):
            continue
        cell.value = ArrayFormula(
            ref=formula.ref.replace(_TEMPLATE_LAST_ROW, last_row),
            text=formula.text.replace(_TEMPLATE_LAST_ROW, last_row),
        )


def _status_formula_templates(ws) -> dict[int, str]:
    """Pre-tokenize each AV..BG row-4 ``Status`` formula into an XML-escaped
    string whose cell-reference rows are replaced by ``_ROW_PH``. Filling a row
    is then a single ``.replace(_ROW_PH, str(row))``.

    Equivalent to ``openpyxl.formula.translate.Translator.translate_formula``
    (these formulas use only relative-row, single-row references) but ~60x
    cheaper, which dominates export time at large NIK counts. The row shift is
    applied strictly inside RANGE operand tokens, so the naive whole-string
    replace that would corrupt month literals like ``1+1`` can't happen.
    """
    templates: dict[int, str] = {}
    for col in _STATUS_FORMULA_COLS:
        formula = ws.cell(row=_DATA_START_ROW, column=col).value
        if not (isinstance(formula, str) and formula.startswith("=")):
            continue
        # Tokenizer drops the leading '=' — exactly what an <f> body needs.
        parts = []
        for tok in Tokenizer(formula).items:
            value = tok.value
            if tok.type == Token.OPERAND and tok.subtype == Token.RANGE:
                value = _RANGE_ROW_RE.sub(lambda m: m.group(1) + _ROW_PH, value)
            parts.append(value)
        templates[col] = _xml_escape("".join(parts))
    return templates


def _splice_rows(
    base_xlsx: bytes,
    pk_name: str,
    year: int,
    rows: list[HipertensiExportRow],
    templates: dict[int, str],
    last_row: int,
) -> bytes:
    """Append rows 5+ as raw ``<row>`` XML into the openpyxl-saved base and
    re-zip. Style indices are read back from the saved base's row 4 so the
    appended cells reference the exact same styles.xml entries."""
    zin = zipfile.ZipFile(BytesIO(base_xlsx))
    sheet_xml = zin.read(_SHEET_PART).decode("utf-8")
    style = _row4_style_map(sheet_xml)
    appended = _build_rows_xml(pk_name, year, rows, templates, style)
    sheet_xml = sheet_xml.replace("</sheetData>", appended + "</sheetData>", 1)
    # openpyxl wrote the dimension for a single data row; widen it to the real
    # last row. Excel tolerates a stale dimension, but keep it honest.
    last_col_letter = get_column_letter(_LAST_FORMULA_COL)
    sheet_xml = re.sub(
        rf'(<dimension ref="A1:{last_col_letter})\d+(")',
        rf"\g<1>{last_row}\g<2>",
        sheet_xml,
    )

    out = BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for item in zin.infolist():
            if item.filename == _SHEET_PART:
                data = sheet_xml
            elif item.filename.startswith(
                "xl/worksheets/"
            ) and item.filename.endswith(".xml"):
                data = zin.read(item.filename).decode("utf-8")
            else:
                zf.writestr(item, zin.read(item.filename))
                continue
            # Drop empty cached formula values (``<f/>…<v></v>``) in this same
            # pass — Excel flags an empty <v> as corrupt and shows the repair
            # prompt; a bare <f> is recalculated on open instead.
            data = data.replace("<v></v>", "").replace("<v/>", "")
            zf.writestr(item, data.encode("utf-8"))
    return out.getvalue()


def _build_rows_xml(
    pk_name: str,
    year: int,
    rows: list[HipertensiExportRow],
    templates: dict[int, str],
    style: dict[int, str],
) -> str:
    """Build the ``<row>`` XML for rows 5+ (every NIK after the first).

    Each row mirrors what openpyxl emits: data columns A..AD (values or empty
    styled cells), the styled-but-empty spill area AE..AU (Excel fills these
    from row 4's array formula), and the AV..BG ``Status`` formulas.
    """
    letters = {c: get_column_letter(c) for c in range(1, _LAST_FORMULA_COL + 1)}
    pk_text = _xml_escape(pk_name)
    pk_sp = ' xml:space="preserve"' if pk_name != pk_name.strip() else ""
    # AE..AU: styled, empty — Excel spills these from the row-4 array formula.
    spill_cols = range(_LAST_DATA_COL + 1, _STATUS_FORMULA_COLS.start)

    out: list[str] = []
    for i in range(1, len(rows)):
        r = str(_DATA_START_ROW + i)
        row = rows[i]
        cells = [
            f'<row r="{r}">',
            f'<c r="A{r}" s="{style[_COL_NAMA_PUSKESMAS]}" t="inlineStr">'
            f"<is><t{pk_sp}>{pk_text}</t></is></c>",
            f'<c r="B{r}" s="{style[_COL_TAHUN]}" t="n"><v>{year}</v></c>',
        ]
        nama = row["nama"]
        nm_sp = ' xml:space="preserve"' if nama != nama.strip() else ""
        cells.append(
            f'<c r="C{r}" s="{style[_COL_NAMA]}" t="inlineStr">'
            f"<is><t{nm_sp}>{_xml_escape(nama)}</t></is></c>"
        )
        diag = row["tanggal_diagnosis"]
        if diag is not None:
            cells.append(
                f'<c r="D{r}" s="{style[_COL_DIAGNOSIS]}" t="n">'
                f"<v>{(diag - _EXCEL_EPOCH).days}</v></c>"
            )
        else:
            cells.append(f'<c r="D{r}" s="{style[_COL_DIAGNOSIS]}"/>')
        cells.append(
            f'<c r="E{r}" s="{style[_COL_OBAT]}" t="inlineStr"><is><t>'
            f'{"Ya" if row["tertatalaksana_obat"] else "Tidak"}</t></is></c>'
        )
        cells.append(
            f'<c r="F{r}" s="{style[_COL_EDUKASI]}" t="inlineStr"><is><t>'
            f'{"Ya" if row["tertatalaksana_edukasi"] else "Tidak"}</t></is></c>'
        )
        sis = row["sistolik_by_month"]
        dia = row["diastolik_by_month"]
        for m in range(1, 13):
            cs = _COL_SIS_JAN + (m - 1) * 2
            cd = cs + 1
            sv = sis.get(m)
            dv = dia.get(m)
            cells.append(
                f'<c r="{letters[cs]}{r}" s="{style[cs]}"><v>{_num_str(sv)}</v></c>'
                if sv is not None
                else f'<c r="{letters[cs]}{r}" s="{style[cs]}"/>'
            )
            cells.append(
                f'<c r="{letters[cd]}{r}" s="{style[cd]}"><v>{_num_str(dv)}</v></c>'
                if dv is not None
                else f'<c r="{letters[cd]}{r}" s="{style[cd]}"/>'
            )
        for col in spill_cols:
            cells.append(f'<c r="{letters[col]}{r}" s="{style[col]}"/>')
        for col in _STATUS_FORMULA_COLS:
            cells.append(
                f'<c r="{letters[col]}{r}" s="{style[col]}">'
                f"<f>{templates[col].replace(_ROW_PH, r)}</f></c>"
            )
        cells.append("</row>")
        out.append("".join(cells))
    return "".join(out)


def _row4_style_map(sheet_xml: str) -> dict[int, str]:
    """Map column index → style id, read from the saved base's row 4. Reading it
    back from the base (not the template) guarantees the indices match the
    styles.xml openpyxl just wrote, regardless of any re-indexing on save."""
    match = re.search(
        rf'<row [^>]*r="{_DATA_START_ROW}".*?</row>', sheet_xml, re.S
    )
    if match is None:  # pragma: no cover - template always has row 4
        return {}
    return {
        column_index_from_string(m.group(1)): m.group(2)
        for m in re.finditer(
            rf'<c r="([A-Z]+){_DATA_START_ROW}"[^>]*?\bs="(\d+)"', match.group(0)
        )
    }


def _xml_escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _num_str(value: float) -> str:
    """Serialize a number the way openpyxl does: whole floats lose the ``.0``."""
    f = float(value)
    return str(int(f)) if f.is_integer() else repr(f)
