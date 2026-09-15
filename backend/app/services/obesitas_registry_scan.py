"""Per-NIK Obesitas **registry** scan (dirjen "Register Sheet" layout).

Fourth sibling of :mod:`app.services.hipertensi_registry_scan`,
:mod:`app.services.dm_registry_scan` and :mod:`app.services.lipid_registry_scan`
— same two-query shape, same ASIK-first sourcing, same follow-up grid — with the
blood-pressure / glucose / lipid block swapped for the anthropometry the
"Obesitas" sheet expects:

  - **Identitas** (NIK, Nama, Jenis Kelamin, Tanggal Lahir, No.Tlp, Alamat,
    Tanggal Berkunjung, Riwayat diagnosis HT, Riwayat diagnosis DM): ASIK
    ``detail_data``, EPUS ``data_pasien`` fallback. Note the sheet puts Tanggal
    Berkunjung and both Riwayat columns INSIDE the "Identitas Pasien" band
    (columns A–I), unlike the Dislipidemia sheet which files them under the
    measurement band. Column order is what makes the export diffable, so it is
    followed here.
  - **Baseline "Hasil Pemeriksaan Antopometri"**: ``BB`` (kg), ``TB`` (cm) and
    the derived ``IMT``, plus ``Interpretasi hasil (pada tanggal berkunjung)``.
  - **Follow Up**: per month from the month AFTER the CKG visit, every EPUS visit
    carrying a weight or height reading, each evaluated against the L16 target.

Inclusion (sheet B1 "Syarat Registri Obesitas"): a NIK appears iff it has ≥1
MATCHED visit in the year AND its baseline IMT is ≥25 — "Obesitas 1 : IMT
25-29.9 / Obesitas II : IMT >= 30". B1 also carries the note "cut off mulai
1 jan 2026", i.e. the dirjen format applies from the 2026 reporting year onward.
That is a **reporting-scope** statement, not a row filter, so it is surfaced in
the UI/export copy rather than hard-coded as a year floor here — the year picker
already scopes the scan, and silently returning nothing for 2025 would look like
a bug rather than a rule.

**Deliberate choices, all read off the sheet — none of them is an oversight to
"fix" back into sibling parity:**

1. **There is no Jenis Obat column.** The Obesitas sheet has none (unlike all
   three siblings), so no drug filter, no prescription sourcing, and no
   ``dalam_pengobatan`` count. Do not add one "for consistency".
2. **IMT is DERIVED, never read.** ``IMT = BB / (TB/100)²``. ASIK has no adult
   IMT question (its adult Gizi form is BB / TB / Lingkar Perut only — ASIK
   computes IMT server-side and does not ship it back), and ePuskesmas's
   ``Hasil IMT`` is a text bucket ("BERISIKO GIZI LEBIH"), not a number.
   Computing it keeps the dashboard, the export's live formula and the syarat
   filter in exact agreement.
3. **The 29.9 / 30 gap is closed upward.** B1 writes "IMT 25-29.9" and
   "IMT >= 30", which literally leaves 29.9 < IMT < 30 unlabelled. Obesitas I is
   therefore ``25 ≤ IMT < 30`` — the reading that closes the gap without moving
   either stated bound.
4. **Control is a 3–6 month WINDOW.** L16 evaluates the target as "penurunan BB
   >5% pada 3-6 bulan berikutnya", so a ``Pasien Missed Visit`` filler is stamped
   only on months baseline+3 … baseline+6 — see :func:`_control_months`. Every
   visit carrying an anthropometry reading is still listed in its own month,
   control window or not. Stamping every empty month (the DM rule) would tell a
   puskesmas their patient missed a visit that was never due; leaving the window
   unmarked would hide the ones that were.
5. **Follow-up is measured against the CKG BASELINE weight**, not against the
   previous visit. L16 says "penurunan BB >5% pada 3-6 bulan berikutnya" — the
   3–6 months are counted from the CKG visit, so the weight it is counted from is
   the CKG visit's.

Cost: EPUS decrypted once per row; ASIK decrypted only for each candidate NIK's
baseline visit, in a single batched second query — never per-row.

The generic helpers (value parsing, identitas, the two blob queries, the batched
ASIK fetch, and both Riwayat detectors) are IMPORTED from the DM and hipertensi
scans rather than copied, for the reason ``lipid_registry_scan`` gives: a fourth
byte-identical copy is the duplication CLAUDE.md §11.2 calls a defect, and it
would drift. Only the anthropometry-specific logic lives here.
"""

from __future__ import annotations

import itertools
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
# "Obesitas 1 : IMT 25-29.9 / Obesitas II : IMT >= 30". Both bounds inclusive at
# the bottom; see divergence (3) for why the upper bound of Obesitas I is 30 and
# not 29.9.
_IMT_MIN_OBESITAS_I = 25.0  # ≥ admits to the registry
_IMT_MIN_OBESITAS_II = 30.0  # ≥ is Obesitas II

# Target: "penurunan BB >5%" — STRICT. Exactly 5.0% is NOT tercapai (the legend
# words the failing side as "penurunan BB <=5%", so the two sides leave no gap).
_TARGET_PENURUNAN_PCT = 5.0

# Baseline interpretasi labels. B1 writes the first as "Obesitas 1" (Arabic) and
# the second as "Obesitas II" (Roman) — an inconsistency in the source document.
# Normalised to Roman numerals here so the two labels read as one scale; the
# thresholds behind them are untouched.
_INTERP_OBESITAS_I = "Obesitas I"
_INTERP_OBESITAS_II = "Obesitas II"
# Measured, but below the syarat. Rows labelled this never enter the registry —
# the label exists because the same function runs before the filter.
_INTERP_NORMAL = "Normal"

# Follow-up "Interpretasi hasil" labels — quoted from the sheet legend (L16:
# "Pasien terdiagnosis Obesitas dievaluasi dengan kategori").
_FU_TERKENDALI = "Pasien Obesitas dengan target tercapai"
_FU_TIDAK_TERKENDALI = "Pasien Obesitas dengan target tidak tercapai"
_FU_MISSED_VISIT = "Pasien Missed Visit"

# NOTE: the legend also defines "Pasien Loss to Follow Up (LTFU)" = no clinical
# visit for 12 CONSECUTIVE months. A single-year scan cannot reach that state —
# a baseline in January leaves at most 11 follow-up months — so LTFU is
# deliberately NOT emitted here, exactly as in the DM and Dislipidemia
# registries. It needs cross-year visit history.

# EPUS field groups carrying BB/TB: Anamnesa → Periksa Fisik is the source of
# truth, PTM → Tekanan Darah & IMT the fallback. Same pair, same precedence, as
# ``epus_to_asik._map_gizi_bb_tb_lp``, so this registry and the converter never
# disagree about a patient's weight.
_EPUS_FISIK_GROUP = "Periksa Fisik"
_EPUS_PTM_GROUP = "Tekanan Darah & IMT"

# Plausibility guards. A mistyped "170" in the BB field (or a TB recorded in
# metres) would otherwise produce an IMT that silently admits or excludes a
# patient. Values outside these ranges are treated as NOT MEASURED — never
# clamped, which would invent a reading nobody took.
_BB_MIN_KG, _BB_MAX_KG = 20.0, 400.0
_TB_MIN_CM, _TB_MAX_CM = 80.0, 250.0


def _empty_antro() -> dict[str, Any]:
    return {"bb": None, "tb": None}


def _has_antro(a: dict[str, Any]) -> bool:
    return a.get("bb") is not None or a.get("tb") is not None


def _plausible_bb(v: float | None) -> float | None:
    return v if v is not None and _BB_MIN_KG <= v <= _BB_MAX_KG else None


def _plausible_tb(v: float | None) -> float | None:
    return v if v is not None and _TB_MIN_CM <= v <= _TB_MAX_CM else None


def imt(bb: float | None, tb: float | None) -> float | None:
    """Body-mass index from weight (kg) and height (cm), rounded to 1 decimal —
    the precision the sheet's own bands are written at ("IMT 25-29.9").

    Returns ``None`` unless BOTH values are present and plausible. The rounding
    happens BEFORE the bands are applied (see :func:`_interpretasi_baseline`) so
    the dashboard, the export's live formula and the syarat filter all classify
    the same displayed number — an IMT of 24.96 shows as 25.0 and must therefore
    also COUNT as 25.0, not fall out of the registry for a hidden decimal.
    """
    if bb is None or tb is None or tb <= 0:
        return None
    return round(bb / (tb / 100.0) ** 2, 1)


# ── EPUS extraction ────────────────────────────────────────────────────────
def _extract_antro_epus(epus: Any) -> dict[str, Any]:
    """Weight/height from one EPUS visit.

    ``Anamnesa → Periksa Fisik`` is the source of truth; ``PTM → Tekanan Darah &
    IMT`` fills its gaps, per field. ``Hasil IMT`` in the same group is
    deliberately ignored — it is a text bucket ("BERISIKO GIZI LEBIH"), not a
    number, and this registry computes IMT itself (divergence 2).
    """
    out = _empty_antro()
    if not isinstance(epus, dict):
        return out
    tabs = epus.get("tabs") or {}
    fisik = ((tabs.get("Anamnesa") or {}).get("fields", {}) or {}).get(
        _EPUS_FISIK_GROUP
    )
    ptm = ((tabs.get("PTM") or {}).get("fields", {}) or {}).get(_EPUS_PTM_GROUP)
    for group in (fisik, ptm):
        if not isinstance(group, dict):
            continue
        if out["bb"] is None:
            out["bb"] = _plausible_bb(_num(group.get("Berat Badan")))
        if out["tb"] is None:
            out["tb"] = _plausible_tb(_num(group.get("Tinggi Badan")))
    return out


# ── ASIK extraction (Gizi BB - TB - Lingkar Perut) ─────────────────────────
def _antro_fields_from_form(fd_items, out: dict[str, Any]) -> None:
    """Fill ``out`` (bb/tb) from (key, value) pairs of an ASIK Gizi form. Labels
    are matched loosely so minor wording drift still resolves; existing values
    are kept (first source wins).

    Live labels (``app/data/asik_form_mapping.json``, form "Gizi (BB - TB -
    Lingkar Perut) <Laki-laki|Perempuan>"): "Berat Badan (Kg)", "Pengukuran
    Tinggi Badan (cm)", "Pengukuran Lingkar Perut".

    Three guards, all load-bearing:

      - **Questions are skipped first.** The CKG anamnesis asks "Apakah berat
        badan Anda berkurang >3 kg dalam 3 bulan terakhir…?" — which contains
        "berat badan". Without this test running before the value tests, a "Ya"
        answer is parsed as a weight (and ``_num`` turning it into ``None`` would
        then be indistinguishable from an unmeasured field).
      - **Birth weight is skipped.** "Berat Lahir" and "Berat Badan Saat Ini
        (usia >24 jam)" belong to the newborn form; neither is an adult's weight.
      - **``Pilih …`` dropdowns are skipped** ("Pilih hasil IMT/U", "Pilih Status
        Lingkar Kepala") — enum verdicts, not measurements.

    "Lingkar Perut" is not collected at all: the Obesitas sheet has no waist
    column, and the syarat is IMT-only.
    """
    for k, v in fd_items:
        kl = str(k).casefold()
        if "apakah" in kl or "pilih" in kl or "lahir" in kl or "lingkar" in kl:
            continue
        if "berat" in kl:
            slot, val = "bb", _plausible_bb(_num(v))
        elif "tinggi badan" in kl:
            slot, val = "tb", _plausible_tb(_num(v))
        else:
            continue
        if out.get(slot) is None:
            out[slot] = val


def _extract_asik_antro(asik: Any) -> dict[str, Any]:
    """Weight/height from the raw ASIK blob. Walks every ``pelayanan_nakes`` /
    ``pemeriksaan_mandiri`` entry whose ``layanan`` mentions gizi or antropometri
    (live: "Skrining Gizi, Tekanan Darah, dan Gula Darah <Laki-laki => 40
    Tahun|Perempuan>"); the first plausible value per slot wins.

    Both spellings of antropometri are accepted — the dirjen sheet's own band is
    headed "Hasil Pemeriksaan Antopometri", so the typo is demonstrably in
    circulation.
    """
    out = _empty_antro()
    if not isinstance(asik, dict):
        return out
    for arr_key in ("pelayanan_nakes", "pemeriksaan_mandiri"):
        for entry in asik.get(arr_key) or []:
            if not isinstance(entry, dict):
                continue
            layanan = str(entry.get("layanan") or "").casefold()
            if not any(
                t in layanan for t in ("gizi", "antropometri", "antopometri")
            ):
                continue
            fd = entry.get("form_data")
            if isinstance(fd, dict):
                _antro_fields_from_form(fd.items(), out)
    return out


# ── classification ─────────────────────────────────────────────────────────
def _interpretasi_baseline(a: dict[str, Any]) -> str:
    """Interpretasi on the visit date, from the derived IMT:

      Obesitas II — IMT ≥ 30
      Obesitas I  — 25 ≤ IMT < 30
      Normal      — IMT computed and below 25
      ""          — IMT not computable (BB or TB missing)

    "Normal" here means only "below the registry's cut-off". The sheet defines no
    band under 25, so no underweight/overweight distinction is invented — and it
    never surfaces anyway, because every row that survives the syarat filter is
    Obesitas I or II by construction.

    Unlike the hipertensi and DM registries, a recorded HT/DM diagnosis does NOT
    pin the label: this sheet admits on measurement alone, and Riwayat HT / DM
    are columns H and I — things it reports, not things it filters on (the same
    reading the Dislipidemia registry applies to the same two columns).
    """
    v = imt(a.get("bb"), a.get("tb"))
    if v is None:
        return ""
    if v >= _IMT_MIN_OBESITAS_II:
        return _INTERP_OBESITAS_II
    if v >= _IMT_MIN_OBESITAS_I:
        return _INTERP_OBESITAS_I
    return _INTERP_NORMAL


def penurunan_pct(bb: float | None, bb_baseline: float | None) -> float | None:
    """Weight change from the CKG baseline, as a POSITIVE percentage for a LOSS
    (rounded to 1 decimal). Weight gain comes back negative. ``None`` when either
    weight is missing.

    Positive-means-loss matches how the legend words the target ("penurunan BB
    >5%"), so the number can be shown next to the label without a sign flip.
    """
    if bb is None or bb_baseline is None or bb_baseline <= 0:
        return None
    return round((bb_baseline - bb) / bb_baseline * 100.0, 1)


def _interpretasi_followup(
    a: dict[str, Any], bb_baseline: float | None
) -> str:
    """Follow-up evaluation (sheet L16 legend).

    target tercapai       — penurunan BB **>5%** from the CKG baseline weight
    target tidak tercapai — penurunan BB ≤5% (including no change, and gain)

    The comparator is STRICT on the tercapai side and inclusive on the other, so
    exactly 5.0% is "tidak tercapai" — the legend's own two sentences
    (">5%" / "<=5%") leave no gap. Do not tidy this into a single ≥.

    A visit with no weight — or a patient with no baseline weight to compare
    against — is not interpretable → "" (blank), never "tidak tercapai". A
    height-only follow-up visit is exactly that case: it is still listed (the
    sheet has a TB column in every month) but carries no verdict.
    """
    pct = penurunan_pct(a.get("bb"), bb_baseline)
    if pct is None:
        return ""
    return (
        _FU_TERKENDALI if pct > _TARGET_PENURUNAN_PCT else _FU_TIDAK_TERKENDALI
    )


def count_interpretasi_bands(patients: list[dict]) -> dict[str, int]:
    """Per-band counts over registry patients, read off each patient's
    already-computed ``interpretasi`` (no rescan). Shared by the registry list
    and summary endpoints.

    Unlike the Dislipidemia registry's four overlapping analyte counts, these two
    are MUTUALLY EXCLUSIVE and DO sum to the registry total: the syarat is a
    single IMT scale cut in two, so every qualifying row is exactly one of them.
    The invariant is asserted in the tests.
    """
    return {
        "obesitas_1": sum(
            1 for p in patients if p.get("interpretasi") == _INTERP_OBESITAS_I
        ),
        "obesitas_2": sum(
            1 for p in patients if p.get("interpretasi") == _INTERP_OBESITAS_II
        ),
    }


def _control_months(baseline_month: int, year: int, today: date) -> list[int]:
    """Months (1..12) in which a follow-up control was DUE, per L16's "3-6 bulan
    berikutnya": baseline month +3, +4, +5, +6.

    Capped at the current month for the current year (a control that has not come
    due yet is not a missed one) and at December otherwise. Only these months get
    a ``Pasien Missed Visit`` filler when empty — every other empty month stays
    blank, because nothing was expected in it.
    """
    last = 12 if year < today.year else (today.month if year == today.year else 0)
    return [m for m in range(baseline_month + 3, baseline_month + 7) if m <= last]


# ── per-visit decode (EPUS) ────────────────────────────────────────────────
class _Visit:
    __slots__ = (
        "id", "fd", "matched", "group", "antro",
        "riwayat_ht", "riwayat_dm", "epus",
    )

    def __init__(
        self, *, id, fd, matched, group, antro, riwayat_ht, riwayat_dm, epus
    ):
        self.id = id
        self.fd = fd
        self.matched = matched
        self.group = group
        self.antro = antro
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
                antro=_extract_antro_epus(epus),
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
    MATCHED (CKG) visit in the year.

    The follow-up interpretasi is deliberately left blank here and computed in
    :func:`_finalize_registry`: it needs the FINAL baseline weight, and ASIK has
    not had its say on that yet. Filling it from the EPUS weight and then
    forgetting to redo it is exactly how the grid would end up disagreeing with
    the baseline column it is measured against.
    """
    matched_visits = [v for v in visits if v.matched]
    if not matched_visits:
        return None, None
    baseline = matched_visits[0]  # visits are filter_date-ascending

    ident = _extract_identitas(baseline.epus)
    nama = ident.get("nama") or nama_db

    # Follow Up: grouped per month, starting the month AFTER the CKG visit month.
    # EVERY visit with an anthropometry reading is listed in date order. Scrape
    # twins collapse: cross-date twins (match_group_id) keep the earliest date,
    # same-date re-scrapes keep one row per date — the freshest scrape wins via
    # the created_at ordering in _blob_query.
    seen_groups: set[uuid.UUID] = set()
    by_date: dict[date, _Visit] = {}
    for v in visits:  # ascending by (filter_date, created_at)
        if v.fd.month <= baseline.fd.month:
            continue
        if not _has_antro(v.antro):
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
                "bb": v.antro.get("bb"),
                "tb": v.antro.get("tb"),
                "imt": imt(v.antro.get("bb"), v.antro.get("tb")),
                "penurunan_pct": None,  # finalized once the baseline BB is final
                "interpretasi": "",  # ditto
            }
        )

    # Missed Visit fillers — control-window months only (see _control_months).
    for m in _control_months(baseline.fd.month, year, today):
        if str(m) not in followup:
            followup[str(m)] = [
                {
                    "tanggal": None,
                    "bb": None,
                    "tb": None,
                    "imt": None,
                    "penurunan_pct": None,
                    "interpretasi": _FU_MISSED_VISIT,
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
        "bb": baseline.antro.get("bb"),
        "tb": baseline.antro.get("tb"),
        "imt": None,  # derived below, from the FINAL bb/tb
        "interpretasi": "",
        "followup": followup,
        "_riwayat_ht_epus": any(v.riwayat_ht for v in visits),
        "_riwayat_dm_epus": any(v.riwayat_dm for v in visits),
        "_riwayat_ht_ckg": False,  # ASIK answer/diagnosis, filled below
        "_riwayat_dm_ckg": False,
        # Per-field source provenance — seeded to the EPUS baseline values here;
        # the ASIK 2nd pass flips these to "ASIK" when ASIK wins.
        "_antro_src": "EPUS" if _has_antro(baseline.antro) else None,
    }
    return patient, baseline.id


def _finalize_registry(
    patients: list[dict], baseline_asik_id: dict, asik_by_id: dict
) -> dict:
    """Batched 2nd pass: raw ASIK is the source of truth for Identitas, the
    baseline BB/TB and both Riwayat columns; the EPUS values already in ``p`` are
    the per-field fallback. Then the derived IMT, both interpretasi layers, and
    the syarat filter. Follow Up stays EPUS."""
    by_nik = {p["nik"]: p for p in patients}
    for nik, vid in baseline_asik_id.items():
        p = by_nik.get(nik)
        if p is None:
            continue
        asik = asik_by_id.get(vid)
        a = _extract_asik_antro(asik)
        # Identitas: ASIK wins per field, EPUS (already in p) fills the gaps.
        ident = _extract_asik_identitas(asik)
        for k in ("nama", "jenis_kelamin", "tanggal_lahir", "no_tlp", "alamat"):
            if ident.get(k):
                p[k] = ident[k]
        # BB / TB: ASIK wins PER FIELD. Both come from one form, but a partly
        # filled Gizi form is common (a weight recorded without a height), so a
        # per-field merge keeps an ePuskesmas value ASIK happens to be missing —
        # and without both, there is no IMT and no registry row at all.
        won_any = False
        for slot in ("bb", "tb"):
            if a.get(slot) is not None:
                p[slot] = a[slot]
                won_any = True
        if won_any:
            p["_antro_src"] = "ASIK"
        # Riwayat HT / DM: reuse the sibling registries' own detectors verbatim,
        # so "Riwayat diagnosis HT" means exactly what it means in the Registri
        # Hipertensi, and likewise for DM. Each is the ASIK self-report answer OR
        # a recorded ASIK tatalaksana diagnosis; the EPUS diagnosis stays the
        # fallback (sticky Ya).
        p["_riwayat_ht_ckg"] = _extract_asik_td(asik)["riwayat_ya"] or _asik_ht_diagnosis(asik)
        p["_riwayat_dm_ckg"] = _extract_asik_glucose(asik)["riwayat_ya"] or _asik_dm_diagnosis(asik)

    # Derived IMT + baseline interpretasi + final riwayat + the follow-up verdicts
    # (which need the final baseline weight), then the syarat filter: keep iff the
    # baseline IMT reaches 25. Normal and unmeasured rows stay out regardless of a
    # recorded HT/DM diagnosis.
    qualified: list[dict] = []
    for p in patients:
        ht_epus = p.pop("_riwayat_ht_epus")
        dm_epus = p.pop("_riwayat_dm_epus")
        ht_ckg = p.pop("_riwayat_ht_ckg")
        dm_ckg = p.pop("_riwayat_dm_ckg")
        p["riwayat_ht"] = "Ya" if (ht_ckg or ht_epus) else "Tidak"
        p["riwayat_dm"] = "Ya" if (dm_ckg or dm_epus) else "Tidak"
        p["imt"] = imt(p["bb"], p["tb"])
        p["interpretasi"] = _interpretasi_baseline(p)
        for readings in p["followup"].values():
            for v in readings:
                if v["interpretasi"] == _FU_MISSED_VISIT:
                    continue
                v["penurunan_pct"] = penurunan_pct(v["bb"], p["bb"])
                v["interpretasi"] = _interpretasi_followup(v, p["bb"])
        antro_src = p.pop("_antro_src")
        p["sources"] = {
            "antropometri": antro_src,
            "riwayat_ht": "ASIK" if ht_ckg else ("EPUS" if ht_epus else None),
            "riwayat_dm": "ASIK" if dm_ckg else ("EPUS" if dm_epus else None),
        }
        if p["interpretasi"] in (_INTERP_OBESITAS_I, _INTERP_OBESITAS_II):
            qualified.append(p)

    qualified.sort(key=lambda x: ((x["nama"] or "").casefold(), x["nik"]))
    return {"patients": qualified, "computed_at": datetime.now(UTC).isoformat()}


def scan_obesitas_registry(
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
