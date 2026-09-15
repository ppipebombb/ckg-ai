from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, LargeBinary
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import SoftDeleteMixin, TimestampMixin, UUIDPKMixin

if TYPE_CHECKING:
    from app.models.user import User


class Puskesmas(UUIDPKMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "puskesmas"

    name: Mapped[str] = mapped_column(nullable=False)
    epus_url: Mapped[str | None] = mapped_column(nullable=True)
    asik_url: Mapped[str | None] = mapped_column(nullable=True)
    epus_cred: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    asik_cred: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)

    # Default domicile for the ASIK "create new patient" flow: ePus has only a
    # free-text address and the ASIK registration step-2 "Alamat Domisili" is a
    # 4-level Provinsi/Kota/Kecamatan/Kelurahan cascade, so we store the
    # puskesmas' own location (picked from ASIK's teritorial-service list, so the
    # names match the cascade exactly) as the fallback. Shape:
    # {"provinsi": {"name","code"}, "kota": {...}, "kecamatan": {...}, "kelurahan": {...}}.
    asik_default_alamat: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Loop-agent bookkeeping. Stamped ONLY when a run reaches a real verdict
    # (covered / no_data) — never on bad_login/failed, so those retry on the
    # nightly sweep until a human fixes the cause. There is deliberately no
    # cooldown: the nightly selection picks rows where this IS NULL.
    last_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    users: Mapped[list["User"]] = relationship(back_populates="puskesmas")
