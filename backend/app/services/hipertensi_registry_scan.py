"""Per-NIK Hipertensi **registry** scan (V8juni2026 dirjen layout).

Unlike ``dashboard_scan`` (EPUS-only, per-month Sistolik/Diastolik grid) this
builds the per-visit registry the new "Kertas Kerja Hipertensi" sheet expects:

  Source of truth for the top block is **raw ASIK** (the CKG screening record);
  the matched EPUS visit on the SAME date is the per-field fallback. Follow Up is
  the exception — it stays EPUS (it tracks the next months' ePuskesmas visits).

  - **Identitas** (NIK, Nama, Jenis Kelamin, Tanggal Lahir, No.Tlp, Alamat):
    ASIK ``detail_data`` (data_individu + data_domisili), EPUS ``data_pasien``
    fallback.
  - **Baseline "Hasil pemeriksaan TD"**: ``Tanggal Berkunjung`` (the earliest
    MATCHED/CKG visit date), ``Riwayat diagnosis HT``, ``TD Sistolik/Diastolik 1``
    (ASIK first reading, EPUS ``Anamnesa → Periksa Fisik`` / ``PTM → Tekanan
    Darah & IMT`` fallback), ``TD Sistolik/Diastolik 2`` (ASIK only),
    ``Rerata``, ``Interpretasi`` (Hipertensi / Pre-Hipertensi / Normal — a
    Riwayat HT = Ya diagnosis is Hipertensi regardless of the reading, else from
    the rerata; see :func:`_interpretasi_baseline`),
    and ``Jenis Obat`` (ASIK tatalaksana Peresepan, EPUS baseline visit's Resep
    fallback). Each baseline value also carries its source (ASIK / ePuskesmas)
    in ``sources`` for the dashboard.
  - **Follow Up**: per month, from the month AFTER the CKG visit month
    ("kunjungan bulan berikutnya" per the sheet legend) — EVERY visit with a
    TD reading in the month is listed in date order, each evaluated
    independently against the <140/90 target (client feedback 2026-06: show
    all visits, not just the last one). Scrape twins collapse to one
    kunjungan: cross-date via ``match_group_id`` (earliest date wins),
    same-date re-scrapes via one-row-per-date (freshest ``created_at`` wins).

Inclusion (sheet "Syarat Registri Hipertensi", dan/atau): a NIK appears iff it
has ≥1 MATCHED visit in the year (the CKG visit anchors Tanggal Berkunjung) AND
  1) **Riwayat diagnosis HT positif** — a diagnosis RECORD, not a high reading:
     the ASIK CKG answer "Apakah Anda pernah dinyatakan tekanan darah tinggi?"
     = Ya, a recorded ASIK tatalaksana Diagnosis with an HT ICD, or (fallback)
     an EPUS diagnosis (ICD I10–I13/I15 in ``penyakit_khusus`` / PTM Diagnosa,
     Riwayat PTM pada Diri Sendiri / Tandai Penyakit Kronis); OR
  2) **Rerata TD (TD1 & TD2) elevated** at the CKG visit — baseline
     ``interpretasi`` is "Hipertensi" (≥140 dan/atau ≥90) or "Pre-Hipertensi"
     (130–139 dan/atau 85–89).
Only a rerata that is Normal (≤129/≤84) with no diagnosis record stays out.

Cost: EPUS is decrypted once per row (same as ``dashboard_scan``); raw ASIK is
decrypted only for each candidate NIK's baseline visit (fetched in a single
batched second query — never per-row).
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

# Hypertension diagnosis: ICD-10 I10–I13 (essential/heart/kidney HT — the codes
# the dirjen sheet names) plus I15 (secondary HT, still hypertension; I14 is
# unused in ICD-10), or a diagnosis name mentioning hypertension in ID/EN.
_HT_ICD_RE = re.compile(r"\bI1[0-35]\b", re.IGNORECASE)
_HT_NAME_RE = re.compile(r"hipertensi|hypertension", re.IGNORECASE)

# Antihypertensive drug filter for the Jenis Obat columns (the dirjen sheet
# marks them "List Obat Hipertensi"; vertical_ver_ht: "nama obat anti
# hipertensi"). Families per Formularium Nasional for FKTP/Puskesmas, with
# Indonesian + INN spellings:
#   CCB (amlodipin…), ACE-inhibitor (kaptopril…), ARB (kandesartan…),
#   diuretics (tiazid/HCT, furosemid, spironolakton, indapamid, klortalidon),
#   beta-blockers, central α2-agonists, α1-blockers, direct vasodilators.
_HT_DRUG_RE = re.compile(
    r"amlodipin|nifedipin|felodipin|nikardipin|nicardipin|lerkanidipin|lercanidipin"
    r"|diltiazem|verapamil"
    r"|captopril|kaptopril|lisinopril|ramipril|enalapril|perindopril|imidapril"
    r"|candesartan|kandesartan|losartan|valsartan|irbesartan|telmisartan|olmesartan"
    r"|tiazid|thiazid|\bhct\b|furosemid|spironolakton|spironolacton|indapamid"
    r"|klortalidon|chlorthalidon"
    r"|bisoprolol|atenolol|propranolol|metoprolol|carvedilol|karvedilol|nebivolol"
    r"|metildopa|methyldopa|klonidin|clonidin|doksazosin|doxazosin|terazosin|prazosin"
    r"|hidralazin|hydralazin|minoxidil",
    re.IGNORECASE,
)

_MONTHS_ID = [
    "", "Januari", "Februari", "Maret", "April", "Mei", "Juni",
    "Juli", "Agustus", "September", "Oktober", "November", "Desember",
]

# Follow-up "Interpretasi hasil" labels — verbatim from the sheet legend (O16:
# "Pasien terdiagnosis hipertensi ... dievaluasi dengan kategori").
_FU_TERKENDALI = "Pasien hipertensi terkendali (target tercapai)"
_FU_TIDAK_TERKENDALI = "Pasien hipertensi tidak terkendali (target tidak tercapai)"
_FU_MISSED_VISIT = "Pasien Missed Visit"

# Baseline interpretasi label. Applies to a recorded HT diagnosis (Riwayat HT =
# Ya) regardless of the reading, and to any rerata ≥140/90 (a high reading is
# Hipertensi whether or not it is confirmed by a 2nd measurement).
_INTERP_HIPERTENSI = "Hipertensi"
# Elevated-but-not-hypertensive band (rerata 130–139/85–89, Riwayat HT = Tidak).
# Referenced by the syarat filter — Pre-Hipertensi rows are shown too.
_INTERP_PRE_HIPERTENSI = "Pre-Hipertensi"

# The ASIK CKG riwayat question on the Tekanan Darah Dewasa Lansia form.
_ASIK_RIWAYAT_KEY = "pernah dinyatakan tekanan darah tinggi"


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


# ── EPUS extraction ────────────────────────────────────────────────────────
def _extract_td1(epus: Any) -> tuple[float | None, float | None]:
    """First blood-pressure pair. Source of truth = ``Anamnesa → Periksa Fisik``
    (Sistole/Diastole), falling back per-field to ``PTM → Tekanan Darah & IMT``."""
    if not isinstance(epus, dict):
        return (None, None)
    tabs = epus.get("tabs") or {}
    fisik = ((tabs.get("Anamnesa") or {}).get("fields", {}) or {}).get("Periksa Fisik")
    ptm = ((tabs.get("PTM") or {}).get("fields", {}) or {}).get("Tekanan Darah & IMT")
    fisik = fisik if isinstance(fisik, dict) else {}
    ptm = ptm if isinstance(ptm, dict) else {}
    sys = _num(fisik.get("Sistole"))
    if sys is None:
        sys = _num(ptm.get("Sistole"))
    dia = _num(fisik.get("Diastole"))
    if dia is None:
        dia = _num(ptm.get("Diastole"))
    return (sys, dia)


def _riwayat_epus_hit(epus: Any) -> bool:
    """True if the EPUS visit carries a hypertension DIAGNOSIS record:
    ``penyakit_khusus`` ICD I10–I13/I15 or a hypertension-named entry, or any
    of the converter's clinical signals (Riwayat PTM pada Diri Sendiri =
    Penyakit Hipertensi Ya, Diagnosa → Tandai Penyakit Kronis → Hipertensi,
    ICD in PTM Diagnosa free text) — the same canonical detection
    ``epus_to_asik._detect_chronic_flags`` uses, so the registry stays
    consistent with the merge/converter pipeline."""
    if not isinstance(epus, dict):
        return False
    for item in epus.get("penyakit_khusus") or []:
        if not isinstance(item, dict):
            continue
        icd = str(item.get("ICDX") or "")
        name = str(item.get("Penyakit") or "")
        if _HT_ICD_RE.search(icd) or _HT_NAME_RE.search(name):
            return True
    try:
        return bool(_detect_chronic_flags(epus)["clinical"]["hipertensi"])
    except Exception:
        return False


def _extract_obat(epus: Any) -> list[str]:
    """Antihypertensive ``Nama Obat`` entries in the visit's Resep table
    (``tabs.Resep.tables.Resep[]``), in order, de-duplicated. Non-HT drugs are
    dropped (the sheet's Jenis Obat columns are "List Obat Hipertensi")."""
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
        if name and name not in seen and _HT_DRUG_RE.search(name):
            seen.add(name)
            out.append(name)
    return out


def _parse_birthdate(epus: Any) -> str | None:
    """Birthdate as an ISO date string from ``data_pasien`` "Tempat/Tgl Lahir"
    (or jaksel "Tempat & Tgl Lahir"). Anchors on the trailing ``DD-MM-YYYY`` so
    the place/separator/whitespace don't matter (mirrors epus_to_asik)."""
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


# ── ASIK / merged extraction (TD pairs + riwayat answer) ───────────────────
def _td_fields_from_form(fd_items, out: dict[str, Any]) -> None:
    """Fill ``out`` (sys1/dia1/sys2/dia2/riwayat_ya) from (key, value) pairs of
    a "Tekanan Darah" form. Field labels are matched loosely so minor wording
    drift still resolves; existing values are kept (first source wins)."""
    for k, v in fd_items:
        kl = str(k).casefold()
        if _ASIK_RIWAYAT_KEY in kl:
            if _is_ya(v):
                out["riwayat_ya"] = True
            continue
        ke2 = "ke-2" in kl or "ke 2" in kl or "ke2" in kl
        if "sistol" in kl:
            slot = "sys2" if ke2 else "sys1"
        elif "diastol" in kl:
            slot = "dia2" if ke2 else "dia1"
        else:
            continue
        if out.get(slot) is None:
            out[slot] = _num(v)


def _extract_asik_td(asik: Any) -> dict[str, Any]:
    """TD pairs + riwayat answer from the raw ASIK "Tekanan Darah Dewasa
    Lansia" form. Walks ``pelayanan_nakes[]`` then ``pemeriksaan_mandiri[]``."""
    out: dict[str, Any] = {"sys1": None, "dia1": None, "sys2": None, "dia2": None, "riwayat_ya": False}
    if not isinstance(asik, dict):
        return out
    for arr_key in ("pelayanan_nakes", "pemeriksaan_mandiri"):
        for entry in asik.get(arr_key) or []:
            if not isinstance(entry, dict):
                continue
            if "tekanan darah" not in str(entry.get("layanan") or "").casefold():
                continue
            fd = entry.get("form_data")
            if isinstance(fd, dict):
                _td_fields_from_form(fd.items(), out)
    return out


# ── ASIK identitas + tatalaksana (Riwayat diagnosis HT + Jenis Obat) ────────
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
    Jenis Kelamin already arrives as "Laki-Laki"/"Perempuan". Missing fields come
    back empty so the per-field EPUS fallback can fill them."""
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


def _asik_td_tatalaksana_forms(asik: Any):
    """Yield the ``form_data`` of each RECORDED "Tekanan Darah" tatalaksana row
    (the nakes' follow-up treatment for hypertension). ``belum_dilakukan`` rows
    carry no form and are skipped."""
    if not isinstance(asik, dict):
        return
    tata = asik.get("tatalaksana")
    if not isinstance(tata, dict):
        return
    for row in tata.get("rows") or []:
        if not isinstance(row, dict):
            continue
        if "tekanan darah" not in str(row.get("kelompok_skrinning") or "").casefold():
            continue
        fd = row.get("form_data")
        if isinstance(fd, dict) and fd:
            yield fd


def _extract_asik_obat(asik: Any) -> list[str]:
    """Antihypertensives prescribed in the recorded ASIK Tekanan Darah
    tatalaksana form (Peresepan "Pilih obat" / "Pilih obat (n)"), filtered to HT
    drugs and de-duplicated — the ASIK source-of-truth for Jenis Obat."""
    out: list[str] = []
    seen: set[str] = set()
    for fd in _asik_td_tatalaksana_forms(asik):
        for k, v in fd.items():
            if not str(k).casefold().startswith("pilih obat"):
                continue
            name = str(v or "").strip()
            if name and name not in seen and _HT_DRUG_RE.search(name):
                seen.add(name)
                out.append(name)
    return out


def _asik_tatalaksana_ht_diagnosis(asik: Any) -> bool:
    """True if a recorded ASIK Tekanan Darah tatalaksana form carries a
    hypertension Diagnosis (ICD I10–I15 or a hypertension-named entry) — an ASIK
    "Riwayat diagnosis HT" signal."""
    for fd in _asik_td_tatalaksana_forms(asik):
        for k, v in fd.items():
            if "diagnosis" not in str(k).casefold():
                continue
            val = str(v or "")
            if _HT_ICD_RE.search(val) or _HT_NAME_RE.search(val):
                return True
    return False


# ── classification ─────────────────────────────────────────────────────────
def _interpretasi_baseline(
    sys: float | None, dia: float | None, *, riwayat_ya: bool
) -> str:
    """Interpretasi on the visit date. A recorded HT diagnosis (Riwayat HT = Ya)
    is "Hipertensi" regardless of the rerata TD — a diagnosed patient stays
    Hipertensi even when the reading is controlled that day. Otherwise the
    rerata TD bands apply, per the CKG juknis (KMK 84/2026) / PNPK 4634/2021
    (ESC/ESH): Normal ≤129/≤84, Prehipertensi 130–139 dan/atau 85–89, Hipertensi
    ≥140 dan/atau ≥90. Hipertensi takes precedence over Pre-Hipertensi.

    A rerata ≥140/90 is "Hipertensi" regardless of how many readings produced it.
    When there is no TD2, rerata == TD1 (see :func:`_rerata`), so a single high
    reading suffices."""
    if riwayat_ya:
        return _INTERP_HIPERTENSI
    if sys is None and dia is None:
        return ""
    s = sys if sys is not None else 0.0
    d = dia if dia is not None else 0.0
    if s >= 140 or d >= 90:
        return _INTERP_HIPERTENSI
    if s >= 130 or d >= 85:
        return _INTERP_PRE_HIPERTENSI
    return "Normal"


def _interpretasi_followup(sys: float | None, dia: float | None) -> str:
    """Follow-up evaluation (sheet O16 legend), using the legend's verbatim
    category text: terkendali (target tercapai) if TD <140/90, else tidak
    terkendali (target tidak tercapai) when sys ≥140 and/or dia ≥90."""
    if sys is None and dia is None:
        return ""
    s = sys if sys is not None else 0.0
    d = dia if dia is not None else 0.0
    return _FU_TIDAK_TERKENDALI if (s >= 140 or d >= 90) else _FU_TERKENDALI


def _rerata(v1: float | None, v2: float | None) -> float | None:
    """Average of the readings present; v1 alone if v2 is absent."""
    vals = [v for v in (v1, v2) if v is not None]
    if not vals:
        return None
    return round(sum(vals) / len(vals), 1)


def count_interpretasi_bands(patients: list[dict]) -> tuple[int, int]:
    """(hipertensi, pre_hipertensi) counts over registry patients — the syarat
    guarantees every listed patient is one or the other, so the two sum to the
    registry total. Reads each patient's already-computed ``interpretasi`` (no
    rescan); shared by the registry list/summary and the dashboard totals card."""
    hipertensi = sum(1 for p in patients if p.get("interpretasi") == _INTERP_HIPERTENSI)
    pre_hipertensi = sum(
        1 for p in patients if p.get("interpretasi") == _INTERP_PRE_HIPERTENSI
    )
    return hipertensi, pre_hipertensi


# ── per-visit decode (EPUS) ────────────────────────────────────────────────
class _Visit:
    __slots__ = ("id", "fd", "matched", "group", "sys1", "dia1", "obat", "riwayat", "epus")

    def __init__(self, *, id, fd, matched, group, sys1, dia1, obat, riwayat, epus):
        self.id = id
        self.fd = fd
        self.matched = matched
        self.group = group
        self.sys1 = sys1
        self.dia1 = dia1
        self.obat = obat
        self.riwayat = riwayat
        self.epus = epus


def _blob_query(puskesmas_id: uuid.UUID, start: date, end: date):
    """EPUS-blob query for one puskesmas over ``[start, end)``, ordered so a NIK's
    visits stream contiguously oldest-first. created_at breaks same-date ties (a
    re-scrape sorts after the original), so "last wins" keeps the freshest scrape.
    Shared by the single-year registry scan and the cross-year warm bundle."""
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
    """Distinct-NIK count over the SAME window/filters as ``_blob_query`` — i.e.
    the exact number of ``groupby(nik)`` iterations. Used as the progress-bar
    denominator (one cheap indexed aggregate before the multi-minute scan)."""
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
        sys1, dia1 = _extract_td1(epus)
        visits.append(
            _Visit(
                id=r.id,
                fd=r.filter_date,
                matched=(r.match_status == MatchStatus.MATCHED),
                group=r.match_group_id,
                sys1=sys1,
                dia1=dia1,
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


def _build_registry_candidate(
    nik: str, nama_db: str, visits: list[_Visit], year: int, today: date
) -> tuple[dict | None, Any]:
    """Build one registry candidate from a NIK's in-year ``visits``. Returns
    ``(patient_dict, baseline_id)`` or ``(None, None)`` when the NIK has no
    MATCHED (CKG) visit in the year. The syarat filter runs later in
    :func:`_finalize_registry` (both legs need the ASIK 2nd pass — riwayat may
    come from the ASIK answer, and TD2 can push a borderline rerata over 140/90)."""
    # Anchor = earliest MATCHED (EPUS+ASIK) visit in the year.
    matched_visits = [v for v in visits if v.matched]
    if not matched_visits:
        return None, None
    baseline = matched_visits[0]  # visits are filter_date-ascending

    ident = _extract_identitas(baseline.epus)
    nama = ident.get("nama") or nama_db

    # Follow Up: grouped per month, starting the month AFTER the CKG visit month
    # (legend: "pada kunjungan bulan berikutnya"). EVERY visit with a TD reading
    # is listed in date order. Scrape twins collapse: cross-date twins
    # (match_group_id — the same real visit on two filter_dates) keep the
    # earliest date, and same-date re-scrapes keep one row per date — the
    # freshest scrape wins via the created_at ordering.
    seen_groups: set[uuid.UUID] = set()
    by_date: dict[date, _Visit] = {}
    for v in visits:  # ascending by (filter_date, created_at)
        if v.fd.month <= baseline.fd.month:
            continue
        if v.sys1 is None and v.dia1 is None:
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
                "sys": v.sys1,
                "dia": v.dia1,
                "interpretasi": _interpretasi_followup(v.sys1, v.dia1),
                "obat": v.obat,
            }
        )

    # Fill gap months (month after the visit month → current month; full year for
    # past years) with a "Pasien Missed Visit" row so the registry shows the
    # no-show. Future months (current year) stay blank.
    last_month = 12 if year < today.year else (today.month if year == today.year else 0)
    for m in range(baseline.fd.month + 1, last_month + 1):
        if str(m) not in followup:
            followup[str(m)] = [
                {
                    "tanggal": None,
                    "sys": None,
                    "dia": None,
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
        "riwayat_ht": "Tidak",  # finalized below
        "td_sys1": baseline.sys1,
        "td_dia1": baseline.dia1,
        "td_sys2": None,  # filled from ASIK below
        "td_dia2": None,
        "rerata_sys": None,
        "rerata_dia": None,
        "interpretasi": "",
        "obat": baseline.obat,
        "followup": followup,
        "_riwayat_epus": any(v.riwayat for v in visits),
        "_riwayat_ckg": False,  # ASIK answer/diagnosis, filled below
        # Per-field source provenance — seeded to the EPUS baseline values here;
        # the ASIK 2nd pass flips these to "ASIK" when ASIK wins.
        "_td1_src": "EPUS"
        if (baseline.sys1 is not None or baseline.dia1 is not None)
        else None,
        "_obat_src": "EPUS" if baseline.obat else None,
    }
    return patient, baseline.id


def _finalize_registry(
    patients: list[dict], baseline_asik_id: dict, asik_by_id: dict
) -> dict:
    """Batched 2nd pass: raw ASIK is the source of truth for Identitas, the
    baseline TD reading, Riwayat HT, and Jenis Obat; the EPUS values already in
    ``p`` are the per-field fallback. Then rerata + interpretasi + the syarat
    filter. ``asik_by_id`` maps each baseline ``Patient.id`` to its
    already-decrypted ASIK dict (or None). Follow Up stays EPUS."""
    by_nik = {p["nik"]: p for p in patients}
    for nik, vid in baseline_asik_id.items():
        p = by_nik.get(nik)
        if p is None:
            continue
        asik = asik_by_id.get(vid)
        a_td = _extract_asik_td(asik)
        # Identitas: ASIK wins per field, EPUS (already in p) fills the gaps.
        ident = _extract_asik_identitas(asik)
        for k in ("nama", "jenis_kelamin", "tanggal_lahir", "no_tlp", "alamat"):
            if ident.get(k):
                p[k] = ident[k]
        # TD1: the ASIK reading wins as a pair; EPUS is the fallback only when
        # ASIK has no first reading at all.
        if a_td["sys1"] is not None or a_td["dia1"] is not None:
            p["td_sys1"] = a_td["sys1"]
            p["td_dia1"] = a_td["dia1"]
            p["_td1_src"] = "ASIK"
        # TD2 only exists in ASIK.
        p["td_sys2"] = a_td["sys2"]
        p["td_dia2"] = a_td["dia2"]
        # Jenis Obat: ASIK tatalaksana prescription wins; EPUS Resep fallback.
        asik_obat = _extract_asik_obat(asik)
        if asik_obat:
            p["obat"] = asik_obat
            p["_obat_src"] = "ASIK"
        # Riwayat HT: ASIK self-report answer OR a recorded ASIK tatalaksana HT
        # diagnosis; EPUS diagnosis stays the fallback (sticky Ya).
        p["_riwayat_ckg"] = a_td["riwayat_ya"] or _asik_tatalaksana_ht_diagnosis(asik)

    # Rerata + baseline interpretasi + final riwayat, then the syarat filter:
    # keep iff Riwayat diagnosis HT positif OR the rerata is elevated
    # (interpretasi "Hipertensi" ≥140/90 or "Pre-Hipertensi" 130–139/85–89).
    # Only a Normal rerata (≤129/≤84) with no diagnosis record stays out.
    qualified: list[dict] = []
    for p in patients:
        riwayat_epus = p.pop("_riwayat_epus")
        riwayat_ckg = p.pop("_riwayat_ckg")
        riwayat = riwayat_ckg or riwayat_epus  # ASIK wins; EPUS fallback
        p["riwayat_ht"] = "Ya" if riwayat else "Tidak"
        p["rerata_sys"] = _rerata(p["td_sys1"], p["td_sys2"])
        p["rerata_dia"] = _rerata(p["td_dia1"], p["td_dia2"])
        has_td2 = p["td_sys2"] is not None or p["td_dia2"] is not None
        p["interpretasi"] = _interpretasi_baseline(
            p["rerata_sys"], p["rerata_dia"], riwayat_ya=(p["riwayat_ht"] == "Ya")
        )
        # Per-field provenance (ASIK / ePuskesmas) for the dashboard. TD2 is
        # ASIK-only; Follow Up is always EPUS (not surfaced per-row). Pop the
        # temp markers unconditionally so they never leak into the payload.
        td1_src = p.pop("_td1_src")
        obat_src = p.pop("_obat_src")
        p["sources"] = {
            "td1": td1_src,
            "td2": "ASIK" if has_td2 else None,
            "riwayat_ht": "ASIK" if riwayat_ckg else ("EPUS" if riwayat_epus else None),
            "obat": obat_src if p["obat"] else None,
        }
        if p["riwayat_ht"] == "Ya" or p["interpretasi"] in (
            _INTERP_HIPERTENSI,
            _INTERP_PRE_HIPERTENSI,
        ):
            qualified.append(p)

    qualified.sort(key=lambda x: ((x["nama"] or "").casefold(), x["nik"]))
    return {"patients": qualified, "computed_at": datetime.now(UTC).isoformat()}


def scan_hipertensi_registry(
    db: Session, puskesmas_id: uuid.UUID, year: int, *, progress=None
) -> dict:
    """Build the cacheable registry payload for (puskesmas, year):
    ``{patients: [...], computed_at}``. ``patients`` is pre-sorted by (nama, nik);
    search and pagination are applied on top of it at request time.

    Two queries (EPUS blobs, then a batched ASIK pass over the baselines). The
    per-NIK decode + build + finalize are shared with the cross-year warm bundle
    (``hipertensi_charts_scan.scan_hipertensi_bundle``) so a nightly warm of both
    years + the charts decrypts each blob once.

    ``progress`` (optional): a ``make_progress_writer`` callback ticked once per
    NIK so the on-miss warm can surface a progress bar. ``None`` (nightly/bundle
    path) → zero overhead."""
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
