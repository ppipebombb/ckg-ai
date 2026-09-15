import enum
import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Date, DateTime, Enum as SAEnum
from sqlalchemy import ForeignKey, Integer, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import SoftDeleteMixin, TimestampMixin, UUIDPKMixin
from app.models.cron_config import CronSourceScope

if TYPE_CHECKING:
    from app.models.cron_backfill import CronBackfill
    from app.models.cron_config import CronConfig
    from app.models.merge_job import MergeJob
    from app.models.puskesmas import Puskesmas
    from app.models.scrape_job import ScrapeJob


class CronRunStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


class CronStep(str, enum.Enum):
    ASIK = "asik"
    EPUS = "epus"
    MERGE = "merge"
    # Optional final step: push merged data into ASIK for this puskesmas+date.
    # Runs after MERGE only when the parent config/backfill has sync_mode != OFF.
    SYNC = "sync"
    # Optional step AFTER sync: register this date's epus_only + tandai_ckg patients
    # into ASIK (create), then fill them. Runs only when create_new is set (which is
    # itself gated on sync_mode != OFF). Same one-ASIK-session lane as SYNC.
    CREATE = "create"


class CronRun(UUIDPKMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "cron_runs"

    cron_config_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("cron_configs.id"),
        nullable=True,
    )
    cron_backfill_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("cron_backfills.id"),
        nullable=True,
    )
    puskesmas_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("puskesmas.id"),
        nullable=False,
    )
    target_date: Mapped[date] = mapped_column(Date, nullable=False)
    # Copied from the parent backfill at creation (BOTH for config/run-now runs).
    # Drives the scope-aware step machine and the two lane partial-unique indexes
    # (uq_cron_runs_active_epus / _asik) — see CronSourceScope.
    source_scope: Mapped[CronSourceScope] = mapped_column(
        SAEnum(
            CronSourceScope,
            name="cron_source_scope",
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
        default=CronSourceScope.BOTH,
    )
    status: Mapped[CronRunStatus] = mapped_column(
        SAEnum(
            CronRunStatus,
            name="cron_run_status",
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
        default=CronRunStatus.PENDING,
    )
    current_step: Mapped[CronStep | None] = mapped_column(
        SAEnum(CronStep, name="cron_step", values_callable=lambda x: [e.value for e in x]),
        nullable=True,
    )
    current_step_attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_step: Mapped[CronStep | None] = mapped_column(
        # create_type=False — current_step above already declares the type;
        # a second create-attempt would explode under metadata.create_all().
        SAEnum(
            CronStep,
            name="cron_step",
            values_callable=lambda x: [e.value for e in x],
            create_type=False,
        ),
        nullable=True,
    )
    asik_scrape_job_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("scrape_jobs.id"),
        nullable=True,
    )
    epus_scrape_job_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("scrape_jobs.id"),
        nullable=True,
    )
    merge_job_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("merge_jobs.id"),
        nullable=True,
    )
    triggered_by_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    # Eligible patients at the moment the SYNC step started — the denominator for
    # sync progress. SyncJobs are created lazily (one per patient as the batch
    # reaches it, so a crash leaves no wedged PENDING rows), so counting them
    # gives the progress so far, never the target.
    sync_total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    cron_config: Mapped["CronConfig | None"] = relationship()
    cron_backfill: Mapped["CronBackfill | None"] = relationship(
        foreign_keys=[cron_backfill_id]
    )
    puskesmas: Mapped["Puskesmas"] = relationship()
    asik_scrape_job: Mapped["ScrapeJob | None"] = relationship(
        foreign_keys=[asik_scrape_job_id]
    )
    epus_scrape_job: Mapped["ScrapeJob | None"] = relationship(
        foreign_keys=[epus_scrape_job_id]
    )
    merge_job: Mapped["MergeJob | None"] = relationship(foreign_keys=[merge_job_id])
