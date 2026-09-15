import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum as SAEnum
from sqlalchemy import Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import SoftDeleteMixin, TimestampMixin, UUIDPKMixin
from app.models.scrape_job import TriggererType

if TYPE_CHECKING:
    from app.models.patient import Patient
    from app.models.puskesmas import Puskesmas


class SyncStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


class SyncJob(UUIDPKMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "sync_jobs"

    puskesmas_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("puskesmas.id"),
        nullable=False,
    )
    patient_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("patients.id"),
        nullable=False,
    )
    # Set when a cron sync batch spawned this job; NULL for a manual sync from
    # the patient detail page. Drives the cron-run detail page's Sync row.
    cron_run_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("cron_runs.id"),
        nullable=True,
    )
    triggered_by_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    triggered_by_type: Mapped[TriggererType] = mapped_column(
        SAEnum(TriggererType, name="triggerer_type", values_callable=lambda x: [e.value for e in x]),
        nullable=False,
    )
    status: Mapped[SyncStatus] = mapped_column(
        SAEnum(SyncStatus, name="sync_status", values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=SyncStatus.PENDING,
    )
    celery_task_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    forms_total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    forms_succeeded: Mapped[int | None] = mapped_column(Integer, nullable=True)
    forms_failed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    forms_skipped: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    cpu_avg_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    cpu_peak_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    mem_avg_mb: Mapped[float | None] = mapped_column(Float, nullable=True)
    mem_peak_mb: Mapped[float | None] = mapped_column(Float, nullable=True)
    resource_samples: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    puskesmas: Mapped["Puskesmas"] = relationship()
    patient: Mapped["Patient"] = relationship()
