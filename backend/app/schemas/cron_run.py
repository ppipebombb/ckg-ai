import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict

from app.models.cron_config import CronSourceScope
from app.models.cron_run import CronRun, CronRunStatus, CronStep


class CronRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    cron_config_id: uuid.UUID | None
    cron_backfill_id: uuid.UUID | None
    puskesmas_id: uuid.UUID
    puskesmas_name: str
    target_date: date
    source_scope: CronSourceScope
    status: CronRunStatus
    current_step: CronStep | None
    current_step_attempt: int
    failed_step: CronStep | None
    asik_scrape_job_id: uuid.UUID | None
    epus_scrape_job_id: uuid.UUID | None
    merge_job_id: uuid.UUID | None
    triggered_by_id: uuid.UUID | None
    error_message: str | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime
    updated_at: datetime


class CronRunSyncSummary(BaseModel):
    """Per-patient ASIK-sync progress for one cron run.

    Separate from CronRunOut because it is a GROUP BY over sync_jobs, not a
    column on the run — the run-list endpoint must not pay for it.
    `total` is the denominator stamped when the sync step started, and is None
    for runs that never reached SYNC (or predate the column).
    """

    model_config = ConfigDict(from_attributes=True)

    total: int | None
    pending: int
    running: int
    success: int
    failed: int
    cancelled: int


def cron_run_to_out(run: CronRun, puskesmas_name: str) -> "CronRunOut":
    return CronRunOut(
        id=run.id,
        cron_config_id=run.cron_config_id,
        cron_backfill_id=run.cron_backfill_id,
        puskesmas_id=run.puskesmas_id,
        puskesmas_name=puskesmas_name,
        target_date=run.target_date,
        source_scope=run.source_scope,
        status=run.status,
        current_step=run.current_step,
        current_step_attempt=run.current_step_attempt,
        failed_step=run.failed_step,
        asik_scrape_job_id=run.asik_scrape_job_id,
        epus_scrape_job_id=run.epus_scrape_job_id,
        merge_job_id=run.merge_job_id,
        triggered_by_id=run.triggered_by_id,
        error_message=run.error_message,
        started_at=run.started_at,
        finished_at=run.finished_at,
        created_at=run.created_at,
        updated_at=run.updated_at,
    )
