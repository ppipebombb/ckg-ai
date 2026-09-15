import enum
import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Date, DateTime, Enum as SAEnum
from sqlalchemy import ForeignKey, Integer, LargeBinary, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import SoftDeleteMixin, TimestampMixin, UUIDPKMixin

if TYPE_CHECKING:
    from app.models.puskesmas import Puskesmas


class SchoolScreeningStatus(str, enum.Enum):
    """Which of the three CKG-Sekolah list tabs the student was scraped from.

    Mirrors the portal's Belum / Sedang / Selesai Pemeriksaan tabs.
    """
    BELUM = "belum"
    SEDANG = "sedang"
    SELESAI = "selesai"


class SchoolPatient(UUIDPKMixin, TimestampMixin, SoftDeleteMixin, Base):
    """A CKG Sekolah (school health checkup) student record.

    Kept fully separate from `patients` (the date-keyed CKG-Umum / ASIK↔EPUS
    store): CKG Sekolah has no date — it is filtered by school × class — its
    forms are a different klaster set, and it has no EPUS counterpart to merge.
    Keyed by (puskesmas_id, nik, school_year) so a re-scrape of the same student
    updates in place (annual CKG). A future school↔EPUS merge can join this
    table to `patients` by NIK; for now `patients.is_ckg_sekolah` is set as a
    cheap cross-reference when a NIK matches.
    """
    __tablename__ = "school_patients"

    puskesmas_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("puskesmas.id"),
        nullable=False,
    )
    nik: Mapped[str] = mapped_column(String(32), nullable=False)
    nama: Mapped[str] = mapped_column(String(255), nullable=False)
    born_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    gender: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # CKG year this row represents (from the list row's register_date). Part of
    # the upsert key so next year's checkup is a new row, not an overwrite.
    school_year: Mapped[int] = mapped_column(Integer, nullable=False)

    reg_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ticket_number: Mapped[str | None] = mapped_column(String(32), nullable=True)

    school_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    school_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    category_code: Mapped[str | None] = mapped_column(String(16), nullable=True)
    class_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    klaster_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    klaster_name: Mapped[str | None] = mapped_column(String(128), nullable=True)

    screening_status: Mapped[SchoolScreeningStatus] = mapped_column(
        SAEnum(
            SchoolScreeningStatus,
            name="school_screening_status",
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
    )

    # Encrypted (encrypt_json) full per-student scrape blob: the list row,
    # formatted identity, every Pelayanan-Nakes form's {question: answer}, and
    # tatalaksana. Lossless — decrypt to read the whole record.
    scraped_sekolah_data: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    scraped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    puskesmas: Mapped["Puskesmas"] = relationship()

    __table_args__ = (
        UniqueConstraint(
            "puskesmas_id", "nik", "school_year",
            name="uq_school_patient_puskesmas_nik_year",
        ),
    )
