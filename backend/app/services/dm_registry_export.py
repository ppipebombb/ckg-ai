"""Kertas Kerja Registri Diabetes Melitus .xlsx export.

Sibling of ``hipertensi_registry_export``; same rendering technique, different
grid. One block of N rows per patient (NIK). Identitas (A–F) and the baseline
"Hasil Pemeriksaan Gula Darah" (G–M) are written once and vertically merged
across the block; the baseline ``Jenis Obat`` (N) stacks one drug per row; and
the Follow Up grid (O–CT, 12 months × **7** columns) fills each month's
column-group independently — EVERY kunjungan in the month stacked in date order,
each visit's drugs one per row. Block height N is the tallest column-group.

Layout note: the dirjen sheet has **no HbA1C column in the baseline block** —
HbA1C appears only in the monthly Follow Up (Tanggal, GDS, GDP, GD2PP, HbA1C,
Interpretasi, Jenis Obat = 7 columns, vs hipertensi's 5). The scan still carries
a baseline ``hba1c`` for the API/dashboard; it is deliberately not emitted here
so the workbook matches the dirjen format column-for-column.

The derived columns are LIVE Excel formulas (with cached values, recalculated on
open): Interpretasi (M) implements the N15 syarat including the "tidak valid"
masking; each month's Interpretasi hasil implements the U17 target bands. A
second worksheet ("Formula & Logika") documents every rule.

Rendered the fast way (raw XML) for the reasons given in
``hipertensi_registry_export``: openpyxl's ``merge_cells`` is O(n²).
"""

from __future__ import annotations

import io
import re
import zipfile
from datetime import date

import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from app.services.dm_registry_scan import (
    _FU_MISSED_VISIT,
    _FU_TERKENDALI,
    _FU_TIDAK_TERKENDALI,
    _INTERP_DM,
    _INTERP_PREDIABETES,
    _INTERP_TIDAK_VALID,
)

_MONTHS_ID = [
    "", "Januari", "Februari", "Maret", "April", "Mei", "Juni",
    "Juli", "Agustus", "September", "Oktober", "November", "Desember",
]

# Column layout (1-based): identitas A–F, baseline G–M, baseline obat N, then 12
# month-blocks of 7 columns each starting at O (15). CT (98) is the last column.
_FOLLOWUP_FIRST_COL = 15
_MONTH_STRIDE = 7
_LAST_COL = _FOLLOWUP_FIRST_COL + 12 * _MONTH_STRIDE - 1  # 98 = CT
_OBAT_COL = 14

_IDENT_HEADERS = [
    "NIK", "Nama", "Jenis Kelamin", "Tanggal Lahir\n(DD/MM/YYYY)", "No. Tlp", "Alamat",
]
_BASELINE_HEADERS = [
    "Tanggal Berkunjung", "Riwayat diagnosis DM",
    "GDS 1\n(mg/dL)", "GDS 2\n(mg/dL)", "GDP\n(mg/dL)", "GD 2PP\n(mg/dL)",
    "Interpretasi hasil",
]
_MONTH_SUBHEADERS = [
    "Tanggal Pemeriksaan\n(DD/MM/YYYY)", "GDS\n(mg/dL)", "GDP\n(mg/dL)",
    "GD2PP\n(mg/dL)", "HbA1C\n(%)", "Interpretasi hasil", "Jenis Obat",
]

_SHEET = "Registri Diabetes Melitus"
_DATE_FMT = "DD/MM/YYYY"
_DATA_START = 8
_GROUP_ROW, _MONTH_ROW, _COL_ROW = 5, 6, 7

# Excel 1900 date system epoch (matches openpyxl): serial = (d - epoch).days.
_EXCEL_EPOCH = date(1899, 12, 30)


def _month_base_col(m: int) -> int:
    """First column index (1-based) of month ``m`` (1..12). Jan→15 (O)."""
    return _FOLLOWUP_FIRST_COL + (m - 1) * _MONTH_STRIDE


def build_dm_registry_workbook(pk_name: str, year: int, patients: list[dict]) -> bytes:
    seed, s, part = _build_seed()
    letter = {c: get_column_letter(c) for c in range(1, _LAST_COL + 1)}

    body: list[str] = []
    merges: list[str] = []
    _emit_header(body, merges, s, letter, pk_name, year)

    r = _DATA_START
    for p in patients:
        r = _emit_block(body, merges, s, letter, p, r)
    max_row = r - 1 if r > _DATA_START else _COL_ROW

    sheet_data = "<sheetData>" + "".join(body) + "</sheetData>"
    merge_xml = (
        f'<mergeCells count="{len(merges)}">' + "".join(merges) + "</mergeCells>"
        if merges
        else ""
    )

    zin = zipfile.ZipFile(io.BytesIO(seed))
    xml = zin.read(part).decode("utf-8")
    xml = re.sub(
        r"<sheetData/?>(?:.*?</sheetData>)?", sheet_data, xml, count=1, flags=re.S
    )
    if merge_xml:
        xml = xml.replace("</sheetData>", "</sheetData>" + merge_xml, 1)
    xml = re.sub(
        r'<dimension ref="[^"]*"/>',
        f'<dimension ref="A1:{get_column_letter(_LAST_COL)}{max_row}"/>',
        xml,
        count=1,
    )

    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for item in zin.infolist():
            zf.writestr(
                item,
                xml.encode("utf-8")
                if item.filename == part
                else zin.read(item.filename),
            )
    return out.getvalue()


# ── header ─────────────────────────────────────────────────────────────────
def _emit_header(body, merges, s, letter, pk_name: str, year: int) -> None:
    body.append(
        f'<row r="1" ht="18" customHeight="1">'
        f'{_text(letter[1], 1, s["title"], "KERTAS KERJA REGISTRI DIABETES MELITUS")}</row>'
    )
    body.append(
        f'<row r="2">{_text(letter[1], 2, s["plain"], "Syarat Registri DM (salah satu): 1) Riwayat Diagnosis DM Positif; ATAU 2) GDP >= 126 mg/dL; ATAU 3) GD2PP >= 200 mg/dL; ATAU 4) GDS ke-2 >= 200 mg/dL. Pasien Prediabetes juga ditampilkan. Catatan: GD2PP tanpa GDP, atau GDS 2 tanpa GDS 1, tidak dapat diinterpretasikan. Follow Up mulai bulan berikutnya setelah bulan kunjungan CKG; semua kunjungan dalam bulan ditampilkan. Lihat sheet \'Formula & Logika\'.")}</row>'
    )
    body.append(
        f'<row r="3">{_text(letter[1], 3, s["bold"], f"Nama Puskesmas: {pk_name}")}'
        f'{_text(letter[7], 3, s["bold"], f"Tahun: {year}")}</row>'
    )
    merges.append(f'<mergeCell ref="A1:{letter[_OBAT_COL]}1"/>')
    merges.append(f'<mergeCell ref="A2:{letter[_OBAT_COL]}2"/>')
    merges.append(f'<mergeCell ref="A3:{letter[6]}3"/>')

    grp, hdr, blkg = s["group"], s["header"], s["blank_group"]
    rows: dict[int, dict[int, str]] = {_GROUP_ROW: {}, _MONTH_ROW: {}, _COL_ROW: {}}

    def gcell(r, c, text, style):
        rows[r][c] = (
            _text(letter[c], r, style, text)
            if text
            else f'<c r="{letter[c]}{r}" s="{style}"/>'
        )

    # Row 5 group band.
    gcell(_GROUP_ROW, 1, "Identitas Pasien", grp)
    gcell(_GROUP_ROW, 7, "Hasil Pemeriksaan Gula Darah (pada Tanggal Berkunjung)", grp)
    gcell(_GROUP_ROW, _OBAT_COL, "Jenis Obat", grp)
    gcell(_GROUP_ROW, _FOLLOWUP_FIRST_COL, "Follow Up", grp)
    merges.append(f'<mergeCell ref="A{_GROUP_ROW}:{letter[6]}{_MONTH_ROW}"/>')
    merges.append(
        f'<mergeCell ref="{letter[7]}{_GROUP_ROW}:{letter[13]}{_MONTH_ROW}"/>'
    )
    merges.append(
        f'<mergeCell ref="{letter[_OBAT_COL]}{_GROUP_ROW}:{letter[_OBAT_COL]}{_COL_ROW}"/>'
    )
    merges.append(
        f'<mergeCell ref="{letter[_FOLLOWUP_FIRST_COL]}{_GROUP_ROW}:{letter[_LAST_COL]}{_GROUP_ROW}"/>'
    )

    # Row 6 month names.
    for m in range(1, 13):
        bc = _month_base_col(m)
        gcell(_MONTH_ROW, bc, _MONTHS_ID[m], grp)
        merges.append(
            f'<mergeCell ref="{letter[bc]}{_MONTH_ROW}:'
            f'{letter[bc + _MONTH_STRIDE - 1]}{_MONTH_ROW}"/>'
        )

    # Row 7 column headers.
    for i, label in enumerate(_IDENT_HEADERS):
        gcell(_COL_ROW, 1 + i, label, hdr)
    for i, label in enumerate(_BASELINE_HEADERS):
        gcell(_COL_ROW, 7 + i, label, hdr)
    for m in range(1, 13):
        bc = _month_base_col(m)
        for i, label in enumerate(_MONTH_SUBHEADERS):
            gcell(_COL_ROW, bc + i, label, hdr)

    for r in (_GROUP_ROW, _MONTH_ROW, _COL_ROW):
        cells = [f'<row r="{r}" ht="30" customHeight="1">']
        style_for = grp if r != _COL_ROW else blkg
        for c in range(1, _LAST_COL + 1):
            cells.append(rows[r].get(c) or f'<c r="{letter[c]}{r}" s="{style_for}"/>')
        cells.append("</row>")
        body.append("".join(cells))


# ── formulas ───────────────────────────────────────────────────────────────
def _baseline_interpretasi_formula(r: int) -> str:
    """Live Excel implementation of ``dm_registry_scan._interpretasi_baseline``.

    Columns on row ``r``: H=Riwayat DM, I=GDS1, J=GDS2, K=GDP, L=GD2PP.

    The N15 validity rule is expressed as the guards ``gds2ok``/``gd2ppok``: an
    orphan GDS2 (no GDS1) or GD2PP (no GDP) is ignored. "Anything usable" then
    reduces to "GDS1 or GDP present", because each guarded reading already
    requires its partner.
    """
    gds2ok = f"AND(COUNT(I{r})>0,COUNT(J{r})>0)"
    gd2ppok = f"AND(COUNT(K{r})>0,COUNT(L{r})>0)"
    any_usable = f"OR(COUNT(I{r})>0,COUNT(K{r})>0)"
    had_invalid = (
        f"OR(AND(COUNT(L{r})>0,COUNT(K{r})=0),AND(COUNT(J{r})>0,COUNT(I{r})=0))"
    )
    is_dm = (
        f"OR(N(K{r})>=126,"
        f"AND({gd2ppok},N(L{r})>=200),"
        f"AND({gds2ok},N(J{r})>=200))"
    )
    is_pre = (
        f"OR(AND(N(K{r})>=100,N(K{r})<=125),"
        f"AND({gd2ppok},N(L{r})>=140,N(L{r})<=199),"
        f"AND(N(I{r})>=140,N(I{r})<=199))"
    )
    return (
        f'IF(H{r}="Ya","{_INTERP_DM}",'
        f'IF(NOT({any_usable}),IF({had_invalid},"{_INTERP_TIDAK_VALID}",""),'
        f'IF({is_dm},"{_INTERP_DM}",'
        f'IF({is_pre},"{_INTERP_PREDIABETES}","Normal"))))'
    )


def _followup_interpretasi_formula(letter, bc: int, r: int) -> str:
    """Live Excel implementation of ``dm_registry_scan._interpretasi_followup``.

    Month columns from ``bc``: +0 Tanggal, +1 GDS, +2 GDP, +3 GD2PP, +4 HbA1C.

    Every threshold is COUNT-guarded because ``N("")`` is 0 — without the guard
    an empty GDP would satisfy ``<80`` and falsely read "tidak terkendali".
    GDS is intentionally absent from the target test: the U17 legend defines no
    GDS band, so a GDS-only visit stays blank.
    """
    tgl, gds = f"{letter[bc]}{r}", f"{letter[bc + 1]}{r}"
    gdp, gd2pp, hba1c = (
        f"{letter[bc + 2]}{r}",
        f"{letter[bc + 3]}{r}",
        f"{letter[bc + 4]}{r}",
    )
    failed = (
        f"OR(AND(COUNT({hba1c})>0,N({hba1c})>=7),"
        f"AND(COUNT({gdp})>0,OR(N({gdp})>130,N({gdp})<80)),"
        f"AND(COUNT({gd2pp})>0,N({gd2pp})>=180))"
    )
    return (
        f'IF(COUNT({tgl},{gds},{gdp},{gd2pp},{hba1c})=0,"{_FU_MISSED_VISIT}",'
        f'IF(COUNT({gdp},{gd2pp},{hba1c})=0,"",'
        f'IF({failed},"{_FU_TIDAK_TERKENDALI}","{_FU_TERKENDALI}")))'
    )


# ── per-patient block ────────────────────────────────────────────────────
def _emit_block(body, merges, s, letter, p: dict, r0: int) -> int:
    obat = p.get("obat") or []
    months = {int(k): (v or []) for k, v in (p.get("followup") or {}).items()}
    month_rows = {
        m: sum(max(1, len(v.get("obat") or [])) for v in months.get(m, []))
        for m in range(1, 13)
    }
    n = max([1, len(obat), *month_rows.values()])
    r_end = r0 + n - 1
    grid: dict[int, dict[int, str]] = {r0 + i: {} for i in range(n)}

    # Identitas A–F (value on r0).
    grid[r0][1] = _text(letter[1], r0, s["text"], p.get("nik"))
    grid[r0][2] = _text(letter[2], r0, s["left"], p.get("nama"))
    grid[r0][3] = _text(letter[3], r0, s["text"], p.get("jenis_kelamin"))
    grid[r0][4] = _date_cell(letter[4], r0, s["date"], p.get("tanggal_lahir"))
    grid[r0][5] = _text(letter[5], r0, s["text"], p.get("no_tlp"))
    grid[r0][6] = _text(letter[6], r0, s["left"], p.get("alamat"))

    # Baseline G–M (value on r0).
    grid[r0][7] = _date_cell(letter[7], r0, s["date"], p.get("tanggal_berkunjung"))
    grid[r0][8] = _text(letter[8], r0, s["text"], p.get("riwayat_dm"))
    grid[r0][9] = _num_cell(letter[9], r0, s["text"], p.get("gds1"))
    grid[r0][10] = _num_cell(letter[10], r0, s["text"], p.get("gds2"))
    grid[r0][11] = _num_cell(letter[11], r0, s["text"], p.get("gdp"))
    grid[r0][12] = _num_cell(letter[12], r0, s["text"], p.get("gd2pp"))
    grid[r0][13] = _formula_cell(
        letter[13], r0, s["text"],
        _baseline_interpretasi_formula(r0),
        p.get("interpretasi"),
    )

    # Baseline Jenis Obat N (stacked).
    for i, drug in enumerate(obat):
        grid[r0 + i][_OBAT_COL] = _text(letter[_OBAT_COL], r0 + i, s["left"], drug)

    # Follow Up months (independent stacks).
    for m in range(1, 13):
        bc = _month_base_col(m)
        rr = r0
        for v in months.get(m, []):
            drugs = v.get("obat") or [None]
            v_start = rr
            for j, drug in enumerate(drugs):
                if j == 0:
                    grid[rr][bc] = _date_cell(letter[bc], rr, s["date"], v.get("tanggal"))
                    grid[rr][bc + 1] = _num_cell(letter[bc + 1], rr, s["text"], v.get("gds"))
                    grid[rr][bc + 2] = _num_cell(letter[bc + 2], rr, s["text"], v.get("gdp"))
                    grid[rr][bc + 3] = _num_cell(letter[bc + 3], rr, s["text"], v.get("gd2pp"))
                    grid[rr][bc + 4] = _num_cell(letter[bc + 4], rr, s["text"], v.get("hba1c"))
                    grid[rr][bc + 5] = _formula_cell(
                        letter[bc + 5], rr, s["text"],
                        _followup_interpretasi_formula(letter, bc, rr),
                        v.get("interpretasi"),
                    )
                if drug is not None:
                    grid[rr][bc + 6] = _text(letter[bc + 6], rr, s["left"], drug)
                rr += 1
            if len(drugs) > 1:
                for col in range(bc, bc + 6):
                    merges.append(
                        f'<mergeCell ref="{letter[col]}{v_start}:{letter[col]}{rr - 1}"/>'
                    )

    # Vertical merges for identitas + baseline (A..M) across the block.
    if n > 1:
        for col in range(1, 14):
            merges.append(f'<mergeCell ref="{letter[col]}{r0}:{letter[col]}{r_end}"/>')

    blank = s["blank"]
    for rr in range(r0, r_end + 1):
        cells = [f'<row r="{rr}">']
        row_cells = grid[rr]
        for c in range(1, _LAST_COL + 1):
            cells.append(row_cells.get(c) or f'<c r="{letter[c]}{rr}" s="{blank}"/>')
        cells.append("</row>")
        body.append("".join(cells))
    return r_end + 1


# ── cell emitters ──────────────────────────────────────────────────────────
def _text(col_letter: str, row: int, style: str, value) -> str:
    if value is None or value == "":
        return f'<c r="{col_letter}{row}" s="{style}"/>'
    text = str(value)
    esc = _xml_escape(text)
    sp = ' xml:space="preserve"' if text != text.strip() else ""
    return (
        f'<c r="{col_letter}{row}" s="{style}" t="inlineStr">'
        f"<is><t{sp}>{esc}</t></is></c>"
    )


def _num_cell(col_letter: str, row: int, style: str, value) -> str:
    if value is None or value == "":
        return f'<c r="{col_letter}{row}" s="{style}"/>'
    return f'<c r="{col_letter}{row}" s="{style}"><v>{_num_str(value)}</v></c>'


def _formula_cell(col_letter: str, row: int, style: str, formula: str, value) -> str:
    """A live formula with the scan's computed value cached (the seed workbook
    sets fullCalcOnLoad, so Excel re-evaluates on open)."""
    f = _xml_escape(formula)
    if value is None or value == "":
        return f'<c r="{col_letter}{row}" s="{style}" t="str"><f>{f}</f><v></v></c>'
    if isinstance(value, (int, float)):
        return f'<c r="{col_letter}{row}" s="{style}"><f>{f}</f><v>{_num_str(value)}</v></c>'
    return (
        f'<c r="{col_letter}{row}" s="{style}" t="str"><f>{f}</f>'
        f"<v>{_xml_escape(str(value))}</v></c>"
    )


def _date_cell(col_letter: str, row: int, style: str, value) -> str:
    d = value if isinstance(value, date) else _parse_iso(value)
    if d is None:
        return _text(col_letter, row, style, value)
    return f'<c r="{col_letter}{row}" s="{style}"><v>{(d - _EXCEL_EPOCH).days}</v></c>'


def _parse_iso(value) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def _xml_escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _num_str(value) -> str:
    f = float(value)
    return str(int(f)) if f.is_integer() else repr(f)


# ── "Formula & Logika" documentation sheet ─────────────────────────────────
# Antidiabetic families (Formularium Nasional, FKTP) — the Jenis Obat filter.
# Keep in sync with ``dm_registry_scan._DM_DRUG_RE``.
_DM_DRUG_FAMILIES = [
    ("Biguanid", "Metformin"),
    ("Sulfonilurea",
     "Glibenklamid, Glimepirid, Gliklazid, Glipizid, Glikuidon (Gliquidone)"),
    ("Penghambat alfa-glukosidase", "Akarbose (Acarbose)"),
    ("Tiazolidindion", "Pioglitazon, Rosiglitazon"),
    ("Penghambat DPP-4",
     "Sitagliptin, Vildagliptin, Linagliptin, Saxagliptin, Alogliptin"),
    ("Penghambat SGLT-2", "Dapagliflozin, Empagliflozin, Kanagliflozin"),
    ("Agonis GLP-1", "Liraglutid, Semaglutid, Exenatid"),
    ("Insulin",
     "Semua sediaan insulin (Insulin Glargine, Aspart, Detemir, dan merek seperti "
     "Novorapid, Lantus, Levemir, Humalog, Humulin, Actrapid, Apidra)"),
]

_FORMULA_SHEET_ROWS: list[tuple[str, str, str]] = [
    # (kind, col A, col B) — kind: "title" | "section" | "item" | "blank"
    # Deliberately plain, non-technical Indonesian — read by puskesmas staff.
    ("title", "CARA MEMBACA KERTAS KERJA REGISTRI DIABETES MELITUS", ""),
    ("blank", "", ""),
    ("item", "Intinya: satu daftar, dua pertanyaan",
     "Bagian 'Hasil Pemeriksaan Gula Darah' (hijau) menjawab: berapa gula darah pasien SAAT skrining CKG? "
     "Bagian 'Follow Up' menjawab: pada bulan-bulan SETELAHNYA, apakah gula darahnya sudah mencapai target? "
     "Karena pertanyaannya berbeda, labelnya bisa berbeda — dan itu memang benar, bukan error."),
    ("blank", "", ""),
    ("section", "1. SIAPA YANG MASUK DAFTAR INI?", ""),
    ("item", "Masuk daftar jika memenuhi SALAH SATU",
     "(1) Sudah tercatat sebagai pasien DM — ada diagnosis diabetes di ePuskesmas, atau pasien menjawab 'Ya' "
     "saat ditanya 'pernah dinyatakan diabetes atau kencing manis oleh dokter?' di skrining CKG → kolom Riwayat = Ya.  "
     "ATAU (2) Hasil gula darahnya memenuhi ambang diagnosis: GDP 126 mg/dL ke atas, GD2PP 200 mg/dL ke atas, "
     "atau GDS ke-2 200 mg/dL ke atas.  "
     "Pasien Prediabetes juga ikut ditampilkan supaya bisa dipantau lebih awal."),
    ("item", "Yang tidak ditampilkan",
     "Pasien yang gula darahnya Normal DAN tidak pernah didiagnosis diabetes — belum perlu dipantau di kertas kerja ini."),
    ("blank", "", ""),
    ("section", "2. ARTI SINGKATAN", ""),
    ("item", "GDS", "Gula Darah Sewaktu — diperiksa kapan saja, tanpa perlu puasa."),
    ("item", "GDS 2", "Gula Darah Sewaktu pemeriksaan KEDUA — dilakukan untuk memastikan hasil GDS 1 yang tinggi."),
    ("item", "GDP", "Gula Darah Puasa — diperiksa setelah puasa (biasanya 8 jam)."),
    ("item", "GD2PP", "Gula Darah 2 Jam Post Prandial — diperiksa 2 jam setelah makan."),
    ("item", "HbA1C", "Rata-rata gula darah selama kurang lebih 3 bulan terakhir, dalam persen (%)."),
    ("blank", "", ""),
    ("section", "3. ARTI LABEL INTERPRETASI (saat kunjungan CKG)", ""),
    ("item", "Kalau sudah punya diagnosis",
     f"Kalau Riwayat = Ya → selalu '{_INTERP_DM}', berapa pun hasil gula darahnya hari itu. "
     "Diagnosis tidak hilang karena satu hasil ukur yang bagus."),
    ("item", _INTERP_DM,
     "GDP 126 mg/dL ke atas, ATAU GD2PP 200 mg/dL ke atas, ATAU GDS 2 200 mg/dL ke atas. "
     "Cukup salah satu yang memenuhi."),
    ("item", _INTERP_PREDIABETES,
     "GDP 100–125 mg/dL, ATAU GD2PP 140–199 mg/dL, ATAU GDS 1 140–199 mg/dL. "
     "Belum diabetes, tapi sudah di atas normal — perlu dipantau."),
    ("item", "Normal", "Hasil gula darah di bawah ambang Prediabetes di atas."),
    ("item", _INTERP_TIDAK_VALID,
     "Muncul kalau hasil yang ada tidak bisa dipakai menyimpulkan apa-apa. Lihat bagian 4."),
    ("blank", "", ""),
    ("section", "4. KAPAN HASIL DIANGGAP TIDAK VALID?", ""),
    ("item", "GD2PP tanpa GDP",
     "GD2PP hanya bisa dibaca kalau ada GDP-nya. Kalau GD2PP terisi tapi GDP kosong, angka GD2PP itu "
     "TIDAK dipakai untuk menyimpulkan."),
    ("item", "GDS 2 tanpa GDS 1",
     "GDS 2 adalah pemeriksaan konfirmasi. Tanpa GDS 1, angkanya TIDAK dipakai untuk menyimpulkan."),
    ("item", "Kalau masih ada hasil lain yang sah",
     "Hasil yang sah tetap dipakai. Contoh: GDS 1 terisi 150 dan GD2PP terisi tanpa GDP → GD2PP diabaikan, "
     f"tapi GDS 1 tetap dibaca → '{_INTERP_PREDIABETES}'. "
     f"Label '{_INTERP_TIDAK_VALID}' hanya muncul kalau TIDAK ADA satu pun hasil yang sah."),
    ("blank", "", ""),
    ("section", "5. CARA BACA FOLLOW UP", ""),
    ("item", "Mulai kapan",
     "Mulai bulan SETELAH bulan skrining CKG. Bulan skrining sendiri tidak diulang di Follow Up karena "
     "sudah ada di bagian hijau."),
    ("item", "Target tercapai",
     f"'{_FU_TERKENDALI}' — HbA1C di bawah 7%, ATAU GDP 80–130 mg/dL, ATAU GD2PP di bawah 180 mg/dL."),
    ("item", "Target tidak tercapai",
     f"'{_FU_TIDAK_TERKENDALI}' — HbA1C 7% ke atas, ATAU GDP di atas 130 mg/dL, ATAU GD2PP 180 mg/dL ke atas. "
     "GDP di BAWAH 80 mg/dL juga dihitung tidak tercapai, karena gula darah terlalu rendah (hipoglikemia) "
     "juga bukan kondisi terkendali."),
    ("item", "Kolom GDS di Follow Up tidak menentukan status",
     "Format dirjen tidak menetapkan batas target untuk GDS. Jadi kalau satu kunjungan HANYA punya GDS "
     "(tanpa GDP / GD2PP / HbA1C), kolom Interpretasi dibiarkan KOSONG — bukan berarti gagal."),
    ("item", "Missed Visit & bulan kosong",
     f"Bulan yang sudah lewat tanpa pemeriksaan gula darah = '{_FU_MISSED_VISIT}'. "
     "Bulan yang belum terjadi dibiarkan kosong."),
    ("item", "Semua kunjungan ditampilkan",
     "Kalau pasien datang beberapa kali dalam sebulan, SEMUA kunjungannya ditampilkan berurutan "
     "di kolom bulan itu — masing-masing dengan tanggal, hasil, dan statusnya sendiri."),
    ("blank", "", ""),
    ("section", "6. KENAPA KOLOM FOLLOW UP BANYAK YANG KOSONG?", ""),
    ("item", "Karena pemeriksaan gula darah jarang dicatat di ePuskesmas",
     "Berbeda dengan tekanan darah yang hampir selalu diukur tiap kunjungan, pemeriksaan gula darah "
     "hanya tercatat pada sebagian kecil kunjungan. Kolom yang kosong berarti pemeriksaannya memang "
     "tidak tercatat — bukan kesalahan sistem. Justru inilah yang perlu diperbaiki: makin lengkap "
     "pencatatan gula darah di ePuskesmas, makin berguna kertas kerja ini."),
    ("item", "HbA1C paling sering kosong",
     "HbA1C jarang tersedia di puskesmas. Kolomnya tetap disediakan sesuai format dirjen, dan akan terisi "
     "otomatis begitu pemeriksaannya tercatat."),
    ("blank", "", ""),
    ("section", "7. KOLOM JENIS OBAT — HANYA OBAT DIABETES", ""),
    ("item", "Aturannya",
     "Hanya obat diabetes yang ditampilkan, sesuai kolom dirjen 'List_obat_dm'. "
     "Vitamin, antibiotik, obat darah tinggi, dan obat lain sengaja tidak ditampilkan."),
    *[("item", fam, drugs) for fam, drugs in _DM_DRUG_FAMILIES],
    ("blank", "", ""),
    ("section", "8. DASAR ATURAN (untuk yang ingin memeriksa)", ""),
    ("item", "Ambang diagnosis DM (GDP 126 / GD2PP 200 / GDS 200) dan Prediabetes",
     "Pedoman skrining dan tata laksana Diabetes Melitus Tipe 2 dewasa, Kemenkes; "
     "Juknis CKG — KMK 84/2026: "
     "https://kesprimkom.kemkes.go.id/assets/uploads/contents/others/2026kepmenkes084.pdf"),
    ("item", "Target pengendalian (HbA1C <7%, GDP 80–130, GD2PP <180)",
     "Legenda format dirjen 'Register Sheet Pasien HT, DM, Dislipidemia dan Obesitas', sheet 'Diabetes Melitus'."),
    ("item", "Daftar obat diabetes di puskesmas",
     "Formularium Nasional — KMK 1199/2025: "
     "https://farmalkes.kemkes.go.id/en/unduh/keputusan-menteri-kesehatan-republik-indonesia-nomor-hk-01-07-menkes-1199-2025-tentang-formularium-nasional/"),
    ("item", "Format & istilah registri",
     "Dokumen dirjen 'Register Sheet Pasien HT, DM, Dislipidemia dan Obesitas', sheet 'Diabetes Melitus'."),
]


def _add_formula_sheet(wb: openpyxl.Workbook) -> None:
    ws = wb.create_sheet("Formula & Logika")
    ws.column_dimensions["A"].width = 46
    ws.column_dimensions["B"].width = 130
    title_font = Font(bold=True, size=13)
    section_font = Font(bold=True, size=11)
    wrap_top = Alignment(vertical="top", wrap_text=True)
    section_fill = PatternFill("solid", fgColor="BDD7EE")
    r = 1
    for kind, a, b in _FORMULA_SHEET_ROWS:
        if kind == "title":
            c = ws.cell(r, 1, a)
            c.font = title_font
        elif kind == "section":
            c = ws.cell(r, 1, a)
            c.font = section_font
            c.fill = section_fill
            ws.cell(r, 2, "").fill = section_fill
        elif kind == "item":
            ca = ws.cell(r, 1, a)
            ca.font = Font(bold=True)
            ca.alignment = wrap_top
            cb = ws.cell(r, 2, b)
            cb.alignment = wrap_top
        r += 1


# ── seed workbook (styles + column widths + freeze) ────────────────────────
def _build_seed() -> tuple[bytes, dict[str, str], str]:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = _SHEET
    ws.freeze_panes = "A8"
    wb.calculation.fullCalcOnLoad = True

    widths = {
        1: 20, 2: 22, 3: 12, 4: 14, 5: 14, 6: 30,
        7: 16, 8: 18, 9: 11, 10: 11, 11: 11, 12: 11, 13: 22, 14: 22,
    }
    for c, w in widths.items():
        ws.column_dimensions[get_column_letter(c)].width = w
    for m in range(1, 13):
        bc = _month_base_col(m)
        for off, w in ((0, 14), (1, 9), (2, 9), (3, 9), (4, 9), (5, 22), (6, 20)):
            ws.column_dimensions[get_column_letter(bc + off)].width = w

    thin = Side(style="thin", color="B0B0B0")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    center = Alignment(horizontal="center", vertical="center", wrap_text=True)
    left = Alignment(horizontal="left", vertical="top", wrap_text=True)
    bold = Font(bold=True)
    title_font = Font(bold=True, size=13)
    group_fill = PatternFill("solid", fgColor="BDD7EE")
    header_fill = PatternFill("solid", fgColor="D9E1F2")

    variants = {
        "title": (1, 1, title_font, None, None, None),
        "plain": (2, 1, None, None, None, None),
        "bold": (3, 1, bold, None, None, None),
        "group": (5, 1, bold, group_fill, center, border),
        "header": (7, 1, bold, header_fill, center, border),
        "blank_group": (5, 2, None, group_fill, None, border),
        "text": (8, 1, None, None, center, border),
        "left": (8, 2, None, None, left, border),
        "blank": (8, 3, None, None, None, border),
    }
    refs: dict[str, tuple[int, int]] = {}
    for name, (r, c, font, fill, align, bd) in variants.items():
        cell = ws.cell(r, c, "x")
        if font:
            cell.font = font
        if fill:
            cell.fill = fill
        if align:
            cell.alignment = align
        if bd:
            cell.border = bd
        refs[name] = (r, c)
    dcell = ws.cell(9, 1, value=date(2024, 1, 1))
    dcell.number_format = _DATE_FMT
    dcell.alignment = center
    dcell.border = border
    refs["date"] = (9, 1)

    _add_formula_sheet(wb)

    buf = io.BytesIO()
    wb.save(buf)
    seed = buf.getvalue()

    z = zipfile.ZipFile(io.BytesIO(seed))
    part = _sheet_part(z, _SHEET)
    sheet_xml = z.read(part).decode("utf-8")

    def style_id(r: int, c: int) -> str:
        ref = f"{get_column_letter(c)}{r}"
        m = re.search(rf'<c r="{ref}"[^>]*?\bs="(\d+)"', sheet_xml)
        return m.group(1) if m else "0"

    styles = {name: style_id(r, c) for name, (r, c) in refs.items()}
    return seed, styles, part


def _sheet_part(z: zipfile.ZipFile, name: str) -> str:
    wb_xml = z.read("xl/workbook.xml").decode("utf-8")
    rels = z.read("xl/_rels/workbook.xml.rels").decode("utf-8")
    rid = None
    for tag in re.finditer(r"<sheet\b[^>]*?/?>", wb_xml):
        nm = re.search(r'name="([^"]+)"', tag.group(0))
        ri = re.search(r'r:id="([^"]+)"', tag.group(0))
        if nm and ri and nm.group(1) == name:
            rid = ri.group(1)
            break
    for tag in re.finditer(r"<Relationship\b[^>]*?/?>", rels):
        i = re.search(r'Id="([^"]+)"', tag.group(0))
        t = re.search(r'Target="([^"]+)"', tag.group(0))
        if i and t and i.group(1) == rid:
            target = t.group(1)
            return target.lstrip("/") if target.startswith("/") else "xl/" + target
    raise ValueError(f"worksheet part for {name!r} not found")
