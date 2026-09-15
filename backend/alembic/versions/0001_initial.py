"""initial schema: puskesmas, admins, users

Revision ID: 0001_initial
Revises:
Create Date: 2026-04-25 00:00:00

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    op.create_table(
        "puskesmas",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("epus_url", sa.String(), nullable=True),
        sa.Column("asik_url", sa.String(), nullable=True),
        sa.Column("epus_cred", sa.LargeBinary(), nullable=True),
        sa.Column("asik_cred", sa.LargeBinary(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_puskesmas_deleted_at", "puskesmas", ["deleted_at"])
    op.execute(
        "CREATE INDEX ix_puskesmas_created ON puskesmas (created_at DESC) "
        "WHERE deleted_at IS NULL"
    )
    op.execute(
        "CREATE INDEX ix_puskesmas_name_trgm ON puskesmas USING gin (name gin_trgm_ops)"
    )

    op.create_table(
        "admins",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("password_hash", sa.String(), nullable=False),
        sa.Column("full_name", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("email"),
    )
    op.create_index("ix_admins_email", "admins", ["email"])
    op.create_index("ix_admins_deleted_at", "admins", ["deleted_at"])

    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("password_hash", sa.String(), nullable=False),
        sa.Column("full_name", sa.String(), nullable=False),
        sa.Column(
            "puskesmas_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("puskesmas.id"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("email"),
    )
    op.create_index("ix_users_email", "users", ["email"])
    op.create_index("ix_users_puskesmas_id", "users", ["puskesmas_id"])
    op.create_index("ix_users_deleted_at", "users", ["deleted_at"])
    op.execute(
        "CREATE INDEX ix_users_created ON users (created_at DESC) "
        "WHERE deleted_at IS NULL"
    )
    op.execute(
        "CREATE INDEX ix_users_full_name_trgm ON users USING gin (full_name gin_trgm_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_users_full_name_trgm")
    op.execute("DROP INDEX IF EXISTS ix_users_created")
    op.drop_index("ix_users_deleted_at", table_name="users")
    op.drop_index("ix_users_puskesmas_id", table_name="users")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
    op.drop_index("ix_admins_deleted_at", table_name="admins")
    op.drop_index("ix_admins_email", table_name="admins")
    op.drop_table("admins")
    op.execute("DROP INDEX IF EXISTS ix_puskesmas_name_trgm")
    op.execute("DROP INDEX IF EXISTS ix_puskesmas_created")
    op.drop_index("ix_puskesmas_deleted_at", table_name="puskesmas")
    op.drop_table("puskesmas")
