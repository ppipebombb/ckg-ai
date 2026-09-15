import datetime as _dt
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, model_validator

from app.models.merge_job import MergeStatus
from app.models.scrape_job import TriggererType

# Range mode fans out one committed MergeJob row + one Celery task per day. Cap
# the span so a single request can't enqueue tens of thousands of jobs and
# starve the workers (DoS). One year is well beyond any real merge window.
MAX_MERGE_RANGE_DAYS = 366


class MergeStart(BaseModel):
    # Single-date mode: `date` is set (or both `date` and the range fields are
    # omitted, which defaults to today on the server). Range mode: `date_from`
    # AND `date_to` are set, `date` must be omitted. Mixing is rejected.
    date: _dt.date | None = None
    date_from: _dt.date | None = None
    date_to: _dt.date | None = None
    force: bool = False

    @model_validator(mode="after")
    def _check_range(self) -> "MergeStart":
        has_single = self.date is not None
        has_from = self.date_from is not None
        has_to = self.date_to is not None
        if has_single and (has_from or has_to):
            raise ValueError(
                "provide either `date` or `date_from`+`date_to`, not both"
            )
        if has_from != has_to:
            raise ValueError(
                "`date_from` and `date_to` must be provided together"
            )
        if has_from and has_to:
            if self.date_from > self.date_to:
                raise ValueError("`date_from` must be <= `date_to`")
            span = (self.date_to - self.date_from).days + 1
            if span > MAX_MERGE_RANGE_DAYS:
                raise ValueError(
                    f"date range too large ({span} days); maximum is "
                    f"{MAX_MERGE_RANGE_DAYS} days"
                )
        return self


class MergePreviewOut(BaseModel):
    matched_count: int
    pending_count: int
    already_merged_count: int


class MergeJobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    puskesmas_id: uuid.UUID
    puskesmas_name: str
    patient_id: uuid.UUID | None = None
    patient_nik: str | None = None
    patient_name: str | None = None
    date_filter: str | None = None
    status: MergeStatus
    triggered_by_id: uuid.UUID
    triggered_by_type: TriggererType
    celery_task_id: str | None
    force_remerge: bool
    total_count: int | None
    processed_count: int | None
    succeeded_count: int | None
    failed_count: int | None
    skipped_count: int | None
    duration_seconds: float | None
    cpu_avg_pct: float | None
    cpu_peak_pct: float | None
    mem_avg_mb: float | None
    mem_peak_mb: float | None
    resource_samples: int | None
    notes: str | None
    started_at: datetime | None
    finished_at: datetime | None
    error_message: str | None
    cron_run_id: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime


class MergeJobLogOut(BaseModel):
    lines: list[str]
