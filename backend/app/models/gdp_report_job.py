import enum
import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, Enum as SAEnum
from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import SoftDeleteMixin, TimestampMixin, UUIDPKMixin
from app.models.scrape_job import TriggererType

if TYPE_CHECKING:
    from app.models.puskesmas import Puskesmas


class GdpReportStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


class GdpReportPhase(str, enum.Enum):
    PENDING = "pending"
    ASIK = "asik"
    EPUS = "epus"
    DONE = "done"


class GdpReportJob(UUIDPKMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "gdp_report_jobs"

    puskesmas_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("puskesmas.id"),
        nullable=False,
    )
    date_from: Mapped[date] = mapped_column(Date, nullable=False)
    date_to: Mapped[date] = mapped_column(Date, nullable=False)
    triggered_by_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    triggered_by_type: Mapped[TriggererType] = mapped_column(
        SAEnum(TriggererType, name="triggerer_type", values_callable=lambda x: [e.value for e in x]),
        nullable=False,
    )
    status: Mapped[GdpReportStatus] = mapped_column(
        SAEnum(GdpReportStatus, name="gdp_report_status", values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=GdpReportStatus.PENDING,
    )
    phase: Mapped[GdpReportPhase] = mapped_column(
        SAEnum(GdpReportPhase, name="gdp_report_phase", values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=GdpReportPhase.PENDING,
    )
    celery_task_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    nik_total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    nik_done: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    dates_total: Mapped[int] = mapped_column(Integer, nullable=False)
    dates_done: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    epus_jobs_total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    epus_jobs_done: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    epus_jobs_failed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # NIK-only mode for ASIK phase. ASIK still walks every date and per-patient
    # detail-screening for NIK + Nama, but skips SurveyJS form-tab opening.
    skip_asik_detail: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    puskesmas: Mapped["Puskesmas"] = relationship()

    __table_args__ = (
        CheckConstraint("date_from <= date_to", name="ck_gdp_report_jobs_date_range"),
    )
