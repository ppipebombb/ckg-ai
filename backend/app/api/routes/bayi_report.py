"""Registri Bayi Kuning — per-bayi registry routes (Ikterus + Ikterus Berat).

Sibling of ``obesitas_report.py`` etc., but EPUS-only and newborn-scoped. One
scan payload per (puskesmas, year) — ``{"bayi": [...], "computed_at": ...}`` —
feeds BOTH sheets; the ``sheet`` query param selects the band via the scan's
``qualifies_*`` flags. There is no separate scrape job: this is a view + Redis
cache over data the existing scrape already populates.

``_authorize`` is reused from ``gdp_report``; ``_export_filename`` is this
module's own copy of the shared sanitizer (the siblings each carry theirs).

See ``app.services.bayi_registry_scan`` for the ikterus derivation, provenance
tags, and why the registry is NOT CKG-filtered.
"""

import json
import logging
import uuid
from datetime import datetime
from typing import Any, Literal

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
from app.schemas.bayi_registry import (
    BayiRegistryDashboardOut,
    BayiRegistryRow,
    BayiRegistrySummaryOut,
)
from app.services.bayi_registry_export import build_bayi_registry_workbook
from app.services.bayi_registry_scan import count_sheet_bands, scan_bayi_registry

log = logging.getLogger(__name__)

router = APIRouter(tags=["bayi-report"])

# Same caching contract as the HT/DM/Obesitas registries (30h TTL > 24h warm).
_REGISTRY_CACHE_TTL_SECONDS = 30 * 60 * 60
_WARM_REPORT_TYPE = "bayi_registry"

# ``qualifies_*`` flag on each scan bayi that admits it to a given sheet.
_SHEET_FLAG = {"ikterus": "qualifies_ikterus", "ikterus_berat": "qualifies_ikterus_berat"}


def _registry_cache_key(puskesmas_id: uuid.UUID, year: int) -> str:
    return f"bayi_registry:dashboard:{puskesmas_id}:{year}"


def warm_bayi_registry(db: Session, rc, puskesmas_id: uuid.UUID, year: int, ttl: int) -> dict:
    """Compute the registry payload and write it to Redis. Shared by the on-miss
    endpoint path and the nightly warm cron (cron.warm_reports)."""
    cache_key = _registry_cache_key(puskesmas_id, year)
    payload = scan_bayi_registry(
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
    """Cached payload, computing it SYNCHRONOUSLY on a miss — for export."""
    cache_key = _registry_cache_key(puskesmas_id, year)
    payload: dict | None = _read_cached(rc, cache_key)
    if payload is None:
        payload = warm_bayi_registry(db, rc, puskesmas_id, year, _REGISTRY_CACHE_TTL_SECONDS)
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


def _sheet_bayi(payload: dict, sheet: str) -> list[dict[str, Any]]:
    """The bayi qualifying for ``sheet`` (band-filtered on the qualifies flag)."""
    flag = _SHEET_FLAG[sheet]
    return [b for b in (payload.get("bayi") or []) if b.get(flag)]


def _bands(payload: dict) -> dict[str, int]:
    pjbk, ikt, berat = count_sheet_bands(payload.get("bayi") or [])
    return {"pjbk": pjbk, "ikterus": ikt, "ikterus_berat": berat}


def _registry_row(b: dict, pk_name: str, year: int) -> BayiRegistryRow:
    return BayiRegistryRow(puskesmas_name=pk_name, tahun_pelaporan=year, **b)


@router.get("/bayi-reports/registry", response_model=BayiRegistryDashboardOut)
def bayi_registry_dashboard(
    puskesmas_id: uuid.UUID = Query(...),
    year: int = Query(..., ge=2000, le=2100),
    sheet: Literal["ikterus", "ikterus_berat"] = Query("ikterus"),
    q: str | None = Query(None, max_length=64),
    params: PageParams = Depends(page_params),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_dashboard_principal),
) -> BayiRegistryDashboardOut:
    """Per-bayi Bayi Kuning registry for one ``sheet`` (Ikterus / Ikterus Berat).
    Cached 30h keyed by (puskesmas, year); the sheet filter, search and pagination
    apply in-memory over the one shared payload. DELETE .../registry/cache rebuilds.
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
        return BayiRegistryDashboardOut(
            items=[], total=0, page=params.page, size=params.size, pages=0,
            cache_hit=False, computed_at=None, computing=True,
            progress=read_progress(rc, cache_key),
        )

    bayi = _sheet_bayi(payload, sheet)
    if q:
        needle = q.strip().casefold()
        if needle:
            bayi = [
                b for b in bayi
                if needle in (b.get("nama") or "").casefold()
                or needle in (b.get("nik") or "").casefold()
            ]

    total = len(bayi)
    pages = (total + params.size - 1) // params.size if total else 0
    start = (params.page - 1) * params.size
    page_slice = bayi[start : start + params.size]

    return BayiRegistryDashboardOut(
        items=[_registry_row(b, pk_name, year) for b in page_slice],
        total=total,
        **_bands(payload),
        page=params.page,
        size=params.size,
        pages=pages,
        cache_hit=True,
        computed_at=datetime.fromisoformat(payload["computed_at"]),
        computing=False,
    )


@router.get("/bayi-reports/registry/summary", response_model=BayiRegistrySummaryOut)
def bayi_registry_summary(
    puskesmas_id: uuid.UUID = Query(...),
    year: int = Query(..., ge=2000, le=2100),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_dashboard_principal),
) -> BayiRegistrySummaryOut:
    """Aggregate band counts over the Bayi Kuning registry (one puskesmas, year).
    Reuses the registry cache; a cold cache enqueues a warm and returns
    ``computing=True`` so the caller polls back."""
    _authorize(principal, puskesmas_id)
    if not db.scalar(select(Puskesmas.id).where(Puskesmas.id == puskesmas_id)):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Puskesmas not found")

    cache_key = _registry_cache_key(puskesmas_id, year)
    rc = redis_client()
    payload = _read_cached(rc, cache_key)
    if payload is None:
        _request_registry_warm(rc, puskesmas_id, year)
        return BayiRegistrySummaryOut(
            cache_hit=False, computed_at=None, computing=True
        )

    return BayiRegistrySummaryOut(
        **_bands(payload),
        cache_hit=True,
        computed_at=datetime.fromisoformat(payload["computed_at"]),
        computing=False,
    )


def _export_filename(pk_name: str, year: int, sheet: str) -> str:
    """ASCII-safe attachment filename (same rule as the sibling report modules)."""
    safe = "".join(c if (c.isalnum() or c in " -_") else "_" for c in pk_name).strip()
    label = "Ikterus Berat" if sheet == "ikterus_berat" else "Ikterus"
    return f"Registri Bayi Kuning {label} - {safe or 'Puskesmas'} - {year}.xlsx"


@router.get("/bayi-reports/registry/export")
def export_bayi_registry(
    puskesmas_id: uuid.UUID = Query(...),
    year: int = Query(..., ge=2000, le=2100),
    sheet: Literal["ikterus", "ikterus_berat"] = Query("ikterus"),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_dashboard_principal),
) -> StreamingResponse:
    """Download one Bayi Kuning sheet as .xlsx for (puskesmas, year). Warms
    SYNCHRONOUSLY on a cold cache — a download cannot return ``computing``."""
    _authorize(principal, puskesmas_id)
    pk_name = db.scalar(select(Puskesmas.name).where(Puskesmas.id == puskesmas_id))
    if pk_name is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Puskesmas not found")

    rc = redis_client()
    payload = _load_registry_payload_or_warm(db, rc, puskesmas_id, year)
    content = build_bayi_registry_workbook(
        pk_name, year, _sheet_bayi(payload, sheet), sheet
    )
    filename = _export_filename(pk_name, year, sheet)
    return StreamingResponse(
        iter([content]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.delete("/bayi-reports/registry/cache", status_code=status.HTTP_204_NO_CONTENT)
def clear_bayi_registry_cache(
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
