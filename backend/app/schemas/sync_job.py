import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.scrape_job import TriggererType
from app.models.sync_job import SyncStatus


class SyncStart(BaseModel):
    headless: bool = True


class SyncJobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    puskesmas_id: uuid.UUID
    puskesmas_name: str
    patient_id: uuid.UUID
    patient_name: str
    patient_nik: str
    status: SyncStatus
    triggered_by_id: uuid.UUID
    triggered_by_type: TriggererType
    celery_task_id: str | None
    forms_total: int | None
    forms_succeeded: int | None
    forms_failed: int | None
    forms_skipped: int | None
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
    created_at: datetime
    updated_at: datetime


class SyncJobLogOut(BaseModel):
    lines: list[str]
