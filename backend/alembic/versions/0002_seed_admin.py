"""seed root admin from env

Revision ID: 0002_seed_admin
Revises: 0001_initial
Create Date: 2026-04-25 00:00:01

"""
import uuid
from collections.abc import Sequence

import bcrypt
import sqlalchemy as sa
from alembic import op

from app.config import settings

revision: str = "0002_seed_admin"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    pw_hash = bcrypt.hashpw(
        settings.ADMIN_PASSWORD.encode("utf-8"), bcrypt.gensalt()
    ).decode("utf-8")
    bind.execute(
        sa.text(
            "INSERT INTO admins (id, email, password_hash, full_name, created_at, updated_at) "
            "VALUES (:id, :email, :pw, :name, now(), now()) "
            "ON CONFLICT (email) DO NOTHING"
        ),
        {
            "id": uuid.uuid4(),
            "email": settings.ADMIN_EMAIL,
            "pw": pw_hash,
            "name": settings.ADMIN_FULL_NAME,
        },
    )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text("DELETE FROM admins WHERE email = :email"),
        {"email": settings.ADMIN_EMAIL},
    )
