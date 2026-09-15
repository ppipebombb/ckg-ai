import enum
import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Date, DateTime, Enum as SAEnum
from sqlalchemy import ForeignKey, LargeBinary, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import SoftDeleteMixin, TimestampMixin, UUIDPKMixin

if TYPE_CHECKING:
    from app.models.puskesmas import Puskesmas


class MatchStatus(str, enum.Enum):
    ASIK_ONLY = "asik_only"
    EPUS_ONLY = "epus_only"
    MATCHED = "matched"


class Patient(UUIDPKMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "patients"

    puskesmas_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("puskesmas.id"),
        nullable=False,
    )
    nik: Mapped[str] = mapped_column(String(32), nullable=False)
    nama: Mapped[str] = mapped_column(String(255), nullable=False)
    match_status: Mapped[MatchStatus] = mapped_column(
        SAEnum(MatchStatus, name="match_status", values_callable=lambda x: [e.value for e in x]),
        nullable=False,
    )
    scraped_asik_data: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    scraped_epus_data: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    merged_data: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    merged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    filter_date: Mapped[date] = mapped_column(Date, nullable=False)
    ruangan: Mapped[str] = mapped_column(String(64), nullable=False, server_default="")
    # Denormalized birth date for the umur/age list filter. EPUS-wins:
    # scraped_epus_data "Tempat/Tgl Lahir", else scraped_asik_data
    # data_individu "Tanggal Lahir" (see services/birthdate.py). NULL = no
    # parseable birth date in any blob; such rows are excluded when an age
    # bound is active. Set by the scrape write-path and the one-time backfill.
    birth_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    # CKG (Cek Kesehatan Gratis) "sudah CKG" flag for this visit's year,
    # denormalized from scraped_epus_data["ckg"]["sudah_ckg"] so the Visit
    # Summary can COUNT it without decrypting blobs. NULL = no EPUS data / no
    # ckg key yet.
    epus_tandai_ckg: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    # Two physical rows that represent the same real-world visit but were
    # scraped on different filter_dates (ASIK lags EPUS by days–weeks) share
    # one match_group_id. NULL = no cross-date twin (single-row visit).
    match_group_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True, index=True,
    )
    # Cross-reference flag: this NIK also has a CKG Sekolah record (school
    # health checkup) in school_patients, set by the asik_sekolah scrape
    # upsert. NULL = never checked / no school record. Orthogonal to
    # match_status (which only encodes the ASIK-umum↔EPUS pairing) — school CKG
    # is a separate program stored in school_patients, not here.
    is_ckg_sekolah: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    # Denormalized "this ASIK blob has a non-empty pemeriksaan_mandiri[]" flag,
    # set by the scrape write-path (_upsert_asik) and the Mandiri patch. Lets the
    # Mandiri-only backfill find NIKs still missing self-exam data with cheap SQL
    # (the blob is encrypted and can't be filtered in-DB). False = no Mandiri yet.
    has_mandiri: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false",
    )
    # Log of default values the ASIK sync pushed for REQUIRED questions we had no
    # data for. List of {layanan, question, value, kind}. Unencrypted — it's
    # metadata about what we auto-filled, not clinical data. NULL = never synced /
    # no defaults needed. Overwritten on each successful sync. See
    # app/services/asik_defaults.py + ASIK_DEFAULT_FILLS.md.
    asik_default_fills: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    # Timestamp of the last SUCCESSFUL ASIK sync (manual button or cron sync step).
    # NULL = never synced. The cron sync step in NORMAL mode skips patients whose
    # asik_synced_at is set; FORCE_RESYNC ignores it. Set on sync success only.
    asik_synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    puskesmas: Mapped["Puskesmas"] = relationship()

    __table_args__ = (
        UniqueConstraint(
            "puskesmas_id", "nik", "filter_date", "ruangan",
            name="uq_patient_puskesmas_nik_date_ruangan",
        ),
    )
