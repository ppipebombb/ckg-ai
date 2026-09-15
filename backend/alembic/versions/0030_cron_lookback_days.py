"""cron_configs.lookback_days — scheduled rolling lookback window

Each scheduled cron fire re-processes the last N days ([target - (N-1) .. target])
by spawning a CronBackfill over that window, so late-arriving EPUS/ASIK that only
match a past date once both sides land gets re-scraped + re-merged. Default 3.

Revision ID: 0030_cron_lookback_days
Revises: 0029_cron_step_sync
Create Date: 2026-07-21 00:02:00

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0030_cron_lookback_days"
down_revision: str | None = "0029_cron_step_sync"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "cron_configs",
        sa.Column(
            "lookback_days",
            sa.Integer(),
            nullable=False,
            server_default="3",
        ),
    )


def downgrade() -> None:
    op.drop_column("cron_configs", "lookback_days")
