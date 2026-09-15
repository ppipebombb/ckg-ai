"""Hipertensi (blood-pressure) per-NIK monthly report.

A sibling of ``gdp_report`` that reads the SAME scraped EPUS blobs but surfaces
Sistolik/Diastolik instead of fasting glucose. There is no separate scrape job:
this module is purely a new view + Redis cache + xlsx export over data the GD
Puasa / DM scrape already populates in the ``patients`` table.

Source of the pair (mirrors ``_map_tekanan_darah_dewasa_lansia`` in
``app.services.epus_to_asik``): ``Anamnesa → Periksa Fisik`` (Sistole/Diastole),
falling back per-field to ``PTM → Tekanan Darah & IMT``. Per (NIK, month) the
latest ``filter_date`` visit's pair wins. Green/Terkendali rule: Sistole<140 AND
Diastole<90.

Generic per-blob helpers (``_parse_decimal``, ``_eligible_date``,
``_extract_tertatalaksana``, ``_authorize``) are reused from ``gdp_report`` so
the two reports stay byte-for-byte consistent.
"""

import json
import logging
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import Principal, get_db, get_dashboard_principal
from app.api.pagination import PageParams, page_params
from app.api.routes.gdp_report import (
    DashboardRow,
    _authorize,
    _eligible_date,
    _extract_tertatalaksana,
    _parse_decimal,
    dashboard_summary_response,
    dashboard_terkendali_response,
)
from app.core.rate_limit import redis_client
from app.core.report_warm import make_progress_writer, read_progress, request_warm
from app.models.puskesmas import Puskesmas
from app.schemas.hipertensi_report import (
    HipertensiReportDashboardOut,
    HipertensiReportRow,
)
from app.services.dashboard_scan import DashboardSpec, DecRows, scan_dashboard_payloads
from app.schemas.report_summary import (
    TerkendaliDashboardOut,
    TerkendaliSummaryOut,
)
from app.schemas.hipertensi_charts import HipertensiChartsOut
from app.schemas.hipertensi_gap import HipertensiGapOut, HipertensiGapRow
from app.schemas.hipertensi_registry import (
    HipertensiRegistryDashboardOut,
    HipertensiRegistryRow,
    HipertensiRegistrySummaryOut,
)
from app.services.hipertensi_diagnose_export import (
    build_hipertensi_diagnose_workbook,
)
from app.services.hipertensi_export import build_hipertensi_workbook
from app.services.hipertensi_gap_export import build_hipertensi_gap_workbook
from app.services.hipertensi_registry_export import (
    build_hipertensi_registry_workbook,
)
from app.services.hipertensi_charts_scan import (
    scan_hipertensi_bundle,
    scan_hipertensi_charts,
)
from app.services.hipertensi_registry_scan import (
    count_interpretasi_bands,
    scan_hipertensi_registry,
)

log = logging.getLogger(__name__)

router = APIRouter(tags=["hipertensi-report"])

# Same caching contract as the GDP dashboard (30h TTL > 24h nightly warm cron).
_DASHBOARD_CACHE_TTL_SECONDS = 30 * 60 * 60


def _dashboard_cache_key(puskesmas_id: uuid.UUID, year: int) -> str:
    return f"hipertensi_report:dashboard:{puskesmas_id}:{year}"


# ── EPUS blood-pressure extraction ────────────────────────────────────────
def _extract_bp(epus_entry: Any) -> tuple[Decimal | None, Decimal | None]:
    """Return (sistole, diastole) for one EPUS visit blob.

    Primary source ``tabs.Anamnesa.fields["Periksa Fisik"]`` Sistole/Diastole,
    falling back per-field to ``tabs.PTM.fields["Tekanan Darah & IMT"]`` — the
    exact source the live ASIK ``Tekanan Darah Dewasa Lansia`` mapper uses.
    """
    if not isinstance(epus_entry, dict):
        return (None, None)
    tabs = epus_entry.get("tabs") or {}
    fisik = ((tabs.get("Anamnesa") or {}).get("fields", {}) or {}).get(
        "Periksa Fisik"
    )
    ptm_imt = ((tabs.get("PTM") or {}).get("fields", {}) or {}).get(
        "Tekanan Darah & IMT"
    )
    fisik = fisik if isinstance(fisik, dict) else {}
    ptm_imt = ptm_imt if isinstance(ptm_imt, dict) else {}
    sistole = _parse_decimal(fisik.get("Sistole"))
    if sistole is None:
        sistole = _parse_decimal(ptm_imt.get("Sistole"))
    diastole = _parse_decimal(fisik.get("Diastole"))
    if diastole is None:
        diastole = _parse_decimal(ptm_imt.get("Diastole"))
    return (sistole, diastole)


# ── Terkendali classification (mirrors the Hipertensi MAP/LAMBDA formula) ──
def _classify_bp(sys: float | None, dia: float | None) -> str:
    if sys is None or dia is None:
        return ""
    return "Terkendali" if (sys < 140 and dia < 90) else "Tidak terkendali"


def _compute_terkendali_quarter(
    pairs: dict[int, tuple[float | None, float | None]],
    diag: date | None,
    tahun: int,
    months_window: tuple[int, int, int],
    cutoff_month: int,
) -> str:
    """Per-quarter status (TW1-4). Mirrors the spreadsheet MAP/LAMBDA formula:
    a month is valid when ``month_start >= eligible`` AND both sys & dia are
    numbers; the last valid month in the quarter decides the status."""
    if diag is None:
        return ""
    eligible = _eligible_date(diag, 3)
    cutoff = date(tahun, cutoff_month, 1)
    if eligible >= cutoff:
        return "Belum 3 bulan"
    last: tuple[float, float] | None = None
    for m in reversed(months_window):
        if date(tahun, m, 1) < eligible:
            continue
        sys, dia = pairs.get(m, (None, None))
        if sys is None or dia is None:
            continue
        last = (sys, dia)
        break
    if last is None:
        return "Tidak ada kunjungan"
    return _classify_bp(last[0], last[1])


def _compute_terkendali_berjalan(
    pairs: dict[int, tuple[float | None, float | None]],
    diag: date | None,
    tahun: int,
) -> str:
    """Rolling-3-month status anchored on TODAY (mirrors the GDP berjalan)."""
    if diag is None:
        return ""
    today = date.today()
    bulan_aktif = today.month
    eligible = _eligible_date(diag, 3)
    if date(today.year, bulan_aktif, 1) < eligible:
        return "Belum 3 bulan"
    last: tuple[float, float] | None = None
    for m in range(bulan_aktif, bulan_aktif - 3, -1):
        if m < 1 or m > 12:
            continue
        sys, dia = pairs.get(m, (None, None))
        if sys is None or dia is None:
            continue
        last = (sys, dia)
        break
    if last is None:
        return "Tidak ada kunjungan"
    return _classify_bp(last[0], last[1])


# ── Cacheable aggregate ────────────────────────────────────────────────────
def _ht_fields(epus: Any) -> dict[str, Decimal | None]:
    """Per-day cell sources for Hipertensi — the Sistolik/Diastolik pair."""
    sys_v, dia_v = _extract_bp(epus)
    return {"sys": sys_v, "dia": dia_v}


def _ht_choose_month(dec_rows: DecRows) -> tuple[dict[str, str | None] | None, date | None]:
    """Month pair: latest visit (rows are DESC) with ANY reading wins; the
    Sistolik/Diastolik pair is taken together from that one chosen visit."""
    for fd, epus in dec_rows:
        if epus is None:
            continue
        s, d = _extract_bp(epus)
        if s is not None or d is not None:
            return {
                "sys": str(s) if s is not None else None,
                "dia": str(d) if d is not None else None,
            }, fd
    return None, None


# Hipertensi report spec for the shared single-pass scanner (app.services.dashboard_scan).
HT_SPEC = DashboardSpec(extract_fields=_ht_fields, choose_month=_ht_choose_month)


def _compute_dashboard_payload(
    db: Session, puskesmas_id: uuid.UUID, year: int, *, progress=None
) -> dict:
    """Build the cacheable Hipertensi aggregate for (puskesmas, year): qualified
    NIKs + per-month Sistolik/Diastolik pair + per-NIK name/first_epus_date, in
    one decrypt pass. Mirrors ``gdp_report._compute_dashboard_payload``."""
    return scan_dashboard_payloads(
        db,
        puskesmas_id,
        year,
        {"hipertensi": HT_SPEC},
        extract_tertatalaksana=_extract_tertatalaksana,
        progress=progress,
    )["hipertensi"]


def warm_hipertensi_dashboard(
    db: Session, rc, puskesmas_id: uuid.UUID, year: int, ttl: int
) -> dict:
    """Compute the dashboard aggregate and write it to Redis. Shared by the
    on-miss endpoint path and the nightly warm-up cron (cron.warm_reports)."""
    cache_key = _dashboard_cache_key(puskesmas_id, year)
    payload = _compute_dashboard_payload(
        db, puskesmas_id, year, progress=make_progress_writer(rc, cache_key)
    )
    try:
        rc.set(cache_key, json.dumps(payload), ex=ttl)
    except Exception as exc:
        log.warning("redis set failed for %s: %s", cache_key, exc)
    return payload


# ── payload → row helpers ──────────────────────────────────────────────────
def _by_month_from_payload(
    monthly: dict[str, dict[str, dict[str, str | None]]], nik: str
) -> tuple[
    dict[int, float | None],
    dict[int, float | None],
    dict[int, tuple[float | None, float | None]],
]:
    cell = monthly.get(nik) or {}
    sis: dict[int, float | None] = {}
    dia: dict[int, float | None] = {}
    pairs: dict[int, tuple[float | None, float | None]] = {}
    for m in range(1, 13):
        c = cell.get(str(m)) or {}
        sv = float(c["sys"]) if c.get("sys") is not None else None
        dv = float(c["dia"]) if c.get("dia") is not None else None
        sis[m] = sv
        dia[m] = dv
        pairs[m] = (sv, dv)
    return sis, dia, pairs


def _bp_by_day_from_payload(
    daily: dict[str, dict[str, dict[str, str | None]]], nik: str
) -> dict[str, dict[str, float | None]]:
    out: dict[str, dict[str, float | None]] = {}
    for d, c in (daily.get(nik) or {}).items():
        out[d] = {
            "sys": float(c["sys"]) if c.get("sys") is not None else None,
            "dia": float(c["dia"]) if c.get("dia") is not None else None,
        }
    return out


# ── Endpoints ──────────────────────────────────────────────────────────────
@router.get(
    "/hipertensi-reports/dashboard", response_model=HipertensiReportDashboardOut
)
def hipertensi_report_dashboard(
    puskesmas_id: uuid.UUID = Query(...),
    year: int = Query(..., ge=2000, le=2100),
    q: str | None = Query(None, max_length=64),
    ckg_only: bool = Query(False),
    params: PageParams = Depends(page_params),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_dashboard_principal),
) -> HipertensiReportDashboardOut:
    """Per-NIK Hipertensi report over the same EPUS blobs as the GD Puasa report.

    A NIK is listed iff at least one visit in the year carries a Sistole or
    Diastole reading. The aggregate is cached in Redis for 30h keyed by
    (puskesmas, year); search/pagination apply in-memory on top of the cached
    payload. Use DELETE .../dashboard/cache to force a rebuild.
    """
    _authorize(principal, puskesmas_id)
    pk_name = db.scalar(select(Puskesmas.name).where(Puskesmas.id == puskesmas_id))
    if pk_name is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Puskesmas not found")

    cache_key = _dashboard_cache_key(puskesmas_id, year)
    rc = redis_client()
    cached: str | None = None
    try:
        cached = rc.get(cache_key)
    except Exception as exc:
        log.warning("redis get failed for %s: %s", cache_key, exc)

    cache_hit = False
    payload: dict | None = None
    if cached:
        try:
            payload = json.loads(cached)
            cache_hit = True
        except Exception:
            payload = None
            cache_hit = False
    if payload is None:
        request_warm(
            rc,
            cache_key,
            "hipertensi_dashboard",
            {"puskesmas_id": str(puskesmas_id), "year": year},
        )
        return HipertensiReportDashboardOut(
            items=[],
            total=0,
            page=params.page,
            size=params.size,
            pages=0,
            cache_hit=False,
            computed_at=None,
            computing=True,
            progress=read_progress(rc, cache_key),
        )

    niks: list[dict[str, Any]] = payload.get("niks") or []
    monthly: dict[str, dict[str, dict[str, str | None]]] = payload.get("monthly") or {}
    daily: dict[str, dict[str, dict[str, str | None]]] = payload.get("daily") or {}

    if ckg_only:
        niks = [n for n in niks if n.get("tandai_ckg")]

    if q:
        needle = q.strip().casefold()
        if needle:
            niks = [
                n
                for n in niks
                if needle in n["nama"].casefold() or needle in n["nik"].casefold()
            ]

    total = len(niks)
    pages = (total + params.size - 1) // params.size if total else 0
    start = (params.page - 1) * params.size
    page_slice = niks[start : start + params.size]

    items: list[HipertensiReportRow] = []
    for n in page_slice:
        sis, dia, pairs = _by_month_from_payload(monthly, n["nik"])
        diag = (
            date.fromisoformat(n["first_epus_date"])
            if n.get("first_epus_date")
            else None
        )
        items.append(
            HipertensiReportRow(
                puskesmas_name=pk_name,
                tahun_pelaporan=year,
                nama=n["nama"],
                nik=n["nik"],
                tanggal_diagnosis=diag,
                tertatalaksana_obat=bool(n.get("tertatalaksana_obat", False)),
                tertatalaksana_edukasi=bool(n.get("tertatalaksana_edukasi", False)),
                sistolik_by_month=sis,
                diastolik_by_month=dia,
                bp_by_day=_bp_by_day_from_payload(daily, n["nik"]),
                terkendali_bulan_berjalan=_compute_terkendali_berjalan(
                    pairs, diag, year
                ),
                terkendali_tw1=_compute_terkendali_quarter(
                    pairs, diag, year, (1, 2, 3), 4
                ),
                terkendali_tw2=_compute_terkendali_quarter(
                    pairs, diag, year, (4, 5, 6), 7
                ),
                terkendali_tw3=_compute_terkendali_quarter(
                    pairs, diag, year, (7, 8, 9), 10
                ),
                terkendali_tw4=_compute_terkendali_quarter(
                    pairs, diag, year, (10, 11, 12), 12
                ),
            )
        )
    return HipertensiReportDashboardOut(
        items=items,
        total=total,
        page=params.page,
        size=params.size,
        pages=pages,
        cache_hit=cache_hit,
        computed_at=datetime.fromisoformat(payload["computed_at"]),
        computing=False,
    )


def _export_filename(prefix: str, pk_name: str, year: int | str) -> str:
    safe = "".join(
        c if (c.isalnum() or c in " -_") else "_" for c in pk_name
    ).strip()
    return f"{prefix} - {safe or 'Puskesmas'} - {year}.xlsx"


def _load_payload_or_warm(
    db: Session, rc, puskesmas_id: uuid.UUID, year: int
) -> dict:
    cache_key = _dashboard_cache_key(puskesmas_id, year)
    payload: dict | None = None
    try:
        cached = rc.get(cache_key)
        if cached:
            payload = json.loads(cached)
    except Exception as exc:
        log.warning("redis get failed for %s: %s", cache_key, exc)
    if payload is None:
        payload = warm_hipertensi_dashboard(
            db, rc, puskesmas_id, year, _DASHBOARD_CACHE_TTL_SECONDS
        )
    return payload


@router.get("/hipertensi-reports/dashboard/export")
def export_hipertensi_dashboard(
    puskesmas_id: uuid.UUID = Query(...),
    year: int = Query(..., ge=2000, le=2100),
    ckg_only: bool = Query(False),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_dashboard_principal),
) -> StreamingResponse:
    """Download the Hipertensi report as an .xlsx for (puskesmas, year).

    Reuses the same cached aggregate as the dashboard (no recompute) but emits
    ALL NIKs — no pagination/search. The Terkendali (AE..BG) and Rekap columns
    stay as live spreadsheet formulas; only the raw data columns (A..AD) are
    filled. See ``app.services.hipertensi_export``.
    """
    _authorize(principal, puskesmas_id)
    pk_name = db.scalar(select(Puskesmas.name).where(Puskesmas.id == puskesmas_id))
    if pk_name is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Puskesmas not found")

    rc = redis_client()
    payload = _load_payload_or_warm(db, rc, puskesmas_id, year)
    niks: list[dict[str, Any]] = payload.get("niks") or []
    monthly: dict[str, dict[str, dict[str, str | None]]] = payload.get("monthly") or {}
    if ckg_only:
        niks = [n for n in niks if n.get("tandai_ckg")]

    rows = []
    for n in niks:
        sis, dia, _pairs = _by_month_from_payload(monthly, n["nik"])
        rows.append({
            "nama": n["nama"],
            "tanggal_diagnosis": (
                date.fromisoformat(n["first_epus_date"])
                if n.get("first_epus_date")
                else None
            ),
            "tertatalaksana_obat": bool(n.get("tertatalaksana_obat", False)),
            "tertatalaksana_edukasi": bool(n.get("tertatalaksana_edukasi", False)),
            "sistolik_by_month": sis,
            "diastolik_by_month": dia,
        })

    content = build_hipertensi_workbook(pk_name, year, rows)
    filename = _export_filename("Hipertensi", pk_name, year)
    return StreamingResponse(
        iter([content]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/hipertensi-reports/dashboard/diagnose-export")
def export_hipertensi_diagnose(
    puskesmas_id: uuid.UUID = Query(...),
    year: int = Query(..., ge=2000, le=2100),
    ckg_only: bool = Query(False),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_dashboard_principal),
) -> StreamingResponse:
    """Download the Hipertensi Full Review Diagnose view as an .xlsx. One row per
    visit-day reading; see ``app.services.hipertensi_diagnose_export``."""
    _authorize(principal, puskesmas_id)
    pk_name = db.scalar(select(Puskesmas.name).where(Puskesmas.id == puskesmas_id))
    if pk_name is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Puskesmas not found")

    rc = redis_client()
    payload = _load_payload_or_warm(db, rc, puskesmas_id, year)
    niks: list[dict[str, Any]] = payload.get("niks") or []
    daily: dict[str, dict[str, dict[str, str | None]]] = payload.get("daily") or {}
    if ckg_only:
        niks = [n for n in niks if n.get("tandai_ckg")]

    rows = []
    for n in niks:
        by_day = _bp_by_day_from_payload(daily, n["nik"])
        if not by_day:
            continue
        readings = [
            {"date": date.fromisoformat(iso), "sys": c["sys"], "dia": c["dia"]}
            for iso, c in sorted(by_day.items())
        ]
        rows.append({"nama": n["nama"], "nik": n["nik"], "readings": readings})

    content = build_hipertensi_diagnose_workbook(pk_name, year, rows)
    filename = _export_filename("Full Review Diagnosa Hipertensi", pk_name, year)
    return StreamingResponse(
        iter([content]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.delete(
    "/hipertensi-reports/dashboard/cache",
    status_code=status.HTTP_204_NO_CONTENT,
)
def clear_hipertensi_dashboard_cache(
    puskesmas_id: uuid.UUID = Query(...),
    year: int = Query(..., ge=2000, le=2100),
    principal: Principal = Depends(get_dashboard_principal),
) -> None:
    _authorize(principal, puskesmas_id)
    key = _dashboard_cache_key(puskesmas_id, year)
    rc = redis_client()
    try:
        rc.delete(key)
    except Exception as exc:
        log.warning("redis delete failed: %s", exc)
    request_warm(
        rc,
        key,
        "hipertensi_dashboard",
        {"puskesmas_id": str(puskesmas_id), "year": year},
    )


@router.get(
    "/hipertensi-reports/dashboard/summary", response_model=TerkendaliSummaryOut
)
def hipertensi_report_dashboard_summary(
    puskesmas_id: uuid.UUID = Query(...),
    year: int = Query(..., ge=2000, le=2100),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_dashboard_principal),
) -> TerkendaliSummaryOut:
    """Terkendali Bulan Berjalan tally over ALL NIKs for (puskesmas, year).

    Sibling of ``/gdp-reports/dashboard/summary`` — reuses the same Redis
    aggregate as the Hipertensi dashboard (no recompute) and the same
    ``_compute_terkendali_berjalan`` classifier. On a cold cache the recompute
    is enqueued and ``computing`` is set so the caller polls back.
    """
    def _statuses(payload: dict) -> list[str]:
        niks: list[dict[str, Any]] = payload.get("niks") or []
        monthly: dict[str, dict[str, dict[str, str | None]]] = (
            payload.get("monthly") or {}
        )
        return [
            _compute_terkendali_berjalan(
                _by_month_from_payload(monthly, n["nik"])[2],
                date.fromisoformat(n["first_epus_date"]) if n.get("first_epus_date") else None,
                year,
            )
            for n in niks
        ]

    return dashboard_summary_response(
        db=db,
        principal=principal,
        puskesmas_id=puskesmas_id,
        year=year,
        cache_key=_dashboard_cache_key(puskesmas_id, year),
        report_type="hipertensi_dashboard",
        compute_statuses=_statuses,
    )


@router.get(
    "/hipertensi-reports/dashboard/terkendali",
    response_model=TerkendaliDashboardOut,
)
def hipertensi_report_dashboard_terkendali(
    puskesmas_id: uuid.UUID = Query(...),
    year: int = Query(..., ge=2000, le=2100),
    ckg_only: bool = Query(False),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_dashboard_principal),
) -> TerkendaliDashboardOut:
    """Per-quarter (TW1-4) terkendali tally + pemberian obat/edukasi counts over
    ALL NIKs for (puskesmas, year). Reuses the dashboard Redis cache (no recompute).

    ``ckg_only`` restricts the tally to NIKs flagged sudah CKG (same filter as
    ``/hipertensi-reports/dashboard``)."""
    def _rows(payload: dict) -> list[DashboardRow]:
        niks: list[dict[str, Any]] = payload.get("niks") or []
        if ckg_only:
            niks = [n for n in niks if n.get("tandai_ckg")]
        monthly: dict[str, dict[str, dict[str, str | None]]] = (
            payload.get("monthly") or {}
        )
        out: list[DashboardRow] = []
        for n in niks:
            pairs = _by_month_from_payload(monthly, n["nik"])[2]
            diag = (
                date.fromisoformat(n["first_epus_date"])
                if n.get("first_epus_date")
                else None
            )
            tws = (
                _compute_terkendali_quarter(pairs, diag, year, (1, 2, 3), 4),
                _compute_terkendali_quarter(pairs, diag, year, (4, 5, 6), 7),
                _compute_terkendali_quarter(pairs, diag, year, (7, 8, 9), 10),
                _compute_terkendali_quarter(pairs, diag, year, (10, 11, 12), 12),
            )
            out.append(
                (
                    tws,
                    bool(n.get("tertatalaksana_obat")),
                    bool(n.get("tertatalaksana_edukasi")),
                )
            )
        return out

    return dashboard_terkendali_response(
        db=db,
        principal=principal,
        puskesmas_id=puskesmas_id,
        year=year,
        cache_key=_dashboard_cache_key(puskesmas_id, year),
        report_type="hipertensi_dashboard",
        compute_rows=_rows,
    )


# ── Registri Hipertensi (V8juni2026 dirjen layout) ─────────────────────────
# A separate, richer per-NIK registry: identitas + a baseline "Hasil pemeriksaan
# TD" block (TD1 from EPUS, TD2 from ASIK) + a per-month Follow Up of every EPUS
# visit reading. Inclusion: HT signal (ICD regex OR TD1 ≥140/90) AND ≥1 MATCHED
# (EPUS+ASIK) visit — so every row is CKG. Own Redis cache, warmed by the same
# 5am cron. See ``app.services.hipertensi_registry_scan`` / ``_export``.
_REGISTRY_CACHE_TTL_SECONDS = 30 * 60 * 60


def _registry_cache_key(puskesmas_id: uuid.UUID, year: int) -> str:
    return f"hipertensi_registry:dashboard:{puskesmas_id}:{year}"


def warm_hipertensi_registry(
    db: Session, rc, puskesmas_id: uuid.UUID, year: int, ttl: int
) -> dict:
    """Compute the registry payload and write it to Redis. Shared by the on-miss
    endpoint path and the nightly warm cron (cron.warm_reports)."""
    cache_key = _registry_cache_key(puskesmas_id, year)
    payload = scan_hipertensi_registry(
        db, puskesmas_id, year, progress=make_progress_writer(rc, cache_key)
    )
    try:
        rc.set(cache_key, json.dumps(payload), ex=ttl)
    except Exception as exc:
        log.warning("redis set failed for %s: %s", cache_key, exc)
    return payload


def _load_registry_payload_or_warm(
    db: Session, rc, puskesmas_id: uuid.UUID, year: int
) -> dict:
    cache_key = _registry_cache_key(puskesmas_id, year)
    payload: dict | None = None
    try:
        cached = rc.get(cache_key)
        if cached:
            payload = json.loads(cached)
    except Exception as exc:
        log.warning("redis get failed for %s: %s", cache_key, exc)
    if payload is None:
        payload = warm_hipertensi_registry(
            db, rc, puskesmas_id, year, _REGISTRY_CACHE_TTL_SECONDS
        )
    return payload


def _registry_row(p: dict, pk_name: str, year: int) -> HipertensiRegistryRow:
    return HipertensiRegistryRow(puskesmas_name=pk_name, tahun_pelaporan=year, **p)


@router.get(
    "/hipertensi-reports/registry",
    response_model=HipertensiRegistryDashboardOut,
)
def hipertensi_registry_dashboard(
    puskesmas_id: uuid.UUID = Query(...),
    year: int = Query(..., ge=2000, le=2100),
    q: str | None = Query(None, max_length=64),
    params: PageParams = Depends(page_params),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_dashboard_principal),
) -> HipertensiRegistryDashboardOut:
    """Per-NIK Hipertensi registry (V8juni2026). One patient per row; the full
    baseline + follow-up detail rides along so the UI can expand it and the
    export emits the wide multi-row sheet. Cached 30h keyed by (puskesmas, year);
    search/pagination apply in-memory. Use DELETE .../registry/cache to rebuild.
    """
    _authorize(principal, puskesmas_id)
    pk_name = db.scalar(select(Puskesmas.name).where(Puskesmas.id == puskesmas_id))
    if pk_name is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Puskesmas not found")

    cache_key = _registry_cache_key(puskesmas_id, year)
    rc = redis_client()
    cached: str | None = None
    try:
        cached = rc.get(cache_key)
    except Exception as exc:
        log.warning("redis get failed for %s: %s", cache_key, exc)

    cache_hit = False
    payload: dict | None = None
    if cached:
        try:
            payload = json.loads(cached)
            cache_hit = True
        except Exception:
            payload = None
            cache_hit = False
    if payload is None:
        request_warm(
            rc,
            cache_key,
            "hipertensi_registry",
            {"puskesmas_id": str(puskesmas_id), "year": year},
        )
        return HipertensiRegistryDashboardOut(
            items=[],
            total=0,
            total_hipertensi=0,
            total_pre_hipertensi=0,
            page=params.page,
            size=params.size,
            pages=0,
            cache_hit=False,
            computed_at=None,
            computing=True,
            progress=read_progress(rc, cache_key),
        )

    patients: list[dict[str, Any]] = payload.get("patients") or []
    if q:
        needle = q.strip().casefold()
        if needle:
            patients = [
                n
                for n in patients
                if needle in (n.get("nama") or "").casefold()
                or needle in n["nik"].casefold()
            ]

    total = len(patients)
    # Band split of the (search-filtered) total for the header breakdown.
    total_hipertensi, total_pre_hipertensi = count_interpretasi_bands(patients)
    pages = (total + params.size - 1) // params.size if total else 0
    start = (params.page - 1) * params.size
    page_slice = patients[start : start + params.size]

    items = [_registry_row(p, pk_name, year) for p in page_slice]
    return HipertensiRegistryDashboardOut(
        items=items,
        total=total,
        total_hipertensi=total_hipertensi,
        total_pre_hipertensi=total_pre_hipertensi,
        page=params.page,
        size=params.size,
        pages=pages,
        cache_hit=cache_hit,
        computed_at=datetime.fromisoformat(payload["computed_at"]),
        computing=False,
    )


@router.get(
    "/hipertensi-reports/registry/summary",
    response_model=HipertensiRegistrySummaryOut,
)
def hipertensi_registry_summary(
    puskesmas_id: uuid.UUID = Query(...),
    year: int = Query(..., ge=2000, le=2100),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_dashboard_principal),
) -> HipertensiRegistrySummaryOut:
    """Aggregate counts over the Hipertensi registry (one puskesmas, year) for the
    dashboard 'Status per Puskesmas' card: total pasien hipertensi (CKG), pasien
    dengan riwayat hipertensi (Ya), dan pasien dalam pengobatan (≥1 obat diresepkan
    pada baseline). Reuses the registry Redis cache; a cold cache enqueues a warm
    and returns ``computing=True`` so the caller polls back."""
    _authorize(principal, puskesmas_id)
    if not db.scalar(select(Puskesmas.id).where(Puskesmas.id == puskesmas_id)):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Puskesmas not found")

    cache_key = _registry_cache_key(puskesmas_id, year)
    rc = redis_client()
    cached: str | None = None
    try:
        cached = rc.get(cache_key)
    except Exception as exc:
        log.warning("redis get failed for %s: %s", cache_key, exc)

    payload: dict | None = None
    if cached:
        try:
            payload = json.loads(cached)
        except Exception:
            payload = None
    if payload is None:
        request_warm(
            rc,
            cache_key,
            "hipertensi_registry",
            {"puskesmas_id": str(puskesmas_id), "year": year},
        )
        return HipertensiRegistrySummaryOut(
            total=0,
            total_hipertensi=0,
            total_pre_hipertensi=0,
            riwayat_ht_ya=0,
            dalam_pengobatan=0,
            cache_hit=False,
            computed_at=None,
            computing=True,
        )

    patients: list[dict[str, Any]] = payload.get("patients") or []
    total_hipertensi, total_pre_hipertensi = count_interpretasi_bands(patients)
    return HipertensiRegistrySummaryOut(
        total=len(patients),
        total_hipertensi=total_hipertensi,
        total_pre_hipertensi=total_pre_hipertensi,
        riwayat_ht_ya=sum(1 for p in patients if p.get("riwayat_ht") == "Ya"),
        dalam_pengobatan=sum(1 for p in patients if p.get("obat")),
        cache_hit=True,
        computed_at=datetime.fromisoformat(payload["computed_at"]),
        computing=False,
    )


@router.get("/hipertensi-reports/registry/export")
def export_hipertensi_registry(
    puskesmas_id: uuid.UUID = Query(...),
    year: int = Query(..., ge=2000, le=2100),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_dashboard_principal),
) -> StreamingResponse:
    """Download the Registri Hipertensi as an .xlsx for (puskesmas, year). Emits
    ALL patients (no pagination/search). See ``hipertensi_registry_export``."""
    _authorize(principal, puskesmas_id)
    pk_name = db.scalar(select(Puskesmas.name).where(Puskesmas.id == puskesmas_id))
    if pk_name is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Puskesmas not found")

    rc = redis_client()
    payload = _load_registry_payload_or_warm(db, rc, puskesmas_id, year)
    patients = payload.get("patients") or []

    content = build_hipertensi_registry_workbook(pk_name, year, patients)
    filename = _export_filename("Registri Hipertensi", pk_name, year)
    return StreamingResponse(
        iter([content]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.delete(
    "/hipertensi-reports/registry/cache",
    status_code=status.HTTP_204_NO_CONTENT,
)
def clear_hipertensi_registry_cache(
    puskesmas_id: uuid.UUID = Query(...),
    year: int = Query(..., ge=2000, le=2100),
    principal: Principal = Depends(get_dashboard_principal),
) -> None:
    _authorize(principal, puskesmas_id)
    key = _registry_cache_key(puskesmas_id, year)
    rc = redis_client()
    try:
        rc.delete(key)
    except Exception as exc:
        log.warning("redis delete failed: %s", exc)
    request_warm(
        rc,
        key,
        "hipertensi_registry",
        {"puskesmas_id": str(puskesmas_id), "year": year},
    )


# ── Dashboard charts (Usulan Grafik Dashboard — 8 charts) ──────────────────
# A rolling CROSS-YEAR aggregate (Feb-2025 → current month) over the same
# CKG-matched registry the Kertas Kerja shows, rolled up into the 8 client
# charts (cascade / tertatalaksana time series / target-tercapai / target-tidak-
# tercapai / tidak-berkunjung / proporsi 2025→2026 / kohort 2 tahun / hipertensi
# 2026). One payload per puskesmas;
# the window is rolling so the cache key is year-less and warmed daily by the 5am
# cron. See ``app.services.hipertensi_charts_scan``.
_CHARTS_CACHE_TTL_SECONDS = 30 * 60 * 60


def _charts_cache_key(puskesmas_id: uuid.UUID) -> str:
    return f"hipertensi_charts:{puskesmas_id}"


def _gap_cache_key(puskesmas_id: uuid.UUID) -> str:
    """Gap Tatalaksana list — the per-patient drill-down behind the gap in the
    "Pasien Hipertensi Tertatalaksana" chart. Its OWN key on purpose: it is ~2k
    rows of patient identity, and GET /charts (the dashboard's hot path)
    json.loads its whole payload on every request."""
    return f"hipertensi_gap:{puskesmas_id}"


def _write_charts_payload(rc, puskesmas_id: uuid.UUID, payload: dict, ttl: int) -> None:
    """Split one scan payload across the two keys: the slim charts counts and
    the fat gap-patient list. Mutates ``payload`` (pops ``gap_patients``) so the
    caller can never accidentally serve the list from the charts endpoint."""
    gap = payload.pop("gap_patients", [])
    for key, value in (
        (_charts_cache_key(puskesmas_id), payload),
        (_gap_cache_key(puskesmas_id), {"patients": gap, "computed_at": payload["computed_at"]}),
    ):
        try:
            rc.set(key, json.dumps(value), ex=ttl)
        except Exception as exc:
            log.warning("redis set failed for %s: %s", key, exc)


def warm_hipertensi_charts(db: Session, rc, puskesmas_id: uuid.UUID, ttl: int) -> dict:
    """Compute the charts payload and write it to Redis. Used by the on-miss
    endpoint path (the nightly cron uses ``warm_hipertensi_bundle`` instead).
    Also fills the Gap Tatalaksana key from the same pass."""
    cache_key = _charts_cache_key(puskesmas_id)
    payload = scan_hipertensi_charts(
        db, puskesmas_id, progress=make_progress_writer(rc, cache_key)
    )
    _write_charts_payload(rc, puskesmas_id, payload, ttl)
    return payload


def warm_hipertensi_bundle(
    db: Session, rc, puskesmas_id: uuid.UUID, ttl: int, years: tuple[int, ...]
) -> dict:
    """Nightly-cron warmer: ONE EPUS+ASIK decrypt pass → the Registri Hipertensi
    cache for EVERY year in ``years`` PLUS the dashboard-charts cache, so warming
    all of them costs a single decryption of the shared blobs (see
    ``hipertensi_charts_scan.scan_hipertensi_bundle``)."""
    bundle = scan_hipertensi_bundle(db, puskesmas_id, list(years))
    for y in years:
        key = _registry_cache_key(puskesmas_id, y)
        try:
            rc.set(key, json.dumps(bundle["registry"][y]), ex=ttl)
        except Exception as exc:
            log.warning("redis set failed for %s: %s", key, exc)
    _write_charts_payload(rc, puskesmas_id, bundle["charts"], ttl)
    return bundle


@router.get("/hipertensi-reports/charts", response_model=HipertensiChartsOut)
def hipertensi_charts(
    puskesmas_id: uuid.UUID = Query(...),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_dashboard_principal),
) -> HipertensiChartsOut:
    """The 8-chart dashboard payload for one puskesmas (rolling cross-year
    window). No ``year`` param — the window is always Feb-2025 → current month.
    Cached 30h keyed by puskesmas; a cold cache enqueues a warm and returns
    ``computing=True`` so the caller polls back. Use DELETE .../charts/cache to
    force a rebuild."""
    _authorize(principal, puskesmas_id)
    if not db.scalar(select(Puskesmas.id).where(Puskesmas.id == puskesmas_id)):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Puskesmas not found")

    cache_key = _charts_cache_key(puskesmas_id)
    rc = redis_client()
    cached: str | None = None
    try:
        cached = rc.get(cache_key)
    except Exception as exc:
        log.warning("redis get failed for %s: %s", cache_key, exc)

    payload: dict | None = None
    if cached:
        try:
            payload = json.loads(cached)
        except Exception:
            payload = None
    if payload is None:
        request_warm(
            rc, cache_key, "hipertensi_charts", {"puskesmas_id": str(puskesmas_id)}
        )
        return HipertensiChartsOut(
            cache_hit=False,
            computed_at=None,
            computing=True,
            progress=read_progress(rc, cache_key),
        )

    return HipertensiChartsOut(
        current_month=payload.get("current_month"),
        monthly=payload.get("monthly") or [],
        cascade=payload.get("cascade") or {},
        proporsi=payload.get("proporsi") or {},
        kohort_2tahun=payload.get("kohort_2tahun") or {},
        hipertensi_2026=payload.get("hipertensi_2026") or {},
        cache_hit=True,
        computed_at=datetime.fromisoformat(payload["computed_at"]),
        computing=False,
    )


@router.delete(
    "/hipertensi-reports/charts/cache", status_code=status.HTTP_204_NO_CONTENT
)
def clear_hipertensi_charts_cache(
    puskesmas_id: uuid.UUID = Query(...),
    principal: Principal = Depends(get_dashboard_principal),
) -> None:
    _authorize(principal, puskesmas_id)
    key = _charts_cache_key(puskesmas_id)
    rc = redis_client()
    try:
        # Both keys come from the same scan — drop them together, or the Gap
        # Tatalaksana page would keep serving rows from the previous pass.
        rc.delete(key, _gap_cache_key(puskesmas_id))
    except Exception as exc:
        log.warning("redis delete failed: %s", exc)
    request_warm(rc, key, "hipertensi_charts", {"puskesmas_id": str(puskesmas_id)})


# ── Gap Tatalaksana (drill-down behind the Tertatalaksana chart) ───────────
def _gap_filtered(payload: dict, year: int | None, q: str | None) -> list[dict[str, Any]]:
    """Apply the page's two filters to the cached gap list. ``year`` is the year
    the patient ENTERED the registry (``registration_ym``), not a reporting year
    — a patient registered in 2025 and still untreated stays under 2025."""
    patients: list[dict[str, Any]] = payload.get("patients") or []
    if year is not None:
        prefix = f"{year:04d}-"
        patients = [p for p in patients if (p.get("registration_ym") or "").startswith(prefix)]
    if q:
        needle = q.strip().casefold()
        if needle:
            patients = [
                p
                for p in patients
                if needle in (p.get("nama") or "").casefold()
                or needle in p["nik"].casefold()
            ]
    return patients


def _load_gap_payload(rc, puskesmas_id: uuid.UUID) -> dict | None:
    key = _gap_cache_key(puskesmas_id)
    try:
        cached = rc.get(key)
    except Exception as exc:
        log.warning("redis get failed for %s: %s", key, exc)
        return None
    if not cached:
        return None
    try:
        return json.loads(cached)
    except Exception:
        return None


@router.get("/hipertensi-reports/charts/gap", response_model=HipertensiGapOut)
def hipertensi_gap_tatalaksana(
    puskesmas_id: uuid.UUID = Query(...),
    year: int | None = Query(None, ge=2000, le=2100),
    q: str | None = Query(None, max_length=64),
    params: PageParams = Depends(page_params),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_dashboard_principal),
) -> HipertensiGapOut:
    """Registry members who have NEVER been prescribed an antihypertensive —
    the patients in the gap between the two lines of the "Pasien Hipertensi
    Tertatalaksana" chart, with the contact details a puskesmas needs to follow
    them up. ``total`` (unfiltered) equals ``registered_cumulative -
    treated_cumulative`` at the chart's last month.

    Filled by the SAME warm as /charts, so the warming flag and progress are
    read off the charts key — a cold cache must not enqueue a second scan."""
    _authorize(principal, puskesmas_id)
    pk_name = db.scalar(select(Puskesmas.name).where(Puskesmas.id == puskesmas_id))
    if pk_name is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Puskesmas not found")

    rc = redis_client()
    payload = _load_gap_payload(rc, puskesmas_id)
    if payload is None:
        charts_key = _charts_cache_key(puskesmas_id)
        request_warm(
            rc, charts_key, "hipertensi_charts", {"puskesmas_id": str(puskesmas_id)}
        )
        return HipertensiGapOut(
            page=params.page,
            size=params.size,
            cache_hit=False,
            computed_at=None,
            computing=True,
            progress=read_progress(rc, charts_key),
        )

    patients = _gap_filtered(payload, year, q)
    total = len(patients)
    pages = (total + params.size - 1) // params.size if total else 0
    start = (params.page - 1) * params.size
    items = [
        HipertensiGapRow(puskesmas_name=pk_name, **p)
        for p in patients[start : start + params.size]
    ]
    return HipertensiGapOut(
        items=items,
        total=total,
        page=params.page,
        size=params.size,
        pages=pages,
        cache_hit=True,
        computed_at=datetime.fromisoformat(payload["computed_at"]),
        computing=False,
    )


@router.get("/hipertensi-reports/charts/gap/export")
def export_hipertensi_gap_tatalaksana(
    puskesmas_id: uuid.UUID = Query(...),
    year: int | None = Query(None, ge=2000, le=2100),
    q: str | None = Query(None, max_length=64),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_dashboard_principal),
) -> StreamingResponse:
    """Download the Gap Tatalaksana list as an .xlsx. Honours the same year/
    search filters as the table (so the file matches what is on screen) but
    emits every matching row, not just the current page. A cold cache computes
    inline — the caller already saw the table, so this is a rare path."""
    _authorize(principal, puskesmas_id)
    pk_name = db.scalar(select(Puskesmas.name).where(Puskesmas.id == puskesmas_id))
    if pk_name is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Puskesmas not found")

    rc = redis_client()
    payload = _load_gap_payload(rc, puskesmas_id)
    if payload is None:
        warm_hipertensi_charts(db, rc, puskesmas_id, _CHARTS_CACHE_TTL_SECONDS)
        payload = _load_gap_payload(rc, puskesmas_id) or {"patients": []}

    patients = _gap_filtered(payload, year, q)
    content = build_hipertensi_gap_workbook(pk_name, year, patients)
    filename = _export_filename("Gap Tatalaksana Hipertensi", pk_name, year or "Semua Tahun")
    return StreamingResponse(
        iter([content]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
