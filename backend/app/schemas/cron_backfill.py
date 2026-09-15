import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, model_validator

from app.models.cron_backfill import CronBackfill, CronBackfillStatus
from app.models.cron_config import CronMergeMode, CronSourceScope, CronSyncMode


class CronBackfillCreate(BaseModel):
    puskesmas_id: uuid.UUID
    date_from: date
    date_to: date
    merge_mode: CronMergeMode = CronMergeMode.NORMAL
    source_scope: CronSourceScope = CronSourceScope.BOTH
    # Pemeriksaan Mandiri-only backfill. The route forces source_scope=ASIK_ONLY
    # server-side when this is set; merge_mode stays as chosen (FORCE_REMERGE to
    # surface it on the merged view, or NO_MERGE for scrape-only).
    mandiri_only: bool = False
    # Optional ASIK sync step after each date's merge. OFF by default.
    sync_mode: CronSyncMode = CronSyncMode.OFF
    # Optional ASIK create step after sync — only meaningful when sync is on.
    create_new: bool = False

    @model_validator(mode="after")
    def _check(self) -> "CronBackfillCreate":
        if self.date_from > self.date_to:
            raise ValueError("date_from must be <= date_to")
        if self.create_new and self.sync_mode is CronSyncMode.OFF:
            raise ValueError("create_new requires sync_mode to be enabled (not OFF)")
        if self.source_scope is CronSourceScope.NONE:
            # NONE = sync-only over existing data (no scrape → MERGE → ASIK sync).
            if self.mandiri_only:
                raise ValueError(
                    "source_scope 'none' cannot be combined with mandiri_only — "
                    "mandiri_only forces an ASIK scrape"
                )
            if self.sync_mode is CronSyncMode.OFF:
                raise ValueError(
                    "source_scope 'none' requires sync_mode on (normal or "
                    "force_resync) — otherwise the run does nothing"
                )
            if self.merge_mode is CronMergeMode.NO_MERGE:
                raise ValueError(
                    "source_scope 'none' cannot use merge_mode 'no_merge' — "
                    "no_merge skips the merge step and never reaches sync"
                )
        return self


class CronBackfillOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    puskesmas_id: uuid.UUID
    puskesmas_name: str
    date_from: date
    date_to: date
    cursor_date: date | None
    status: CronBackfillStatus
    merge_mode: CronMergeMode
    source_scope: CronSourceScope
    mandiri_only: bool
    sync_mode: CronSyncMode
    create_new: bool
    triggered_by_id: uuid.UUID | None
    current_cron_run_id: uuid.UUID | None
    total_dates: int
    completed_dates: int
    failed_date: date | None
    error_message: str | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime
    updated_at: datetime


def cron_backfill_to_out(
    obj: CronBackfill, puskesmas_name: str
) -> CronBackfillOut:
    return CronBackfillOut(
        id=obj.id,
        puskesmas_id=obj.puskesmas_id,
        puskesmas_name=puskesmas_name,
        date_from=obj.date_from,
        date_to=obj.date_to,
        cursor_date=obj.cursor_date,
        status=obj.status,
        merge_mode=obj.merge_mode,
        source_scope=obj.source_scope,
        mandiri_only=obj.mandiri_only,
        sync_mode=obj.sync_mode,
        create_new=obj.create_new,
        triggered_by_id=obj.triggered_by_id,
        current_cron_run_id=obj.current_cron_run_id,
        total_dates=obj.total_dates,
        completed_dates=obj.completed_dates,
        failed_date=obj.failed_date,
        error_message=obj.error_message,
        started_at=obj.started_at,
        finished_at=obj.finished_at,
        created_at=obj.created_at,
        updated_at=obj.updated_at,
    )
