"""cron_backfills.cron_config_id — link scheduled backfills to their config

dispatch_due spawns a CronBackfill per scheduled fire; this nullable FK ties it to
the originating cron config so disabling/deleting the config cancels its in-flight
scheduled backfill. Manual date-range backfills leave it NULL and are untouched.

Revision ID: 0031_backfill_cron_config_link
Revises: 0030_cron_lookback_days
Create Date: 2026-07-21 00:03:00

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0031_backfill_cron_config_link"
down_revision: str | None = "0030_cron_lookback_days"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "cron_backfills",
        sa.Column("cron_config_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_cron_backfills_cron_config_id",
        "cron_backfills",
        "cron_configs",
        ["cron_config_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_cron_backfills_cron_config_id", "cron_backfills", type_="foreignkey"
    )
    op.drop_column("cron_backfills", "cron_config_id")
