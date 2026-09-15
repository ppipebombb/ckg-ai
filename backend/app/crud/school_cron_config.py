import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.crud.cron_config import compute_next_run_at
from app.models.school_cron_config import SchoolCronConfig


def get_by_puskesmas(db: Session, puskesmas_id: uuid.UUID) -> SchoolCronConfig | None:
    return db.scalar(
        select(SchoolCronConfig).where(SchoolCronConfig.puskesmas_id == puskesmas_id)
    )


def create(
    db: Session,
    *,
    puskesmas_id: uuid.UUID,
    hour: int,
    minute: int,
    enabled: bool = True,
) -> SchoolCronConfig:
    obj = SchoolCronConfig(
        puskesmas_id=puskesmas_id,
        hour=hour,
        minute=minute,
        enabled=enabled,
        next_run_at=compute_next_run_at(hour, minute),
    )
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


def update(
    db: Session,
    obj: SchoolCronConfig,
    *,
    hour: int | None = None,
    minute: int | None = None,
    enabled: bool | None = None,
) -> SchoolCronConfig:
    schedule_changed = False
    if hour is not None and hour != obj.hour:
        obj.hour = hour
        schedule_changed = True
    if minute is not None and minute != obj.minute:
        obj.minute = minute
        schedule_changed = True
    if enabled is not None and enabled != obj.enabled:
        obj.enabled = enabled
        schedule_changed = True
    if schedule_changed:
        obj.next_run_at = compute_next_run_at(obj.hour, obj.minute)
    db.commit()
    db.refresh(obj)
    return obj


def soft_delete(db: Session, obj: SchoolCronConfig) -> None:
    obj.deleted_at = datetime.now(UTC)
    db.commit()
