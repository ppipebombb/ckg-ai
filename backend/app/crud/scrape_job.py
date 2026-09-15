import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.models.scrape_job import ScrapeJob, ScrapeKind, ScrapeStatus, TriggererType


def create(
    db: Session,
    puskesmas_id: uuid.UUID,
    kind: ScrapeKind,
    date_filter: str | None,
    triggered_by_id: uuid.UUID,
    triggered_by_type: TriggererType,
    cron_run_id: uuid.UUID | None = None,
    patient_id: uuid.UUID | None = None,
    target_nik: str | None = None,
    parent_gdp_job_id: uuid.UUID | None = None,
    asik_list_only: bool = False,
    asik_mandiri_only: bool = False,
    target_niks: str | None = None,
) -> ScrapeJob:
    obj = ScrapeJob(
        puskesmas_id=puskesmas_id,
        patient_id=patient_id,
        kind=kind,
        date_filter=date_filter,
        triggered_by_id=triggered_by_id,
        triggered_by_type=triggered_by_type,
        status=ScrapeStatus.PENDING,
        cron_run_id=cron_run_id,
        target_nik=target_nik,
        parent_gdp_job_id=parent_gdp_job_id,
        asik_list_only=asik_list_only,
        asik_mandiri_only=asik_mandiri_only,
        target_niks=target_niks,
    )
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


def mark_running(db: Session, obj: ScrapeJob, celery_task_id: str, started_at: datetime) -> None:
    obj.status = ScrapeStatus.RUNNING
    obj.celery_task_id = celery_task_id
    obj.started_at = started_at
    db.commit()


def _apply_resource_metrics(obj: ScrapeJob, metrics: dict | None) -> None:
    if not metrics:
        return
    obj.cpu_avg_pct = metrics.get("cpu_avg_pct")
    obj.cpu_peak_pct = metrics.get("cpu_peak_pct")
    obj.mem_avg_mb = metrics.get("mem_avg_mb")
    obj.mem_peak_mb = metrics.get("mem_peak_mb")
    obj.resource_samples = metrics.get("samples")


def mark_success(
    db: Session,
    obj: ScrapeJob,
    scraped_count: int,
    inserted_count: int,
    updated_count: int,
    duration_seconds: float,
    finished_at: datetime,
    notes: str | None = None,
    metrics: dict | None = None,
) -> None:
    obj.status = ScrapeStatus.SUCCESS
    obj.scraped_count = scraped_count
    obj.inserted_count = inserted_count
    obj.updated_count = updated_count
    obj.duration_seconds = duration_seconds
    obj.finished_at = finished_at
    obj.notes = notes
    _apply_resource_metrics(obj, metrics)
    db.commit()


def mark_failed(
    db: Session,
    obj: ScrapeJob,
    error_message: str,
    finished_at: datetime,
    metrics: dict | None = None,
) -> None:
    obj.status = ScrapeStatus.FAILED
    obj.error_message = error_message
    obj.finished_at = finished_at
    _apply_resource_metrics(obj, metrics)
    db.commit()


def mark_cancelled(db: Session, obj: ScrapeJob) -> None:
    obj.status = ScrapeStatus.CANCELLED
    obj.finished_at = datetime.now(UTC)
    db.commit()


def set_resource_metrics(db: Session, obj: ScrapeJob, metrics: dict) -> None:
    _apply_resource_metrics(obj, metrics)
    db.commit()


