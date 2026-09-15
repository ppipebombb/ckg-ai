import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.models.scrape_job import TriggererType
from app.models.sync_job import SyncJob, SyncStatus


def create(
    db: Session,
    *,
    puskesmas_id: uuid.UUID,
    patient_id: uuid.UUID,
    triggered_by_id: uuid.UUID,
    triggered_by_type: TriggererType,
    cron_run_id: uuid.UUID | None = None,
) -> SyncJob:
    obj = SyncJob(
        puskesmas_id=puskesmas_id,
        patient_id=patient_id,
        triggered_by_id=triggered_by_id,
        triggered_by_type=triggered_by_type,
        cron_run_id=cron_run_id,
        status=SyncStatus.PENDING,
        forms_total=0,
        forms_succeeded=0,
        forms_failed=0,
        forms_skipped=0,
    )
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


def mark_running(
    db: Session,
    obj: SyncJob,
    celery_task_id: str,
    started_at: datetime,
    forms_total: int,
) -> None:
    obj.status = SyncStatus.RUNNING
    obj.celery_task_id = celery_task_id
    obj.started_at = started_at
    obj.forms_total = forms_total
    db.commit()


def _apply_resource_metrics(obj: SyncJob, metrics: dict | None) -> None:
    if not metrics:
        return
    obj.cpu_avg_pct = metrics.get("cpu_avg_pct")
    obj.cpu_peak_pct = metrics.get("cpu_peak_pct")
    obj.mem_avg_mb = metrics.get("mem_avg_mb")
    obj.mem_peak_mb = metrics.get("mem_peak_mb")
    obj.resource_samples = metrics.get("samples")


def mark_success(
    db: Session,
    obj: SyncJob,
    duration_seconds: float,
    finished_at: datetime,
    *,
    forms_succeeded: int,
    forms_failed: int,
    forms_skipped: int,
    notes: str | None = None,
    metrics: dict | None = None,
) -> None:
    obj.status = SyncStatus.SUCCESS
    obj.duration_seconds = duration_seconds
    obj.finished_at = finished_at
    obj.forms_succeeded = forms_succeeded
    obj.forms_failed = forms_failed
    obj.forms_skipped = forms_skipped
    obj.notes = notes
    _apply_resource_metrics(obj, metrics)
    db.commit()


def mark_failed(
    db: Session,
    obj: SyncJob,
    error_message: str,
    finished_at: datetime,
    *,
    forms_succeeded: int = 0,
    forms_failed: int = 0,
    forms_skipped: int = 0,
    metrics: dict | None = None,
) -> None:
    obj.status = SyncStatus.FAILED
    obj.error_message = error_message
    obj.finished_at = finished_at
    obj.forms_succeeded = forms_succeeded
    obj.forms_failed = forms_failed
    obj.forms_skipped = forms_skipped
    _apply_resource_metrics(obj, metrics)
    db.commit()


def mark_cancelled(
    db: Session, obj: SyncJob, *, error_message: str | None = None
) -> None:
    obj.status = SyncStatus.CANCELLED
    obj.finished_at = datetime.now(UTC)
    if error_message is not None:
        obj.error_message = error_message
    db.commit()


def set_resource_metrics(db: Session, obj: SyncJob, metrics: dict) -> None:
    _apply_resource_metrics(obj, metrics)
    db.commit()
