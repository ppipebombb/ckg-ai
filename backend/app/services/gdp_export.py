"""Render the GD Puasa export workbook from dashboard data.

Loads the committed template ``app/data/gdp_template.xlsx`` (built by
``app.data.build_gdp_template``), fills the Puskesmas sheet's data columns
(A..R) from row 3 down, and shrinks the legacy array formulas (S3:W3) to the
real row count. The Terkendali columns (S..W) and the Rekap recap sheet stay as
*formulas* — Excel computes them on open — so the exported file behaves exactly
like the master template.

The template uses legacy array formulas (``<f t="array" ref=...>``) whose range
bounds are the literal ``33766`` (the master's last row). We rewrite that
literal to the export's last data row in both the formula text and its ``ref``.

Generation strategy (fast path): openpyxl builds the *base* workbook — the
template with row 3 (the first NIK) filled and the array formulas resized — so
styles.xml / the Rekap + Panduan sheets / the array formulas are produced by the
tested library. Rows 4+ are then appended as raw ``<row>`` XML spliced into the
saved sheet, which avoids openpyxl's per-cell object model and ``save()`` over
tens of thousands of rows (~12x faster at large NIK counts) while producing a
byte-equivalent file. Unlike the Hipertensi export there are no per-row Status
formulas — S..W are spilling array formulas — so appended rows carry only the
data columns A..R.
"""

from __future__ import annotations

import re
import zipfile
from datetime import date
from io import BytesIO
from pathlib import Path
from typing import TypedDict

import openpyxl
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.formula import ArrayFormula

_TEMPLATE_PATH = Path(__file__).resolve().parents[1] / "data" / "gdp_template.xlsx"

# Puskesmas sheet layout (1-based columns).
_SHEET = "Puskesmas"
# Puskesmas is the template's 2nd sheet (Panduan, Puskesmas, Rekap) → openpyxl
# writes it as sheet2.xml. The raw-XML splice targets that part directly.
_SHEET_PART = "xl/worksheets/sheet2.xml"
_DATA_START_ROW = 3
_COL_NAMA_PUSKESMAS = 1  # A
_COL_TAHUN = 2  # B
_COL_NAMA = 3  # C
_COL_DIAGNOSIS = 4  # D
_COL_OBAT = 5  # E
_COL_EDUKASI = 6  # F
_COL_GDP_JAN = 7  # G (months 1..12 → cols 7..18)
_LAST_DATA_COL = 18  # R
_FORMULA_COLS = (19, 20, 21, 22, 23)  # S..W (Terkendali)
# The literal last-row bound baked into the master's array formulas / refs.
_TEMPLATE_LAST_ROW = "33766"

# Excel's 1900 date system epoch, matching openpyxl's date serialization:
# serial = (d - _EXCEL_EPOCH).days.
_EXCEL_EPOCH = date(1899, 12, 30)


class GdpExportRow(TypedDict):
    nama: str
    tanggal_diagnosis: date | None
    tertatalaksana_obat: bool
    tertatalaksana_edukasi: bool
    gdp_by_month: dict[int, float | None]


def build_gdp_workbook(pk_name: str, year: int, rows: list[GdpExportRow]) -> bytes:
    """Return the .xlsx bytes for the given puskesmas/year and per-NIK rows."""
    wb = openpyxl.load_workbook(_TEMPLATE_PATH, data_only=False)
    ws = wb[_SHEET]
    last_row = _DATA_START_ROW + len(rows) - 1 if rows else _DATA_START_ROW

    # openpyxl owns row 3 (the first NIK) and the spilling array formulas; rows
    # 4+ are appended as raw XML below.
    if rows:
        _fill_data_row(ws, _DATA_START_ROW, pk_name, year, rows[0])
    _resize_array_formulas(ws, str(last_row))

    buf = BytesIO()
    wb.save(buf)
    return _splice_rows(buf.getvalue(), pk_name, year, rows, last_row)


_FORMULA_TRIGGERS = ("=", "+", "-", "@", "\t", "\r")


def _formula_safe(value: str) -> str:
    """Neutralize spreadsheet formula injection for the openpyxl path.

    openpyxl turns any string assigned to ``cell.value`` that starts with ``=``
    into a live formula cell. Patient ``nama`` / ``pk_name`` originate from
    scraped data, so a value like ``=HYPERLINK(...)`` would execute on open.
    Prefix a leading formula trigger with ``'`` so it's stored as literal text.
    (The raw-XML row path emits ``t="inlineStr"`` cells, which Excel never
    evaluates, so it needs no equivalent.)
    """
    if value and value[0] in _FORMULA_TRIGGERS:
        return "'" + value
    return value


def _fill_data_row(
    ws, r: int, pk_name: str, year: int, row: GdpExportRow
) -> None:
    """Write one NIK's data columns (A..R) into ``ws`` via openpyxl."""
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
    months = row["gdp_by_month"]
    for m in range(1, 13):
        v = months.get(m)
        if v is not None:
            ws.cell(row=r, column=_COL_GDP_JAN + (m - 1)).value = v


def _resize_array_formulas(ws, last_row: str) -> None:
    """Shrink the legacy array formulas S3:W3 to the real last data row so the
    spill covers exactly the filled rows (not the master's 33766)."""
    for col in _FORMULA_COLS:
        cell = ws.cell(row=_DATA_START_ROW, column=col)
        formula = cell.value
        if not isinstance(formula, ArrayFormula):
            continue
        cell.value = ArrayFormula(
            ref=formula.ref.replace(_TEMPLATE_LAST_ROW, last_row),
            text=formula.text.replace(_TEMPLATE_LAST_ROW, last_row),
        )


def _splice_rows(
    base_xlsx: bytes,
    pk_name: str,
    year: int,
    rows: list[GdpExportRow],
    last_row: int,
) -> bytes:
    """Append rows 4+ as raw ``<row>`` XML into the openpyxl-saved base and
    re-zip. Style indices are read back from the saved base's row 3 so the
    appended cells reference the exact same styles.xml entries."""
    zin = zipfile.ZipFile(BytesIO(base_xlsx))
    sheet_xml = zin.read(_SHEET_PART).decode("utf-8")
    style = _row3_style_map(sheet_xml)
    appended = _build_rows_xml(pk_name, year, rows, style)
    sheet_xml = sheet_xml.replace("</sheetData>", appended + "</sheetData>", 1)
    sheet_xml = re.sub(
        r'(<dimension ref="A1:[A-Z]+)\d+(")',
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
            # Drop empty cached formula values (Excel flags an empty <v> as
            # corrupt); Excel recalcs the bare <f> on open.
            data = data.replace("<v></v>", "").replace("<v/>", "")
            zf.writestr(item, data.encode("utf-8"))
    return out.getvalue()


def _build_rows_xml(
    pk_name: str, year: int, rows: list[GdpExportRow], style: dict[int, str]
) -> str:
    """Build the ``<row>`` XML for rows 4+ (every NIK after the first). Each row
    carries only the data columns A..R; S..W spill from row 3's array formula."""
    letters = {c: get_column_letter(c) for c in range(1, _LAST_DATA_COL + 1)}
    pk_text = _xml_escape(pk_name)
    pk_sp = ' xml:space="preserve"' if pk_name != pk_name.strip() else ""

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
        months = row["gdp_by_month"]
        for m in range(1, 13):
            col = _COL_GDP_JAN + (m - 1)
            v = months.get(m)
            cells.append(
                f'<c r="{letters[col]}{r}" s="{style[col]}"><v>{_num_str(v)}</v></c>'
                if v is not None
                else f'<c r="{letters[col]}{r}" s="{style[col]}"/>'
            )
        cells.append("</row>")
        out.append("".join(cells))
    return "".join(out)


def _row3_style_map(sheet_xml: str) -> dict[int, str]:
    """Map column index → style id, read from the saved base's row 3 so the
    indices match the styles.xml openpyxl just wrote."""
    match = re.search(
        rf'<row [^>]*r="{_DATA_START_ROW}".*?</row>', sheet_xml, re.S
    )
    if match is None:  # pragma: no cover - template always has row 3
        return {}
    return {
        _col_index(m.group(1)): m.group(2)
        for m in re.finditer(
            rf'<c r="([A-Z]+){_DATA_START_ROW}"[^>]*?\bs="(\d+)"', match.group(0)
        )
    }


def _col_index(letters: str) -> int:
    idx = 0
    for ch in letters:
        idx = idx * 26 + (ord(ch) - ord("A") + 1)
    return idx


def _xml_escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _num_str(value: float) -> str:
    """Serialize a number the way openpyxl does: whole floats lose the ``.0``."""
    f = float(value)
    return str(int(f)) if f.is_integer() else repr(f)
