"""Registri Diabetes Melitus — per-NIK registry routes.

Sibling of the Registri Hipertensi block in ``hipertensi_report.py``, over the
same scraped EPUS/ASIK blobs but surfacing the glucose panel (GDS/GDP/GD2PP/
HbA1C) instead of blood pressure. There is no separate scrape job: this is a new
view + Redis cache over data the existing scrape already populates.

Deliberately a SEPARATE module from the older ``gdp_report`` ("Kertas Kerja DM
Terkendali", currently hidden from the dashboard sidebar). The two coexist:
gdp_report is a per-month GD-Puasa grid, this is the dirjen per-NIK register.
Nothing in gdp_report is changed by this module.

``_authorize`` is reused from ``gdp_report`` so the puskesmas-scope check stays
byte-for-byte identical across reports. ``_export_filename`` is NOT reusable —
``gdp_report``'s hardcodes the "GD Puasa" prefix — so this module carries its own
copy of the same sanitizer, as ``hipertensi_report`` does.

See ``app.services.dm_registry_scan`` for the scan, thresholds and syarat.
"""

import json
import logging
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import Principal, get_db, get_dashboard_principal
from app.api.pagination import PageParams, page_params
from app.api.routes.gdp_report import _authorize
from app.core.rate_limit import redis_client
from app.core.report_warm import make_progress_writer, read_progress, request_warm
from app.models.puskesmas import Puskesmas
from app.schemas.dm_charts import DmChartsOut
from app.schemas.dm_registry import (
    DmRegistryDashboardOut,
    DmRegistryRow,
    DmRegistrySummaryOut,
)
from app.services.dm_charts_scan import scan_dm_charts
from app.services.dm_registry_export import build_dm_registry_workbook
from app.services.dm_registry_scan import count_interpretasi_bands, scan_dm_registry

log = logging.getLogger(__name__)

router = APIRouter(tags=["dm-report"])

# Same caching contract as the Hipertensi registry (30h TTL > 24h nightly warm).
_REGISTRY_CACHE_TTL_SECONDS = 30 * 60 * 60

# The report_type string ``request_warm`` dispatches on — must match the branch
# in ``app.tasks.cron.warm_one_report``.
_WARM_REPORT_TYPE = "dm_registry"


def _registry_cache_key(puskesmas_id: uuid.UUID, year: int) -> str:
    return f"dm_registry:dashboard:{puskesmas_id}:{year}"


def warm_dm_registry(
    db: Session, rc, puskesmas_id: uuid.UUID, year: int, ttl: int
) -> dict:
    """Compute the registry payload and write it to Redis. Shared by the on-miss
    endpoint path and the nightly warm cron (cron.warm_reports)."""
    cache_key = _registry_cache_key(puskesmas_id, year)
    payload = scan_dm_registry(
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
    """Cached payload, computing it SYNCHRONOUSLY on a miss. Used by the export
    route, which cannot return a ``computing`` placeholder."""
    cache_key = _registry_cache_key(puskesmas_id, year)
    payload: dict | None = None
    try:
        cached = rc.get(cache_key)
        if cached:
            payload = json.loads(cached)
    except Exception as exc:
        log.warning("redis get failed for %s: %s", cache_key, exc)
    if payload is None:
        payload = warm_dm_registry(
            db, rc, puskesmas_id, year, _REGISTRY_CACHE_TTL_SECONDS
        )
    return payload


def _request_registry_warm(rc, puskesmas_id: uuid.UUID, year: int) -> None:
    request_warm(
        rc,
        _registry_cache_key(puskesmas_id, year),
        _WARM_REPORT_TYPE,
        {"puskesmas_id": str(puskesmas_id), "year": year},
    )


def _read_cached(rc, cache_key: str) -> dict | None:
    try:
        cached = rc.get(cache_key)
    except Exception as exc:
        log.warning("redis get failed for %s: %s", cache_key, exc)
        return None
    if not cached:
        return None
    try:
        return json.loads(cached)
    except Exception:
        return None


def _registry_row(p: dict, pk_name: str, year: int) -> DmRegistryRow:
    return DmRegistryRow(puskesmas_name=pk_name, tahun_pelaporan=year, **p)


@router.get("/dm-reports/registry", response_model=DmRegistryDashboardOut)
def dm_registry_dashboard(
    puskesmas_id: uuid.UUID = Query(...),
    year: int = Query(..., ge=2000, le=2100),
    q: str | None = Query(None, max_length=64),
    params: PageParams = Depends(page_params),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_dashboard_principal),
) -> DmRegistryDashboardOut:
    """Per-NIK Diabetes Melitus registry. One patient per row; the full baseline
    + follow-up detail rides along so the UI can expand it and the export emits
    the wide multi-row sheet. Cached 30h keyed by (puskesmas, year);
    search/pagination apply in-memory. Use DELETE .../registry/cache to rebuild.
    """
    _authorize(principal, puskesmas_id)
    pk_name = db.scalar(select(Puskesmas.name).where(Puskesmas.id == puskesmas_id))
    if pk_name is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Puskesmas not found")

    cache_key = _registry_cache_key(puskesmas_id, year)
    rc = redis_client()
    payload = _read_cached(rc, cache_key)
    if payload is None:
        _request_registry_warm(rc, puskesmas_id, year)
        return DmRegistryDashboardOut(
            items=[],
            total=0,
            total_dm=0,
            total_prediabetes=0,
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
    total_dm, total_prediabetes = count_interpretasi_bands(patients)
    pages = (total + params.size - 1) // params.size if total else 0
    start = (params.page - 1) * params.size
    page_slice = patients[start : start + params.size]

    return DmRegistryDashboardOut(
        items=[_registry_row(p, pk_name, year) for p in page_slice],
        total=total,
        total_dm=total_dm,
        total_prediabetes=total_prediabetes,
        page=params.page,
        size=params.size,
        pages=pages,
        cache_hit=True,
        computed_at=datetime.fromisoformat(payload["computed_at"]),
        computing=False,
    )


@router.get("/dm-reports/registry/summary", response_model=DmRegistrySummaryOut)
def dm_registry_summary(
    puskesmas_id: uuid.UUID = Query(...),
    year: int = Query(..., ge=2000, le=2100),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_dashboard_principal),
) -> DmRegistrySummaryOut:
    """Aggregate counts over the DM registry (one puskesmas, year): total pasien
    (CKG) split into Diabetes Melitus / Prediabetes, pasien dengan riwayat DM
    (Ya), dan pasien dalam pengobatan (≥1 obat diresepkan pada baseline). Reuses
    the registry Redis cache; a cold cache enqueues a warm and returns
    ``computing=True`` so the caller polls back."""
    _authorize(principal, puskesmas_id)
    if not db.scalar(select(Puskesmas.id).where(Puskesmas.id == puskesmas_id)):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Puskesmas not found")

    cache_key = _registry_cache_key(puskesmas_id, year)
    rc = redis_client()
    payload = _read_cached(rc, cache_key)
    if payload is None:
        _request_registry_warm(rc, puskesmas_id, year)
        return DmRegistrySummaryOut(
            total=0,
            total_dm=0,
            total_prediabetes=0,
            riwayat_dm_ya=0,
            dalam_pengobatan=0,
            cache_hit=False,
            computed_at=None,
            computing=True,
        )

    patients: list[dict[str, Any]] = payload.get("patients") or []
    total_dm, total_prediabetes = count_interpretasi_bands(patients)
    return DmRegistrySummaryOut(
        total=len(patients),
        total_dm=total_dm,
        total_prediabetes=total_prediabetes,
        riwayat_dm_ya=sum(1 for p in patients if p.get("riwayat_dm") == "Ya"),
        dalam_pengobatan=sum(1 for p in patients if p.get("obat")),
        cache_hit=True,
        computed_at=datetime.fromisoformat(payload["computed_at"]),
        computing=False,
    )


def _export_filename(pk_name: str, year: int) -> str:
    """ASCII-safe attachment filename. Non-ASCII chars (rare in puskesmas names)
    are dropped so the Content-Disposition header stays valid. Same rule as the
    gdp/hipertensi report modules, which each carry their own copy."""
    safe = "".join(c if (c.isalnum() or c in " -_") else "_" for c in pk_name).strip()
    return f"Registri Diabetes Melitus - {safe or 'Puskesmas'} - {year}.xlsx"


@router.get("/dm-reports/registry/export")
def export_dm_registry(
    puskesmas_id: uuid.UUID = Query(...),
    year: int = Query(..., ge=2000, le=2100),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_dashboard_principal),
) -> StreamingResponse:
    """Download the Registri Diabetes Melitus as an .xlsx for (puskesmas, year).
    Emits ALL patients (no pagination/search). Unlike the list endpoint this
    warms SYNCHRONOUSLY on a cold cache — a download cannot return a
    ``computing`` placeholder. See ``dm_registry_export``."""
    _authorize(principal, puskesmas_id)
    pk_name = db.scalar(select(Puskesmas.name).where(Puskesmas.id == puskesmas_id))
    if pk_name is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Puskesmas not found")

    rc = redis_client()
    payload = _load_registry_payload_or_warm(db, rc, puskesmas_id, year)
    content = build_dm_registry_workbook(pk_name, year, payload.get("patients") or [])
    filename = _export_filename(pk_name, year)
    return StreamingResponse(
        iter([content]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.delete("/dm-reports/registry/cache", status_code=status.HTTP_204_NO_CONTENT)
def clear_dm_registry_cache(
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
    _request_registry_warm(rc, puskesmas_id, year)


# ── Dashboard charts (DM 2 tahun + DM 2026) ────────────────────────────────
# A rolling CROSS-YEAR aggregate (2025 → current month) over the same
# CKG-matched DM registry, rolled up into the 2 cohort charts the client's
# Dashboard Diabetes Melitus shows. One payload per puskesmas; the window is
# rolling so the cache key is year-less and warmed daily by the 5am cron. See
# ``app.services.dm_charts_scan``.
_CHARTS_CACHE_TTL_SECONDS = 30 * 60 * 60


def _charts_cache_key(puskesmas_id: uuid.UUID) -> str:
    return f"dm_charts:{puskesmas_id}"


def warm_dm_charts(db: Session, rc, puskesmas_id: uuid.UUID, ttl: int) -> dict:
    """Compute the DM charts payload and write it to Redis. Shared by the on-miss
    endpoint path and the nightly warm cron."""
    cache_key = _charts_cache_key(puskesmas_id)
    payload = scan_dm_charts(
        db, puskesmas_id, progress=make_progress_writer(rc, cache_key)
    )
    try:
        rc.set(cache_key, json.dumps(payload), ex=ttl)
    except Exception as exc:
        log.warning("redis set failed for %s: %s", cache_key, exc)
    return payload


@router.get("/dm-reports/charts", response_model=DmChartsOut)
def dm_charts(
    puskesmas_id: uuid.UUID = Query(...),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_dashboard_principal),
) -> DmChartsOut:
    """The 2-chart DM dashboard payload for one puskesmas (rolling cross-year
    window). No ``year`` param — the window is always 2025 → current month.
    Cached 30h keyed by puskesmas; a cold cache enqueues a warm and returns
    ``computing=True`` so the caller polls back. Use DELETE .../charts/cache to
    force a rebuild."""
    _authorize(principal, puskesmas_id)
    if not db.scalar(select(Puskesmas.id).where(Puskesmas.id == puskesmas_id)):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Puskesmas not found")

    cache_key = _charts_cache_key(puskesmas_id)
    rc = redis_client()
    payload = _read_cached(rc, cache_key)
    if payload is None:
        request_warm(rc, cache_key, "dm_charts", {"puskesmas_id": str(puskesmas_id)})
        return DmChartsOut(
            cache_hit=False,
            computed_at=None,
            computing=True,
            progress=read_progress(rc, cache_key),
        )

    return DmChartsOut(
        kohort_2tahun=payload.get("kohort_2tahun") or {},
        dm_2026=payload.get("dm_2026") or {},
        cache_hit=True,
        computed_at=datetime.fromisoformat(payload["computed_at"]),
        computing=False,
    )


@router.delete("/dm-reports/charts/cache", status_code=status.HTTP_204_NO_CONTENT)
def clear_dm_charts_cache(
    puskesmas_id: uuid.UUID = Query(...),
    principal: Principal = Depends(get_dashboard_principal),
) -> None:
    _authorize(principal, puskesmas_id)
    key = _charts_cache_key(puskesmas_id)
    rc = redis_client()
    try:
        rc.delete(key)
    except Exception as exc:
        log.warning("redis delete failed: %s", exc)
    request_warm(rc, key, "dm_charts", {"puskesmas_id": str(puskesmas_id)})
