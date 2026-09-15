import enum
import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime
from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, Integer, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import SoftDeleteMixin, TimestampMixin, UUIDPKMixin
from app.models.cron_config import CronMergeMode, CronSourceScope, CronSyncMode

if TYPE_CHECKING:
    from app.models.cron_run import CronRun
    from app.models.puskesmas import Puskesmas


class CronBackfillStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


class CronBackfill(UUIDPKMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "cron_backfills"
    __table_args__ = (
        CheckConstraint(
            "date_from <= date_to", name="ck_cron_backfills_date_range"
        ),
    )

    puskesmas_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("puskesmas.id"),
        nullable=False,
    )
    date_from: Mapped[date] = mapped_column(Date, nullable=False)
    date_to: Mapped[date] = mapped_column(Date, nullable=False)
    cursor_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[CronBackfillStatus] = mapped_column(
        SAEnum(
            CronBackfillStatus,
            name="cron_backfill_status",
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
        default=CronBackfillStatus.PENDING,
    )
    merge_mode: Mapped[CronMergeMode] = mapped_column(
        SAEnum(
            CronMergeMode,
            name="cron_merge_mode",
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
        default=CronMergeMode.NORMAL,
    )
    source_scope: Mapped[CronSourceScope] = mapped_column(
        SAEnum(
            CronSourceScope,
            name="cron_source_scope",
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
        default=CronSourceScope.BOTH,
    )
    # Pemeriksaan Mandiri-only backfill: the per-date ASIK child scrapes ONLY the
    # Mandiri forms for NIKs already in our DB that still lack Mandiri, and the
    # ingestion patches the existing blob (no Nakes clobber). Forces
    # source_scope=ASIK_ONLY at creation; merge_mode stays user-selectable
    # (FORCE_REMERGE to surface it, or NO_MERGE for scrape-only).
    mandiri_only: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    # Optional ASIK sync step after merge (per date). OFF by default.
    sync_mode: Mapped[CronSyncMode] = mapped_column(
        SAEnum(
            CronSyncMode,
            name="cron_sync_mode",
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
        default=CronSyncMode.OFF,
    )
    # Optional ASIK create step AFTER sync (per date): register this date's epus_only +
    # tandai_ckg patients into ASIK, then fill. OFF by default; only meaningful when
    # sync_mode != OFF (enforced at create time). Same one-account ASIK lane as sync.
    create_new: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    triggered_by_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    # Set when a scheduled cron config spawned this backfill (NULL for a manual
    # date-range run). Lets disabling/deleting the config cancel its in-flight
    # scheduled backfill (a manual backfill is never touched by config changes).
    cron_config_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("cron_configs.id"),
        nullable=True,
    )
    current_cron_run_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("cron_runs.id"),
        nullable=True,
    )
    total_dates: Mapped[int] = mapped_column(Integer, nullable=False)
    completed_dates: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    failed_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    puskesmas: Mapped["Puskesmas"] = relationship()
    current_cron_run: Mapped["CronRun | None"] = relationship(
        foreign_keys=[current_cron_run_id]
    )
