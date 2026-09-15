"""cron create_new toggle: cron_step 'create' value + create_new columns

The optional ASIK CREATE step (register this date's epus_only + tandai_ckg patients
into ASIK, then fill — runs AFTER the sync step) is a new CronStep, plus a create_new
bool on cron_configs and cron_backfills. Postgres enum values can't be added inside a
transaction block, so the ADD VALUE runs in an autocommit block; the columns are added
transactionally after.

Revision ID: 0035_cron_create_new
Revises: 0034_puskesmas_default_alamat
Create Date: 2026-08-06

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0035_cron_create_new"
down_revision: str | None = "0034_puskesmas_default_alamat"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ADD VALUE cannot run inside a transaction block; autocommit_block exits the
    # migration's transaction for just this statement. IF NOT EXISTS = idempotent.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE cron_step ADD VALUE IF NOT EXISTS 'create'")
    op.add_column(
        "cron_configs",
        sa.Column("create_new", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "cron_backfills",
        sa.Column("create_new", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("cron_backfills", "create_new")
    op.drop_column("cron_configs", "create_new")
    # Postgres has no DROP VALUE for enums; the unused 'create' value is harmless.
