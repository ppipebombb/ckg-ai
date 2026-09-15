import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.models.merge_job import MergeJob, MergeStatus
from app.models.scrape_job import TriggererType


def create(
    db: Session,
    *,
    puskesmas_id: uuid.UUID,
    date_filter: str | None,
    triggered_by_id: uuid.UUID,
    triggered_by_type: TriggererType,
    force_remerge: bool,
    cron_run_id: uuid.UUID | None = None,
    patient_id: uuid.UUID | None = None,
) -> MergeJob:
    obj = MergeJob(
        puskesmas_id=puskesmas_id,
        patient_id=patient_id,
        date_filter=date_filter,
        triggered_by_id=triggered_by_id,
        triggered_by_type=triggered_by_type,
        force_remerge=force_remerge,
        status=MergeStatus.PENDING,
        total_count=0,
        processed_count=0,
        succeeded_count=0,
        failed_count=0,
        skipped_count=0,
        cron_run_id=cron_run_id,
    )
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


def mark_running(
    db: Session,
    obj: MergeJob,
    celery_task_id: str,
    started_at: datetime,
    total_count: int,
) -> None:
    obj.status = MergeStatus.RUNNING
    obj.celery_task_id = celery_task_id
    obj.started_at = started_at
    obj.total_count = total_count
    db.commit()


def _apply_resource_metrics(obj: MergeJob, metrics: dict | None) -> None:
    if not metrics:
        return
    obj.cpu_avg_pct = metrics.get("cpu_avg_pct")
    obj.cpu_peak_pct = metrics.get("cpu_peak_pct")
    obj.mem_avg_mb = metrics.get("mem_avg_mb")
    obj.mem_peak_mb = metrics.get("mem_peak_mb")
    obj.resource_samples = metrics.get("samples")


def mark_success(
    db: Session,
    obj: MergeJob,
    duration_seconds: float,
    finished_at: datetime,
    notes: str | None = None,
    metrics: dict | None = None,
) -> None:
    obj.status = MergeStatus.SUCCESS
    obj.duration_seconds = duration_seconds
    obj.finished_at = finished_at
    obj.notes = notes
    _apply_resource_metrics(obj, metrics)
    db.commit()


def mark_failed(
    db: Session,
    obj: MergeJob,
    error_message: str,
    finished_at: datetime,
    metrics: dict | None = None,
    duration_seconds: float | None = None,
) -> None:
    obj.status = MergeStatus.FAILED
    obj.error_message = error_message
    obj.finished_at = finished_at
    if duration_seconds is not None:
        obj.duration_seconds = duration_seconds
    _apply_resource_metrics(obj, metrics)
    db.commit()


def mark_cancelled(db: Session, obj: MergeJob) -> None:
    obj.status = MergeStatus.CANCELLED
    obj.finished_at = datetime.now(UTC)
    db.commit()


def set_resource_metrics(db: Session, obj: MergeJob, metrics: dict) -> None:
    _apply_resource_metrics(obj, metrics)
    db.commit()


def bump_counters(
    db: Session,
    obj: MergeJob,
    *,
    processed: int = 0,
    succeeded: int = 0,
    failed: int = 0,
    skipped: int = 0,
) -> None:
    if processed:
        obj.processed_count = (obj.processed_count or 0) + processed
    if succeeded:
        obj.succeeded_count = (obj.succeeded_count or 0) + succeeded
    if failed:
        obj.failed_count = (obj.failed_count or 0) + failed
    if skipped:
        obj.skipped_count = (obj.skipped_count or 0) + skipped
