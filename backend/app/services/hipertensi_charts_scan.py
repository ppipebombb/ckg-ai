"""Cross-year Hipertensi **dashboard charts** aggregation.

The client's "Usulan Grafik Dashboard" wants 8 charts over the SAME CKG-matched
hipertensi registry the "Kertas Kerja Hipertensi" page shows, but rolled up as
counts across the whole 2025→current-month window instead of per-patient rows:

  1. Cascade (current month):  registered → treated → controlled.
  2. Tertatalaksana (monthly):  cumulative registered vs cumulative treated.
  3. Target Tercapai (monthly): of cumulative-treated, controlled that month.
  4. Target Tidak Tercapai:     of cumulative-treated, uncontrolled that month.
  5. Tidak Berkunjung:          of cumulative-treated, no reading that month.
  6. Proporsi 2025→2026:        reg-2025 → both years → controlled at CKG-2026
                                baseline → controlled this month.
  7. Kohort 2 tahun:            HT MURNI 2025 (rerata TD ≥140/90, no riwayat
                                gate) → diperiksa lagi CKG 2026 → TD 2026
                                tinggi/terkendali → each split diobati/tidak
                                (diobati bar is nested under Bar 3, not a
                                total).
  8. Hipertensi 2026:           HT MURNI 2026 → pasien baru (tanpa riwayat) vs
                                sudah hipertensi (ada riwayat) → each split
                                diobati/tidak (diobati bar is nested under
                                Bar 2, not a total).

Charts 7-8 use a DIFFERENT Bar-1 population than charts 1-6: "HT murni"
(``_ht_murni``, rerata sistolik ≥140 dan/atau diastolik ≥90 semata) instead of
registry membership (``in_reg_2025``/``in_reg_2026``, which also admits
Pre-Hipertensi and riwayat-gated patients whose TD reading is actually
controlled) — per explicit client decision, since chart 7/8 need to isolate
patients hypertensive BY MEASUREMENT.

Why a NEW scan (not two per-year ``scan_hipertensi_registry`` payloads): a NIK
registered via a CKG visit in 2025 can have plain monthly ePuskesmas follow-up
visits in 2026 that are NOT a new CKG screening — the 2025 payload stops at Dec
2025 and the 2026 payload only contains NIKs with a fresh matched 2026 CKG visit,
so composing the two would DROP those 2026 readings. This scans ``Patient`` rows
directly across ``[2025-01-01, first-of-next-month)`` and groups by NIK once.

All field extraction + classification reuses the pure helpers from
``hipertensi_registry_scan`` (single source of truth for the registry logic), so
the charts stay byte-consistent with the Kertas Kerja registry. ``scan_hipertensi_bundle``
folds this together with BOTH per-year registry scans into a single EPUS+ASIK
decrypt pass (used by the nightly warm cron).

Decisions baked in (see documents/Usulan_Grafik_Dashboard_Scraping_AI.md):
  - Universe = CKG-matched registry members only (≥1 MATCHED visit + syarat/year).
  - Monthly control rule = ANY controlled reading in the month → controlled; else
    if any reading → uncontrolled; else missed. "Controlled" needs BOTH sys<140
    AND dia<90 present.
  - Chart-6 Bar-2 = STRICT reg-2025 ∩ reg-2026 (both syarat-filtered registries).
  - Payload carries ABSOLUTE counts + cohort bases; percentages are a frontend
    concern (denominator is still an open client question).
"""

from __future__ import annotations

import itertools
import uuid
from collections import namedtuple
from datetime import UTC, date, datetime

from sqlalchemy.orm import Session

from app.services.hipertensi_registry_scan import (
    _INTERP_HIPERTENSI,
    _INTERP_PRE_HIPERTENSI,
    _asik_tatalaksana_ht_diagnosis,
    _blob_nik_count_query,
    _blob_query,
    _build_registry_candidate,
    _decode_group,
    _extract_asik_identitas,
    _extract_asik_obat,
    _extract_asik_td,
    _extract_identitas,
    _fetch_asik_by_id,
    _finalize_registry,
    _interpretasi_baseline,
    _rerata,
)

# Cumulative axis floor. The client counts "sejak Februari 2025"; registry
# membership still uses full-year 2025 (Jan assumed empty — CKG began ~Feb 2025).
_AXIS_START = (2025, 2)
_RANGE_START = date(2025, 1, 1)

# Lightweight per-year baseline kept in the charts accumulator (NOT the whole
# _Visit, so the decrypted EPUS dict isn't retained across all NIKs).
_ChartsBaseline = namedtuple("_ChartsBaseline", "id fd sys1 dia1")


def _first_of_next_month(d: date) -> date:
    return date(d.year + 1, 1, 1) if d.month == 12 else date(d.year, d.month + 1, 1)


def _month_axis(current_ym: tuple[int, int]) -> list[tuple[int, int]]:
    """Every (year, month) from Feb-2025 through ``current_ym`` inclusive."""
    out: list[tuple[int, int]] = []
    y, m = _AXIS_START
    while (y, m) <= current_ym:
        out.append((y, m))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def _controlled(sys: float | None, dia: float | None) -> bool:
    """Terkendali: BOTH readings present and below target (<140 / <90)."""
    return sys is not None and dia is not None and sys < 140 and dia < 90


def _ht_murni(sys: float | None, dia: float | None) -> bool:
    """Hipertensi MURNI oleh hasil pengukuran (rerata) semata, tanpa riwayat
    gate: sistolik ≥140 dan/atau diastolik ≥90. Beda dari ``interpretasi``
    (selalu "Hipertensi" saat riwayat_ya=True walau TD terkendali) — populasi
    Bar 1 chart 7/8 per keputusan client (Hipertensi murni, exclude
    Pre-Hipertensi dan riwayat-gated-tapi-TD-normal)."""
    s = sys if sys is not None else 0.0
    d = dia if dia is not None else 0.0
    return s >= 140 or d >= 90


# ── pass 1: per-NIK accumulation (from shared decoded visits) ───────────────
def _charts_accumulate(
    nik: str, visits: list, per_nik: dict, id_to_ny: dict, nama_db: str = ""
) -> None:
    """Fold one NIK's decoded ``_Visit`` list into the charts accumulators.
    ``per_nik`` and ``id_to_ny`` are mutated in place."""
    # Global scrape-twin dedup BEFORE anything else: a cross-date twin (same real
    # visit scraped on two dates, e.g. a Dec-2025/Jan-2026 boundary twin) must not
    # count as two visits, a phantom second-month reading, or a second-year CKG
    # registration. visits are ascending → earliest wins.
    seen_groups: set = set()
    deduped: list = []
    for v in visits:
        if v.group is not None:
            if v.group in seen_groups:
                continue
            seen_groups.add(v.group)
        deduped.append(v)
    visits = deduped

    # Per-year baseline = earliest MATCHED (EPUS+ASIK CKG) visit that year.
    # Identitas is read off the SAME baseline EPUS blob the Kertas Kerja registry
    # uses (_build_registry_candidate), so the Gap Tatalaksana list and the
    # registry can never disagree on a patient's nama / no telp / alamat. Only
    # the small extracted dict is kept — the decrypted EPUS blob itself is still
    # dropped when this NIK's group goes out of scope.
    baseline_by_year: dict[int, _ChartsBaseline] = {}
    ident_by_year: dict[int, dict] = {}
    for v in visits:
        if v.matched and v.fd.year not in baseline_by_year:
            baseline_by_year[v.fd.year] = _ChartsBaseline(v.id, v.fd, v.sys1, v.dia1)
            ident_by_year[v.fd.year] = _extract_identitas(v.epus)

    # Per-(year,month) BP: any-controlled rule. A reading needs at least one of
    # sys/dia to count as "has_reading"; controlled needs both < target.
    by_ym: dict[tuple[int, int], dict] = {}
    for v in visits:
        if v.sys1 is None and v.dia1 is None:
            continue
        cell = by_ym.setdefault((v.fd.year, v.fd.month), {"has": False, "ctrl": False})
        cell["has"] = True
        if _controlled(v.sys1, v.dia1):
            cell["ctrl"] = True

    per_nik[nik] = {
        "baseline_by_year": baseline_by_year,
        "ident_by_year": ident_by_year,
        "nama_db": nama_db,
        "by_ym": by_ym,
        "treated_epus_ym": {(v.fd.year, v.fd.month) for v in visits if v.obat},
        "riwayat_epus_year": {v.fd.year for v in visits if v.riwayat},
        # filled by the ASIK pass:
        "syarat_year": {},
        "baseline_month": {},
        "baseline_info": {},
        "asik_obat_ym": set(),
        "baseline_2026_controlled": False,
        "riwayat_year": {},
        "ht_murni_year": {},
    }
    for yr, bv in baseline_by_year.items():
        id_to_ny[bv.id] = (nik, yr)


def _charts_gap_row(nik: str, acc: dict) -> dict:
    """One "Gap Tatalaksana" row: identitas + the CKG baseline of the year the
    patient ENTERED the registry (the oldest one — that is how long they have
    been waiting). Empty fields stay empty strings / None; the frontend renders
    the em dash."""
    reg_ym = acc["registration_ym"]
    ident = acc["ident_by_year"].get(reg_ym[0]) or {}
    info = acc["baseline_info"].get(reg_ym[0]) or {}
    return {
        "nik": nik,
        "nama": ident.get("nama") or acc.get("nama_db") or "",
        "jenis_kelamin": ident.get("jenis_kelamin") or "",
        "tanggal_lahir": ident.get("tanggal_lahir"),
        "no_tlp": ident.get("no_tlp") or "",
        "alamat": ident.get("alamat") or "",
        "tanggal_berkunjung": info.get("tanggal_berkunjung"),
        "rerata_sys": info.get("rerata_sys"),
        "rerata_dia": info.get("rerata_dia"),
        "interpretasi": info.get("interpretasi") or "",
        "registration_ym": f"{reg_ym[0]:04d}-{reg_ym[1]:02d}",
    }


# ── pass 2: ASIK finalize + aggregate ──────────────────────────────────────
def _charts_finalize(
    per_nik: dict, id_to_ny: dict, asik_by_id: dict, as_of: date
) -> dict:
    """Apply the batched ASIK pass (syarat + baseline-2026-controlled) then build
    the 6-chart payload. ``asik_by_id`` maps each baseline id to its decrypted
    ASIK dict (or None)."""
    for vid, (nik, yr) in id_to_ny.items():
        acc = per_nik[nik]
        bv = acc["baseline_by_year"][yr]
        asik = asik_by_id.get(vid)
        a_td = _extract_asik_td(asik)
        # TD1: the ASIK reading wins as a pair; EPUS baseline is the fallback.
        if a_td["sys1"] is not None or a_td["dia1"] is not None:
            td_sys1, td_dia1 = a_td["sys1"], a_td["dia1"]
        else:
            td_sys1, td_dia1 = bv.sys1, bv.dia1
        rerata_sys = _rerata(td_sys1, a_td["sys2"])
        rerata_dia = _rerata(td_dia1, a_td["dia2"])
        riwayat_ckg = a_td["riwayat_ya"] or _asik_tatalaksana_ht_diagnosis(asik)
        riwayat = riwayat_ckg or (yr in acc["riwayat_epus_year"])
        interp = _interpretasi_baseline(rerata_sys, rerata_dia, riwayat_ya=riwayat)
        acc["syarat_year"][yr] = riwayat or interp in (
            _INTERP_HIPERTENSI,
            _INTERP_PRE_HIPERTENSI,
        )
        acc["baseline_month"][yr] = (bv.fd.year, bv.fd.month)
        # Identitas + the baseline clinical facts, for the Gap Tatalaksana list.
        # Same precedence as the registry (_finalize_registry): ASIK wins per
        # field, the EPUS baseline already in ``ident`` fills the gaps.
        ident = acc["ident_by_year"].setdefault(yr, {})
        a_ident = _extract_asik_identitas(asik)
        for k in ("nama", "jenis_kelamin", "tanggal_lahir", "no_tlp", "alamat"):
            if a_ident.get(k):
                ident[k] = a_ident[k]
        acc["baseline_info"][yr] = {
            "tanggal_berkunjung": bv.fd.isoformat(),
            "rerata_sys": rerata_sys,
            "rerata_dia": rerata_dia,
            "interpretasi": interp,
        }
        if _extract_asik_obat(asik):
            acc["asik_obat_ym"].add((bv.fd.year, bv.fd.month))
        if yr == 2026:
            acc["baseline_2026_controlled"] = _controlled(rerata_sys, rerata_dia)
        acc["riwayat_year"][yr] = riwayat
        acc["ht_murni_year"][yr] = _ht_murni(rerata_sys, rerata_dia)

    current_ym = (as_of.year, as_of.month)
    months = _month_axis(current_ym)

    # ── Per-NIK derived facts + registry membership. ───────────────────────
    registry: list[str] = []
    for nik, acc in per_nik.items():
        acc["in_reg_2025"] = acc["syarat_year"].get(2025, False)
        acc["in_reg_2026"] = acc["syarat_year"].get(2026, False)
        acc["in_registry"] = any(acc["syarat_year"].values())
        if not acc["in_registry"]:
            continue
        reg_months = [
            acc["baseline_month"][yr]
            for yr in acc["baseline_by_year"]
            if acc["syarat_year"].get(yr)
        ]
        acc["registration_ym"] = min(reg_months)
        treated_ym = acc["treated_epus_ym"] | acc["asik_obat_ym"]
        acc["treated"] = bool(treated_ym)
        # A patient joins the treated cohort only once registered — clamp so the
        # cumulative treated line can never exceed the registered line.
        acc["treated_enter_ym"] = (
            max(acc["registration_ym"], min(treated_ym)) if treated_ym else None
        )
        registry.append(nik)

    # ── Gap Tatalaksana: the registry members never treated. ───────────────
    # This is the drill-down behind the gap in Chart 2 — registry members with
    # no antihypertensive prescription in ANY month of the window, i.e. exactly
    # ``registered_cumulative - treated_cumulative`` at the last month (the
    # cumulative treated line only ever grows, so "not treated by the last
    # month" == "not treated at all"). ``_charts_gap_row`` reads facts already
    # accumulated above — no extra query, no extra decrypt.
    gap_patients = [
        _charts_gap_row(nik, per_nik[nik])
        for nik in registry
        if not per_nik[nik]["treated"]
    ]
    gap_patients.sort(key=lambda p: (p["registration_ym"], p["nama"].casefold()))

    # ── Chart 2/3/4/5: monthly cumulative series. ──────────────────────────
    monthly: list[dict] = []
    for ym in months:
        registered = 0
        cohort: list[str] = []
        for nik in registry:
            acc = per_nik[nik]
            if acc["registration_ym"] <= ym:
                registered += 1
                if acc["treated"] and acc["treated_enter_ym"] <= ym:
                    cohort.append(nik)
        tercapai = tidak_tercapai = tidak_berkunjung = 0
        for nik in cohort:
            cell = per_nik[nik]["by_ym"].get(ym)
            if cell and cell["ctrl"]:
                tercapai += 1
            elif cell and cell["has"]:
                tidak_tercapai += 1
            else:
                tidak_berkunjung += 1
        monthly.append(
            {
                "ym": f"{ym[0]:04d}-{ym[1]:02d}",
                "registered_cumulative": registered,
                "treated_cumulative": len(cohort),
                "tercapai": tercapai,
                "tidak_tercapai": tidak_tercapai,
                "tidak_berkunjung": tidak_berkunjung,
            }
        )

    # ── Chart 1: cascade at the current month. ─────────────────────────────
    treated_niks = [nik for nik in registry if per_nik[nik]["treated"]]
    cascade_controlled = sum(
        1
        for nik in treated_niks
        if (c := per_nik[nik]["by_ym"].get(current_ym)) and c["ctrl"]
    )
    cascade = {
        "registered": len(registry),
        "treated": len(treated_niks),
        "controlled": cascade_controlled,
    }

    # ── Chart 6: Proporsi 2025→2026 (strict reg-2025 ∩ reg-2026). ──────────
    both = [
        nik
        for nik, acc in per_nik.items()
        if acc.get("in_reg_2025") and acc.get("in_reg_2026")
    ]
    proporsi = {
        "registry_2025": sum(1 for acc in per_nik.values() if acc.get("in_reg_2025")),
        "both_years": len(both),
        "controlled_baseline_2026": sum(
            1 for nik in both if per_nik[nik]["baseline_2026_controlled"]
        ),
        "controlled_current_month": sum(
            1
            for nik in both
            if (c := per_nik[nik]["by_ym"].get(current_ym)) and c["ctrl"]
        ),
    }

    # ── Chart 7: Kohort 2 tahun — HT murni 2025 → diperiksa lagi CKG 2026 →
    # TD 2026 tinggi/terkendali → pernah diobati (kapan saja 2025-2026). ────
    ht_2025 = [nik for nik, acc in per_nik.items() if acc["ht_murni_year"].get(2025)]
    diperiksa_2026 = [nik for nik in ht_2025 if 2026 in per_nik[nik]["baseline_by_year"]]
    tinggi_2026 = [nik for nik in diperiksa_2026 if not per_nik[nik]["baseline_2026_controlled"]]
    terkendali_2026 = [nik for nik in diperiksa_2026 if per_nik[nik]["baseline_2026_controlled"]]
    kohort_2tahun = {
        "hipertensi_2025": len(ht_2025),
        "diperiksa_2026": len(diperiksa_2026),
        "td_2026_tinggi": len(tinggi_2026),
        "td_2026_terkendali": len(terkendali_2026),
        "tinggi_diobati": sum(1 for nik in tinggi_2026 if per_nik[nik].get("treated")),
        "tinggi_tidak_diobati": sum(1 for nik in tinggi_2026 if not per_nik[nik].get("treated")),
        "terkendali_diobati": sum(1 for nik in terkendali_2026 if per_nik[nik].get("treated")),
        "terkendali_tidak_diobati": sum(
            1 for nik in terkendali_2026 if not per_nik[nik].get("treated")
        ),
    }

    # ── Chart 8: Hipertensi 2026 — HT murni 2026 → pasien baru (tanpa
    # riwayat) vs sudah hipertensi (ada riwayat) → pernah diobati. ──────────
    ht_2026 = [nik for nik, acc in per_nik.items() if acc["ht_murni_year"].get(2026)]
    baru_2026 = [nik for nik in ht_2026 if not per_nik[nik]["riwayat_year"].get(2026)]
    sudah_2026 = [nik for nik in ht_2026 if per_nik[nik]["riwayat_year"].get(2026)]
    hipertensi_2026 = {
        "hipertensi_2026": len(ht_2026),
        "pasien_baru": len(baru_2026),
        "sudah_hipertensi": len(sudah_2026),
        "baru_diobati": sum(1 for nik in baru_2026 if per_nik[nik].get("treated")),
        "baru_tidak_diobati": sum(1 for nik in baru_2026 if not per_nik[nik].get("treated")),
        "sudah_diobati": sum(1 for nik in sudah_2026 if per_nik[nik].get("treated")),
        "sudah_tidak_diobati": sum(1 for nik in sudah_2026 if not per_nik[nik].get("treated")),
    }

    return {
        "current_month": f"{current_ym[0]:04d}-{current_ym[1]:02d}",
        "monthly": monthly,
        "cascade": cascade,
        "proporsi": proporsi,
        "kohort_2tahun": kohort_2tahun,
        "hipertensi_2026": hipertensi_2026,
        # Split off into its own Redis key by the warmers — it is ~2k rows of
        # patient identity and must never ride along on the hot /charts GET.
        "gap_patients": gap_patients,
        "computed_at": datetime.now(UTC).isoformat(),
    }


def scan_hipertensi_charts(
    db: Session, puskesmas_id: uuid.UUID, *, as_of: date | None = None, progress=None
) -> dict:
    """Build the cacheable 6-chart payload for one puskesmas across the full
    2025→current-month window (one EPUS decrypt pass + one batched ASIK pass).

    ``progress`` (optional): a ``make_progress_writer`` callback ticked once per
    NIK so the on-miss warm can surface a progress bar. ``None`` → zero overhead."""
    as_of = as_of or date.today()
    range_end = _first_of_next_month(as_of)

    total = 0
    if progress:
        total = db.scalar(_blob_nik_count_query(puskesmas_id, _RANGE_START, range_end)) or 0
    done = 0

    per_nik: dict[str, dict] = {}
    id_to_ny: dict = {}
    for nik, group in itertools.groupby(
        db.execute(_blob_query(puskesmas_id, _RANGE_START, range_end)),
        key=lambda r: r.nik,
    ):
        nama_db, visits = _decode_group(group)
        _charts_accumulate(nik, visits, per_nik, id_to_ny, nama_db)
        if progress:
            done += 1
            progress(done, total)

    asik_by_id = _fetch_asik_by_id(db, set(id_to_ny.keys()))
    return _charts_finalize(per_nik, id_to_ny, asik_by_id, as_of)


def scan_hipertensi_bundle(
    db: Session,
    puskesmas_id: uuid.UUID,
    years: list[int],
    *,
    as_of: date | None = None,
) -> dict:
    """ONE EPUS+ASIK decrypt pass → both per-year registry payloads AND the
    cross-year charts payload. Returns ``{"registry": {year: payload}, "charts":
    payload}``. Used by the nightly warm cron so warming registry-2025,
    registry-2026 and the charts costs a single decryption of the shared blobs.

    Correctness note: the charts BP-by-month map does NOT require a MATCHED
    pairing (a 2026 plain-EPUS follow-up of a 2025-registered NIK still counts),
    while the per-year registry builds get their own year-filtered visit slice."""
    as_of = as_of or date.today()
    today = date.today()
    range_start = date(min(years), 1, 1)
    range_end = _first_of_next_month(as_of)

    reg_patients: dict[int, list] = {y: [] for y in years}
    reg_baseline: dict[int, dict] = {y: {} for y in years}
    charts_per_nik: dict[str, dict] = {}
    charts_id_to_ny: dict = {}

    for nik, group in itertools.groupby(
        db.execute(_blob_query(puskesmas_id, range_start, range_end)),
        key=lambda r: r.nik,
    ):
        nama_db, visits = _decode_group(group)  # decode EPUS once
        for y in years:
            yv = [v for v in visits if v.fd.year == y]
            if not yv:
                continue
            patient, bid = _build_registry_candidate(nik, nama_db, yv, y, today)
            if patient is not None:
                reg_patients[y].append(patient)
                reg_baseline[y][nik] = bid
        _charts_accumulate(nik, visits, charts_per_nik, charts_id_to_ny, nama_db)

    # One ASIK batch over the union of every baseline id (registry per year +
    # charts — the same rows, so this decrypts each ASIK blob once).
    all_ids: set = set(charts_id_to_ny.keys())
    for y in years:
        all_ids |= set(reg_baseline[y].values())
    asik_by_id = _fetch_asik_by_id(db, all_ids)

    registry = {
        y: _finalize_registry(reg_patients[y], reg_baseline[y], asik_by_id)
        for y in years
    }
    charts = _charts_finalize(charts_per_nik, charts_id_to_ny, asik_by_id, as_of)
    return {"registry": registry, "charts": charts}
