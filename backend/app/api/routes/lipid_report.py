"""Registri Dislipidemia — per-NIK registry routes.

Sibling of ``dm_report.py`` and the Registri Hipertensi block in
``hipertensi_report.py``, over the same scraped EPUS/ASIK blobs but surfacing the
lipid panel (Kolesterol Total / LDL / HDL / Trigliserida). There is no separate
scrape job: this is a new view + Redis cache over data the existing scrape
already populates.

``_authorize`` is reused from ``gdp_report`` so the puskesmas-scope check stays
byte-for-byte identical across reports. ``_export_filename`` is NOT reusable —
``gdp_report``'s hardcodes the "GD Puasa" prefix — so this module carries its own
copy of the same sanitizer, as ``dm_report`` and ``hipertensi_report`` do.

See ``app.services.lipid_registry_scan`` for the scan, thresholds and syarat —
including the three documented divergences from the DM registry (measurement-only
syarat, riwayat does not pin the label, quarterly control months).
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
from app.schemas.lipid_registry import (
    LipidRegistryDashboardOut,
    LipidRegistryRow,
    LipidRegistrySummaryOut,
)
from app.services.lipid_registry_export import build_lipid_registry_workbook
from app.services.lipid_registry_scan import count_analyte_bands, scan_lipid_registry

log = logging.getLogger(__name__)

router = APIRouter(tags=["lipid-report"])

# Same caching contract as the Hipertensi/DM registries (30h TTL > 24h nightly
# warm).
_REGISTRY_CACHE_TTL_SECONDS = 30 * 60 * 60

# The report_type string ``request_warm`` dispatches on — must match the branch
# in ``app.tasks.cron.warm_one_report``.
_WARM_REPORT_TYPE = "lipid_registry"


def _registry_cache_key(puskesmas_id: uuid.UUID, year: int) -> str:
    return f"lipid_registry:dashboard:{puskesmas_id}:{year}"


def warm_lipid_registry(
    db: Session, rc, puskesmas_id: uuid.UUID, year: int, ttl: int
) -> dict:
    """Compute the registry payload and write it to Redis. Shared by the on-miss
    endpoint path and the nightly warm cron (cron.warm_reports)."""
    cache_key = _registry_cache_key(puskesmas_id, year)
    payload = scan_lipid_registry(
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
        payload = warm_lipid_registry(
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


def _registry_row(p: dict, pk_name: str, year: int) -> LipidRegistryRow:
    return LipidRegistryRow(puskesmas_name=pk_name, tahun_pelaporan=year, **p)


@router.get("/lipid-reports/registry", response_model=LipidRegistryDashboardOut)
def lipid_registry_dashboard(
    puskesmas_id: uuid.UUID = Query(...),
    year: int = Query(..., ge=2000, le=2100),
    q: str | None = Query(None, max_length=64),
    params: PageParams = Depends(page_params),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_dashboard_principal),
) -> LipidRegistryDashboardOut:
    """Per-NIK Dislipidemia registry. One patient per row; the full baseline +
    follow-up detail rides along so the UI can expand it and the export emits the
    wide multi-row sheet. Cached 30h keyed by (puskesmas, year);
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
        return LipidRegistryDashboardOut(
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
    # Per-analyte breakdown of the (search-filtered) rows for the header.
    bands = count_analyte_bands(patients)
    pages = (total + params.size - 1) // params.size if total else 0
    start = (params.page - 1) * params.size
    page_slice = patients[start : start + params.size]

    return LipidRegistryDashboardOut(
        items=[_registry_row(p, pk_name, year) for p in page_slice],
        total=total,
        **bands,
        page=params.page,
        size=params.size,
        pages=pages,
        cache_hit=True,
        computed_at=datetime.fromisoformat(payload["computed_at"]),
        computing=False,
    )


@router.get("/lipid-reports/registry/summary", response_model=LipidRegistrySummaryOut)
def lipid_registry_summary(
    puskesmas_id: uuid.UUID = Query(...),
    year: int = Query(..., ge=2000, le=2100),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_dashboard_principal),
) -> LipidRegistrySummaryOut:
    """Aggregate counts over the Dislipidemia registry (one puskesmas, year):
    total pasien (CKG), the four per-analyte counts, pasien dengan riwayat HT /
    DM (Ya), dan pasien dalam pengobatan (≥1 obat diresepkan pada baseline).
    Reuses the registry Redis cache; a cold cache enqueues a warm and returns
    ``computing=True`` so the caller polls back."""
    _authorize(principal, puskesmas_id)
    if not db.scalar(select(Puskesmas.id).where(Puskesmas.id == puskesmas_id)):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Puskesmas not found")

    cache_key = _registry_cache_key(puskesmas_id, year)
    rc = redis_client()
    payload = _read_cached(rc, cache_key)
    if payload is None:
        _request_registry_warm(rc, puskesmas_id, year)
        return LipidRegistrySummaryOut(
            total=0,
            riwayat_ht_ya=0,
            riwayat_dm_ya=0,
            dalam_pengobatan=0,
            cache_hit=False,
            computed_at=None,
            computing=True,
        )

    patients: list[dict[str, Any]] = payload.get("patients") or []
    return LipidRegistrySummaryOut(
        total=len(patients),
        **count_analyte_bands(patients),
        riwayat_ht_ya=sum(1 for p in patients if p.get("riwayat_ht") == "Ya"),
        riwayat_dm_ya=sum(1 for p in patients if p.get("riwayat_dm") == "Ya"),
        dalam_pengobatan=sum(1 for p in patients if p.get("obat")),
        cache_hit=True,
        computed_at=datetime.fromisoformat(payload["computed_at"]),
        computing=False,
    )


def _export_filename(pk_name: str, year: int) -> str:
    """ASCII-safe attachment filename. Non-ASCII chars (rare in puskesmas names)
    are dropped so the Content-Disposition header stays valid. Same rule as the
    gdp/hipertensi/dm report modules, which each carry their own copy."""
    safe = "".join(c if (c.isalnum() or c in " -_") else "_" for c in pk_name).strip()
    return f"Registri Dislipidemia - {safe or 'Puskesmas'} - {year}.xlsx"


@router.get("/lipid-reports/registry/export")
def export_lipid_registry(
    puskesmas_id: uuid.UUID = Query(...),
    year: int = Query(..., ge=2000, le=2100),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_dashboard_principal),
) -> StreamingResponse:
    """Download the Registri Dislipidemia as an .xlsx for (puskesmas, year).
    Emits ALL patients (no pagination/search). Unlike the list endpoint this
    warms SYNCHRONOUSLY on a cold cache — a download cannot return a
    ``computing`` placeholder. See ``lipid_registry_export``."""
    _authorize(principal, puskesmas_id)
    pk_name = db.scalar(select(Puskesmas.name).where(Puskesmas.id == puskesmas_id))
    if pk_name is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Puskesmas not found")

    rc = redis_client()
    payload = _load_registry_payload_or_warm(db, rc, puskesmas_id, year)
    content = build_lipid_registry_workbook(
        pk_name, year, payload.get("patients") or []
    )
    filename = _export_filename(pk_name, year)
    return StreamingResponse(
        iter([content]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.delete(
    "/lipid-reports/registry/cache", status_code=status.HTTP_204_NO_CONTENT
)
def clear_lipid_registry_cache(
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
