import json
import logging
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import String, and_, cast, case, distinct, func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_admin_id, get_db
from app.api.routes.gdp_report import _extract_lab_gdp, _extract_ptm_gdp
from app.config import settings
from app.core.rate_limit import redis_client
from app.core.report_warm import request_warm
from app.core.security import decrypt_json
from app.models.patient import MatchStatus, Patient
from app.schemas.report import DelayBucket, GdpSourceQualityOut, VisitSummaryOut

log = logging.getLogger(__name__)
router = APIRouter(tags=["report"])

_GDP_QUALITY_TTL_SECONDS = 86400
_GDP_QUALITY_KEY_ALL = "reports:gdp_source_quality:all"


def _gdp_quality_cache_key(puskesmas_id: uuid.UUID | None) -> str:
    if puskesmas_id is None:
        return _GDP_QUALITY_KEY_ALL
    return f"reports:gdp_source_quality:puskesmas:{puskesmas_id}"


@router.get("/reports/visit-summary", response_model=VisitSummaryOut)
def get_visit_summary(
    puskesmas_id: uuid.UUID | None = None,
    db: Session = Depends(get_db),
    _: uuid.UUID = Depends(get_current_admin_id),
) -> VisitSummaryOut:
    # A "visit" = match_group_id for matched twins (collapses the two physical
    # rows scraped on different filter_dates), else the row id. Counting
    # distinct visit_key per status undoes the backfill doubling of `matched`.
    visit_key = case(
        (
            and_(Patient.match_status == MatchStatus.MATCHED, Patient.match_group_id.is_not(None)),
            cast(Patient.match_group_id, String),
        ),
        else_=cast(Patient.id, String),
    )

    def visits(*statuses: MatchStatus):
        return func.count(distinct(case((Patient.match_status.in_(statuses), visit_key))))

    # Soft-delete filter (deleted_at IS NULL) is auto-injected on this SELECT.
    stmt = select(
        visits(MatchStatus.ASIK_ONLY, MatchStatus.MATCHED).label("data_on_asik"),
        visits(MatchStatus.EPUS_ONLY, MatchStatus.MATCHED).label("data_on_epus"),
        visits(MatchStatus.MATCHED).label("matched"),
        func.count(distinct(case((Patient.epus_tandai_ckg.is_(True), visit_key)))).label("tandai_ckg"),
    )
    if puskesmas_id is not None:
        stmt = stmt.where(Patient.puskesmas_id == puskesmas_id)

    row = db.execute(stmt).one()

    # Delayed-input distribution: for each cross-date CKG visit (match_group_id
    # set, EPUS side marked CKG), the gap in days between its two physical rows
    # (different filter_dates). Capped at the live match window — the backfill
    # may have linked rows farther apart, but the feature intentionally only
    # reports delays within MATCH_WINDOW_DAYS. Soft-delete auto-filter applies.
    window = settings.MATCH_WINDOW_DAYS
    gap = (func.max(Patient.filter_date) - func.min(Patient.filter_date)).label("gap")
    grp = (
        select(gap)
        .where(Patient.match_group_id.is_not(None))
        .group_by(Patient.match_group_id)
        .having(func.bool_or(Patient.epus_tandai_ckg).is_(True))
    )
    if puskesmas_id is not None:
        grp = grp.where(Patient.puskesmas_id == puskesmas_id)
    grp = grp.subquery()
    dist_rows = db.execute(
        select(grp.c.gap, func.count())
        .where(grp.c.gap.between(1, window))
        .group_by(grp.c.gap)
    ).all()

    by_gap = {int(g): int(c) for g, c in dist_rows}
    delayed_ckg = sum(by_gap.values())
    distribution = [
        DelayBucket(
            days=d,
            count=by_gap.get(d, 0),
            pct=round(by_gap.get(d, 0) / delayed_ckg * 100.0, 1) if delayed_ckg else 0.0,
        )
        for d in range(1, window + 1)
    ]
    pct = (delayed_ckg / row.tandai_ckg * 100.0) if row.tandai_ckg else 0.0
    return VisitSummaryOut(
        data_on_asik=row.data_on_asik,
        data_on_epus=row.data_on_epus,
        matched=row.matched,
        tandai_ckg=row.tandai_ckg,
        delayed_ckg=delayed_ckg,
        delayed_ckg_pct=round(pct, 1),
        delay_distribution=distribution,
    )


def _compute_gdp_source_quality(db: Session, puskesmas_id: uuid.UUID | None) -> dict:
    """Per distinct person (puskesmas_id, nik) among CKG visits: does a
    Laboratorium GDP exist anywhere in their visits, and/or a PTM GDP? Presence
    only — value comparison is moot because lab + PTM almost never co-occur, so
    the report's lab-first/PTM-fallback logic just reduces to which source the
    person has at all. Soft-delete auto-filter applies to the SELECT."""
    stmt = (
        select(Patient.puskesmas_id, Patient.nik, Patient.scraped_epus_data)
        .where(
            Patient.epus_tandai_ckg.is_(True),
            Patient.scraped_epus_data.is_not(None),
        )
        .execution_options(yield_per=200, stream_results=True)
    )
    if puskesmas_id is not None:
        stmt = stmt.where(Patient.puskesmas_id == puskesmas_id)

    has_lab: set[tuple[str, str]] = set()
    has_ptm: set[tuple[str, str]] = set()
    for pid, nik, blob in db.execute(stmt):
        try:
            epus = decrypt_json(blob)
        except Exception:
            continue
        key = (str(pid), nik)
        if _extract_lab_gdp(epus) is not None:
            has_lab.add(key)
        if _extract_ptm_gdp(epus) is not None:
            has_ptm.add(key)

    lab_backed = len(has_lab)
    ptm_fallback = len(has_ptm - has_lab)
    people_with_gdp = len(has_lab | has_ptm)
    pct = (ptm_fallback / people_with_gdp * 100.0) if people_with_gdp else 0.0
    return {
        "people_with_gdp": people_with_gdp,
        "lab_backed": lab_backed,
        "ptm_fallback": ptm_fallback,
        "ptm_fallback_pct": round(pct, 1),
        "computed_at": datetime.now(UTC).isoformat(),
    }


def warm_gdp_source_quality(db: Session, rc, puskesmas_id: uuid.UUID | None, ttl: int) -> dict:
    """Compute the GD Puasa source-quality summary and write it to Redis.
    Shared by the on-miss endpoint path and the nightly cron.warm_reports."""
    key = _gdp_quality_cache_key(puskesmas_id)
    payload = _compute_gdp_source_quality(db, puskesmas_id)
    try:
        rc.set(key, json.dumps(payload), ex=ttl)
    except Exception as exc:
        log.warning("redis set failed for %s: %s", key, exc)
    return payload


@router.get("/reports/gdp-source-quality", response_model=GdpSourceQualityOut)
def get_gdp_source_quality(
    puskesmas_id: uuid.UUID | None = Query(default=None),
    db: Session = Depends(get_db),
    _: uuid.UUID = Depends(get_current_admin_id),
) -> GdpSourceQualityOut:
    key = _gdp_quality_cache_key(puskesmas_id)
    rc = redis_client()
    cached: str | None = None
    try:
        cached = rc.get(key)
    except Exception as exc:
        log.warning("redis get failed for %s: %s", key, exc)

    payload = None
    cache_hit = False
    if cached:
        try:
            payload = json.loads(cached)
            cache_hit = True
        except Exception:
            payload = None

    if payload is None:
        # Decrypt scan — recompute in the background, return a `computing`
        # placeholder so the request never blocks (no timeout).
        request_warm(rc, key, "gdp_source_quality", {"puskesmas_id": str(puskesmas_id) if puskesmas_id else None})
        return GdpSourceQualityOut(
            puskesmas_id=puskesmas_id,
            people_with_gdp=0,
            lab_backed=0,
            ptm_fallback=0,
            ptm_fallback_pct=0.0,
            computed_at=None,
            cache_hit=False,
            computing=True,
        )

    return GdpSourceQualityOut(
        puskesmas_id=puskesmas_id,
        people_with_gdp=payload["people_with_gdp"],
        lab_backed=payload["lab_backed"],
        ptm_fallback=payload["ptm_fallback"],
        ptm_fallback_pct=payload["ptm_fallback_pct"],
        computed_at=datetime.fromisoformat(payload["computed_at"]),
        cache_hit=cache_hit,
        computing=False,
    )


@router.delete("/reports/gdp-source-quality/cache", status_code=status.HTTP_204_NO_CONTENT)
def clear_gdp_source_quality_cache(
    puskesmas_id: uuid.UUID | None = Query(default=None),
    _: uuid.UUID = Depends(get_current_admin_id),
) -> None:
    """Drop the cached GD Puasa source-quality summary, then kick off a
    background recompute so it's ready by the time the client polls back."""
    key = _gdp_quality_cache_key(puskesmas_id)
    rc = redis_client()
    try:
        rc.delete(key)
    except Exception as exc:
        log.warning("redis delete failed for %s: %s", key, exc)
    request_warm(rc, key, "gdp_source_quality", {"puskesmas_id": str(puskesmas_id) if puskesmas_id else None})
