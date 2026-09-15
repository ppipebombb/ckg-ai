import datetime as _dt
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.scrape_job import ScrapeKind, ScrapeStatus, TriggererType


class ScrapeStart(BaseModel):
    date: _dt.date | None = None
    headless: bool = True


class PatientScrapeStart(BaseModel):
    headless: bool = True


class ScrapeJobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    puskesmas_id: uuid.UUID
    puskesmas_name: str
    patient_id: uuid.UUID | None = None
    patient_nik: str | None = None
    patient_name: str | None = None
    kind: ScrapeKind
    date_filter: str | None = None
    status: ScrapeStatus
    triggered_by_id: uuid.UUID
    triggered_by_type: TriggererType
    celery_task_id: str | None
    scraped_count: int | None
    inserted_count: int | None
    updated_count: int | None
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
    parent_gdp_job_id: uuid.UUID | None = None
    target_nik: str | None = None
    created_at: datetime
    updated_at: datetime


class ScrapeJobLogOut(BaseModel):
    lines: list[str]
