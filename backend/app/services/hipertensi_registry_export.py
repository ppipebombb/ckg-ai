"""Kertas Kerja Registri Hipertensi (V8juni2026 dirjen layout) .xlsx export.

One block of N rows per patient (NIK). Identitas (A–F) and the baseline "Hasil
Pemeriksaan TD" (G–O) are written once and vertically merged across the block;
the baseline ``Jenis Obat`` (P) stacks one drug per row; and the Follow Up grid
(Q–BX, 12 months × 5 columns) fills each month's column-group independently —
EVERY kunjungan in the month stacked in date order, each visit's drugs one per
row. Block height N is the tallest column-group.

The derived columns are LIVE Excel formulas (with cached values, recalculated
on open): Rerata (M,N) = ROUND(AVERAGE(TD1,TD2),1); Interpretasi (O) = the
≥140/90 / ≥120/80 bands; each month's Interpretasi hasil = the <140/90
terkendali rule (or "Pasien Missed Visit" when the month has no reading). A
second worksheet ("Formula & Logika") documents every rule so the reader can
see exactly how each conclusion was reached.

Rendered the fast way (raw XML, like ``diagnose_export``): openpyxl builds a tiny
*seed* carrying the cell styles we need (so styles.xml/theme are authored by the
tested library); we read those style indices back and emit every row plus the
``<mergeCells>`` block as raw XML. openpyxl's ``merge_cells`` is O(n²) and its
per-cell setters are heavy — a few hundred patients would take minutes; this
emits thousands of patients in seconds.
"""

from __future__ import annotations

import io
import re
import zipfile
from datetime import date

import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from app.services.hipertensi_registry_scan import (
    _FU_MISSED_VISIT,
    _FU_TERKENDALI,
    _FU_TIDAK_TERKENDALI,
    _INTERP_HIPERTENSI,
)

_MONTHS_ID = [
    "", "Januari", "Februari", "Maret", "April", "Mei", "Juni",
    "Juli", "Agustus", "September", "Oktober", "November", "Desember",
]

# Column layout (1-based): identitas A–F, baseline G–O, baseline obat P, then 12
# month-blocks of 5 columns each starting at Q (17). BX (76) is the last column.
_FOLLOWUP_FIRST_COL = 17
_MONTH_STRIDE = 5
_LAST_COL = _FOLLOWUP_FIRST_COL + 12 * _MONTH_STRIDE - 1  # 76 = BX

_IDENT_HEADERS = [
    "NIK", "Nama", "Jenis Kelamin", "Tanggal Lahir\n(DD/MM/YYYY)", "No. Tlp", "Alamat",
]
_BASELINE_HEADERS = [
    "Tanggal Berkunjung", "Riwayat diagnosis HT",
    "TD Sistolik 1\n(mmHg)", "TD Diastolik 1\n(mmHg)",
    "TD Sistolik 2\n(mmHg)", "TD Diastolik 2\n(mmHg)",
    "Rerata TD Sistolik", "Rerata TD Diastolik", "Interpretasi hasil",
]
_MONTH_SUBHEADERS = [
    "Tanggal Pemeriksaan\n(DD/MM/YYYY)", "TD Sistolik\n(mmHg)",
    "TD Diastolik\n(mmHg)", "Interpretasi hasil", "Jenis Obat",
]

_SHEET = "Registri Hipertensi"
_DATE_FMT = "DD/MM/YYYY"
_DATA_START = 8
_GROUP_ROW, _MONTH_ROW, _COL_ROW = 5, 6, 7

# Excel 1900 date system epoch (matches openpyxl): serial = (d - epoch).days.
_EXCEL_EPOCH = date(1899, 12, 30)


def _month_base_col(m: int) -> int:
    """First column index (1-based) of month ``m`` (1..12). Jan→17 (Q)."""
    return _FOLLOWUP_FIRST_COL + (m - 1) * _MONTH_STRIDE


def build_hipertensi_registry_workbook(
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
    xml = re.sub(r"<sheetData/?>(?:.*?</sheetData>)?", sheet_data, xml, count=1, flags=re.S)
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
                item, xml.encode("utf-8") if item.filename == part else zin.read(item.filename)
            )
    return out.getvalue()


# ── header ─────────────────────────────────────────────────────────────────
def _emit_header(body, merges, s, letter, pk_name: str, year: int) -> None:
    # Row 1: title (A1:P1). Row 2: syarat (A2:P2). Row 3: meta.
    body.append(
        f'<row r="1" ht="18" customHeight="1">{_text(letter[1], 1, s["title"], "KERTAS KERJA REGISTRI HIPERTENSI")}</row>'
    )
    body.append(
        f'<row r="2">{_text(letter[1], 2, s["plain"], "Syarat Registri Hipertensi (dan/atau): 1) Riwayat Diagnosis HT Positif; ATAU 2) Rerata TD (TD1 & TD2) saat kunjungan CKG Sistole >= 140 dan/atau Diastole >= 90. Follow Up mulai bulan berikutnya setelah bulan kunjungan CKG; semua kunjungan dalam bulan ditampilkan, masing-masing dengan statusnya. Lihat sheet \'Formula & Logika\'.")}</row>'
    )
    body.append(
        f'<row r="3">{_text(letter[1], 3, s["bold"], f"Nama Puskesmas: {pk_name}")}'
        f'{_text(letter[7], 3, s["bold"], f"Tahun: {year}")}</row>'
    )
    merges.append(f'<mergeCell ref="A1:{letter[16]}1"/>')
    merges.append(f'<mergeCell ref="A2:{letter[16]}2"/>')
    merges.append(f'<mergeCell ref="A3:{letter[6]}3"/>')

    # Header band rows 5–7. Build per-row cell dicts so spanned cells get a
    # bordered fill (the merge boxes render fully).
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
    gcell(_GROUP_ROW, 7, "Hasil Pemeriksaan TD (pada Tanggal Berkunjung)", grp)
    gcell(_GROUP_ROW, 16, "Jenis Obat", grp)
    gcell(_GROUP_ROW, _FOLLOWUP_FIRST_COL, "Follow Up", grp)
    merges.append(f'<mergeCell ref="A{_GROUP_ROW}:{letter[6]}{_MONTH_ROW}"/>')
    merges.append(f'<mergeCell ref="{letter[7]}{_GROUP_ROW}:{letter[15]}{_MONTH_ROW}"/>')
    merges.append(f'<mergeCell ref="{letter[16]}{_GROUP_ROW}:{letter[16]}{_COL_ROW}"/>')
    merges.append(
        f'<mergeCell ref="{letter[_FOLLOWUP_FIRST_COL]}{_GROUP_ROW}:{letter[_LAST_COL]}{_GROUP_ROW}"/>'
    )

    # Row 6 month names.
    for m in range(1, 13):
        bc = _month_base_col(m)
        gcell(_MONTH_ROW, bc, _MONTHS_ID[m], grp)
        merges.append(
            f'<mergeCell ref="{letter[bc]}{_MONTH_ROW}:{letter[bc + 4]}{_MONTH_ROW}"/>'
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

    # Fill every remaining header-band cell with a bordered group fill so the
    # merged spans render boxed, then emit the three rows.
    for r in (_GROUP_ROW, _MONTH_ROW, _COL_ROW):
        cells = [f'<row r="{r}" ht="30" customHeight="1">']
        style_for = grp if r != _COL_ROW else blkg
        for c in range(1, _LAST_COL + 1):
            cells.append(
                rows[r].get(c) or f'<c r="{letter[c]}{r}" s="{style_for}"/>'
            )
        cells.append("</row>")
        body.append("".join(cells))


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

    # Baseline G–O (value on r0).
    grid[r0][7] = _date_cell(letter[7], r0, s["date"], p.get("tanggal_berkunjung"))
    grid[r0][8] = _text(letter[8], r0, s["text"], p.get("riwayat_ht"))
    grid[r0][9] = _num_cell(letter[9], r0, s["text"], p.get("td_sys1"))
    grid[r0][10] = _num_cell(letter[10], r0, s["text"], p.get("td_dia1"))
    grid[r0][11] = _num_cell(letter[11], r0, s["text"], p.get("td_sys2"))
    grid[r0][12] = _num_cell(letter[12], r0, s["text"], p.get("td_dia2"))
    # Rerata + Interpretasi are live formulas (cached value = the scan's
    # computed value) so the reader can audit how the conclusion was reached.
    grid[r0][13] = _formula_cell(
        letter[13], r0, s["text"],
        f"IF(COUNT(I{r0},K{r0})=0,\"\",ROUND(AVERAGE(I{r0},K{r0}),1))",
        p.get("rerata_sys"),
    )
    grid[r0][14] = _formula_cell(
        letter[14], r0, s["text"],
        f"IF(COUNT(J{r0},L{r0})=0,\"\",ROUND(AVERAGE(J{r0},L{r0}),1))",
        p.get("rerata_dia"),
    )
    # Riwayat HT = Ya (col H) is "Hipertensi" regardless of the reading; else
    # rerata ≥140 dan/atau ≥90 = "Hipertensi", 130–139 / 85–89 = "Pre-Hipertensi",
    # below that "Normal". Mirrors _interpretasi_baseline in the scan.
    grid[r0][15] = _formula_cell(
        letter[15], r0, s["text"],
        f"IF(H{r0}=\"Ya\",\"{_INTERP_HIPERTENSI}\","
        f"IF(COUNT(M{r0},N{r0})=0,\"\","
        f"IF(OR(N(M{r0})>=140,N(N{r0})>=90),\"{_INTERP_HIPERTENSI}\","
        f"IF(OR(N(M{r0})>=130,N(N{r0})>=85),\"Pre-Hipertensi\",\"Normal\"))))",
        p.get("interpretasi"),
    )

    # Baseline Jenis Obat P (stacked).
    for i, drug in enumerate(obat):
        grid[r0 + i][16] = _text(letter[16], r0 + i, s["left"], drug)

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
                    grid[rr][bc + 1] = _num_cell(letter[bc + 1], rr, s["text"], v.get("sys"))
                    grid[rr][bc + 2] = _num_cell(letter[bc + 2], rr, s["text"], v.get("dia"))
                    cs, cd = letter[bc + 1], letter[bc + 2]
                    grid[rr][bc + 3] = _formula_cell(
                        letter[bc + 3], rr, s["text"],
                        f"IF(COUNT({cs}{rr},{cd}{rr})=0,\"{_FU_MISSED_VISIT}\","
                        f"IF(OR(N({cs}{rr})>=140,N({cd}{rr})>=90),"
                        f"\"{_FU_TIDAK_TERKENDALI}\",\"{_FU_TERKENDALI}\"))",
                        v.get("interpretasi"),
                    )
                if drug is not None:
                    grid[rr][bc + 4] = _text(letter[bc + 4], rr, s["left"], drug)
                rr += 1
            if len(drugs) > 1:
                for col in range(bc, bc + 4):
                    merges.append(
                        f'<mergeCell ref="{letter[col]}{v_start}:{letter[col]}{rr - 1}"/>'
                    )

    # Vertical merges for identitas + baseline (A..O) across the block.
    if n > 1:
        for col in range(1, 16):
            merges.append(f'<mergeCell ref="{letter[col]}{r0}:{letter[col]}{r_end}"/>')

    # Emit each row, filling untouched cells with a bordered blank.
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
    return f'<c r="{col_letter}{row}" s="{style}" t="inlineStr"><is><t{sp}>{esc}</t></is></c>'


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
# Antihypertensive families (Formularium Nasional, FKTP) — the Jenis Obat
# filter. Keep in sync with ``hipertensi_registry_scan._HT_DRUG_RE``.
_HT_DRUG_FAMILIES = [
    ("Antagonis kalsium (CCB)",
     "Amlodipin, Nifedipin, Felodipin, Nikardipin, Lerkanidipin, Diltiazem, Verapamil"),
    ("ACE inhibitor",
     "Kaptopril (Captopril), Lisinopril, Ramipril, Enalapril, Perindopril, Imidapril"),
    ("ARB (sartan)",
     "Kandesartan (Candesartan), Losartan, Valsartan, Irbesartan, Telmisartan, Olmesartan"),
    ("Diuretik",
     "Hidroklorotiazid (HCT) dan tiazid lain, Furosemid, Spironolakton, Indapamid, Klortalidon"),
    ("Beta-blocker",
     "Bisoprolol, Atenolol, Propranolol, Metoprolol, Carvedilol, Nebivolol"),
    ("Lainnya (agonis sentral / alpha-blocker / vasodilator)",
     "Metildopa, Klonidin, Doksazosin, Terazosin, Prazosin, Hidralazin, Minoxidil"),
]

_FORMULA_SHEET_ROWS: list[tuple[str, str, str]] = [
    # (kind, col A, col B) — kind: "title" | "section" | "item" | "blank"
    # Wording is deliberately plain, non-technical Indonesian — this sheet is
    # read by puskesmas staff. The technical detail lives in
    # documents/KERTAS_KERJA_HIPERTENSI_LOGIC.md.
    ("title", "CARA MEMBACA KERTAS KERJA REGISTRI HIPERTENSI", ""),
    ("blank", "", ""),
    ("item", "Intinya: satu daftar, dua pertanyaan",
     "Bagian 'Hasil Pemeriksaan TD' (hijau) menjawab: berapa tensi pasien SAAT skrining CKG? "
     "Bagian 'Follow Up' menjawab: pada bulan-bulan SETELAHNYA, apakah tensinya sudah di bawah 140/90? "
     "Karena pertanyaannya berbeda, labelnya bisa berbeda — dan itu memang benar, bukan error."),
    ("blank", "", ""),
    ("section", "1. SIAPA YANG MASUK DAFTAR INI?", ""),
    ("item", "Masuk daftar jika memenuhi SALAH SATU",
     "(1) Sudah tercatat sebagai pasien hipertensi — ada diagnosis hipertensi di ePuskesmas, atau pasien "
     "menjawab 'Ya' saat ditanya 'pernah dinyatakan tekanan darah tinggi?' di skrining CKG → kolom Riwayat = Ya.  "
     "ATAU (2) Tensinya di atas normal saat skrining CKG — rata-rata pengukuran 130/85 ke atas → kolom "
     "Interpretasi = Hipertensi (140/90 ke atas) atau Pre-Hipertensi (130–139/85–89)."),
    ("item", "Yang tidak ditampilkan",
     "Pasien yang tensinya Normal (di bawah 130/85) DAN tidak pernah didiagnosis hipertensi — belum perlu "
     "dipantau di kertas kerja ini."),
    ("blank", "", ""),
    ("section", "2. DARI MANA ANGKA TENSINYA?", ""),
    ("item", "TD 1 (pengukuran pertama)",
     "Dari pemeriksaan di ePuskesmas pada hari kunjungan CKG."),
    ("item", "TD 2 (pengukuran kedua)",
     "Dari data skrining CKG (ASIK). Sering kosong — artinya petugas hanya mengukur satu kali. "
     "Kosong itu normal, bukan error."),
    ("item", "Rerata (rata-rata)",
     "Rerata = (TD1 + TD2) dibagi 2. Kalau TD2 kosong, rerata = TD1 saja. "
     "Rumusnya tertanam langsung di kolom — klik sel Rerata atau Interpretasi di sheet sebelah untuk melihatnya."),
    ("blank", "", ""),
    ("section", "3. ARTI LABEL", ""),
    ("item", "Interpretasi (saat kunjungan CKG)",
     "Kalau pasien SUDAH punya diagnosis hipertensi (Riwayat = Ya) → selalu 'Hipertensi', berapa pun tensinya. "
     "Kalau Riwayat = Tidak, dinilai dari tensinya: 140/90 ke atas → 'Hipertensi'.  130–139 / 85–89 → "
     "'Pre-Hipertensi'.  Di bawah itu → 'Normal'. "
     "PENTING: cukup SATU angka yang tinggi. Contoh 137/100 = Hipertensi, karena angka bawahnya (100) sudah 90 ke atas, "
     "walaupun angka atasnya (137) belum 140. Batas ini sesuai aturan resmi Kemenkes untuk CKG.  "
     "Yang dinilai adalah RATA-RATA (kolom Rerata). Kalau hanya ada satu kali ukur (TD2 kosong), rata-ratanya = TD1, "
     "jadi satu kali ukur yang tinggi sudah cukup untuk 'Hipertensi'."),
    ("item", "Status Follow Up (tiap bulan)",
     f"Di bawah 140/90 → '{_FU_TERKENDALI}'.  140/90 ke atas → '{_FU_TIDAK_TERKENDALI}'.  "
     f"Tidak ada pemeriksaan tensi bulan itu → '{_FU_MISSED_VISIT}'."),
    ("blank", "", ""),
    ("section", "4. CARA BACA FOLLOW UP", ""),
    ("item", "Mulai kapan",
     "Mulai bulan SETELAH bulan skrining CKG. Bulan skrining sendiri tidak diulang di Follow Up karena "
     "sudah ada di bagian hijau."),
    ("item", "Semua kunjungan ditampilkan",
     "Kalau pasien datang beberapa kali dalam sebulan, SEMUA kunjungannya ditampilkan berurutan "
     "di kolom bulan itu — masing-masing dengan tanggal, hasil tensi, dan statusnya sendiri."),
    ("item", "Missed Visit & bulan kosong",
     "Bulan yang sudah lewat tanpa pemeriksaan tensi = 'Pasien Missed Visit'. "
     "Bulan yang belum terjadi dibiarkan kosong."),
    ("blank", "", ""),
    ("section", "5. KOLOM JENIS OBAT — HANYA OBAT DARAH TINGGI", ""),
    ("item", "Aturannya",
     "Hanya obat darah tinggi yang ditampilkan, sesuai kolom dirjen 'List Obat Hipertensi'. "
     "Vitamin, antibiotik, obat gula, dan obat lain sengaja tidak ditampilkan."),
    *[("item", fam, drugs) for fam, drugs in _HT_DRUG_FAMILIES],
    ("blank", "", ""),
    ("section", "6. KALAU LABELNYA TERLIHAT 'BERTENTANGAN'", ""),
    ("item", "'Hipertensi' di awal, lalu 'terkendali' di Follow Up",
     "Artinya: saat skrining tensinya tinggi (itulah alasan dia masuk daftar), lalu bulan-bulan berikutnya "
     "sudah di bawah 140/90. Ini justru kabar baik — skrining berhasil menemukan, kontrolnya berhasil. "
     "Label awal tidak berubah karena ia mencatat kondisi saat skrining."),
    ("item", "Interpretasi 'Hipertensi' padahal tensinya hari itu bagus",
     "Artinya: pasien ini SUDAH punya diagnosis hipertensi (Riwayat = Ya), jadi tetap berlabel 'Hipertensi' "
     "walau tensinya hari itu di bawah 140/90 — diagnosisnya tidak hilang karena satu hasil ukur yang bagus. "
     "Kalau tensinya sudah terkontrol, Follow Up bulan berikutnya akan menyebutnya 'terkendali'."),
    ("item", "Riwayat 'Tidak' tapi Interpretasi 'Hipertensi'",
     "Riwayat = pernah didiagnosis SEBELUMNYA. Pasien yang baru ketahuan tensinya tinggi saat skrining "
     "memang riwayatnya 'Tidak' — dia pasien hipertensi yang baru ditemukan."),
    ("item", "Interpretasi 'Pre-Hipertensi' tapi di Follow Up disebut 'pasien hipertensi'",
     "Pasien Pre-Hipertensi (tensinya 130–139/85–89, belum didiagnosis) ikut dipantau lebih awal. "
     "Tulisan 'Pasien hipertensi terkendali/tidak terkendali' di Follow Up adalah istilah baku format dirjen "
     "(bukan berarti dia sudah pasti didiagnosis) — bacalah sebagai: target di bawah 140/90 tercapai atau tidak."),
    ("blank", "", ""),
    ("section", "7. DASAR ATURAN (untuk yang ingin memeriksa)", ""),
    ("item", "Batas Normal / Pre-Hipertensi / Hipertensi + aturan rata-rata 2x ukur",
     "Juknis CKG — KMK 84/2026: https://kesprimkom.kemkes.go.id/assets/uploads/contents/others/2026kepmenkes084.pdf"),
    ("item", "Klasifikasi hipertensi dewasa",
     "PNPK Hipertensi Dewasa — KMK 4634/2021: "
     "https://kemkes.go.id/app_asset/file_content_download/1700108499655598d3c61e16.60954826.pdf"),
    ("item", "'Terkendali' = di bawah 140/90 pada kunjungan terakhir; kontrol minimal 1x/bulan",
     "Pedoman Pengendalian Hipertensi di FKTP (Kemenkes 2024): "
     "https://diskes.badungkab.go.id/storage/diskes/file/Buku%20Pedoman%20Hipertensi%202024.pdf "
     "dan Permenkes 4/2019 (SPM): https://peraturan.bpk.go.id/Details/111713/permenkes-no-4-tahun-2019"),
    ("item", "Daftar obat darah tinggi di puskesmas",
     "Formularium Nasional — KMK 1199/2025: "
     "https://farmalkes.kemkes.go.id/en/unduh/keputusan-menteri-kesehatan-republik-indonesia-nomor-hk-01-07-menkes-1199-2025-tentang-formularium-nasional/"),
    ("item", "Format & istilah registri",
     "Dokumen dirjen 'V2. Registri HT, DM, IMT, dan Dislipidemia', sheet 'hasil rpt dirjen_V8juni2026 Hip'."),
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
    # Derived columns carry live formulas with cached values — make Excel
    # recalculate them on open.
    wb.calculation.fullCalcOnLoad = True

    # Column widths.
    widths = {
        1: 20, 2: 22, 3: 12, 4: 14, 5: 14, 6: 30,
        7: 16, 8: 16, 9: 11, 10: 11, 11: 11, 12: 11, 13: 12, 14: 12, 15: 14, 16: 22,
    }
    for c, w in widths.items():
        ws.column_dimensions[get_column_letter(c)].width = w
    for m in range(1, 13):
        bc = _month_base_col(m)
        for off, w in ((0, 14), (1, 9), (2, 9), (3, 13), (4, 20)):
            ws.column_dimensions[get_column_letter(bc + off)].width = w

    thin = Side(style="thin", color="B0B0B0")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    center = Alignment(horizontal="center", vertical="center", wrap_text=True)
    left = Alignment(horizontal="left", vertical="top", wrap_text=True)
    bold = Font(bold=True)
    title_font = Font(bold=True, size=13)
    group_fill = PatternFill("solid", fgColor="BDD7EE")
    header_fill = PatternFill("solid", fgColor="D9E1F2")

    # One cell per distinct style variant so styles.xml carries them all.
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
