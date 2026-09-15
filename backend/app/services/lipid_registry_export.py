"""Kertas Kerja Registri Dislipidemia .xlsx export.

Sibling of ``dm_registry_export`` / ``hipertensi_registry_export``; same
rendering technique, different grid. One block of N rows per patient (NIK).
Identitas (A–F) and the baseline "Hasil Pemeriksaan Lipid" (G–N) are written once
and vertically merged across the block; the baseline ``Jenis Obat`` (O) stacks one
drug per row; and the Follow Up grid (P–CU, 12 months × **7** columns) fills each
month's column-group independently — EVERY kunjungan in the month stacked in date
order, each visit's drugs one per row. Block height N is the tallest column-group.

Layout matches the dirjen sheet column-for-column, including its two extra
baseline columns (``Riwayat diagnosis HT`` and ``Riwayat diagnosis DM``) and the
sheet's analyte order — **Kolesterol Total, LDL, HDL, Trigliserida**. LDL before
HDL looks wrong next to the syarat text, which lists HDL second; the sheet's
column order is what it is, and the register must be diffable against it.

A month column-group is written ONLY for months the scan emitted. Because the
scan stamps ``Pasien Missed Visit`` on control months alone (baseline +3/+6/+9/
+12 — see ``lipid_registry_scan._control_months``), a non-control month with no
kunjungan simply has no cells, and stays blank. The live formula's
"nothing at all → Missed Visit" branch therefore only ever fires on a row the
scan deliberately emitted as a missed control. Do not "fix" the formula to stamp
every empty month: that would put the workbook at odds with the dashboard.

The derived columns are LIVE Excel formulas (with cached values, recalculated on
open): Interpretasi (N) implements the B1 syarat; each month's Interpretasi hasil
implements the N17 target. A second worksheet ("Formula & Logika") documents
every rule.

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

from app.services.lipid_registry_scan import (
    _FU_MISSED_VISIT,
    _FU_TERKENDALI,
    _FU_TIDAK_TERKENDALI,
    _INTERP_DISLIPIDEMIA,
    _INTERP_NORMAL,
    _KOL_TOTAL_MIN_TINGGI,
    _LDL_MIN_TINGGI,
    _HDL_MIN_NORMAL,
    _TRIGLISERIDA_MAX_NORMAL,
)

_MONTHS_ID = [
    "", "Januari", "Februari", "Maret", "April", "Mei", "Juni",
    "Juli", "Agustus", "September", "Oktober", "November", "Desember",
]

# Column layout (1-based): identitas A–F, baseline G–N, baseline obat O, then 12
# month-blocks of 7 columns each starting at P (16). CU (99) is the last column.
_FOLLOWUP_FIRST_COL = 16
_MONTH_STRIDE = 7
_LAST_COL = _FOLLOWUP_FIRST_COL + 12 * _MONTH_STRIDE - 1  # 99 = CU
_OBAT_COL = 15

_IDENT_HEADERS = [
    "NIK", "Nama", "Jenis Kelamin", "Tanggal Lahir\n(DD/MM/YYYY)", "No. Tlp", "Alamat",
]
_BASELINE_HEADERS = [
    "Tanggal Berkunjung", "Riwayat diagnosis HT", "Riwayat diagnosis DM",
    "Kolesterol Total\n(mg/dL)", "LDL\n(mg/dL)", "HDL\n(mg/dL)",
    "Trigliserida\n(mg/dL)", "Interpretasi hasil",
]
_MONTH_SUBHEADERS = [
    "Tanggal Pemeriksaan\n(DD/MM/YYYY)", "Kolesterol Total\n(mg/dL)", "LDL\n(mg/dL)",
    "HDL\n(mg/dL)", "Trigliserida\n(mg/dL)", "Interpretasi hasil", "Jenis Obat",
]

_SHEET = "Registri Dislipidemia"
_DATE_FMT = "DD/MM/YYYY"
_DATA_START = 8
_GROUP_ROW, _MONTH_ROW, _COL_ROW = 5, 6, 7

# Excel 1900 date system epoch (matches openpyxl): serial = (d - epoch).days.
_EXCEL_EPOCH = date(1899, 12, 30)

# Threshold literals for the formulas, rendered without a trailing ".0".
_KOL = int(_KOL_TOTAL_MIN_TINGGI)
_LDL = int(_LDL_MIN_TINGGI)
_HDL = int(_HDL_MIN_NORMAL)
_TRIG = int(_TRIGLISERIDA_MAX_NORMAL)


def _month_base_col(m: int) -> int:
    """First column index (1-based) of month ``m`` (1..12). Jan→16 (P)."""
    return _FOLLOWUP_FIRST_COL + (m - 1) * _MONTH_STRIDE


def build_lipid_registry_workbook(
    pk_name: str, year: int, patients: list[dict]
) -> bytes:
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
    # The replacement MUST be a callable, not the string itself. `sheet_data`
    # carries patient free text (nama / alamat / Nama Obat / puskesmas name), and
    # a STRING replacement is parsed as a regex template: one backslash anywhere
    # in that text raises re.PatternError ("bad escape \D", "invalid group
    # reference 2") and 500s the whole download. A callable is returned verbatim.
    # ``\`` in an ePuskesmas address ("JL X RT.01\RW.02") is not exotic.
    xml = re.sub(
        r"<sheetData/?>(?:.*?</sheetData>)?",
        lambda _m: sheet_data,
        xml,
        count=1,
        flags=re.S,
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
        f'{_text(letter[1], 1, s["title"], "KERTAS KERJA REGISTRI DISLIPIDEMIA")}</row>'
    )
    body.append(
        f'<row r="2">{_text(letter[1], 2, s["plain"], "Syarat Registri Dislipidemia (salah satu): 1) Kolesterol Total >= 200 mg/dL; ATAU 2) LDL >= 130 mg/dL; ATAU 3) HDL < 40 mg/dL; ATAU 4) Trigliserida > 150 mg/dL. Riwayat HT / DM ditampilkan sebagai informasi, bukan syarat masuk. Follow Up mulai bulan berikutnya setelah bulan kunjungan CKG; kontrol dijadwalkan setiap 3 bulan. Lihat sheet \'Formula & Logika\'.")}</row>'
    )
    body.append(
        f'<row r="3">{_text(letter[1], 3, s["bold"], f"Nama Puskesmas: {pk_name}")}'
        f'{_text(letter[8], 3, s["bold"], f"Tahun: {year}")}</row>'
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
    gcell(_GROUP_ROW, 7, "Hasil Pemeriksaan Lipid (pada Tanggal Berkunjung)", grp)
    gcell(_GROUP_ROW, _OBAT_COL, "Jenis Obat", grp)
    gcell(_GROUP_ROW, _FOLLOWUP_FIRST_COL, "Follow Up", grp)
    merges.append(f'<mergeCell ref="A{_GROUP_ROW}:{letter[6]}{_MONTH_ROW}"/>')
    merges.append(
        f'<mergeCell ref="{letter[7]}{_GROUP_ROW}:{letter[14]}{_MONTH_ROW}"/>'
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
def _abnormal_expr(kol: str, ldl: str, hdl: str, trig: str) -> str:
    """The B1 syarat as an Excel OR over four cell refs.

    Every threshold is COUNT-guarded because ``N("")`` is 0 — without the guard
    an empty HDL cell would satisfy ``<40`` and falsely read abnormal. The
    comparators mirror the sheet exactly: three inclusive, Trigliserida strict.
    """
    return (
        f"OR(AND(COUNT({kol})>0,N({kol})>={_KOL}),"
        f"AND(COUNT({ldl})>0,N({ldl})>={_LDL}),"
        f"AND(COUNT({hdl})>0,N({hdl})<{_HDL}),"
        f"AND(COUNT({trig})>0,N({trig})>{_TRIG}))"
    )


def _baseline_interpretasi_formula(r: int) -> str:
    """Live Excel implementation of ``lipid_registry_scan._interpretasi_baseline``.

    Columns on row ``r``: J=Kolesterol Total, K=LDL, L=HDL, M=Trigliserida.

    Riwayat (H, I) is deliberately absent from this formula — unlike the HT and
    DM registers, a recorded diagnosis does not pin the label here.
    """
    kol, ldl, hdl, trig = f"J{r}", f"K{r}", f"L{r}", f"M{r}"
    return (
        f'IF({_abnormal_expr(kol, ldl, hdl, trig)},"{_INTERP_DISLIPIDEMIA}",'
        f'IF(COUNT({kol},{ldl},{hdl},{trig})=0,"","{_INTERP_NORMAL}"))'
    )


def _followup_interpretasi_formula(letter, bc: int, r: int) -> str:
    """Live Excel implementation of ``lipid_registry_scan._interpretasi_followup``.

    Month columns from ``bc``: +0 Tanggal, +1 Kolesterol Total, +2 LDL, +3 HDL,
    +4 Trigliserida.

    The "everything empty → Missed Visit" branch is correct here only because the
    scan emits a row for a month at all ONLY when there was a kunjungan or a
    missed CONTROL — see this module's docstring.
    """
    tgl = f"{letter[bc]}{r}"
    kol, ldl = f"{letter[bc + 1]}{r}", f"{letter[bc + 2]}{r}"
    hdl, trig = f"{letter[bc + 3]}{r}", f"{letter[bc + 4]}{r}"
    return (
        f'IF(COUNT({tgl},{kol},{ldl},{hdl},{trig})=0,"{_FU_MISSED_VISIT}",'
        f'IF(COUNT({kol},{ldl},{hdl},{trig})=0,"",'
        f'IF({_abnormal_expr(kol, ldl, hdl, trig)},'
        f'"{_FU_TIDAK_TERKENDALI}","{_FU_TERKENDALI}")))'
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

    # Baseline G–N (value on r0).
    grid[r0][7] = _date_cell(letter[7], r0, s["date"], p.get("tanggal_berkunjung"))
    grid[r0][8] = _text(letter[8], r0, s["text"], p.get("riwayat_ht"))
    grid[r0][9] = _text(letter[9], r0, s["text"], p.get("riwayat_dm"))
    grid[r0][10] = _num_cell(letter[10], r0, s["text"], p.get("kol_total"))
    grid[r0][11] = _num_cell(letter[11], r0, s["text"], p.get("ldl"))
    grid[r0][12] = _num_cell(letter[12], r0, s["text"], p.get("hdl"))
    grid[r0][13] = _num_cell(letter[13], r0, s["text"], p.get("trigliserida"))
    grid[r0][14] = _formula_cell(
        letter[14], r0, s["text"],
        _baseline_interpretasi_formula(r0),
        p.get("interpretasi"),
    )

    # Baseline Jenis Obat O (stacked).
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
                    grid[rr][bc + 1] = _num_cell(letter[bc + 1], rr, s["text"], v.get("kol_total"))
                    grid[rr][bc + 2] = _num_cell(letter[bc + 2], rr, s["text"], v.get("ldl"))
                    grid[rr][bc + 3] = _num_cell(letter[bc + 3], rr, s["text"], v.get("hdl"))
                    grid[rr][bc + 4] = _num_cell(letter[bc + 4], rr, s["text"], v.get("trigliserida"))
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

    # Vertical merges for identitas + baseline (A..N) across the block.
    if n > 1:
        for col in range(1, 15):
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
# Lipid-lowering families (Formularium Nasional, FKTP) — the Jenis Obat filter.
# Keep in sync with ``lipid_registry_scan._LIPID_DRUG_RE``.
_LIPID_DRUG_FAMILIES = [
    ("Statin",
     "Simvastatin, Atorvastatin, Rosuvastatin, Pravastatin, Lovastatin, Fluvastatin"),
    ("Fibrat", "Gemfibrozil, Fenofibrat"),
    ("Penghambat penyerapan kolesterol", "Ezetimib"),
    ("Pengikat asam empedu", "Kolestiramin (Cholestyramine)"),
]

_FORMULA_SHEET_ROWS: list[tuple[str, str, str]] = [
    # (kind, col A, col B) — kind: "title" | "section" | "item" | "blank"
    # Deliberately plain, non-technical Indonesian — read by puskesmas staff.
    ("title", "CARA MEMBACA KERTAS KERJA REGISTRI DISLIPIDEMIA", ""),
    ("blank", "", ""),
    ("item", "Intinya: satu daftar, dua pertanyaan",
     "Bagian 'Hasil Pemeriksaan Lipid' (hijau) menjawab: bagaimana profil lemak darah pasien SAAT skrining CKG? "
     "Bagian 'Follow Up' menjawab: pada kontrol berikutnya, apakah sudah mencapai target? "
     "Karena pertanyaannya berbeda, labelnya bisa berbeda — dan itu memang benar, bukan error."),
    ("blank", "", ""),
    ("section", "1. SIAPA YANG MASUK DAFTAR INI?", ""),
    ("item", "Masuk daftar jika memenuhi SALAH SATU",
     f"Kolesterol Total {_KOL} mg/dL ke atas; ATAU LDL {_LDL} mg/dL ke atas; ATAU HDL di bawah {_HDL} mg/dL; "
     f"ATAU Trigliserida di ATAS {_TRIG} mg/dL. Cukup satu saja yang memenuhi. "
     "Perhatikan Trigliserida: tepat 150 mg/dL masih dihitung normal, 151 mg/dL baru dihitung tinggi."),
    ("item", "Riwayat HT dan DM hanya informasi, bukan syarat",
     "Kolom 'Riwayat diagnosis HT' dan 'Riwayat diagnosis DM' ditampilkan supaya terlihat pasien mana yang "
     "punya penyakit penyerta — TAPI tidak menentukan siapa yang masuk daftar. Yang menentukan hanya hasil "
     "pengukuran lemak darahnya. Pasien dengan LDL tinggi tetap masuk daftar walaupun belum pernah "
     "didiagnosis hipertensi maupun diabetes."),
    ("item", "Beda dengan kertas kerja Hipertensi dan Diabetes",
     "Di dua kertas kerja itu, pasien yang sudah punya diagnosis SELALU diberi label penyakitnya walaupun "
     "hasil ukur hari itu bagus. Di sini tidak: label mengikuti hasil pengukuran, karena daftar ini memang "
     "disusun dari pengukuran."),
    ("item", "Yang tidak ditampilkan",
     "Pasien yang keempat nilai lemak darahnya masih dalam batas normal, dan pasien yang memang belum "
     "diperiksa lemak darahnya."),
    ("blank", "", ""),
    ("section", "2. ARTI SINGKATAN", ""),
    ("item", "Kolesterol Total", "Jumlah seluruh kolesterol dalam darah."),
    ("item", "LDL", "Kolesterol 'jahat' — makin tinggi makin berisiko menyumbat pembuluh darah."),
    ("item", "HDL", "Kolesterol 'baik' — makin TINGGI makin bagus. Karena itu batasnya terbalik: yang bermasalah justru kalau nilainya RENDAH."),
    ("item", "Trigliserida", "Jenis lemak lain dalam darah, ikut naik kalau pola makan tinggi gula dan lemak."),
    ("blank", "", ""),
    ("section", "3. ARTI LABEL INTERPRETASI (saat kunjungan CKG)", ""),
    ("item", _INTERP_DISLIPIDEMIA,
     f"Ada minimal SATU nilai yang melewati batas: Kolesterol Total >= {_KOL}, LDL >= {_LDL}, "
     f"HDL < {_HDL}, atau Trigliserida > {_TRIG} mg/dL."),
    ("item", _INTERP_NORMAL,
     "Lemak darah sudah diperiksa dan keempat nilainya masih dalam batas normal."),
    ("item", "Kosong",
     "Belum ada satu pun hasil pemeriksaan lemak darah pada kunjungan itu — bukan berarti normal."),
    ("blank", "", ""),
    ("section", "4. CARA BACA FOLLOW UP", ""),
    ("item", "Mulai kapan",
     "Mulai bulan SETELAH bulan skrining CKG. Bulan skrining sendiri tidak diulang di Follow Up karena "
     "sudah ada di bagian hijau."),
    ("item", "Kontrol dijadwalkan tiap 3 BULAN",
     "Format dirjen menilai target 'pada kunjungan 3 bulan berikutnya'. Jadi bulan kontrolnya adalah "
     "3, 6, 9, dan 12 bulan setelah bulan skrining CKG. Ini berbeda dengan kertas kerja Hipertensi dan "
     "Diabetes yang kontrolnya bulanan."),
    ("item", "Target tercapai",
     f"'{_FU_TERKENDALI}' — Kolesterol Total di bawah {_KOL}, DAN LDL di bawah {_LDL}, DAN HDL {_HDL} ke atas, "
     f"DAN Trigliserida {_TRIG} ke bawah. Semua nilai yang terisi harus dalam batas normal."),
    ("item", "Target tidak tercapai",
     f"'{_FU_TIDAK_TERKENDALI}' — ada minimal SATU nilai yang masih melewati batas. "
     "Satu nilai yang masih tinggi sudah cukup, walaupun nilai yang lain sudah bagus."),
    ("item", "Missed Visit hanya di bulan kontrol",
     f"'{_FU_MISSED_VISIT}' hanya muncul di bulan kontrol (3/6/9/12 bulan setelah skrining) yang terlewat "
     "tanpa pemeriksaan. Bulan di ANTARA jadwal kontrol sengaja dibiarkan kosong — memang tidak ada "
     "kontrol yang dijadwalkan di bulan itu, jadi tidak adil kalau dihitung terlewat. Bulan yang belum "
     "terjadi juga dibiarkan kosong."),
    ("item", "Semua kunjungan ditampilkan",
     "Kalau pasien diperiksa beberapa kali dalam sebulan, SEMUA kunjungannya ditampilkan berurutan "
     "di kolom bulan itu — masing-masing dengan tanggal, hasil, dan statusnya sendiri. Pemeriksaan di "
     "luar bulan kontrol tetap dicatat dan tetap dinilai."),
    ("blank", "", ""),
    ("section", "5. KENAPA KOLOM FOLLOW UP BANYAK YANG KOSONG?", ""),
    ("item", "Karena pemeriksaan lemak darah jarang dilakukan",
     "Pemeriksaan profil lipid di CKG hanya disediakan untuk usia 40 tahun ke atas DAN penyandang "
     "hipertensi dan/atau diabetes. Di luar itu, ePuskesmas jarang mencatat pemeriksaan lemak darah pada "
     "kunjungan biasa. Kolom yang kosong berarti pemeriksaannya memang tidak tercatat — bukan kesalahan "
     "sistem. Justru inilah yang perlu diperbaiki: makin lengkap pencatatannya, makin berguna kertas "
     "kerja ini."),
    ("blank", "", ""),
    ("section", "6. KOLOM JENIS OBAT — HANYA OBAT PENURUN LEMAK DARAH", ""),
    ("item", "Aturannya",
     "Hanya obat penurun lemak darah yang ditampilkan, sesuai kolom dirjen 'List Obat Dislipidemia'. "
     "Vitamin, antibiotik, obat darah tinggi, obat diabetes, dan obat lain sengaja tidak ditampilkan."),
    *[("item", fam, drugs) for fam, drugs in _LIPID_DRUG_FAMILIES],
    ("blank", "", ""),
    ("section", "7. DASAR ATURAN (untuk yang ingin memeriksa)", ""),
    ("item", f"Ambang Dislipidemia (Kol-total {_KOL} / LDL {_LDL} / HDL {_HDL} / Trigliserida {_TRIG})",
     "Legenda format dirjen 'Register Sheet Pasien HT, DM, Dislipidemia dan Obesitas', sheet 'Dislipidemia', "
     "bagian 'Syarat Registri Dislipidemia'."),
    ("item", "Target pengendalian dan jadwal kontrol 3 bulan",
     "Legenda format dirjen pada sheet yang sama, bagian kategori evaluasi pasien Dislipidemia."),
    ("item", "Pemeriksaan lemak darah di CKG",
     "Juknis CKG — KMK 84/2026, paket 'POCT Lipid Panel' (usia >= 40 tahun dan penyandang HT dan/atau DM): "
     "https://kesprimkom.kemkes.go.id/assets/uploads/contents/others/2026kepmenkes084.pdf"),
    ("item", "Daftar obat penurun lemak darah di puskesmas",
     "Formularium Nasional — KMK 1199/2025: "
     "https://farmalkes.kemkes.go.id/en/unduh/keputusan-menteri-kesehatan-republik-indonesia-nomor-hk-01-07-menkes-1199-2025-tentang-formularium-nasional/"),
    ("item", "Format & istilah registri",
     "Dokumen dirjen 'Register Sheet Pasien HT, DM, Dislipidemia dan Obesitas', sheet 'Dislipidemia'."),
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
        7: 16, 8: 18, 9: 18, 10: 13, 11: 11, 12: 11, 13: 13, 14: 24, 15: 22,
    }
    for c, w in widths.items():
        ws.column_dimensions[get_column_letter(c)].width = w
    for m in range(1, 13):
        bc = _month_base_col(m)
        for off, w in ((0, 14), (1, 13), (2, 9), (3, 9), (4, 13), (5, 24), (6, 20)):
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
