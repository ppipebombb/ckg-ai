import uuid
from datetime import UTC, date, datetime

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.models.cron_backfill import CronBackfill, CronBackfillStatus
from app.models.cron_config import CronMergeMode, CronSourceScope, CronSyncMode


def create(
    db: Session,
    *,
    puskesmas_id: uuid.UUID,
    date_from: date,
    date_to: date,
    merge_mode: CronMergeMode,
    triggered_by_id: uuid.UUID | None,
    source_scope: CronSourceScope = CronSourceScope.BOTH,
    mandiri_only: bool = False,
    sync_mode: CronSyncMode = CronSyncMode.OFF,
    create_new: bool = False,
    cron_config_id: uuid.UUID | None = None,
) -> CronBackfill:
    total = (date_to - date_from).days + 1
    obj = CronBackfill(
        puskesmas_id=puskesmas_id,
        date_from=date_from,
        date_to=date_to,
        merge_mode=merge_mode,
        source_scope=source_scope,
        mandiri_only=mandiri_only,
        sync_mode=sync_mode,
        create_new=create_new,
        triggered_by_id=triggered_by_id,
        cron_config_id=cron_config_id,
        status=CronBackfillStatus.PENDING,
        total_dates=total,
        completed_dates=0,
    )
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


def mark_running(
    db: Session, obj: CronBackfill, started_at: datetime
) -> bool:
    new_started = obj.started_at if obj.started_at is not None else started_at
    # UPDATE is not auto-filtered for soft-delete (CLAUDE.md §6); guard explicitly.
    res = db.execute(
        update(CronBackfill)
        .where(
            CronBackfill.id == obj.id,
            CronBackfill.status == CronBackfillStatus.PENDING,
            CronBackfill.deleted_at.is_(None),
        )
        .values(
            status=CronBackfillStatus.RUNNING,
            started_at=new_started,
        )
    )
    db.commit()
    db.refresh(obj)
    return res.rowcount > 0


def mark_success(
    db: Session, obj: CronBackfill, finished_at: datetime
) -> None:
    obj.status = CronBackfillStatus.SUCCESS
    obj.finished_at = finished_at
    obj.current_cron_run_id = None
    db.commit()


def mark_failed(
    db: Session,
    obj: CronBackfill,
    failed_date: date,
    error_message: str,
    finished_at: datetime,
) -> None:
    obj.status = CronBackfillStatus.FAILED
    obj.failed_date = failed_date
    obj.error_message = error_message[:4000]
    obj.finished_at = finished_at
    obj.current_cron_run_id = None
    db.commit()


def mark_cancelled(db: Session, obj: CronBackfill) -> None:
    obj.status = CronBackfillStatus.CANCELLED
    obj.finished_at = datetime.now(UTC)
    obj.current_cron_run_id = None
    db.commit()


def advance_cursor(
    db: Session, obj: CronBackfill, next_cursor: date
) -> None:
    obj.cursor_date = next_cursor
    obj.completed_dates = obj.completed_dates + 1
    db.commit()


def set_current_run(
    db: Session, obj: CronBackfill, cron_run_id: uuid.UUID | None
) -> None:
    obj.current_cron_run_id = cron_run_id
    db.commit()
