"""cron_step enum: add 'sync' value

The optional ASIK sync step (see 0028) is a new CronStep. Postgres enum values
can't be added inside a transaction block, so this runs in an autocommit block,
separate from 0028's transactional column adds.

Revision ID: 0029_cron_step_sync
Revises: 0028_cron_sync_mode
Create Date: 2026-07-21 00:01:00

"""
from collections.abc import Sequence

from alembic import op

revision: str = "0029_cron_step_sync"
down_revision: str | None = "0028_cron_sync_mode"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ADD VALUE cannot run inside a transaction block; autocommit_block exits the
    # migration's transaction for just this statement. IF NOT EXISTS makes it
    # idempotent across reruns.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE cron_step ADD VALUE IF NOT EXISTS 'sync'")


def downgrade() -> None:
    # Postgres has no DROP VALUE for enums; removing 'sync' would require
    # recreating the cron_step type and rewriting cron_runs.current_step /
    # failed_step. The unused value is harmless, so downgrade is a no-op.
    pass
