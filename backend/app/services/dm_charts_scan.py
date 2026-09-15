"""Cross-year Diabetes Melitus **dashboard charts** aggregation.

Sibling of :mod:`app.services.hipertensi_charts_scan`, over the DM registry
instead of the hipertensi one. Produces the TWO cohort charts the client's
"Dashboard Diabetes Melitus" shows (no monthly/cascade series — those are
hipertensi-only):

  1. Kohort 2 tahun:  DM MURNI 2025 (glukosa memenuhi ambang diagnosis, no
                      riwayat gate) → diperiksa lagi CKG 2026 → glukosa 2026
                      masih tinggi / sudah terkendali → each split
                      diobati/tidak (the diobati bar is nested under Bar 3,
                      not a total).
  2. DM 2026:         DM MURNI 2026 → pasien baru (tanpa riwayat) vs sudah DM
                      (ada riwayat) → each split diobati/tidak (nested under
                      Bar 2, not a total).

"DM murni oleh hasil ukur" reuses the registry's own baseline interpretasi with
the riwayat gate OFF: a NIK counts iff its combined CKG glucose reaches the DM
diagnosis threshold (``GDP≥126`` / ``GD2PP≥200`` / ``GDS-2≥200``). This is the
direct analog of hipertensi's "HT murni" (rerata TD ≥140/90) — Prediabetes and
riwayat-gated-but-normal patients are excluded, by explicit client decision. The
2026 Ya/Tidak split uses the SAME diagnosis threshold (client chose the
symmetric-with-hipertensi option, not the follow-up "target tercapai" band).

All field extraction + classification reuses the pure helpers from
``dm_registry_scan`` (single source of truth), so the charts stay byte-consistent
with the Registri Diabetes Melitus. One EPUS decrypt pass + one batched ASIK
pass, exactly like the registry scan.
"""

from __future__ import annotations

import itertools
import uuid
from collections import namedtuple
from datetime import UTC, date, datetime

from sqlalchemy.orm import Session

from app.services.dm_registry_scan import (
    _INTERP_DM,
    _asik_tatalaksana_dm_diagnosis,
    _blob_nik_count_query,
    _blob_query,
    _decode_group,
    _extract_asik_glucose,
    _extract_asik_obat,
    _fetch_asik_by_id,
    _interpretasi_baseline,
)

_RANGE_START = date(2025, 1, 1)

# Lightweight per-year baseline: the id (for the ASIK batch) and the EPUS glucose
# dict, so the decrypted EPUS blob itself is dropped once the NIK goes out of
# scope.
_ChartsBaseline = namedtuple("_ChartsBaseline", "id gluc")


def _first_of_next_month(d: date) -> date:
    return date(d.year + 1, 1, 1) if d.month == 12 else date(d.year, d.month + 1, 1)


def _dm_murni(gluc: dict) -> bool:
    """Diabetes Melitus MURNI oleh hasil ukur: the registry's baseline
    interpretasi with the riwayat gate OFF equals "Diabetes Melitus" (i.e. the
    reading reaches the diagnosis threshold GDP≥126 / GD2PP≥200 / GDS-2≥200,
    honoring the N15 validity masking). Beda dari registri (yang selalu
    "Diabetes Melitus" saat riwayat=Ya walau glukosa terkendali) — populasi Bar
    1 chart per keputusan client (DM murni, exclude Prediabetes dan
    riwayat-gated-tapi-normal)."""
    return _interpretasi_baseline(gluc, riwayat_ya=False) == _INTERP_DM


def _combine_glucose(epus_gluc: dict, asik_gluc: dict) -> dict:
    """ASIK wins per field, the EPUS baseline fills the gaps — the same
    precedence ``dm_registry_scan._finalize_registry`` applies."""
    out = dict(epus_gluc)
    for slot in ("gds1", "gds2", "gdp", "gd2pp", "hba1c"):
        if asik_gluc.get(slot) is not None:
            out[slot] = asik_gluc[slot]
    return out


# ── pass 1: per-NIK accumulation (from shared decoded visits) ───────────────
def _charts_accumulate(nik: str, visits: list, per_nik: dict, id_to_ny: dict) -> None:
    """Fold one NIK's decoded ``_Visit`` list into the charts accumulators.
    ``per_nik`` and ``id_to_ny`` are mutated in place."""
    # Global scrape-twin dedup (same real visit scraped on two dates); visits are
    # ascending → earliest wins.
    seen_groups: set = set()
    deduped: list = []
    for v in visits:
        if v.group is not None:
            if v.group in seen_groups:
                continue
            seen_groups.add(v.group)
        deduped.append(v)
    visits = deduped

    baseline_by_year: dict[int, _ChartsBaseline] = {}
    for v in visits:
        if v.matched and v.fd.year not in baseline_by_year:
            baseline_by_year[v.fd.year] = _ChartsBaseline(v.id, dict(v.gluc))

    per_nik[nik] = {
        "baseline_by_year": baseline_by_year,
        # Diobati "kapan saja": any EPUS visit with an antidiabetic; the ASIK
        # pass ORs in any baseline's ASIK prescription.
        "treated_epus": any(v.obat for v in visits),
        "riwayat_epus_year": {v.fd.year for v in visits if v.riwayat},
        # filled by the ASIK pass:
        "treated_asik": False,
        "riwayat_year": {},
        "dm_murni_year": {},
    }
    for yr, bv in baseline_by_year.items():
        id_to_ny[bv.id] = (nik, yr)


# ── pass 2: ASIK finalize + aggregate ──────────────────────────────────────
def _charts_finalize(per_nik: dict, id_to_ny: dict, asik_by_id: dict) -> dict:
    for vid, (nik, yr) in id_to_ny.items():
        acc = per_nik[nik]
        bv = acc["baseline_by_year"][yr]
        asik = asik_by_id.get(vid)
        a_gluc = _extract_asik_glucose(asik)
        combined = _combine_glucose(bv.gluc, a_gluc)
        riwayat_ckg = a_gluc.get("riwayat_ya") or _asik_tatalaksana_dm_diagnosis(asik)
        riwayat = riwayat_ckg or (yr in acc["riwayat_epus_year"])
        acc["riwayat_year"][yr] = riwayat
        acc["dm_murni_year"][yr] = _dm_murni(combined)
        if _extract_asik_obat(asik):
            acc["treated_asik"] = True

    for acc in per_nik.values():
        acc["treated"] = acc["treated_epus"] or acc["treated_asik"]

    # ── Chart 1: Kohort 2 tahun — DM murni 2025 → diperiksa lagi CKG 2026 →
    # glukosa 2026 tinggi/terkendali → each split diobati/tidak. ─────────────
    dm_2025 = [nik for nik, acc in per_nik.items() if acc["dm_murni_year"].get(2025)]
    diperiksa_2026 = [nik for nik in dm_2025 if 2026 in per_nik[nik]["baseline_by_year"]]
    # tinggi = masih memenuhi ambang diagnosis DM di 2026; terkendali = tidak.
    # The two partition diperiksa_2026, so tinggi + terkendali == diperiksa_2026.
    tinggi_2026 = [nik for nik in diperiksa_2026 if per_nik[nik]["dm_murni_year"].get(2026)]
    terkendali_2026 = [
        nik for nik in diperiksa_2026 if not per_nik[nik]["dm_murni_year"].get(2026)
    ]
    kohort_2tahun = {
        "dm_2025": len(dm_2025),
        "diperiksa_2026": len(diperiksa_2026),
        "dm_2026_tinggi": len(tinggi_2026),
        "dm_2026_terkendali": len(terkendali_2026),
        "tinggi_diobati": sum(1 for nik in tinggi_2026 if per_nik[nik]["treated"]),
        "tinggi_tidak_diobati": sum(1 for nik in tinggi_2026 if not per_nik[nik]["treated"]),
        "terkendali_diobati": sum(1 for nik in terkendali_2026 if per_nik[nik]["treated"]),
        "terkendali_tidak_diobati": sum(
            1 for nik in terkendali_2026 if not per_nik[nik]["treated"]
        ),
    }

    # ── Chart 2: DM 2026 — DM murni 2026 → pasien baru (tanpa riwayat) vs
    # sudah DM (ada riwayat) → each split diobati/tidak. ────────────────────
    dm_2026 = [nik for nik, acc in per_nik.items() if acc["dm_murni_year"].get(2026)]
    baru_2026 = [nik for nik in dm_2026 if not per_nik[nik]["riwayat_year"].get(2026)]
    sudah_2026 = [nik for nik in dm_2026 if per_nik[nik]["riwayat_year"].get(2026)]
    dm_2026_payload = {
        "dm_2026": len(dm_2026),
        "pasien_baru": len(baru_2026),
        "sudah_dm": len(sudah_2026),
        "baru_diobati": sum(1 for nik in baru_2026 if per_nik[nik]["treated"]),
        "baru_tidak_diobati": sum(1 for nik in baru_2026 if not per_nik[nik]["treated"]),
        "sudah_diobati": sum(1 for nik in sudah_2026 if per_nik[nik]["treated"]),
        "sudah_tidak_diobati": sum(1 for nik in sudah_2026 if not per_nik[nik]["treated"]),
    }

    return {
        "kohort_2tahun": kohort_2tahun,
        "dm_2026": dm_2026_payload,
        "computed_at": datetime.now(UTC).isoformat(),
    }


def scan_dm_charts(
    db: Session, puskesmas_id: uuid.UUID, *, as_of: date | None = None, progress=None
) -> dict:
    """Build the cacheable 2-chart DM payload for one puskesmas across the full
    2025→current-month window (one EPUS decrypt pass + one batched ASIK pass).

    ``progress`` (optional): a ``make_progress_writer`` callback ticked once per
    NIK so the on-miss warm can surface a progress bar."""
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
        _nama_db, visits = _decode_group(group)
        _charts_accumulate(nik, visits, per_nik, id_to_ny)
        if progress:
            done += 1
            progress(done, total)

    asik_by_id = _fetch_asik_by_id(db, set(id_to_ny.keys()))
    return _charts_finalize(per_nik, id_to_ny, asik_by_id)
