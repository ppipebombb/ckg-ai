"""admins.scope (login partition) + seed prod admin from env

Adds the `scope` column to admins ("internal" default; "prod" for the external
frontend-dashboard app) and seeds one prod admin from PROD_ADMIN_* env vars. If those
env vars are unset the seed is skipped (no insecure default account) — the column
is still added so existing admins become "internal".

Revision ID: 0019_admin_scope
Revises: 0018_patient_epus_tandai_ckg
Create Date: 2026-06-05 00:00:00

"""
import uuid
from collections.abc import Sequence

import bcrypt
import sqlalchemy as sa
from alembic import op

from app.config import settings

revision: str = "0019_admin_scope"
down_revision: str | None = "0018_patient_epus_tandai_ckg"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "admins",
        sa.Column(
            "scope", sa.String(length=16), nullable=False, server_default="internal"
        ),
    )

    if not settings.PROD_ADMIN_EMAIL or not settings.PROD_ADMIN_PASSWORD:
        return

    bind = op.get_bind()
    pw_hash = bcrypt.hashpw(
        settings.PROD_ADMIN_PASSWORD.encode("utf-8"), bcrypt.gensalt()
    ).decode("utf-8")
    bind.execute(
        sa.text(
            "INSERT INTO admins "
            "(id, email, password_hash, full_name, scope, created_at, updated_at) "
            "VALUES (:id, :email, :pw, :name, 'prod', now(), now()) "
            "ON CONFLICT (email) DO NOTHING"
        ),
        {
            "id": uuid.uuid4(),
            "email": settings.PROD_ADMIN_EMAIL,
            "pw": pw_hash,
            "name": settings.PROD_ADMIN_FULL_NAME,
        },
    )


def downgrade() -> None:
    bind = op.get_bind()
    if settings.PROD_ADMIN_EMAIL:
        bind.execute(
            sa.text("DELETE FROM admins WHERE email = :email"),
            {"email": settings.PROD_ADMIN_EMAIL},
        )
    op.drop_column("admins", "scope")
