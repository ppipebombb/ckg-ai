"""Per-NIK Dislipidemia **registry** scan (dirjen "Register Sheet" layout).

Third sibling of :mod:`app.services.hipertensi_registry_scan` and
:mod:`app.services.dm_registry_scan` — same two-query shape, same ASIK-first
sourcing, same follow-up grid — with the blood-pressure / glucose block swapped
for the lipid panel the "Dislipidemia" sheet expects:

  - **Identitas** (NIK, Nama, Jenis Kelamin, Tanggal Lahir, No.Tlp, Alamat):
    ASIK ``detail_data``, EPUS ``data_pasien`` fallback.
  - **Baseline "Hasil pemeriksaan Lipid"**: ``Tanggal Berkunjung`` (the earliest
    MATCHED/CKG visit), ``Riwayat diagnosis HT``, ``Riwayat diagnosis DM``,
    ``Kolesterol Total``, ``LDL``, ``HDL``, ``Trigliserida``, ``Interpretasi``,
    and ``Jenis Obat``.
  - **Follow Up**: per month from the month AFTER the CKG visit, every EPUS visit
    carrying a lipid reading, each evaluated against the N17 target.

Inclusion (sheet B1 "Syarat Registri Dislipidemia"): a NIK appears iff it has ≥1
MATCHED visit in the year AND its baseline lipid panel breaches a threshold —
Kol-total ≥200, HDL <40, LDL ≥130, or Trigliserida >150 mg/dL.

**Three deliberate divergences from the DM sibling. All three come from the
sheet; none of them is an oversight to "fix" back into DM parity:**

1. **Syarat is measurement-only.** The N17 legend says "semua pasien dengan
   riwayat DM dan/atau HT yang sudah ditegakkan diagnosis Dislipidemia melalui
   pengukuran…", but B1 — the sheet's own ``Syarat Registri`` statement — lists
   only the four lab thresholds. B1 wins: ``Riwayat diagnosis HT`` and ``Riwayat
   diagnosis DM`` are columns H and I of the register, i.e. things it *reports*,
   not things it filters on. Gating on them would silently drop a patient with
   LDL 190 and no recorded HT/DM. In practice the distinction is near-moot —
   ASIK's lipid form is ``POCT Lipid Panel (Khusus usia >=40 thn dan penyandang
   HT dan/atau DM)``, so almost every row that HAS lipid data already carries one
   of the two diagnoses.
2. **A recorded diagnosis does NOT force the baseline label.** Both siblings
   pin "Riwayat = Ya" to the disease label regardless of that day's readings.
   Here it must not: per (1) the register admits on measurement alone, so
   riwayat has nothing to pin. A patient with Riwayat HT = Ya and a clean lipid
   panel is "Normal" — and is excluded by the syarat.
3. **Control is QUARTERLY.** N17 evaluates the target "pada kunjungan 3 bulan
   berikutnya" and defines Missed Visit as no visit "pada waktu kontrol". So a
   ``Pasien Missed Visit`` filler is stamped only on control months (baseline
   month +3/+6/+9/+12) — see :func:`_control_months`. Every visit carrying a
   lipid reading is still listed in its own month, control month or not. Marking
   every empty month (the DM rule) would tell a puskesmas their patient missed a
   visit that was never due.

Cost: EPUS decrypted once per row; ASIK decrypted only for each candidate NIK's
baseline visit, in a single batched second query — never per-row.

The generic helpers (value parsing, identitas, the two blob queries, the batched
ASIK fetch) are IMPORTED from :mod:`app.services.dm_registry_scan` rather than
copied. They are already byte-identical between the hipertensi and DM scans; a
third copy is the duplication CLAUDE.md §11.2 calls a defect, and it would drift.
Only the lipid-specific logic lives here.
"""

from __future__ import annotations

import itertools
import re
import uuid
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.core.security import decrypt_json
from app.models.patient import MatchStatus
from app.services.dm_registry_scan import (
    _blob_nik_count_query,
    _blob_query,
    _extract_asik_glucose,
    _extract_asik_identitas,
    _extract_identitas,
    _fetch_asik_by_id,
    _num,
)
from app.services.dm_registry_scan import (
    _asik_tatalaksana_dm_diagnosis as _asik_dm_diagnosis,
)
from app.services.dm_registry_scan import (
    _riwayat_epus_hit as _riwayat_dm_epus_hit,
)
from app.services.hipertensi_registry_scan import (
    _asik_tatalaksana_ht_diagnosis as _asik_ht_diagnosis,
)
from app.services.hipertensi_registry_scan import (
    _extract_asik_td,
)
from app.services.hipertensi_registry_scan import (
    _riwayat_epus_hit as _riwayat_ht_epus_hit,
)

# ── syarat thresholds (sheet B1) ───────────────────────────────────────────
# Note the comparators: three are inclusive, Trigliserida alone is STRICT. The
# sheet reads "Kol-total ≥200 mg/dl; atau HDL <40 mg/dl; atau LDL ≥130 mg/dl;
# atau Trigliserida >150 mg/dl". The N17 target side is the exact complement
# (Kol <200, HDL ≥40, LDL <130, TG ≤150), so the two sides leave no gap — a
# reading of exactly 150 mg/dL TG is normal, 151 is not. Do not "tidy" this into
# four ≥/< comparisons.
_KOL_TOTAL_MIN_TINGGI = 200.0  # ≥ is abnormal
_HDL_MIN_NORMAL = 40.0  # < is abnormal
_LDL_MIN_TINGGI = 130.0  # ≥ is abnormal
_TRIGLISERIDA_MAX_NORMAL = 150.0  # > is abnormal (strict)

_ANALYTES = ("kol_total", "ldl", "hdl", "trigliserida")

# Lipid-lowering drug filter for the Jenis Obat columns (the sheet marks them
# "List Obat Dislipidemia"). Families per Formularium Nasional for FKTP /
# Puskesmas, with Indonesian + INN spellings: statin, fibrat, penghambat
# absorpsi kolesterol, and bile-acid sequestrant.
_LIPID_DRUG_RE = re.compile(
    r"simvastatin|atorvastatin|rosuvastatin|pravastatin|lovastatin|fluvastatin"
    r"|gemfibrozil"
    r"|fenofibrat|fenofibrate"
    r"|ezetimib"
    r"|kolestiramin|cholestyramin|colestyramin",
    re.IGNORECASE,
)

# Follow-up "Interpretasi hasil" labels — from the sheet legend (N17: "Pasien
# terdiagnosis Dislipidemia ... dievaluasi dengan kategori").
_FU_TERKENDALI = "Pasien Dislipidemia terkendali (target tercapai)"
_FU_TIDAK_TERKENDALI = "Pasien Dislipidemia tidak terkendali (target tidak tercapai)"
_FU_MISSED_VISIT = "Pasien Missed Visit"

# NOTE: the legend also defines "Pasien Loss to Follow Up (LTFU)" = no clinical
# visit for 12 CONSECUTIVE months. A single-year scan cannot reach that state —
# a baseline in January leaves at most 11 follow-up months — so LTFU is
# deliberately NOT emitted here, exactly as in the DM registry. It needs
# cross-year visit history.

# Baseline interpretasi labels. There is no middle band: the sheet defines one
# threshold per analyte, not a borderline range, so nothing here corresponds to
# hipertensi's "Pre-Hipertensi" or DM's "Prediabetes". Do not invent one.
_INTERP_DISLIPIDEMIA = "Dislipidemia"
_INTERP_NORMAL = "Normal"

# The CKG riwayat question that shares the word "kolesterol" with the value
# labels — see the guard in :func:`_lipid_fields_from_form`.
_ASIK_RIWAYAT_KEY = "pemeriksaan kolesterol"

# EPUS lab table that carries lipid results (same table the DM scan reads for
# Glukosa Puasa / HbA1c).
_LAB_TABLE_NAME = "Ubah Data Laboratorium"


def _empty_lipid() -> dict[str, Any]:
    return {"kol_total": None, "ldl": None, "hdl": None, "trigliserida": None}


def _has_lipid(g: dict[str, Any]) -> bool:
    return any(g.get(k) is not None for k in _ANALYTES)


# ── EPUS extraction ────────────────────────────────────────────────────────
def _lab_slot(name: str) -> str | None:
    """Laboratorium row name → lipid slot, or None.

    HDL/LDL are tested BEFORE the total-cholesterol test on purpose: lab rows are
    routinely named "Kolesterol HDL" / "Kolesterol LDL", and those are HDL and
    LDL — not Kolesterol Total. Reversing the order silently files every HDL
    result as total cholesterol.
    """
    if "hdl" in name:
        return "hdl"
    if "ldl" in name:
        return "ldl"
    if "trigliserida" in name or "triglyceride" in name:
        return "trigliserida"
    if "kolesterol" in name or "cholesterol" in name:
        return "kol_total"
    return None


def _extract_lipid_epus(epus: Any) -> dict[str, Any]:
    """Lipid readings from one EPUS visit.

    Source of truth is ``PTM → Profil Lipid`` (the same fields
    ``epus_to_asik._map_*`` feeds into the POCT Lipid Panel form); the
    ``Laboratorium`` table fills its gaps.
    """
    out = _empty_lipid()
    if not isinstance(epus, dict):
        return out
    tabs = epus.get("tabs") or {}
    lipid = ((tabs.get("PTM") or {}).get("fields", {}) or {}).get("Profil Lipid")
    if isinstance(lipid, dict):
        out["kol_total"] = _num(lipid.get("Cholesterol Total"))
        out["hdl"] = _num(lipid.get("HDL"))
        out["ldl"] = _num(lipid.get("LDL"))
        out["trigliserida"] = _num(lipid.get("Trigliserida"))

    rows = ((tabs.get("Laboratorium") or {}).get("tables", {}) or {}).get(
        _LAB_TABLE_NAME
    )
    if isinstance(rows, list):
        # Collect first, apply after: within the array the LAST matching row wins
        # (per-array latest — a re-test on the same visit supersedes the earlier
        # result). This is the rule commit 5592dc9 had to restore in the DM scan:
        # applying the PTM gap-fill inside the loop freezes the FIRST lab row and
        # makes this report disagree with its siblings about the same value.
        lab = _empty_lipid()
        for row in rows:
            if not isinstance(row, dict):
                continue
            val = _num(row.get("Hasil"))
            if val is None:
                continue
            slot = _lab_slot(str(row.get("Pemeriksaan") or "").casefold())
            if slot:
                lab[slot] = val
        # PTM stays the source of truth; the lab table only fills its gaps.
        for slot in _ANALYTES:
            if out[slot] is None:
                out[slot] = lab[slot]
    return out


def _extract_obat(epus: Any) -> list[str]:
    """Lipid-lowering ``Nama Obat`` entries in the visit's Resep table
    (``tabs.Resep.tables.Resep[]``), in order, de-duplicated. Other drugs are
    dropped (the sheet's Jenis Obat columns are "List Obat Dislipidemia")."""
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
        if name and name not in seen and _LIPID_DRUG_RE.search(name):
            seen.add(name)
            out.append(name)
    return out


# ── ASIK extraction (POCT Lipid Panel) ─────────────────────────────────────
def _lipid_fields_from_form(fd_items, out: dict[str, Any]) -> None:
    """Fill ``out`` (kol_total/ldl/hdl/trigliserida) from (key, value) pairs of a
    POCT Lipid Panel form. Labels are matched loosely so minor wording drift
    still resolves; existing values are kept (first source wins).

    Live labels (``app/data/asik_form_mapping.json``, form "POCT Lipid Panel
    (Khusus usia >=40 thn dan penyandang HT dan/atau DM)"): "Kolesterol Total",
    "Masukkan nilai HDL", "HDL", "LDL", "Trigliserida", "Interpretasi
    Dislipidemia".

    Three guards, all load-bearing:

      - **The riwayat question is skipped first.** The CKG anamnesis asks
        "Apakah Anda pernah didiagnosa atau mendapatkan hasil pemeriksaan
        kolesterol (lemak darah) tinggi?" — which contains "kolesterol". Without
        this test running before the value tests, the question TEXT is parsed as
        a Kolesterol Total reading.
      - **"Interpretasi Dislipidemia" is skipped.** It is ASIK's own verdict
        string, not a number, and this registry computes its own interpretasi
        from the four values so the label always matches the thresholds the
        export's live formulas apply.
      - **HDL/LDL before kolesterol**, for the reason given in :func:`_lab_slot`.
    """
    for k, v in fd_items:
        kl = str(k).casefold()
        if _ASIK_RIWAYAT_KEY in kl or "apakah" in kl or "interpretasi" in kl:
            continue
        if "hdl" in kl:
            slot = "hdl"
        elif "ldl" in kl:
            slot = "ldl"
        elif "trigliserida" in kl:
            slot = "trigliserida"
        elif "kolesterol" in kl or "cholesterol" in kl:
            slot = "kol_total"
        else:
            continue
        if out.get(slot) is None:
            out[slot] = _num(v)


def _extract_asik_lipid(asik: Any) -> dict[str, Any]:
    """Lipid readings from the raw ASIK blob. Walks every ``pelayanan_nakes`` /
    ``pemeriksaan_mandiri`` entry whose ``layanan`` mentions lipid or kolesterol
    (live: "Skrining Laboratorium =>40 thn <Laki-laki|Perempuan> … Profil
    Lipid"); the first non-null value per slot wins."""
    out = _empty_lipid()
    if not isinstance(asik, dict):
        return out
    for arr_key in ("pelayanan_nakes", "pemeriksaan_mandiri"):
        for entry in asik.get(arr_key) or []:
            if not isinstance(entry, dict):
                continue
            layanan = str(entry.get("layanan") or "").casefold()
            if "lipid" not in layanan and "kolesterol" not in layanan:
                continue
            fd = entry.get("form_data")
            if isinstance(fd, dict):
                _lipid_fields_from_form(fd.items(), out)
    return out


def _asik_lipid_tatalaksana_forms(asik: Any):
    """Yield the ``form_data`` of each RECORDED lipid tatalaksana row.
    ``belum_dilakukan`` rows carry no form and are skipped."""
    if not isinstance(asik, dict):
        return
    tata = asik.get("tatalaksana")
    if not isinstance(tata, dict):
        return
    for row in tata.get("rows") or []:
        if not isinstance(row, dict):
            continue
        kel = str(row.get("kelompok_skrinning") or "").casefold()
        if not any(t in kel for t in ("lipid", "kolesterol", "dislipidemia")):
            continue
        fd = row.get("form_data")
        if isinstance(fd, dict) and fd:
            yield fd


def _extract_asik_obat(asik: Any) -> list[str]:
    """Lipid-lowering drugs prescribed in the recorded ASIK lipid tatalaksana
    form (Peresepan "Pilih obat" / "Pilih obat (n)"), filtered and de-duplicated
    — the ASIK source-of-truth for Jenis Obat."""
    out: list[str] = []
    seen: set[str] = set()
    for fd in _asik_lipid_tatalaksana_forms(asik):
        for k, v in fd.items():
            if not str(k).casefold().startswith("pilih obat"):
                continue
            name = str(v or "").strip()
            if name and name not in seen and _LIPID_DRUG_RE.search(name):
                seen.add(name)
                out.append(name)
    return out


# ── classification ─────────────────────────────────────────────────────────
def _abnormal_analytes(g: dict[str, Any]) -> list[str]:
    """Which of the four analytes breach the sheet's syarat, in sheet order.
    Empty list = nothing abnormal (which is NOT the same as nothing measured —
    check :func:`_has_lipid` for that)."""
    out: list[str] = []
    kol, ldl = g.get("kol_total"), g.get("ldl")
    hdl, trig = g.get("hdl"), g.get("trigliserida")
    if kol is not None and kol >= _KOL_TOTAL_MIN_TINGGI:
        out.append("kol_total")
    if ldl is not None and ldl >= _LDL_MIN_TINGGI:
        out.append("ldl")
    if hdl is not None and hdl < _HDL_MIN_NORMAL:
        out.append("hdl")
    if trig is not None and trig > _TRIGLISERIDA_MAX_NORMAL:
        out.append("trigliserida")
    return out


def _interpretasi_baseline(g: dict[str, Any]) -> str:
    """Interpretasi on the visit date: "Dislipidemia" if ANY analyte breaches its
    threshold, "Normal" if the panel was measured and none did, "" if nothing was
    measured at all.

    Unlike the hipertensi and DM registries, a recorded diagnosis does NOT force
    the label — see divergence (2) in the module docstring.
    """
    if _abnormal_analytes(g):
        return _INTERP_DISLIPIDEMIA
    return _INTERP_NORMAL if _has_lipid(g) else ""


def _interpretasi_followup(g: dict[str, Any]) -> str:
    """Follow-up evaluation (sheet N17 legend).

    target tercapai       — Kol-total <200, HDL ≥40, LDL <130, and TG ≤150
    target tidak tercapai — any of Kol-total ≥200, HDL <40, LDL ≥130, TG >150

    The legend words BOTH sides as an OR of four, which overlaps: a visit with
    Kol-total 180 (passing) and LDL 150 (failing) satisfies both sentences as
    written. Resolved the same way both siblings resolve their own overlap —
    **any failing analyte wins** — which also keeps the follow-up consistent with
    the baseline syarat, where any single breach is already Dislipidemia.

    A visit with no lipid value at all is not interpretable → "" (blank), never
    "tidak tercapai".
    """
    if not _has_lipid(g):
        return ""
    return _FU_TIDAK_TERKENDALI if _abnormal_analytes(g) else _FU_TERKENDALI


def count_analyte_bands(patients: list[dict]) -> dict[str, int]:
    """Per-analyte abnormal counts over registry patients, read off each
    patient's already-extracted baseline values (no rescan). Shared by the
    registry list and summary endpoints.

    These deliberately **overlap and do NOT sum to the registry total** — the
    syarat is an OR of four independent thresholds, so one patient routinely
    breaches several at once. That is why Dislipidemia gets per-analyte counts
    instead of the two exclusive bands the hipertensi ("Hipertensi" /
    "Pre-Hipertensi") and DM ("Diabetes Melitus" / "Prediabetes") registries
    report: this sheet defines no middle band to split on.
    """
    out = {
        "kol_total_tinggi": 0,
        "ldl_tinggi": 0,
        "hdl_rendah": 0,
        "trigliserida_tinggi": 0,
    }
    field = {
        "kol_total": "kol_total_tinggi",
        "ldl": "ldl_tinggi",
        "hdl": "hdl_rendah",
        "trigliserida": "trigliserida_tinggi",
    }
    for p in patients:
        for a in _abnormal_analytes(p):
            out[field[a]] += 1
    return out


def _control_months(baseline_month: int, year: int, today: date) -> list[int]:
    """Months (1..12) in which a follow-up control was DUE, per N17's "kunjungan
    3 bulan berikutnya": baseline month +3, +6, +9, +12.

    Capped at the current month for the current year (a control that has not come
    due yet is not a missed one) and at December otherwise. Only these months get
    a ``Pasien Missed Visit`` filler when empty — every other empty month stays
    blank, because nothing was expected in it.
    """
    last = 12 if year < today.year else (today.month if year == today.year else 0)
    return [m for m in range(baseline_month + 3, 13, 3) if m <= last]


# ── per-visit decode (EPUS) ────────────────────────────────────────────────
class _Visit:
    __slots__ = (
        "id", "fd", "matched", "group", "lipid", "obat",
        "riwayat_ht", "riwayat_dm", "epus",
    )

    def __init__(
        self, *, id, fd, matched, group, lipid, obat, riwayat_ht, riwayat_dm, epus
    ):
        self.id = id
        self.fd = fd
        self.matched = matched
        self.group = group
        self.lipid = lipid
        self.obat = obat
        self.riwayat_ht = riwayat_ht
        self.riwayat_dm = riwayat_dm
        self.epus = epus


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
                lipid=_extract_lipid_epus(epus),
                obat=_extract_obat(epus),
                riwayat_ht=_riwayat_ht_epus_hit(epus),
                riwayat_dm=_riwayat_dm_epus_hit(epus),
                epus=epus,
            )
        )
    return nama_db, visits


def _build_registry_candidate(
    nik: str, nama_db: str, visits: list[_Visit], year: int, today: date
) -> tuple[dict | None, Any]:
    """Build one registry candidate from a NIK's in-year ``visits``. Returns
    ``(patient_dict, baseline_id)`` or ``(None, None)`` when the NIK has no
    MATCHED (CKG) visit in the year. The syarat filter runs later in
    :func:`_finalize_registry`, once ASIK has had its say on the values."""
    matched_visits = [v for v in visits if v.matched]
    if not matched_visits:
        return None, None
    baseline = matched_visits[0]  # visits are filter_date-ascending

    ident = _extract_identitas(baseline.epus)
    nama = ident.get("nama") or nama_db

    # Follow Up: grouped per month, starting the month AFTER the CKG visit month.
    # EVERY visit with a lipid reading is listed in date order. Scrape twins
    # collapse: cross-date twins (match_group_id) keep the earliest date,
    # same-date re-scrapes keep one row per date — the freshest scrape wins via
    # the created_at ordering in _blob_query.
    seen_groups: set[uuid.UUID] = set()
    by_date: dict[date, _Visit] = {}
    for v in visits:  # ascending by (filter_date, created_at)
        if v.fd.month <= baseline.fd.month:
            continue
        if not _has_lipid(v.lipid):
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
                "kol_total": v.lipid.get("kol_total"),
                "ldl": v.lipid.get("ldl"),
                "hdl": v.lipid.get("hdl"),
                "trigliserida": v.lipid.get("trigliserida"),
                "interpretasi": _interpretasi_followup(v.lipid),
                "obat": v.obat,
            }
        )

    # Quarterly Missed Visit fillers — control months only (see _control_months).
    for m in _control_months(baseline.fd.month, year, today):
        if str(m) not in followup:
            followup[str(m)] = [
                {
                    "tanggal": None,
                    "kol_total": None,
                    "ldl": None,
                    "hdl": None,
                    "trigliserida": None,
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
        "riwayat_dm": "Tidak",  # finalized below
        "kol_total": baseline.lipid.get("kol_total"),
        "ldl": baseline.lipid.get("ldl"),
        "hdl": baseline.lipid.get("hdl"),
        "trigliserida": baseline.lipid.get("trigliserida"),
        "interpretasi": "",
        "obat": baseline.obat,
        "followup": followup,
        "_riwayat_ht_epus": any(v.riwayat_ht for v in visits),
        "_riwayat_dm_epus": any(v.riwayat_dm for v in visits),
        "_riwayat_ht_ckg": False,  # ASIK answer/diagnosis, filled below
        "_riwayat_dm_ckg": False,
        # Per-field source provenance — seeded to the EPUS baseline values here;
        # the ASIK 2nd pass flips these to "ASIK" when ASIK wins.
        "_lipid_src": "EPUS" if _has_lipid(baseline.lipid) else None,
        "_obat_src": "EPUS" if baseline.obat else None,
    }
    return patient, baseline.id


def _finalize_registry(
    patients: list[dict], baseline_asik_id: dict, asik_by_id: dict
) -> dict:
    """Batched 2nd pass: raw ASIK is the source of truth for Identitas, the
    baseline lipid readings, both Riwayat columns, and Jenis Obat; the EPUS
    values already in ``p`` are the per-field fallback. Then interpretasi + the
    syarat filter. Follow Up stays EPUS."""
    by_nik = {p["nik"]: p for p in patients}
    for nik, vid in baseline_asik_id.items():
        p = by_nik.get(nik)
        if p is None:
            continue
        asik = asik_by_id.get(vid)
        a = _extract_asik_lipid(asik)
        # Identitas: ASIK wins per field, EPUS (already in p) fills the gaps.
        ident = _extract_asik_identitas(asik)
        for k in ("nama", "jenis_kelamin", "tanggal_lahir", "no_tlp", "alamat"):
            if ident.get(k):
                p[k] = ident[k]
        # Lipid: ASIK wins PER FIELD. The four analytes come from one form, but
        # a partially-filled POCT panel is common, so a per-field merge keeps an
        # ePuskesmas value that ASIK happens to be missing.
        won_any = False
        for slot in _ANALYTES:
            if a.get(slot) is not None:
                p[slot] = a[slot]
                won_any = True
        if won_any:
            p["_lipid_src"] = "ASIK"
        # Jenis Obat: ASIK tatalaksana prescription wins; EPUS Resep fallback.
        asik_obat = _extract_asik_obat(asik)
        if asik_obat:
            p["obat"] = asik_obat
            p["_obat_src"] = "ASIK"
        # Riwayat HT / DM: reuse the sibling registries' own detectors verbatim,
        # so "Riwayat diagnosis HT" means exactly what it means in the Registri
        # Hipertensi, and likewise for DM. Each is the ASIK self-report answer OR
        # a recorded ASIK tatalaksana diagnosis; the EPUS diagnosis stays the
        # fallback (sticky Ya).
        p["_riwayat_ht_ckg"] = _extract_asik_td(asik)["riwayat_ya"] or _asik_ht_diagnosis(asik)
        p["_riwayat_dm_ckg"] = _extract_asik_glucose(asik)["riwayat_ya"] or _asik_dm_diagnosis(asik)

    # Baseline interpretasi + final riwayat, then the syarat filter: keep iff the
    # panel breaches a threshold. Normal and unmeasured rows stay out regardless
    # of a recorded HT/DM diagnosis — see divergences (1) and (2) in the module
    # docstring.
    qualified: list[dict] = []
    for p in patients:
        ht_epus = p.pop("_riwayat_ht_epus")
        dm_epus = p.pop("_riwayat_dm_epus")
        ht_ckg = p.pop("_riwayat_ht_ckg")
        dm_ckg = p.pop("_riwayat_dm_ckg")
        p["riwayat_ht"] = "Ya" if (ht_ckg or ht_epus) else "Tidak"
        p["riwayat_dm"] = "Ya" if (dm_ckg or dm_epus) else "Tidak"
        p["interpretasi"] = _interpretasi_baseline(p)
        lipid_src = p.pop("_lipid_src")
        obat_src = p.pop("_obat_src")
        p["sources"] = {
            "lipid": lipid_src,
            "riwayat_ht": "ASIK" if ht_ckg else ("EPUS" if ht_epus else None),
            "riwayat_dm": "ASIK" if dm_ckg else ("EPUS" if dm_epus else None),
            "obat": obat_src if p["obat"] else None,
        }
        if p["interpretasi"] == _INTERP_DISLIPIDEMIA:
            qualified.append(p)

    qualified.sort(key=lambda x: ((x["nama"] or "").casefold(), x["nik"]))
    return {"patients": qualified, "computed_at": datetime.now(UTC).isoformat()}


def scan_lipid_registry(
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
