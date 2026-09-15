import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import SoftDeleteMixin, TimestampMixin, UUIDPKMixin

if TYPE_CHECKING:
    from app.models.puskesmas import Puskesmas


class SchoolCronConfig(UUIDPKMixin, TimestampMixin, SoftDeleteMixin, Base):
    """Schedule for the date-less CKG-Sekolah scrape.

    Deliberately separate from CronConfig: that one drives the date-based
    EPUS→ASIK→merge step machine (target_offset_days, merge_mode), none of which
    applies to school CKG. Here a fire simply creates one asik_sekolah ScrapeJob
    (date_filter NULL) that dynamically walks every school × class. One live
    config per puskesmas (partial unique index in the migration).
    """
    __tablename__ = "school_cron_configs"

    puskesmas_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("puskesmas.id"),
        nullable=False,
    )
    hour: Mapped[int] = mapped_column(Integer, nullable=False)
    minute: Mapped[int] = mapped_column(Integer, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    next_run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_fired_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    puskesmas: Mapped["Puskesmas"] = relationship()
