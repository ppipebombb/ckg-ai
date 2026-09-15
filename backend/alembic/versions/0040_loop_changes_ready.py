"""loop agent: changes_ready status + per-run PR decision

- loop_run_status gains 'changes_ready': code changed and the branch is
  pushed, but auto_open_pr was off (config default or per-run override) —
  work is safe on GitHub, a human opens the PR from the dashboard.
- loop_runs.open_pr stores the per-run PR decision resolved at creation
  (NULL = follow loop_config.auto_open_pr; manual runs store the explicit
  choice), so a config change mid-run cannot flip what the runner does.
- loop_config.auto_open_pr is the fleet default for that decision.

Revision ID: 0040_loop_changes_ready
Revises: 0039_loop_coverage_findings
Create Date: 2026-09-11

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0040_loop_changes_ready"
down_revision: str | None = "0039_loop_coverage_findings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Postgres cannot add an enum value inside a transaction block.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE loop_run_status ADD VALUE IF NOT EXISTS 'changes_ready'")
    op.add_column("loop_runs", sa.Column("open_pr", sa.Boolean(), nullable=True))
    op.add_column(
        "loop_config",
        sa.Column("auto_open_pr", sa.Boolean(), nullable=False, server_default=sa.true()),
    )


def downgrade() -> None:
    # Postgres has no DROP VALUE; the unused 'changes_ready' label is harmless.
    op.drop_column("loop_config", "auto_open_pr")
    op.drop_column("loop_runs", "open_pr")
