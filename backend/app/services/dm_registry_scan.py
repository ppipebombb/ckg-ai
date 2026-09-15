"""Per-NIK Diabetes Melitus **registry** scan (dirjen "Register Sheet" layout).

Sibling of :mod:`app.services.hipertensi_registry_scan` — same two-query shape,
same ASIK-first sourcing, same follow-up grid — with the blood-pressure block
swapped for the glucose block the "Diabetes Melitus" sheet expects:

  - **Identitas** (NIK, Nama, Jenis Kelamin, Tanggal Lahir, No.Tlp, Alamat):
    ASIK ``detail_data``, EPUS ``data_pasien`` fallback.
  - **Baseline "Hasil pemeriksaan Gula Darah"**: ``Tanggal Berkunjung`` (the
    earliest MATCHED/CKG visit), ``Riwayat diagnosis DM``, ``GDS 1``, ``GDS 2``,
    ``GDP``, ``GD2PP``, ``HbA1C``, ``Interpretasi``, and ``Jenis Obat``.
  - **Follow Up**: per month from the month AFTER the CKG visit, every EPUS
    visit carrying a glucose reading, each evaluated against the U17 target.

Inclusion (sheet DO note N15 — the wider of the two syarat statements; the C1
header omits GD2PP): a NIK appears iff it has ≥1 MATCHED visit in the year AND
  1) **Riwayat diagnosis DM positif** — the ASIK CKG answer "Apakah Anda pernah
     dinyatakan diabetes atau kencing manis oleh Dokter?" = Ya, a recorded ASIK
     tatalaksana Diagnosis with a DM ICD, or (fallback) an EPUS diagnosis
     (ICD E10–E14, Riwayat PTM pada Diri Sendiri, Tandai Penyakit Kronis); OR
  2) the baseline ``interpretasi`` is "Diabetes Melitus" or "Prediabetes".

**Data reality (measured 2026-07-20, sample of 4k rows):** the baseline block
fills well (GDS1 58%, GDP 24%, riwayat answered 62%) but the EPUS follow-up is
sparse — GDP 4.7%, GDS 4.4%, GD2PP 1.6%, HbA1C 0.9% of visits. The 12-month grid
is therefore mostly empty by construction, which is the intended finding: it
shows where ePuskesmas glucose recording is missing. Do not "fix" this by
inventing fallbacks.

Cost: EPUS decrypted once per row; ASIK decrypted only for each candidate NIK's
baseline visit, in a single batched second query — never per-row.
"""

from __future__ import annotations

import itertools
import re
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.security import decrypt_json
from app.models.patient import MatchStatus, Patient
from app.services.epus_to_asik import _detect_chronic_flags

# Diabetes diagnosis: ICD-10 E10–E14, or a diagnosis name mentioning diabetes in
# ID/EN. Mirrors ``epus_to_asik._DM_ICDX_PREFIXES``.
_DM_ICD_RE = re.compile(r"\bE1[0-4]\b", re.IGNORECASE)
_DM_NAME_RE = re.compile(r"diabetes|kencing manis", re.IGNORECASE)

# Antidiabetic drug filter for the Jenis Obat columns (the sheet marks them
# "List_obat_dm"). Families per Formularium Nasional for FKTP/Puskesmas, with
# Indonesian + INN spellings:
#   biguanide, sulfonilurea, alpha-glucosidase inhibitor, thiazolidinedione,
#   DPP-4 inhibitor, SGLT2 inhibitor, GLP-1 agonist, and every insulin.
_DM_DRUG_RE = re.compile(
    r"metformin"
    r"|glibenklamid|glibenclamid|glimepirid|gliklazid|gliclazid|glipizid"
    r"|glikuidon|gliquidon"
    r"|akarbose|acarbose"
    r"|pioglitazon|rosiglitazon"
    r"|sitagliptin|vildagliptin|linagliptin|saxagliptin|alogliptin"
    r"|dapagliflozin|empagliflozin|kanagliflozin|canagliflozin"
    r"|liraglutid|semaglutid|exenatid"
    r"|insulin|novorapid|novomix|lantus|levemir|humalog|humulin|actrapid|apidra",
    re.IGNORECASE,
)

_MONTHS_ID = [
    "", "Januari", "Februari", "Maret", "April", "Mei", "Juni",
    "Juli", "Agustus", "September", "Oktober", "November", "Desember",
]

# Follow-up "Interpretasi hasil" labels — from the sheet legend (U17: "Pasien
# terdiagnosis Diabetes Melitus ... dievaluasi dengan kategori").
_FU_TERKENDALI = "Pasien DM terkendali (target tercapai)"
_FU_TIDAK_TERKENDALI = "Pasien DM tidak terkendali (target tidak tercapai)"
_FU_MISSED_VISIT = "Pasien Missed Visit"

# NOTE: the legend also defines "Pasien Loss to Follow Up (LTFU)" = no clinical
# visit for 12 CONSECUTIVE months. A single-year scan cannot reach that state —
# a baseline in January leaves at most 11 follow-up months — so LTFU is
# deliberately NOT emitted here. It needs cross-year visit history; see the
# hipertensi charts bundle for the pattern if it is ever added.

# Baseline interpretasi labels.
_INTERP_DM = "Diabetes Melitus"
# Elevated-but-not-diabetic band. NOT defined by the sheet — taken from the
# Kemkes pedoman skrining DM, consistent with ``epus_to_asik._gds_bucket``
# (which buckets GDS 140–199 as Prediabetes).
_INTERP_PREDIABETES = "Prediabetes"
# The N15 "tidak valid" cases (see :func:`_interpretasi_baseline`).
_INTERP_TIDAK_VALID = "Tidak dapat diinterpretasikan"

# The ASIK CKG riwayat question on the Pemeriksaan Gula Darah forms.
_ASIK_RIWAYAT_KEY = "pernah dinyatakan diabetes"

# EPUS lab table that carries Glukosa Puasa / HbA1c results.
_LAB_TABLE_NAME = "Ubah Data Laboratorium"


# ── value parsing ──────────────────────────────────────────────────────────
def _num(raw: Any) -> float | None:
    if raw is None or str(raw).strip() == "":
        return None
    try:
        return float(Decimal(str(raw).replace(",", ".").strip()))
    except (InvalidOperation, ValueError):
        return None


def _is_ya(raw: Any) -> bool:
    return str(raw or "").strip().lower() in ("ya", "iya", "y")


def _empty_glucose() -> dict[str, Any]:
    return {"gds1": None, "gds2": None, "gdp": None, "gd2pp": None, "hba1c": None}


# ── EPUS extraction ────────────────────────────────────────────────────────
def _extract_glucose_epus(epus: Any) -> dict[str, Any]:
    """Glucose readings from one EPUS visit.

    Source of truth is ``PTM → Pemeriksaan``; the ``Laboratorium`` table fills
    GDP/HbA1C gaps (measured: it adds ~50% more GDP coverage than the PTM tab
    alone). ``Pemeriksaan Gula`` is EPUS's generic glucose field — treat it as
    GDS only when the dedicated GDP field is empty, otherwise it duplicates GDP
    (same rule ``epus_to_asik._map_pemeriksaan_gula_darah_dewasa_lansia`` uses).
    """
    out = _empty_glucose()
    if not isinstance(epus, dict):
        return out
    tabs = epus.get("tabs") or {}
    pem = ((tabs.get("PTM") or {}).get("fields", {}) or {}).get("Pemeriksaan")
    if isinstance(pem, dict):
        out["gdp"] = _num(pem.get("Pemeriksaan Gula Darah Puasa"))
        out["gd2pp"] = _num(pem.get("Pemeriksaan Gula Darah 2 Jam PP"))
        out["hba1c"] = _num(pem.get("HbA1c"))
        generic = _num(pem.get("Pemeriksaan Gula"))
        out["gds1"] = generic if (generic is not None and out["gdp"] is None) else None

    rows = ((tabs.get("Laboratorium") or {}).get("tables", {}) or {}).get(
        _LAB_TABLE_NAME
    )
    if isinstance(rows, list):
        # Collect first, apply after: within the array the LAST matching row wins
        # (per-array latest, the same rule gdp_report._extract_lab_gdp uses — a
        # re-test on the same visit supersedes the earlier result). Applying the
        # PTM gap-fill inside the loop instead would freeze the FIRST lab row and
        # make this report disagree with the GD Puasa report about the same value.
        lab_gdp: float | None = None
        lab_hba1c: float | None = None
        for row in rows:
            if not isinstance(row, dict):
                continue
            name = str(row.get("Pemeriksaan") or "").casefold()
            val = _num(row.get("Hasil"))
            if val is None:
                continue
            if "hba1c" in name or "hb1ac" in name:
                lab_hba1c = val
            elif "glukosa puasa" in name or "gula puasa" in name:
                lab_gdp = val
        # PTM stays the source of truth; the lab table only fills its gaps —
        # one rule for both fields, as this module's docstring states.
        if out["gdp"] is None:
            out["gdp"] = lab_gdp
        if out["hba1c"] is None:
            out["hba1c"] = lab_hba1c
    return out


def _riwayat_epus_hit(epus: Any) -> bool:
    """True if the EPUS visit carries a diabetes DIAGNOSIS record:
    ``penyakit_khusus`` ICD E10–E14 or a diabetes-named entry, or any of the
    converter's clinical signals (Riwayat PTM pada Diri Sendiri = Penyakit
    Diabetes, Diagnosa → Tandai Penyakit Kronis → Diabetes Mellitus, ICD in PTM
    Diagnosa free text) — the same canonical detection
    ``epus_to_asik._detect_chronic_flags`` uses, so the registry stays consistent
    with the merge/converter pipeline."""
    if not isinstance(epus, dict):
        return False
    for item in epus.get("penyakit_khusus") or []:
        if not isinstance(item, dict):
            continue
        icd = str(item.get("ICDX") or "")
        name = str(item.get("Penyakit") or "")
        if _DM_ICD_RE.search(icd) or _DM_NAME_RE.search(name):
            return True
    try:
        return bool(_detect_chronic_flags(epus)["clinical"]["diabetes"])
    except Exception:
        return False


def _extract_obat(epus: Any) -> list[str]:
    """Antidiabetic ``Nama Obat`` entries in the visit's Resep table
    (``tabs.Resep.tables.Resep[]``), in order, de-duplicated. Non-DM drugs are
    dropped (the sheet's Jenis Obat columns are "List_obat_dm")."""
    if not isinstance(epus, dict):
        return []
    rows = (
        ((epus.get("tabs") or {}).get("Resep") or {}).get("tables", {}) or {}
    ).get("Resep")
    if not isinstance(rows, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = (row.get("Nama Obat") or "").strip()
        if name and name not in seen and _DM_DRUG_RE.search(name):
            seen.add(name)
            out.append(name)
    return out


def _parse_birthdate(epus: Any) -> str | None:
    """Birthdate as an ISO date string from ``data_pasien`` "Tempat/Tgl Lahir"
    (or jaksel "Tempat & Tgl Lahir"). Anchors on the trailing ``DD-MM-YYYY``."""
    if not isinstance(epus, dict):
        return None
    dp = epus.get("data_pasien") or {}
    ttl = dp.get("Tempat/Tgl Lahir") or dp.get("Tempat & Tgl Lahir")
    if ttl in (None, ""):
        return None
    s = re.sub(r"\s+", " ", str(ttl)).strip()
    m = re.search(r"(\d{1,2})-(\d{1,2})-(\d{4})\s*$", s)
    if not m:
        return None
    d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
    try:
        return date(y, mo, d).isoformat()
    except ValueError:
        return None


def _extract_identitas(epus: Any) -> dict[str, Any]:
    """Identitas fields from EPUS ``data_pasien``."""
    if not isinstance(epus, dict):
        return {}
    dp = epus.get("data_pasien") or {}
    jk_raw = (dp.get("Jenis Kelamin") or "").strip()
    jk = {"L": "Laki-Laki", "P": "Perempuan"}.get(jk_raw.upper(), jk_raw)
    alamat = dp.get("Alamat")
    return {
        "nama": (dp.get("Nama Pasien") or dp.get("Nama") or "").strip(),
        "jenis_kelamin": jk,
        "tanggal_lahir": _parse_birthdate(epus),
        "no_tlp": (dp.get("No Telp / HP") or dp.get("No. Telp") or "").strip(),
        "alamat": re.sub(r"\s+", " ", str(alamat)).strip() if alamat else "",
    }


# ── ASIK extraction (glucose + riwayat answer) ─────────────────────────────
def _glucose_fields_from_form(fd_items, out: dict[str, Any]) -> None:
    """Fill ``out`` (gds1/gds2/gdp/gd2pp/hba1c/riwayat_ya) from (key, value)
    pairs of a "Gula Darah" form. Labels are matched loosely so minor wording
    drift still resolves; existing values are kept (first source wins).

    Order matters: "Gula Darah Sewaktu Kedua (GDS 2)…" also contains "sewaktu",
    so the GDS-2 test must run first. "Gula Darah Puasa Lanjutan (GDP)" is
    matched by the same "puasa" test as the plain GDP field — both are GDP.
    """
    for k, v in fd_items:
        kl = str(k).casefold()
        if _ASIK_RIWAYAT_KEY in kl:
            if _is_ya(v):
                out["riwayat_ya"] = True
            continue
        if "sewaktu kedua" in kl or "gds 2" in kl or "gds2" in kl:
            slot = "gds2"
        elif "sewaktu" in kl:
            slot = "gds1"
        elif "puasa" in kl:
            slot = "gdp"
        elif "2 jam pp" in kl:
            slot = "gd2pp"
        elif "hba1c" in kl or "hb1ac" in kl:
            slot = "hba1c"
        else:
            continue
        if out.get(slot) is None:
            out[slot] = _num(v)


def _extract_asik_glucose(asik: Any) -> dict[str, Any]:
    """Glucose readings + riwayat answer from the raw ASIK blob.

    Unlike hipertensi (one "Tekanan Darah" form) the CKG glucose values are
    spread over SEVERAL layanan — measured on 3k matched rows: "Pemeriksaan Gula
    Darah Dewasa Lansia", "Skrining Gula Darah", "Pemeriksaan Gula Darah
    Lanjutan (GDP & GD 2 PP)", "Pemeriksaan Gula Darah Lanjutan (HbA1C)", and
    the mandiri "Tekanan Darah & Gula Darah". So every form whose ``layanan``
    mentions gula darah is walked, and the first non-null value per slot wins.
    """
    out: dict[str, Any] = _empty_glucose()
    out["riwayat_ya"] = False
    if not isinstance(asik, dict):
        return out
    for arr_key in ("pelayanan_nakes", "pemeriksaan_mandiri"):
        for entry in asik.get(arr_key) or []:
            if not isinstance(entry, dict):
                continue
            layanan = str(entry.get("layanan") or "").casefold()
            if "gula darah" not in layanan and "hba1c" not in layanan:
                continue
            fd = entry.get("form_data")
            if isinstance(fd, dict):
                _glucose_fields_from_form(fd.items(), out)
    return out


# ── ASIK identitas + tatalaksana ───────────────────────────────────────────
_MONTH_NUM = {m.casefold(): i for i, m in enumerate(_MONTHS_ID) if m}


def _parse_asik_birthdate(raw: Any) -> str | None:
    """ASIK ``data_individu`` "Tanggal Lahir" is "DD NamaBulan YYYY"
    (e.g. "25 Januari 2000") → ISO date string."""
    if raw in (None, ""):
        return None
    s = re.sub(r"\s+", " ", str(raw)).strip()
    m = re.match(r"^(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})$", s)
    if not m:
        return None
    mo = _MONTH_NUM.get(m.group(2).casefold())
    if not mo:
        return None
    try:
        return date(int(m.group(3)), mo, int(m.group(1))).isoformat()
    except ValueError:
        return None


def _extract_asik_identitas(asik: Any) -> dict[str, Any]:
    """Identitas from raw ASIK ``detail_data`` (data_individu + data_domisili).
    Missing fields come back empty so the per-field EPUS fallback can fill them."""
    if not isinstance(asik, dict):
        return {}
    dd = asik.get("detail_data") or {}
    di = dd.get("data_individu") or {}
    dom = dd.get("data_domisili") or {}
    alamat = dom.get("Alamat Domisili")
    return {
        "nama": (di.get("Nama") or "").strip(),
        "jenis_kelamin": (di.get("Jenis Kelamin") or "").strip(),
        "tanggal_lahir": _parse_asik_birthdate(di.get("Tanggal Lahir")),
        "no_tlp": (di.get("No. HP/WA orang tua") or "").strip(),
        "alamat": re.sub(r"\s+", " ", str(alamat)).strip() if alamat else "",
    }


def _asik_dm_tatalaksana_forms(asik: Any):
    """Yield the ``form_data`` of each RECORDED "Gula Darah" tatalaksana row.
    ``belum_dilakukan`` rows carry no form and are skipped."""
    if not isinstance(asik, dict):
        return
    tata = asik.get("tatalaksana")
    if not isinstance(tata, dict):
        return
    for row in tata.get("rows") or []:
        if not isinstance(row, dict):
            continue
        if "gula darah" not in str(row.get("kelompok_skrinning") or "").casefold():
            continue
        fd = row.get("form_data")
        if isinstance(fd, dict) and fd:
            yield fd


def _extract_asik_obat(asik: Any) -> list[str]:
    """Antidiabetics prescribed in the recorded ASIK Gula Darah tatalaksana form
    (Peresepan "Pilih obat" / "Pilih obat (n)"), filtered to DM drugs and
    de-duplicated — the ASIK source-of-truth for Jenis Obat."""
    out: list[str] = []
    seen: set[str] = set()
    for fd in _asik_dm_tatalaksana_forms(asik):
        for k, v in fd.items():
            if not str(k).casefold().startswith("pilih obat"):
                continue
            name = str(v or "").strip()
            if name and name not in seen and _DM_DRUG_RE.search(name):
                seen.add(name)
                out.append(name)
    return out


def _asik_tatalaksana_dm_diagnosis(asik: Any) -> bool:
    """True if a recorded ASIK Gula Darah tatalaksana form carries a diabetes
    Diagnosis (ICD E10–E14 or a diabetes-named entry)."""
    for fd in _asik_dm_tatalaksana_forms(asik):
        for k, v in fd.items():
            if "diagnosis" not in str(k).casefold():
                continue
            val = str(v or "")
            if _DM_ICD_RE.search(val) or _DM_NAME_RE.search(val):
                return True
    return False


# ── classification ─────────────────────────────────────────────────────────
def _usable_readings(g: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """Apply the sheet's N15 validity rule and return ``(usable, had_invalid)``.

    N15: "apabila GD2PP tanpa GDP; or GDS2 tanpa GDS1 ... maka tidak valid, jadi
    tidak bisa diinterpretasikan". Rather than discarding the whole row, the
    unpaired reading alone is masked out — a GDS1 of 250 stays interpretable
    even when an orphan GD2PP sits beside it. ``had_invalid`` records that
    something was masked so the caller can label a row that has nothing left.
    """
    usable = dict(g)
    had_invalid = False
    if usable.get("gd2pp") is not None and usable.get("gdp") is None:
        usable["gd2pp"] = None
        had_invalid = True
    if usable.get("gds2") is not None and usable.get("gds1") is None:
        usable["gds2"] = None
        had_invalid = True
    return usable, had_invalid


def _interpretasi_baseline(g: dict[str, Any], *, riwayat_ya: bool) -> str:
    """Interpretasi on the visit date.

    A recorded DM diagnosis (Riwayat DM = Ya) is "Diabetes Melitus" regardless of
    the readings — a diagnosed patient stays diabetic even when controlled that
    day (same rule the hipertensi registry applies to Riwayat HT).

    Otherwise, per the sheet DO note (N15) plus the Kemkes prediabetes bands:
      Diabetes Melitus — GDP ≥126, GD2PP ≥200, or GDS2 ≥200
      Prediabetes      — GDP 100–125, GD2PP 140–199, or GDS1 140–199
      Normal           — below those
    Diabetes takes precedence over Prediabetes. Readings masked by the N15
    validity rule do not count; a row left with nothing usable but which DID
    carry an invalid combination is "Tidak dapat diinterpretasikan" rather than
    silently "Normal".
    """
    if riwayat_ya:
        return _INTERP_DM
    usable, had_invalid = _usable_readings(g)
    gds1, gds2 = usable.get("gds1"), usable.get("gds2")
    gdp, gd2pp = usable.get("gdp"), usable.get("gd2pp")

    if all(v is None for v in (gds1, gds2, gdp, gd2pp)):
        return _INTERP_TIDAK_VALID if had_invalid else ""

    if (
        (gdp is not None and gdp >= 126)
        or (gd2pp is not None and gd2pp >= 200)
        or (gds2 is not None and gds2 >= 200)
    ):
        return _INTERP_DM
    if (
        (gdp is not None and 100 <= gdp <= 125)
        or (gd2pp is not None and 140 <= gd2pp <= 199)
        or (gds1 is not None and 140 <= gds1 <= 199)
    ):
        return _INTERP_PREDIABETES
    return "Normal"


def _interpretasi_followup(g: dict[str, Any]) -> str:
    """Follow-up evaluation (sheet U17 legend).

    target tercapai      — HbA1c <7, GDP 80–130, or GD2PP <180
    target tidak tercapai — HbA1c ≥7, GDP >130, or GD2PP ≥180

    Any failing signal wins over a passing one (mirrors the hipertensi rule,
    where either an elevated systolic OR diastolic marks the visit uncontrolled).

    Two gaps in the legend, resolved here and documented for the formula card:
      - **GDS has no target band.** A visit carrying only GDS is NOT
        interpretable → "" (blank), never "tidak tercapai".
      - **GDP <80 is undefined.** Treated as tidak tercapai — hypoglycaemia is
        not "terkendali".
    """
    hba1c, gdp, gd2pp = g.get("hba1c"), g.get("gdp"), g.get("gd2pp")
    if hba1c is None and gdp is None and gd2pp is None:
        return ""
    failed = (
        (hba1c is not None and hba1c >= 7)
        or (gdp is not None and (gdp > 130 or gdp < 80))
        or (gd2pp is not None and gd2pp >= 180)
    )
    return _FU_TIDAK_TERKENDALI if failed else _FU_TERKENDALI


def count_interpretasi_bands(patients: list[dict]) -> tuple[int, int]:
    """(diabetes, prediabetes) counts over registry patients. Reads each
    patient's already-computed ``interpretasi`` (no rescan); shared by the
    registry list and summary endpoints.

    These DO sum to the registry total, because every qualifying row is either
    Riwayat DM = Ya (always labelled "Diabetes Melitus") or was admitted for
    having interpretasi "Diabetes Melitus"/"Prediabetes" — see the syarat filter
    in :func:`_finalize_registry`. The invariant is asserted in the tests.
    """
    diabetes = sum(1 for p in patients if p.get("interpretasi") == _INTERP_DM)
    prediabetes = sum(1 for p in patients if p.get("interpretasi") == _INTERP_PREDIABETES)
    return diabetes, prediabetes


# ── per-visit decode (EPUS) ────────────────────────────────────────────────
class _Visit:
    __slots__ = ("id", "fd", "matched", "group", "gluc", "obat", "riwayat", "epus")

    def __init__(self, *, id, fd, matched, group, gluc, obat, riwayat, epus):
        self.id = id
        self.fd = fd
        self.matched = matched
        self.group = group
        self.gluc = gluc
        self.obat = obat
        self.riwayat = riwayat
        self.epus = epus


def _blob_query(puskesmas_id: uuid.UUID, start: date, end: date):
    """EPUS-blob query for one puskesmas over ``[start, end)``, ordered so a NIK's
    visits stream contiguously oldest-first. created_at breaks same-date ties (a
    re-scrape sorts after the original), so "last wins" keeps the freshest scrape."""
    return (
        select(
            Patient.id,
            Patient.nik,
            Patient.nama,
            Patient.filter_date,
            Patient.match_status,
            Patient.match_group_id,
            Patient.scraped_epus_data,
        )
        .where(
            Patient.puskesmas_id == puskesmas_id,
            Patient.filter_date >= start,
            Patient.filter_date < end,
            Patient.scraped_epus_data.isnot(None),
        )
        .order_by(Patient.nik, Patient.filter_date.asc(), Patient.created_at.asc())
        .execution_options(yield_per=200, stream_results=True)
    )


def _blob_nik_count_query(puskesmas_id: uuid.UUID, start: date, end: date):
    """Distinct-NIK count over the SAME window/filters as ``_blob_query`` — the
    progress-bar denominator (one cheap indexed aggregate before the scan)."""
    return select(func.count(func.distinct(Patient.nik))).where(
        Patient.puskesmas_id == puskesmas_id,
        Patient.filter_date >= start,
        Patient.filter_date < end,
        Patient.scraped_epus_data.isnot(None),
    )


def _decode_group(group) -> tuple[str, list[_Visit]]:
    """Decode one NIK's EPUS rows into ``_Visit`` objects — each EPUS blob is
    decrypted exactly once here. Returns ``(nama_db, visits)`` in row order."""
    visits: list[_Visit] = []
    nama_db = ""
    for r in group:
        nama_db = nama_db or (r.nama or "")
        try:
            epus = decrypt_json(r.scraped_epus_data)
        except Exception:
            epus = None
        visits.append(
            _Visit(
                id=r.id,
                fd=r.filter_date,
                matched=(r.match_status == MatchStatus.MATCHED),
                group=r.match_group_id,
                gluc=_extract_glucose_epus(epus),
                obat=_extract_obat(epus),
                riwayat=_riwayat_epus_hit(epus),
                epus=epus,
            )
        )
    return nama_db, visits


def _fetch_asik_by_id(db: Session, ids: set) -> dict:
    """Batch-decrypt the ASIK blobs for the given baseline row ids →
    ``{id: asik_dict | None}`` (each ASIK blob decrypted at most once)."""
    asik_by_id: dict = {}
    if not ids:
        return asik_by_id
    asik_q = select(Patient.id, Patient.scraped_asik_data).where(
        Patient.id.in_(list(ids))
    )
    for r in db.execute(asik_q):
        if r.id not in ids:
            continue
        asik = None
        if r.scraped_asik_data is not None:
            try:
                asik = decrypt_json(r.scraped_asik_data)
            except Exception:
                asik = None
        asik_by_id[r.id] = asik
    return asik_by_id


def _has_glucose(g: dict[str, Any]) -> bool:
    return any(g.get(k) is not None for k in ("gds1", "gds2", "gdp", "gd2pp", "hba1c"))


def _build_registry_candidate(
    nik: str, nama_db: str, visits: list[_Visit], year: int, today: date
) -> tuple[dict | None, Any]:
    """Build one registry candidate from a NIK's in-year ``visits``. Returns
    ``(patient_dict, baseline_id)`` or ``(None, None)`` when the NIK has no
    MATCHED (CKG) visit in the year. The syarat filter runs later in
    :func:`_finalize_registry` (both legs need the ASIK 2nd pass)."""
    matched_visits = [v for v in visits if v.matched]
    if not matched_visits:
        return None, None
    baseline = matched_visits[0]  # visits are filter_date-ascending

    ident = _extract_identitas(baseline.epus)
    nama = ident.get("nama") or nama_db

    # Follow Up: grouped per month, starting the month AFTER the CKG visit month
    # ("pada kunjungan bulan berikutnya"). EVERY visit with a glucose reading is
    # listed in date order. Scrape twins collapse: cross-date twins
    # (match_group_id) keep the earliest date, same-date re-scrapes keep one row
    # per date — the freshest scrape wins via the created_at ordering.
    seen_groups: set[uuid.UUID] = set()
    by_date: dict[date, _Visit] = {}
    for v in visits:  # ascending by (filter_date, created_at)
        if v.fd.month <= baseline.fd.month:
            continue
        if not _has_glucose(v.gluc):
            continue
        if v.group is not None:
            if v.group in seen_groups:
                continue
            seen_groups.add(v.group)
        by_date[v.fd] = v

    followup: dict[str, list[dict]] = {}
    for fd in sorted(by_date):
        v = by_date[fd]
        followup.setdefault(str(fd.month), []).append(
            {
                "tanggal": fd.isoformat(),
                "gds": v.gluc.get("gds1"),
                "gdp": v.gluc.get("gdp"),
                "gd2pp": v.gluc.get("gd2pp"),
                "hba1c": v.gluc.get("hba1c"),
                "interpretasi": _interpretasi_followup(v.gluc),
                "obat": v.obat,
            }
        )

    # Fill gap months (month after the visit month → current month; full year for
    # past years) with a "Pasien Missed Visit" row. Future months stay blank.
    last_month = 12 if year < today.year else (today.month if year == today.year else 0)
    for m in range(baseline.fd.month + 1, last_month + 1):
        if str(m) not in followup:
            followup[str(m)] = [
                {
                    "tanggal": None,
                    "gds": None,
                    "gdp": None,
                    "gd2pp": None,
                    "hba1c": None,
                    "interpretasi": _FU_MISSED_VISIT,
                    "obat": [],
                }
            ]

    patient = {
        "nik": nik,
        "nama": nama,
        "jenis_kelamin": ident.get("jenis_kelamin", ""),
        "tanggal_lahir": ident.get("tanggal_lahir"),
        "no_tlp": ident.get("no_tlp", ""),
        "alamat": ident.get("alamat", ""),
        "tanggal_berkunjung": baseline.fd.isoformat(),
        "riwayat_dm": "Tidak",  # finalized below
        "gds1": baseline.gluc.get("gds1"),
        "gds2": None,  # ASIK-only (EPUS has no 2nd sewaktu reading)
        "gdp": baseline.gluc.get("gdp"),
        "gd2pp": baseline.gluc.get("gd2pp"),
        "hba1c": baseline.gluc.get("hba1c"),
        "interpretasi": "",
        "obat": baseline.obat,
        "followup": followup,
        "_riwayat_epus": any(v.riwayat for v in visits),
        "_riwayat_ckg": False,  # ASIK answer/diagnosis, filled below
        # Per-field source provenance — seeded to the EPUS baseline values here;
        # the ASIK 2nd pass flips these to "ASIK" when ASIK wins.
        "_gluc_src": "EPUS" if _has_glucose(baseline.gluc) else None,
        "_obat_src": "EPUS" if baseline.obat else None,
    }
    return patient, baseline.id


def _finalize_registry(
    patients: list[dict], baseline_asik_id: dict, asik_by_id: dict
) -> dict:
    """Batched 2nd pass: raw ASIK is the source of truth for Identitas, the
    baseline glucose readings, Riwayat DM, and Jenis Obat; the EPUS values
    already in ``p`` are the per-field fallback. Then interpretasi + the syarat
    filter. Follow Up stays EPUS."""
    by_nik = {p["nik"]: p for p in patients}
    for nik, vid in baseline_asik_id.items():
        p = by_nik.get(nik)
        if p is None:
            continue
        asik = asik_by_id.get(vid)
        a = _extract_asik_glucose(asik)
        # Identitas: ASIK wins per field, EPUS (already in p) fills the gaps.
        ident = _extract_asik_identitas(asik)
        for k in ("nama", "jenis_kelamin", "tanggal_lahir", "no_tlp", "alamat"):
            if ident.get(k):
                p[k] = ident[k]
        # Glucose: ASIK wins PER FIELD (unlike hipertensi's TD1, which wins as a
        # pair) — the CKG readings are spread across several forms and any one of
        # them may be absent while ePuskesmas has the value.
        won_any = False
        for slot in ("gds1", "gds2", "gdp", "gd2pp", "hba1c"):
            if a.get(slot) is not None:
                p[slot] = a[slot]
                won_any = True
        if won_any:
            p["_gluc_src"] = "ASIK"
        # Jenis Obat: ASIK tatalaksana prescription wins; EPUS Resep fallback.
        asik_obat = _extract_asik_obat(asik)
        if asik_obat:
            p["obat"] = asik_obat
            p["_obat_src"] = "ASIK"
        # Riwayat DM: ASIK self-report answer OR a recorded ASIK tatalaksana DM
        # diagnosis; EPUS diagnosis stays the fallback (sticky Ya).
        p["_riwayat_ckg"] = a["riwayat_ya"] or _asik_tatalaksana_dm_diagnosis(asik)

    # Baseline interpretasi + final riwayat, then the syarat filter: keep iff
    # Riwayat diagnosis DM positif OR the interpretasi is Diabetes Melitus /
    # Prediabetes. Normal, blank and "tidak valid" rows without a diagnosis
    # record stay out.
    qualified: list[dict] = []
    for p in patients:
        riwayat_epus = p.pop("_riwayat_epus")
        riwayat_ckg = p.pop("_riwayat_ckg")
        riwayat = riwayat_ckg or riwayat_epus  # ASIK wins; EPUS fallback
        p["riwayat_dm"] = "Ya" if riwayat else "Tidak"
        p["interpretasi"] = _interpretasi_baseline(
            p, riwayat_ya=(p["riwayat_dm"] == "Ya")
        )
        gluc_src = p.pop("_gluc_src")
        obat_src = p.pop("_obat_src")
        p["sources"] = {
            "gula_darah": gluc_src,
            "riwayat_dm": "ASIK" if riwayat_ckg else ("EPUS" if riwayat_epus else None),
            "obat": obat_src if p["obat"] else None,
        }
        if p["riwayat_dm"] == "Ya" or p["interpretasi"] in (
            _INTERP_DM,
            _INTERP_PREDIABETES,
        ):
            qualified.append(p)

    qualified.sort(key=lambda x: ((x["nama"] or "").casefold(), x["nik"]))
    return {"patients": qualified, "computed_at": datetime.now(UTC).isoformat()}


def scan_dm_registry(
    db: Session, puskesmas_id: uuid.UUID, year: int, *, progress=None
) -> dict:
    """Build the cacheable registry payload for (puskesmas, year):
    ``{patients: [...], computed_at}``. ``patients`` is pre-sorted by (nama, nik);
    search and pagination are applied on top of it at request time.

    Two queries (EPUS blobs, then a batched ASIK pass over the baselines).

    ``progress`` (optional): a ``make_progress_writer`` callback ticked once per
    NIK so the on-miss warm can surface a progress bar."""
    year_start = date(year, 1, 1)
    year_end = date(year + 1, 1, 1)
    today = date.today()

    total = 0
    if progress:
        total = db.scalar(_blob_nik_count_query(puskesmas_id, year_start, year_end)) or 0
    done = 0

    # Candidates = every NIK with ≥1 MATCHED visit; the syarat filter runs later.
    patients: list[dict] = []
    baseline_asik_id: dict[str, Any] = {}  # nik -> baseline visit id
    for nik, group in itertools.groupby(
        db.execute(_blob_query(puskesmas_id, year_start, year_end)),
        key=lambda r: r.nik,
    ):
        nama_db, visits = _decode_group(group)
        patient, bid = _build_registry_candidate(nik, nama_db, visits, year, today)
        if patient is not None:
            patients.append(patient)
            baseline_asik_id[nik] = bid
        if progress:
            done += 1
            progress(done, total)

    asik_by_id = _fetch_asik_by_id(db, set(baseline_asik_id.values()))
    return _finalize_registry(patients, baseline_asik_id, asik_by_id)
