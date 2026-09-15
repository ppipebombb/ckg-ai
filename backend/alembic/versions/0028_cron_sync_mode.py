"""cron_configs/cron_backfills.sync_mode + patients.asik_synced_at

Adds an optional ASIK sync step to cron runs. `sync_mode` (off | normal |
force_resync) on both cron_configs and cron_backfills controls whether a run
pushes merged data into ASIK after the merge step, and whether it re-syncs
already-synced patients. `patients.asik_synced_at` records the last successful
sync so NORMAL mode can skip already-synced patients (FORCE_RESYNC ignores it).

Revision ID: 0028_cron_sync_mode
Revises: 0027_asik_default_fills
Create Date: 2026-07-21 00:00:00

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0028_cron_sync_mode"
down_revision: str | None = "0027_asik_default_fills"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


CRON_SYNC_MODE_VALUES = ("off", "normal", "force_resync")
_TABLES = ("cron_configs", "cron_backfills")


def upgrade() -> None:
    bind = op.get_bind()
    sync_mode = postgresql.ENUM(
        *CRON_SYNC_MODE_VALUES, name="cron_sync_mode", create_type=False
    )
    sync_mode.create(bind, checkfirst=True)

    for table in _TABLES:
        op.add_column(
            table,
            sa.Column(
                "sync_mode",
                sync_mode,
                nullable=False,
                server_default="off",
            ),
        )

    op.add_column(
        "patients",
        sa.Column(
            "asik_synced_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("patients", "asik_synced_at")
    for table in _TABLES:
        op.drop_column(table, "sync_mode")
    postgresql.ENUM(name="cron_sync_mode").drop(op.get_bind(), checkfirst=True)
