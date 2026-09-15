import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Enum as SAEnum
from sqlalchemy import Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import SoftDeleteMixin, TimestampMixin, UUIDPKMixin

if TYPE_CHECKING:
    from app.models.patient import Patient
    from app.models.puskesmas import Puskesmas


class ScrapeKind(str, enum.Enum):
    ASIK = "asik"
    EPUS = "epus"
    # CKG Sekolah (school health checkup) — same ASIK portal/credentials, but a
    # date-less program filtered by school × class. Writes to the separate
    # school_patients table, not patients. See models/school_patient.py.
    ASIK_SEKOLAH = "asik_sekolah"


class ScrapeStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TriggererType(str, enum.Enum):
    ADMIN = "admin"
    USER = "user"
    CRON = "cron"


class ScrapeJob(UUIDPKMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "scrape_jobs"

    puskesmas_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("puskesmas.id"),
        nullable=False,
    )
    patient_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("patients.id", ondelete="SET NULL"),
        nullable=True,
    )
    triggered_by_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    triggered_by_type: Mapped[TriggererType] = mapped_column(
        SAEnum(TriggererType, name="triggerer_type", values_callable=lambda x: [e.value for e in x]),
        nullable=False,
    )
    kind: Mapped[ScrapeKind] = mapped_column(
        SAEnum(ScrapeKind, name="scrape_kind", values_callable=lambda x: [e.value for e in x]),
        nullable=False,
    )
    date_filter: Mapped[str | None] = mapped_column(String(16), nullable=True)
    status: Mapped[ScrapeStatus] = mapped_column(
        SAEnum(ScrapeStatus, name="scrape_status", values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=ScrapeStatus.PENDING,
    )
    celery_task_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    scraped_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    inserted_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
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
    cron_run_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("cron_runs.id"),
        nullable=True,
    )
    parent_gdp_job_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("gdp_report_jobs.id", ondelete="SET NULL"),
        nullable=True,
    )
    # Set when the orchestrator wants an EPUS scrape for a NIK that has no
    # Patient row yet (e.g. before any data exists for that filter_date).
    # Worker uses (puskesmas_id, target_nik, date_filter) directly when
    # patient_id is null and target_nik is set.
    target_nik: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # JSON list of ISO dates ("YYYY-MM-DD"). When set on an ASIK puskesmas-wide
    # scrape, the worker invokes the ASIK scraper with --dates so it walks every
    # date in one browser session. Mutually exclusive with date_filter for ASIK.
    date_filters: Mapped[str | None] = mapped_column(Text, nullable=True)
    # When True on an ASIK scrape, worker passes --list-only so per-patient
    # form-tab opens are skipped (NIK + Nama only). Used by GDP orchestrator.
    asik_list_only: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # When True on an ASIK scrape, worker passes --mandiri-only so ONLY the
    # Pemeriksaan Mandiri forms are opened (Nakes + Tatalaksana skipped) and the
    # ingestion patches the existing scraped_asik_data blob instead of replacing
    # it. Used by the Mandiri-only date-range backfill (cron_backfills.mandiri_only).
    asik_mandiri_only: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # JSON list of NIKs. When set on an EPUS multi-date scrape, the worker
    # passes --niks so the scraper iterates niks × dates with searchKey={nik}
    # filter applied per (date, nik). Used by GDP orchestrator after ASIK
    # phase to restrict EPUS scrape to NIKs that came back from ASIK.
    target_niks: Mapped[str | None] = mapped_column(Text, nullable=True)

    puskesmas: Mapped["Puskesmas"] = relationship()
    patient: Mapped["Patient | None"] = relationship()
