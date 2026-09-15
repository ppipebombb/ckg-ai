"""GDP-report orchestrator.

Spawns one multi-date ASIK scrape, then one multi-date EPUS scrape over the
same date range. Each child is a regular ``scrape_jobs`` row so it reuses the
existing log/stream/cancel infrastructure.

The orchestrator does NOT touch Patient rows directly — the child workers
upsert as usual. The dashboard query (``/gdp-reports/dashboard``) restricts
itself to NIKs that have any ASIK data in the puskesmas date range.
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Iterable

import redis
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.celery_app import celery_app
from app.config import settings
from app.crud import gdp_report_job as gdp_crud
from app.crud import scrape_job as scrape_job_crud
from app.database import SessionLocal
from app.models.gdp_report_job import GdpReportJob, GdpReportPhase, GdpReportStatus
from app.models.patient import Patient
from app.models.scrape_job import ScrapeJob, ScrapeKind, ScrapeStatus

log = logging.getLogger(__name__)

# Polling cadence for child scrape_job status. Mirrors scrape.run cancel poll.
_POLL_SECONDS = 5
# Hard ceiling — defends against a wedged child that never reaches terminal.
_MAX_WAIT_PER_CHILD_HOURS = 48


def cancel_key(job_id: str) -> str:
    return f"gdp_report:job:{job_id}:cancel"


def _redis() -> "redis.Redis":
    return redis.from_url(settings.REDIS_URL, decode_responses=True)


def _is_cancelled(rc: "redis.Redis", job_id: str) -> bool:
    try:
        return rc.get(cancel_key(job_id)) == "1"
    except Exception:
        return False


def _date_range_iso(date_from: date, date_to: date) -> list[str]:
    out: list[str] = []
    cur = date_from
    while cur <= date_to:
        out.append(cur.isoformat())
        cur = cur + timedelta(days=1)
    return out


def _wait_child(
    db: Session,
    rc: "redis.Redis",
    parent_id: str,
    child_id: uuid.UUID,
) -> ScrapeStatus:
    """Block until the child reaches a terminal state. Returns its final status.

    Honors the parent cancel flag — when set, propagates a cancel to the child
    via the existing scrape cancel-flag, then waits for the child to ACK.
    """
    deadline = time.monotonic() + _MAX_WAIT_PER_CHILD_HOURS * 3600
    sent_cancel = False
    while True:
        if _is_cancelled(rc, parent_id) and not sent_cancel:
            try:
                rc.set(f"scrape:job:{child_id}:cancel", "1", ex=86400)
            except Exception:
                pass
            sent_cancel = True
        status = db.scalar(
            select(ScrapeJob.status).where(ScrapeJob.id == child_id)
        )
        if status in (ScrapeStatus.SUCCESS, ScrapeStatus.FAILED, ScrapeStatus.CANCELLED):
            return status
        if time.monotonic() > deadline:
            log.warning("gdp_report: child %s exceeded max wait", child_id)
            return ScrapeStatus.FAILED
        time.sleep(_POLL_SECONDS)


def _spawn_child_scrape(
    db: Session,
    job: GdpReportJob,
    *,
    kind: ScrapeKind,
    dates_iso: Iterable[str],
    target_niks: list[str] | None = None,
) -> uuid.UUID:
    """Create + queue one multi-date scrape_job. Returns its id."""
    iso_list = list(dates_iso)
    asik_list_only = bool(job.skip_asik_detail and kind == ScrapeKind.ASIK)
    try:
        child = scrape_job_crud.create(
            db,
            puskesmas_id=job.puskesmas_id,
            kind=kind,
            date_filter=None,
            triggered_by_id=job.triggered_by_id,
            triggered_by_type=job.triggered_by_type,
            parent_gdp_job_id=job.id,
            asik_list_only=asik_list_only,
        )
        # date_filters / target_niks live outside the canonical create(...)
        # signature — only the GDP orchestrator uses them.
        child.date_filters = json.dumps(iso_list)
        if target_niks:
            child.target_niks = json.dumps(target_niks)
        db.commit()
        db.refresh(child)
    except IntegrityError as exc:
        db.rollback()
        raise RuntimeError(
            f"another {kind.value} scrape already in progress for puskesmas {job.puskesmas_id}"
        ) from exc

    celery_app.send_task("scrape.run", args=[str(child.id), kind.value])
    return child.id


def _resume_or_spawn(
    db: Session,
    job: GdpReportJob,
    rc: "redis.Redis",
    parent_id: str,
    *,
    kind: ScrapeKind,
    dates_iso: Iterable[str],
    target_niks: list[str] | None = None,
) -> ScrapeStatus:
    """Idempotent child handling for orchestrator retries.

    Celery's task_acks_late + reject_on_worker_lost can re-queue this task on
    worker death. Without this guard, a fresh ASIK child would be spawned even
    though the previous run already finished — wasting hours of scrape time.

    Logic:
      - SUCCESS child for this (parent, kind) → reuse, return SUCCESS.
      - PENDING/RUNNING child → wait on it instead of spawning a new one.
      - No child or terminal failure (FAILED/CANCELLED) → spawn fresh.
    """
    # Prefer SUCCESS over RUNNING/PENDING over CANCELLED/FAILED. After a
    # retry on a CANCELLED parent, an earlier SUCCESS child should be reused
    # even if a later CANCELLED child exists for the same kind.
    children = db.scalars(
        select(ScrapeJob)
        .where(
            ScrapeJob.parent_gdp_job_id == job.id,
            ScrapeJob.kind == kind,
        )
        .order_by(ScrapeJob.created_at.desc())
    ).all()
    success = next((c for c in children if c.status == ScrapeStatus.SUCCESS), None)
    if success is not None:
        return ScrapeStatus.SUCCESS
    in_flight = next(
        (c for c in children if c.status in (ScrapeStatus.PENDING, ScrapeStatus.RUNNING)),
        None,
    )
    if in_flight is not None:
        return _wait_child(db, rc, parent_id, in_flight.id)
    # No SUCCESS or in-flight child → spawn fresh.

    try:
        child_id = _spawn_child_scrape(
            db, job, kind=kind, dates_iso=dates_iso, target_niks=target_niks,
        )
    except RuntimeError as exc:
        gdp_crud.mark_failed(db, job, str(exc), datetime.now(UTC))
        return ScrapeStatus.FAILED
    return _wait_child(db, rc, parent_id, child_id)


def _gather_asik_niks(db: Session, job: GdpReportJob) -> list[str]:
    """Collect NIKs that have ASIK data in the puskesmas's date range.

    Source of truth for "this NIK is running CKG" — only these NIKs are
    cross-checked against EPUS in phase 2.
    """
    rows = db.execute(
        select(Patient.nik)
        .where(
            Patient.puskesmas_id == job.puskesmas_id,
            Patient.filter_date >= job.date_from,
            Patient.filter_date <= job.date_to,
            Patient.scraped_asik_data.isnot(None),
        )
        .distinct()
    ).all()
    return [r.nik for r in rows]


@celery_app.task(bind=True, name="gdp_report.run")
def run_gdp_report(self, job_id: str) -> None:
    db = SessionLocal()
    rc = _redis()
    job: GdpReportJob | None = None
    try:
        job_uuid = uuid.UUID(job_id)
        job = db.scalar(
            select(GdpReportJob).where(GdpReportJob.id == job_uuid)
        )
        if job is None:
            return
        # Idempotent re-entry guard. Celery may re-deliver this task after a
        # worker restart (acks_late) — bail if the run is already terminal so
        # we don't spawn duplicate children.
        if job.status in (
            GdpReportStatus.SUCCESS,
            GdpReportStatus.FAILED,
            GdpReportStatus.CANCELLED,
        ):
            return

        gdp_crud.mark_running(db, job, self.request.id or "", datetime.now(UTC))
        dates_iso = _date_range_iso(job.date_from, job.date_to)

        # Phase 1: ASIK multi-date.
        gdp_crud.set_phase(db, job, GdpReportPhase.ASIK)
        asik_status = _resume_or_spawn(
            db, job, rc, job_id,
            kind=ScrapeKind.ASIK, dates_iso=dates_iso,
        )
        if asik_status == ScrapeStatus.CANCELLED:
            gdp_crud.mark_cancelled(db, job)
            return
        if asik_status == ScrapeStatus.FAILED:
            # mark_failed already called by _resume_or_spawn on spawn-fail;
            # for a child that ran and failed, persist a generic message here.
            db.refresh(job)
            if job.status not in (GdpReportStatus.FAILED, GdpReportStatus.CANCELLED):
                gdp_crud.mark_failed(db, job, "ASIK scrape failed", datetime.now(UTC))
            return
        # dates_done is monotonic — only bump on first success transition.
        if job.dates_done < job.dates_total:
            gdp_crud.increment_progress(
                db, job, dates_done_delta=job.dates_total - job.dates_done,
            )

        # Phase 2: EPUS multi-date, restricted to NIKs that came back from
        # ASIK (single source of truth for "this NIK is running CKG").
        gdp_crud.set_phase(db, job, GdpReportPhase.EPUS)
        niks = _gather_asik_niks(db, job)
        gdp_crud.set_nik_total(db, job, len(niks))
        if not niks:
            # Nothing to cross-check; ASIK was empty for this range.
            gdp_crud.mark_success(
                db, job, datetime.now(UTC),
                notes="ASIK returned no NIKs — EPUS phase skipped.",
            )
            return
        if (job.epus_jobs_total or 0) < 1:
            gdp_crud.set_epus_jobs_total(db, job, 1)

        epus_status = _resume_or_spawn(
            db, job, rc, job_id,
            kind=ScrapeKind.EPUS, dates_iso=dates_iso, target_niks=niks,
        )
        if epus_status == ScrapeStatus.CANCELLED:
            gdp_crud.mark_cancelled(db, job)
            return
        if epus_status == ScrapeStatus.FAILED:
            db.refresh(job)
            if job.status not in (GdpReportStatus.FAILED, GdpReportStatus.CANCELLED):
                gdp_crud.increment_progress(db, job, epus_failed_delta=1)
                gdp_crud.mark_failed(db, job, "EPUS scrape failed", datetime.now(UTC))
            return
        if (job.epus_jobs_done or 0) < 1:
            gdp_crud.increment_progress(db, job, epus_done_delta=1)

        gdp_crud.mark_success(db, job, datetime.now(UTC))
    except Exception as exc:
        db.rollback()
        log.exception("gdp_report task failed")
        if job is not None:
            try:
                gdp_crud.mark_failed(db, job, str(exc)[:2000], datetime.now(UTC))
            except Exception:
                pass
        raise
    finally:
        db.close()
