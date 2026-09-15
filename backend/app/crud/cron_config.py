import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.cron_config import CronConfig, CronMergeMode, CronSyncMode

_JKT = ZoneInfo("Asia/Jakarta")


def compute_next_run_at(
    hour: int,
    minute: int,
    *,
    from_: datetime | None = None,
) -> datetime:
    """Return the next datetime (UTC) where local Jakarta time matches hour:minute,
    strictly after `from_`. Defaults to now."""
    base = (from_ or datetime.now(UTC)).astimezone(_JKT)
    candidate = base.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= base:
        candidate = candidate + timedelta(days=1)
    return candidate.astimezone(UTC)


def get_by_puskesmas(db: Session, puskesmas_id: uuid.UUID) -> CronConfig | None:
    return db.scalar(
        select(CronConfig).where(CronConfig.puskesmas_id == puskesmas_id)
    )


def create(
    db: Session,
    *,
    puskesmas_id: uuid.UUID,
    hour: int,
    minute: int,
    target_offset_days: int,
    lookback_days: int = 3,
    enabled: bool = True,
    merge_mode: CronMergeMode = CronMergeMode.NORMAL,
    sync_mode: CronSyncMode = CronSyncMode.OFF,
    create_new: bool = False,
) -> CronConfig:
    obj = CronConfig(
        puskesmas_id=puskesmas_id,
        hour=hour,
        minute=minute,
        target_offset_days=target_offset_days,
        lookback_days=lookback_days,
        enabled=enabled,
        merge_mode=merge_mode,
        sync_mode=sync_mode,
        create_new=create_new,
        next_run_at=compute_next_run_at(hour, minute),
    )
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


def update(
    db: Session,
    obj: CronConfig,
    *,
    hour: int | None = None,
    minute: int | None = None,
    target_offset_days: int | None = None,
    lookback_days: int | None = None,
    enabled: bool | None = None,
    merge_mode: CronMergeMode | None = None,
    sync_mode: CronSyncMode | None = None,
    create_new: bool | None = None,
) -> CronConfig:
    schedule_changed = False
    if hour is not None and hour != obj.hour:
        obj.hour = hour
        schedule_changed = True
    if minute is not None and minute != obj.minute:
        obj.minute = minute
        schedule_changed = True
    if target_offset_days is not None:
        obj.target_offset_days = target_offset_days
    if lookback_days is not None:
        obj.lookback_days = lookback_days
    if enabled is not None and enabled != obj.enabled:
        obj.enabled = enabled
        schedule_changed = True
    if merge_mode is not None:
        obj.merge_mode = merge_mode
    if sync_mode is not None:
        obj.sync_mode = sync_mode
    if create_new is not None:
        obj.create_new = create_new
    if schedule_changed:
        obj.next_run_at = compute_next_run_at(obj.hour, obj.minute)
    db.commit()
    db.refresh(obj)
    return obj


def soft_delete(db: Session, obj: CronConfig) -> None:
    obj.deleted_at = datetime.now(UTC)
    db.commit()
