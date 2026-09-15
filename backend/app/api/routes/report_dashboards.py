"""Cross-puskesmas dashboard rollups shared by the GD Puasa and Hipertensi tabs.

The 'total pasien per puskesmas' card needs one number per puskesmas (Hipertensi:
the Registri Hipertensi CKG patient count; GD Puasa: the qualified-NIK count).
Reading it from each puskesmas's warm cache in a single Redis round-trip replaces
the N per-puskesmas terkendali requests the tab used to fan out.
"""

import json
import logging
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import Principal, get_dashboard_principal, get_db
from app.api.routes.gdp_report import _dashboard_cache_key as _gdp_dash_key
from app.api.routes.hipertensi_report import _registry_cache_key as _ht_registry_key
from app.core.rate_limit import redis_client
from app.core.report_warm import request_warm
from app.models.puskesmas import Puskesmas
from app.schemas.report_dashboard_totals import DashboardTotalsOut, PuskesmasTotalOut
from app.services.hipertensi_registry_scan import count_interpretasi_bands

log = logging.getLogger(__name__)

router = APIRouter(tags=["report-dashboards"])


def _count_gdp_niks(payload: dict, ckg_only: bool) -> tuple[int, int | None, int | None]:
    """GD Puasa total = qualified NIKs in the dashboard cache (``ckg_only`` keeps
    only those flagged sudah CKG). No interpretasi bands apply → (total, None, None)."""
    niks = payload.get("niks") or []
    if ckg_only:
        niks = [n for n in niks if n.get("tandai_ckg")]
    return len(niks), None, None


def _count_registry_patients(
    payload: dict, ckg_only: bool
) -> tuple[int, int | None, int | None]:
    """Hipertensi total = patients in the Registri Hipertensi CKG cache, plus the
    interpretasi-band split (Hipertensi / Pre-Hipertensi). The registry is
    inherently CKG (matched ePus+ASIK) and syarat-filtered, so this is the SAME
    number as the registry table/export/summary card; ``ckg_only`` is a no-op."""
    patients = payload.get("patients") or []
    hipertensi, pre_hipertensi = count_interpretasi_bands(patients)
    return len(patients), hipertensi, pre_hipertensi


# disease -> (cache-key builder, warm report_type understood by report.warm_one,
# payload->total counter). Hipertensi reads the registry cache so the top card
# matches the Registri Hipertensi CKG total; GD Puasa reads its dashboard cache.
_REPORT: dict[str, tuple] = {
    "gdp": (_gdp_dash_key, "gdp_dashboard", _count_gdp_niks),
    "hipertensi": (_ht_registry_key, "hipertensi_registry", _count_registry_patients),
}


@router.get("/report-dashboards/totals", response_model=DashboardTotalsOut)
def report_dashboard_totals(
    disease: Literal["gdp", "hipertensi"] = Query(...),
    year: int = Query(..., ge=2000, le=2100),
    ckg_only: bool = Query(False),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_dashboard_principal),
) -> DashboardTotalsOut:
    """Per-puskesmas total for one report, from the warm caches in a SINGLE
    ``mget``. Hipertensi counts the Registri Hipertensi CKG patients (matched
    ePus+ASIK + syarat hipertensi) — identical to the registry table/export — so
    the dashboard's top card matches its Status-per-Puskesmas card. GD Puasa
    counts qualified NIKs (``ckg_only`` → only those flagged sudah CKG). A cold
    puskesmas reports ``total=None``, enqueues an NX-deduped warm, and flips
    ``computing`` so the caller polls back — the 5am cron normally keeps every
    entry warm, so this only fires for a new / failed / non-current-year cache."""
    key_fn, report_type, count_total = _REPORT[disease]
    # Column-select (not the ORM entity) → no heavy puskesmas blobs; soft-delete
    # auto-filter excludes deleted puskesmas.
    stmt = select(Puskesmas.id, Puskesmas.name).order_by(Puskesmas.name)
    # Tenant scope: this is a cross-puskesmas rollup for admins (internal + prod).
    # A puskesmas USER must only ever see their own clinic's total — otherwise a
    # user could read every other clinic's qualified-NIK counts by calling this
    # endpoint directly (it takes no puskesmas_id to authorize, so scope here).
    if principal.typ == "user":
        stmt = stmt.where(Puskesmas.id == principal.puskesmas_id)
    rows = db.execute(stmt).all()

    rc = redis_client()
    keys = [key_fn(r.id, year) for r in rows]
    raws: list[str | None] = []
    if keys:
        try:
            raws = rc.mget(keys)
        except Exception as exc:
            log.warning("dashboard totals mget failed: %s", exc)
            raws = [None] * len(keys)

    items: list[PuskesmasTotalOut] = []
    grand_total = 0
    computing = False
    for r, raw in zip(rows, raws):
        total: int | None = None
        hipertensi: int | None = None
        pre_hipertensi: int | None = None
        if raw:
            try:
                total, hipertensi, pre_hipertensi = count_total(json.loads(raw), ckg_only)
            except Exception:
                total = None
        if total is None:
            computing = True
            request_warm(
                rc, key_fn(r.id, year), report_type,
                {"puskesmas_id": str(r.id), "year": year},
            )
        else:
            grand_total += total
        items.append(
            PuskesmasTotalOut(
                puskesmas_id=r.id,
                name=r.name,
                total=total,
                total_hipertensi=hipertensi,
                total_pre_hipertensi=pre_hipertensi,
            )
        )
    return DashboardTotalsOut(items=items, grand_total=grand_total, computing=computing)
