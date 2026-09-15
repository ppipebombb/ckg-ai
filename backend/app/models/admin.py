from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import SoftDeleteMixin, TimestampMixin, UUIDPKMixin


class Admin(UUIDPKMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "admins"

    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(nullable=False)
    full_name: Mapped[str] = mapped_column(nullable=False)
    # Login partition: "internal" admins use /admin/auth, "prod" admins use
    # /prod/auth (the external frontend-dashboard app). Both carry full admin
    # privileges once authenticated; the split is enforced only at login.
    scope: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="internal"
    )
