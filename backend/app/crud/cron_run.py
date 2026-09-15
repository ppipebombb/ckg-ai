import uuid
from datetime import UTC, date, datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models.cron_config import CronSourceScope
from app.models.cron_run import CronRun, CronRunStatus, CronStep


def create(
    db: Session,
    *,
    puskesmas_id: uuid.UUID,
    target_date: date,
    cron_config_id: uuid.UUID | None,
    triggered_by_id: uuid.UUID | None,
    cron_backfill_id: uuid.UUID | None = None,
    source_scope: CronSourceScope = CronSourceScope.BOTH,
) -> CronRun:
    obj = CronRun(
        puskesmas_id=puskesmas_id,
        target_date=target_date,
        cron_config_id=cron_config_id,
        cron_backfill_id=cron_backfill_id,
        triggered_by_id=triggered_by_id,
        source_scope=source_scope,
        status=CronRunStatus.PENDING,
        current_step_attempt=0,
    )
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


def mark_running(db: Session, obj: CronRun, started_at: datetime) -> bool:
    """Conditionally transition PENDING → RUNNING. Returns True if this call
    won the transition. Returns False when a concurrent cancel/fail already
    wrote a terminal status — caller should bail without dispatching work."""
    new_started = obj.started_at if obj.started_at is not None else started_at
    res = db.execute(
        update(CronRun)
        .where(
            CronRun.id == obj.id,
            CronRun.status == CronRunStatus.PENDING,
        )
        .values(status=CronRunStatus.RUNNING, started_at=new_started)
    )
    db.commit()
    db.refresh(obj)
    return res.rowcount > 0


def set_step(
    db: Session,
    obj: CronRun,
    step: CronStep,
    *,
    attempt: int,
    job_id: uuid.UUID | None = None,
) -> None:
    obj.current_step = step
    obj.current_step_attempt = attempt
    if job_id is not None:
        if step == CronStep.ASIK:
            obj.asik_scrape_job_id = job_id
        elif step == CronStep.EPUS:
            obj.epus_scrape_job_id = job_id
        else:
            obj.merge_job_id = job_id
    db.commit()


def mark_success(db: Session, obj: CronRun, finished_at: datetime) -> None:
    obj.status = CronRunStatus.SUCCESS
    obj.finished_at = finished_at
    obj.current_step = None
    db.commit()


def mark_failed(
    db: Session,
    obj: CronRun,
    failed_step: CronStep,
    error_message: str,
    finished_at: datetime,
) -> None:
    obj.status = CronRunStatus.FAILED
    obj.failed_step = failed_step
    obj.current_step = None
    obj.error_message = error_message[:4000]
    obj.finished_at = finished_at
    db.commit()


def mark_cancelled(db: Session, obj: CronRun) -> None:
    obj.status = CronRunStatus.CANCELLED
    obj.current_step = None
    obj.finished_at = datetime.now(UTC)
    db.commit()


def cancel_cron_run_and_children(
    db: Session,
    run: CronRun,
    *,
    exclude_job_id: uuid.UUID | None = None,
) -> None:
    """Mark cron_run CANCELLED (if still active) + cancel every non-terminal
    child job (asik / epus / merge), excluding `exclude_job_id` when one of
    them already wrote CANCELLED itself (the originating per-job cancel route).

    Keeps the cron-orchestration invariant: when the run is cancelled, no
    downstream child kicks off. cron.advance / cron.handle_failure both
    re-check cron_run.status and the cancel Redis flag at entry."""
    from app.celery_app import celery_app
    from app.core.rate_limit import redis_client
    from app.crud import merge_job as merge_job_crud
    from app.crud import scrape_job as scrape_job_crud
    from app.models.merge_job import MergeJob, MergeStatus
    from app.models.scrape_job import ScrapeJob, ScrapeStatus
    from app.tasks.cron import cancel_key as cron_cancel_key

    rc = redis_client()
    if run.status in (CronRunStatus.PENDING, CronRunStatus.RUNNING):
        mark_cancelled(db, run)
    rc.set(cron_cancel_key(str(run.id)), "1", ex=86400)

    def _cancel_scrape(job_id: uuid.UUID) -> None:
        job = db.scalar(select(ScrapeJob).where(ScrapeJob.id == job_id))
        if job is None or job.status not in (
            ScrapeStatus.PENDING, ScrapeStatus.RUNNING
        ):
            return
        scrape_job_crud.mark_cancelled(db, job)
        rc.set(f"scrape:job:{job_id}:cancel", "1", ex=86400)
        if job.celery_task_id:
            try:
                celery_app.control.revoke(job.celery_task_id, terminate=False)
            except Exception:
                pass

    def _cancel_merge(job_id: uuid.UUID) -> None:
        job = db.scalar(select(MergeJob).where(MergeJob.id == job_id))
        if job is None or job.status not in (
            MergeStatus.PENDING, MergeStatus.RUNNING
        ):
            return
        merge_job_crud.mark_cancelled(db, job)
        rc.set(f"merge:job:{job_id}:cancel", "1", ex=86400)
        if job.celery_task_id:
            try:
                celery_app.control.revoke(job.celery_task_id, terminate=False)
            except Exception:
                pass

    if (
        run.asik_scrape_job_id is not None
        and run.asik_scrape_job_id != exclude_job_id
    ):
        _cancel_scrape(run.asik_scrape_job_id)
    if (
        run.epus_scrape_job_id is not None
        and run.epus_scrape_job_id != exclude_job_id
    ):
        _cancel_scrape(run.epus_scrape_job_id)
    if run.merge_job_id is not None and run.merge_job_id != exclude_job_id:
        _cancel_merge(run.merge_job_id)
