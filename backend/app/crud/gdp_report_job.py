import uuid
from datetime import UTC, date, datetime

from sqlalchemy.orm import Session

from app.models.gdp_report_job import GdpReportJob, GdpReportPhase, GdpReportStatus
from app.models.scrape_job import TriggererType


def create(
    db: Session,
    *,
    puskesmas_id: uuid.UUID,
    date_from: date,
    date_to: date,
    triggered_by_id: uuid.UUID,
    triggered_by_type: TriggererType,
    skip_asik_detail: bool = False,
) -> GdpReportJob:
    dates_total = (date_to - date_from).days + 1
    obj = GdpReportJob(
        puskesmas_id=puskesmas_id,
        date_from=date_from,
        date_to=date_to,
        triggered_by_id=triggered_by_id,
        triggered_by_type=triggered_by_type,
        status=GdpReportStatus.PENDING,
        phase=GdpReportPhase.PENDING,
        dates_total=dates_total,
        skip_asik_detail=skip_asik_detail,
    )
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


def mark_running(
    db: Session, obj: GdpReportJob, celery_task_id: str, started_at: datetime
) -> None:
    obj.status = GdpReportStatus.RUNNING
    obj.celery_task_id = celery_task_id
    obj.started_at = started_at
    db.commit()


def set_phase(db: Session, obj: GdpReportJob, phase: GdpReportPhase) -> None:
    obj.phase = phase
    db.commit()


def set_nik_total(db: Session, obj: GdpReportJob, nik_total: int) -> None:
    obj.nik_total = nik_total
    db.commit()


def set_epus_jobs_total(db: Session, obj: GdpReportJob, epus_jobs_total: int) -> None:
    obj.epus_jobs_total = epus_jobs_total
    db.commit()


def increment_progress(
    db: Session,
    obj: GdpReportJob,
    *,
    epus_done_delta: int = 0,
    epus_failed_delta: int = 0,
    nik_done_delta: int = 0,
    dates_done_delta: int = 0,
) -> None:
    obj.epus_jobs_done = obj.epus_jobs_done + epus_done_delta
    obj.epus_jobs_failed = obj.epus_jobs_failed + epus_failed_delta
    obj.nik_done = obj.nik_done + nik_done_delta
    obj.dates_done = obj.dates_done + dates_done_delta
    db.commit()


def mark_success(db: Session, obj: GdpReportJob, finished_at: datetime, notes: str | None = None) -> None:
    obj.status = GdpReportStatus.SUCCESS
    obj.phase = GdpReportPhase.DONE
    obj.finished_at = finished_at
    if notes is not None:
        obj.notes = notes
    db.commit()


def mark_failed(
    db: Session,
    obj: GdpReportJob,
    error_message: str,
    finished_at: datetime,
) -> None:
    obj.status = GdpReportStatus.FAILED
    obj.error_message = error_message[:4000]
    obj.finished_at = finished_at
    db.commit()


def mark_cancelled(db: Session, obj: GdpReportJob) -> None:
    obj.status = GdpReportStatus.CANCELLED
    obj.finished_at = datetime.now(UTC)
    db.commit()


def reset_for_retry(db: Session, obj: GdpReportJob) -> None:
    """Move CANCELLED/FAILED job back to PENDING so the orchestrator can
    re-enter. Existing children are kept — `_resume_or_spawn` reuses any
    SUCCESS child and waits on any still-RUNNING child. Cleared fields
    avoid stale terminal markers leaking into the resumed run.
    """
    obj.status = GdpReportStatus.PENDING
    obj.finished_at = None
    obj.error_message = None
    obj.celery_task_id = None
    db.commit()
