"""Per-bayi newborn **registry** scan — PJBK + Ikterus + Ikterus Berat.

Builds the per-bayi registry the three "Register Sheet Pasien PJB, Ikterus"
sheets expect (PJBK / Bayi Kuning_Ikterus / Bayi Kuning_Ikterus Berat). Unlike
the hipertensi registry this is **EPUS-only** — measured on prod 2026-08-24, of
331 "BAYI %" records 330 were ``epus_only`` and 1 ``asik_only`` (0 matched), so
the client's "match ASIK∩EPUS" rule yields ~0; the newborn registries drop the
ASIK-match requirement (like the dashboard scans).

**Bayi vs. parent identity.** In one Persalinan visit EPUS carries TWO separate
``pelayanan`` records: the parent (``umur_tahun=30``) and the bayi
(``umur_tahun=0``, nama "BAYI NYONYA <ibu>"). The bayi carries the **parent's
NIK** (no KTP). So we **never** trust NIK to separate bayi from parent — we
filter to the bayi's own record by ``umur==0`` / nama prefix "BAYI " (mirrors
``scrapers/epus/patient_scraper._is_bayi_record``) and read THAT record's own
tabs. Grouping a bayi's repeat visits (baseline + Pemantauan) uses (NIK, nama)
AFTER the bayi filter, so the parent is already excluded; the only residual
collision is same-mother twins/siblings in one year (rare — noted).

**Ikterus classification — two sources, provenance-tagged.** In priority:
  1. EPUS's own ``MtbmDetail[klasifikasi]`` select (Tidak ada ikterus(1) /
     Ikterus(2) / Ikterus berat(3)) — JS-applied, recovered into
     ``tabs[<mtbm>].saved_detail`` by ``_augment_bayi_forms``. Source tag
     ``"EPUS"``.
  2. When that field is absent (every row today — no bayi has a filled
     saved_detail yet), the band is DERIVED from the server-rendered
     "Memeriksa Ikterus" questionnaire in ``fields`` per the MTBM rule:
     not kuning → Tidak ada ikterus; kuning + (onset < 24 jam / > 14 hari, or
     kuning reaching telapak tangan/kaki) → Ikterus berat; kuning otherwise →
     Ikterus. Source tag ``"Hitung"`` (backend-computed). The tag lets the UI
     show which rows are EPUS-native vs derived (mirrors the HT/DM EPUS/ASIK
     provenance pill).
  - **PJB** ← the ``SkriningPjb[...][interpretasi]`` field on the
    "Skrining PJB" tab, plus the pulse-ox saturations (Tangan Kanan %, Kaki %).

**Inclusion (per sheet):**
  - **PJBK**: PJB interpretasi ∈ {Waspada PJB, Terduga PJB}.
  - **Ikterus**: baseline ikterus klasifikasi ∈ {Ikterus, Ikterus berat}.
  - **Ikterus Berat**: baseline ikterus klasifikasi = Ikterus berat.
A bayi is emitted iff it qualifies for ≥1 sheet; the report layer filters per
sheet on the ``qualifies_*`` flags. **NOT CKG-filtered** (unlike HT/DM): measured
on prod 2026-08, of 958 Tebet bayi NIKs the CKG-flagged (``epus_tandai_ckg``) and
the ikterus-positive sets are DISJOINT (0 overlap) — the MTBM ikterus screening is
recorded on visits EPUS does not mark CKG, so a CKG filter empties the registry.
Inclusion is clinical (a recorded ikterus/PJB result), not CKG-program membership.

**Rujuk Eksternal** ← the show page's "Data Rujukan External" table (top-level
``rujukan.external``, already captured by the scraper, scoped to THIS visit):
the destination facility name(s) (e.g. "RSUD POSO"), de-duplicated and joined
with "; ". "" when the visit made no external referral. Always EPUS-native.

⚠ **Deferred verification.** The ikterus *questionnaire derivation* is verified
against real prod data (2026-08: 36 jaundiced bayi, severity fields filled
30–35/36). Still UNVERIFIED against a FILLED bayi, because none exist yet:
(a) the ``saved_detail`` ikterus path — MTBM saved_detail may carry a per-section
klasifikasi, so confirm we read the ikterus section's code when a re-scrape first
fills it; (b) ``_extract_pjb`` entirely (no bayi has PJB pulse-ox data). Both
degrade to ``None``/"" on any shape mismatch (never raise, never fabricate) and
are verified at re-scrape time (agreed deferral).
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
from app.models.patient import Patient

# ── labels (verbatim from the registry sheets / EPUS select options) ────────
_IKTERUS_TIDAK = "Tidak ada ikterus"
_IKTERUS = "Ikterus"
_IKTERUS_BERAT = "Ikterus berat"
# The MtbmDetail[klasifikasi] select codes → labels (1/2/3, per the live form).
_IKTERUS_BY_CODE = {"1": _IKTERUS_TIDAK, "2": _IKTERUS, "3": _IKTERUS_BERAT}
# Baseline klasifikasi values that put a bayi in the Ikterus / Ikterus Berat sheets.
_IKTERUS_POSITIVE = {_IKTERUS, _IKTERUS_BERAT}

_PJB_WASPADA = "Waspada PJB"
_PJB_TERDUGA = "Terduga PJB"
# Interpretasi values that qualify a bayi for the PJBK registry (sheet syarat:
# "1. Waspada PJB / 2. Terduga PJB"). Matched loosely (casefold contains) so
# minor EPUS wording drift ("Terduga PJB-K") still resolves.
_PJB_POSITIVE_TOKENS = ("waspada", "terduga")

# Bayi markers — mirror scrapers/epus/patient_scraper._BAYI_NAME_RE/_UMUR_RE.
_BAYI_NAME_RE = re.compile(r"^\s*bayi\b", re.I)
_BAYI_UMUR_RE = re.compile(r"^\s*0\s*(thn|tahun)\b", re.I)


# ── value parsing ──────────────────────────────────────────────────────────
def _num_str(raw: Any) -> str | None:
    """A saturation percentage as a clean string ("98"), or None. Kept as a
    string (not float) so the sheet shows exactly what EPUS recorded."""
    if raw is None:
        return None
    s = str(raw).strip().rstrip("%").strip()
    if s == "":
        return None
    try:
        d = Decimal(s.replace(",", "."))
    except (InvalidOperation, ValueError):
        return s  # non-numeric — surface verbatim rather than dropping
    # Normalise "98.0" → "98" but keep genuine decimals.
    return str(d.to_integral_value()) if d == d.to_integral_value() else str(d)


# ── bayi identity ──────────────────────────────────────────────────────────
def _data_pasien(epus: Any) -> dict[str, Any]:
    if not isinstance(epus, dict):
        return {}
    dp = epus.get("data_pasien")
    return dp if isinstance(dp, dict) else {}


def _is_bayi(epus: Any) -> bool:
    """A newborn record: nama begins with "BAYI " or Umur reads "0 Thn ...".
    NEVER key bayi logic on NIK (bayi carry the parent's NIK)."""
    dp = _data_pasien(epus)
    nama = str(dp.get("Nama Pasien") or dp.get("Nama") or "")
    if _BAYI_NAME_RE.match(nama):
        return True
    return bool(_BAYI_UMUR_RE.match(str(dp.get("Umur") or "")))


def _parse_birthdate(epus: Any) -> str | None:
    """Birthdate ISO string from ``data_pasien`` "Tempat/Tgl Lahir" (or jaksel
    "Tempat & Tgl Lahir"), anchored on the trailing ``DD-MM-YYYY`` (mirrors
    ``hipertensi_registry_scan._parse_birthdate``)."""
    dp = _data_pasien(epus)
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


def _clean_nik(raw: Any) -> str:
    """Bayi NIK may carry HTML junk (e.g. ``</br>``) — keep digits only."""
    return re.sub(r"\D", "", str(raw or ""))


def _extract_identitas(epus: Any) -> dict[str, Any]:
    dp = _data_pasien(epus)
    jk_raw = (dp.get("Jenis Kelamin") or "").strip()
    jk = {"L": "Laki-Laki", "P": "Perempuan"}.get(jk_raw.upper(), jk_raw)
    alamat = dp.get("Alamat")
    return {
        "nama": (dp.get("Nama Pasien") or dp.get("Nama") or "").strip(),
        "jenis_kelamin": jk,
        "tanggal_lahir": _parse_birthdate(epus),
        "no_tlp": (dp.get("No Telp / HP") or dp.get("No. Telp") or dp.get("No. HP") or "").strip(),
        "alamat": re.sub(r"\s+", " ", str(alamat)).strip() if alamat else "",
    }


# ── tab lookup ─────────────────────────────────────────────────────────────
def _find_tab(epus: Any, *, module: str) -> dict[str, Any]:
    """The first tab whose ``module`` matches (tabs are display-name keyed, but
    ``module`` is stable). Returns {} when absent."""
    if not isinstance(epus, dict):
        return {}
    for t in (epus.get("tabs") or {}).values():
        if isinstance(t, dict) and t.get("module") == module:
            return t
    return {}


def _find_key_value(obj: Any, key_token: str):
    """Yield the value of every dict entry whose key contains ``key_token``
    (casefold), anywhere in a nested structure."""
    kt = key_token.casefold()
    if isinstance(obj, dict):
        for k, v in obj.items():
            if kt in str(k).casefold():
                yield v
            yield from _find_key_value(v, key_token)
    elif isinstance(obj, list):
        for v in obj:
            yield from _find_key_value(v, key_token)


# ── ikterus (MTBM) ─────────────────────────────────────────────────────────
# Source tags for the ikterus band (mirrors the HT/DM EPUS/ASIK provenance pill).
_SRC_EPUS = "EPUS"          # EPUS's own klasifikasi field (saved_detail)
_SRC_DERIVED = "Hitung"     # backend-derived from the MTBM questionnaire


def _ikt_field(ikt: dict[str, Any], token: str) -> Any:
    """Value of the first "Memeriksa Ikterus" question whose label contains
    ``token`` (casefold) — robust to minor per-region label drift."""
    for k, v in ikt.items():
        if token in str(k).casefold():
            return v
    return None


def _onset_is_severe(raw: Any) -> bool:
    """MTBM severe onset: kuning timbul < 24 jam (hari pertama) OR > 14 hari.
    The middle option "> 24 jam s/d 14 hari" is NOT severe (starts "> 24")."""
    s = re.sub(r"\s+", " ", str(raw or "")).strip().casefold()
    return s.startswith("< 24") or s.startswith("<24") or s.startswith("> 14") or s.startswith(">14")


def _derive_ikterus_from_questionnaire(mtbm: dict[str, Any]) -> str:
    """Ikterus band derived from the server-rendered "Memeriksa Ikterus"
    questionnaire, per the MTBM classification: not kuning → Tidak ada ikterus;
    kuning + (onset < 24 jam / > 14 hari, or kuning reaching telapak tangan/kaki)
    → Ikterus berat; kuning otherwise → Ikterus. "" when unanswered."""
    ikt = (mtbm.get("fields") or {}).get("Memeriksa Ikterus")
    if not isinstance(ikt, dict):
        return ""
    kuning = str(_ikt_field(ikt, "apakah bayi kuning") or "").strip().casefold()
    if kuning == "tidak":
        return _IKTERUS_TIDAK
    if kuning != "ya":
        return ""  # unanswered → no classification (not counted)
    telapak = str(_ikt_field(ikt, "telapak") or "").strip().casefold()
    if _onset_is_severe(_ikt_field(ikt, "pertama kali timbul")) or telapak == "ya":
        return _IKTERUS_BERAT
    return _IKTERUS


def _extract_ikterus_klasifikasi(epus: Any) -> tuple[str, str]:
    """Ikterus band + its source for one visit.

    Returns ``(label, source)`` where label ∈ {"", Tidak ada ikterus, Ikterus,
    Ikterus berat} and source ∈ {"", "EPUS", "Hitung"}:
      - EPUS's own klasifikasi field in ``saved_detail`` → source "EPUS";
      - else derived from the "Memeriksa Ikterus" questionnaire → source "Hitung".

    ⚠ The saved_detail path is still UNVERIFIED against a filled bayi (none exist
    yet). MTBM saved_detail may carry a per-section klasifikasi; when a re-scrape
    first fills it, confirm we read the IKTERUS section's code, not another
    section's — see the module docstring's deferred-verification note."""
    mtbm = _find_tab(epus, module="mtbm")
    if not mtbm:
        return "", ""

    sd = mtbm.get("saved_detail")
    if sd is not None:
        for v in _find_key_value(sd, "klasifikasi"):
            label = _ikterus_label_from(v)
            if label:
                return label, _SRC_EPUS

    label = _derive_ikterus_from_questionnaire(mtbm)
    return (label, _SRC_DERIVED) if label else ("", "")


def _ikterus_label_from(v: Any) -> str:
    """Coerce a raw klasifikasi cell to a canonical ikterus label, or "".
    Accepts a code ("1"/"2"/"3"), a nested {index: code} dict (the bracketed
    ``[klasifikasi][2]`` form), or a label string containing "ikterus"."""
    if isinstance(v, dict):
        for inner in v.values():
            label = _ikterus_label_from(inner)
            if label:
                return label
        return ""
    if isinstance(v, list):
        for inner in v:
            label = _ikterus_label_from(inner)
            if label:
                return label
        return ""
    s = str(v).strip()
    if s in _IKTERUS_BY_CODE:
        return _IKTERUS_BY_CODE[s]
    sl = s.casefold()
    if "ikterus" not in sl:
        return ""
    if "berat" in sl:
        return _IKTERUS_BERAT
    if "tidak" in sl or "tdk" in sl:
        return _IKTERUS_TIDAK
    return _IKTERUS


# ── PJB pulse-ox (Skrining PJB) ────────────────────────────────────────────
def _pjb_rows(pjb_tab: dict[str, Any]) -> list[dict[str, Any]]:
    """The pemeriksaan rows. JS-applied readings land in ``saved_detail``;
    server-rendered ones land in ``tables`` (empty rows are dropped by the
    scraper). Return a list of dicts, preferring ``saved_detail``.

    ⚠ UNVERIFIED shape — a filled bayi decides which branch carries data."""
    sd = pjb_tab.get("saved_detail")
    for v in _find_key_value(sd, "pemeriksaan"):
        if isinstance(v, list) and v:
            return [r for r in v if isinstance(r, dict)]
    if isinstance(sd, list) and sd and all(isinstance(r, dict) for r in sd):
        return sd

    tables = pjb_tab.get("tables")
    if isinstance(tables, dict):
        for rows in tables.values():
            if isinstance(rows, list) and rows:
                return [r for r in rows if isinstance(r, dict)]
    return []


def _row_get(row: dict[str, Any], *tokens: str) -> Any:
    """First value whose key contains any token (casefold). Handles both the
    bracket field names (``saturasi_tangan``) and the table header labels
    (``Saturasi Tangan``)."""
    for k, v in row.items():
        kl = str(k).casefold()
        if any(t in kl for t in tokens):
            return v
    return None


def _extract_pjb(epus: Any) -> dict[str, Any] | None:
    """PJB pulse-ox for one visit → {saturasi_tangan_kanan, saturasi_kaki,
    interpretasi, diagnosis, rujuk_eksternal} or None when the bayi has no PJB
    tab/data. The sheet wants "Tangan Kanan (%)" + "Kaki (%)"."""
    pjb_tab = epus.get("tabs", {}).get("Skrining PJB") if isinstance(epus, dict) else None
    if not isinstance(pjb_tab, dict):
        pjb_tab = _find_tab(epus, module="skriningpjb")
    if not pjb_tab:
        return None

    rows = _pjb_rows(pjb_tab)
    sat_tangan_kanan: str | None = None
    sat_kaki: str | None = None
    interpretasi = ""
    for row in rows:
        tangan = str(_row_get(row, "tangan") or "")
        sat_t = _num_str(_row_get(row, "saturasi_tangan", "saturasi tangan"))
        sat_k = _num_str(_row_get(row, "saturasi_kaki", "saturasi kaki"))
        interp = str(_row_get(row, "interpretasi") or "").strip()
        # "Tangan Kanan" wins for the Tangan Kanan (%) column; else first tangan.
        if sat_t is not None and (sat_tangan_kanan is None or "kanan" in tangan.casefold()):
            sat_tangan_kanan = sat_t
        if sat_k is not None and sat_kaki is None:
            sat_kaki = sat_k
        if interp and not interpretasi:
            interpretasi = interp

    if sat_tangan_kanan is None and sat_kaki is None and not interpretasi:
        return None
    return {
        "saturasi_tangan_kanan": sat_tangan_kanan,
        "saturasi_kaki": sat_kaki,
        "interpretasi": interpretasi,
        "diagnosis": _extract_diagnosis(epus),
        "rujuk_eksternal": _extract_rujuk_eksternal(epus),
    }


def _pjb_qualifies(pjb: dict[str, Any] | None) -> bool:
    if not pjb:
        return False
    interp = str(pjb.get("interpretasi") or "").casefold()
    return any(tok in interp for tok in _PJB_POSITIVE_TOKENS)


# ── diagnosis (shared) ─────────────────────────────────────────────────────
def _extract_diagnosis(epus: Any) -> str:
    """Best-effort diagnosis text: the Diagnosa tab's diagnosa rows, else the
    ``penyakit_khusus`` panel. De-duplicated, joined with "; ". "" when absent."""
    names: list[str] = []
    seen: set[str] = set()

    diag_tab = _find_tab(epus, module="diagnosa")
    tables = diag_tab.get("tables") if isinstance(diag_tab, dict) else None
    if isinstance(tables, dict):
        for rows in tables.values():
            if not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, dict):
                    continue
                name = str(_row_get(row, "diagnosa", "penyakit", "icd") or "").strip()
                if name and name not in seen:
                    seen.add(name)
                    names.append(name)

    if isinstance(epus, dict):
        for item in epus.get("penyakit_khusus") or []:
            if not isinstance(item, dict):
                continue
            name = str(item.get("Penyakit") or "").strip()
            if name and name not in seen:
                seen.add(name)
                names.append(name)
    return "; ".join(names)


# ── rujuk eksternal (show-page referral table) ─────────────────────────────
def _extract_rujuk_eksternal(epus: Any) -> str:
    """External referral destination(s) for THIS visit, from the show page's
    "Data Rujukan External" table (top-level ``rujukan.external``). Joins the
    destination facility names ("Rujukan External" column), de-duped; "" when the
    visit made no external referral."""
    if not isinstance(epus, dict):
        return ""
    dests: list[str] = []
    seen: set[str] = set()
    for row in (epus.get("rujukan") or {}).get("external") or []:
        if not isinstance(row, dict):
            continue
        dest = str(_row_get(row, "external", "eksternal") or "").strip()
        if dest and dest not in seen:
            seen.add(dest)
            dests.append(dest)
    return "; ".join(dests)


# ── per-bayi visit decode ──────────────────────────────────────────────────
class _Visit:
    __slots__ = ("fd", "group", "epus", "ikterus", "ikterus_src", "pjb", "diagnosis")

    def __init__(self, *, fd, group, epus):
        self.fd = fd
        self.group = group
        self.epus = epus
        self.ikterus, self.ikterus_src = _extract_ikterus_klasifikasi(epus)
        self.pjb = _extract_pjb(epus)
        self.diagnosis = _extract_diagnosis(epus)


def _blob_query(puskesmas_id: uuid.UUID, start: date, end: date):
    """EPUS-blob query for one puskesmas over ``[start, end)``, ordered so a
    NIK's visits stream contiguously oldest-first (created_at breaks same-date
    ties → freshest re-scrape wins). Mirrors ``hipertensi_registry_scan``."""
    return (
        select(
            Patient.id,
            Patient.nik,
            Patient.nama,
            Patient.filter_date,
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
    """Distinct-NIK count over the same window — the progress-bar denominator."""
    return select(func.count(func.distinct(Patient.nik))).where(
        Patient.puskesmas_id == puskesmas_id,
        Patient.filter_date >= start,
        Patient.filter_date < end,
        Patient.scraped_epus_data.isnot(None),
    )


def _decode_bayi_visits(group) -> list[_Visit]:
    """Decode one NIK's rows, keeping only BAYI records (parent excluded), each
    EPUS blob decrypted exactly once. Cross-date/same-date scrape twins collapse
    on ``match_group_id`` (earliest date wins)."""
    seen_groups: set[uuid.UUID] = set()
    visits: list[_Visit] = []
    for r in group:  # ascending by (filter_date, created_at)
        try:
            epus = decrypt_json(r.scraped_epus_data)
        except Exception:
            epus = None
        if not _is_bayi(epus):
            continue
        if r.match_group_id is not None:
            if r.match_group_id in seen_groups:
                continue
            seen_groups.add(r.match_group_id)
        visits.append(_Visit(fd=r.filter_date, group=r.match_group_id, epus=epus))
    return visits


def _build_bayi(nik: str, visits: list[_Visit]) -> dict | None:
    """One registry bayi from its in-year bayi ``visits`` (date-ascending), or
    None when it qualifies for no sheet. Baseline = earliest visit; the PJB
    reading is taken from the first visit that has one (birth screening)."""
    if not visits:
        return None
    baseline = visits[0]
    ident = _extract_identitas(baseline.epus)

    pjb = next((v.pjb for v in visits if v.pjb), None)

    # Ikterus: baseline classification + up to the follow-up ("Pemantauan")
    # visits, each with its own klasifikasi/diagnosis. Only visits that recorded
    # an ikterus classification are surfaced as pemantauan rows.
    baseline_ikterus = baseline.ikterus
    pemantauan = [
        {
            "tanggal": v.fd.isoformat(),
            "klasifikasi": v.ikterus,
            "diagnosis": v.diagnosis,
            "rujuk_eksternal": _extract_rujuk_eksternal(v.epus),
            "sources": {
                "klasifikasi": v.ikterus_src or None,
                "diagnosis": _SRC_EPUS if v.diagnosis else None,
            },
        }
        for v in visits[1:]
        if v.ikterus
    ]
    ikterus = None
    if baseline_ikterus or pemantauan:
        ikterus = {
            "baseline": {
                "klasifikasi": baseline_ikterus,
                "diagnosis": baseline.diagnosis,
                "rujuk_eksternal": _extract_rujuk_eksternal(baseline.epus),
                "sources": {
                    "klasifikasi": baseline.ikterus_src or None,
                    "diagnosis": _SRC_EPUS if baseline.diagnosis else None,
                },
            },
            "pemantauan": pemantauan,
        }

    qualifies_pjbk = _pjb_qualifies(pjb)
    qualifies_ikterus = baseline_ikterus in _IKTERUS_POSITIVE
    qualifies_ikterus_berat = baseline_ikterus == _IKTERUS_BERAT
    if not (qualifies_pjbk or qualifies_ikterus or qualifies_ikterus_berat):
        return None

    return {
        "nik": _clean_nik(nik),
        "nama": ident.get("nama") or "",
        "jenis_kelamin": ident.get("jenis_kelamin", ""),
        "tanggal_lahir": ident.get("tanggal_lahir"),
        "no_tlp": ident.get("no_tlp", ""),
        "alamat": ident.get("alamat", ""),
        "tanggal_berkunjung": baseline.fd.isoformat(),
        "pjb": pjb,
        "ikterus": ikterus,
        "qualifies_pjbk": qualifies_pjbk,
        "qualifies_ikterus": qualifies_ikterus,
        "qualifies_ikterus_berat": qualifies_ikterus_berat,
    }


def count_sheet_bands(bayi: list[dict]) -> tuple[int, int, int]:
    """(pjbk, ikterus, ikterus_berat) counts over registry bayi — how many rows
    each sheet shows. Reads the already-computed ``qualifies_*`` flags (no
    rescan)."""
    pjbk = sum(1 for b in bayi if b.get("qualifies_pjbk"))
    ikt = sum(1 for b in bayi if b.get("qualifies_ikterus"))
    berat = sum(1 for b in bayi if b.get("qualifies_ikterus_berat"))
    return pjbk, ikt, berat


def scan_bayi_registry(
    db: Session, puskesmas_id: uuid.UUID, year: int, *, progress=None
) -> dict:
    """Build the cacheable newborn-registry payload for (puskesmas, year):
    ``{bayi: [...], computed_at}``, pre-sorted by (nama, nik). The report layer
    filters per sheet on the ``qualifies_*`` flags; search/pagination apply on
    top at request time. One EPUS-blob query, each blob decrypted once."""
    year_start = date(year, 1, 1)
    year_end = date(year + 1, 1, 1)

    total = 0
    if progress:
        total = db.scalar(_blob_nik_count_query(puskesmas_id, year_start, year_end)) or 0
    done = 0

    bayi: list[dict] = []
    for nik, group in itertools.groupby(
        db.execute(_blob_query(puskesmas_id, year_start, year_end)),
        key=lambda r: r.nik,
    ):
        visits = _decode_bayi_visits(group)
        b = _build_bayi(nik, visits)
        if b is not None:
            bayi.append(b)
        if progress:
            done += 1
            progress(done, total)

    bayi.sort(key=lambda x: ((x["nama"] or "").casefold(), x["nik"]))
    return {"bayi": bayi, "computed_at": datetime.now(UTC).isoformat()}
