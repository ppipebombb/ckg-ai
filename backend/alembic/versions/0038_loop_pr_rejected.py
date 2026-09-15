"""loop agent: pr_rejected status + one-active-run-per-puskesmas index

- loop_run_status gains 'pr_rejected' (a fix PR closed unmerged); the nightly
  sweep re-fires it (crud.NIGHTLY_RETRY_STATUSES).
- uq_loop_runs_active_per_puskesmas enforces the PLAN §5.1 rule that was never
  added in 0036: at most one pending/running run per puskesmas.

Revision ID: 0038_loop_pr_rejected
Revises: 0037_llm_route_order
Create Date: 2026-09-02

"""
from collections.abc import Sequence

from alembic import op

revision: str = "0038_loop_pr_rejected"
down_revision: str | None = "0037_llm_route_order"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Postgres cannot add an enum value inside a transaction block.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE loop_run_status ADD VALUE IF NOT EXISTS 'pr_rejected'")
    op.execute(
        "CREATE UNIQUE INDEX uq_loop_runs_active_per_puskesmas "
        "ON loop_runs (puskesmas_id) "
        "WHERE status IN ('pending', 'running') AND deleted_at IS NULL"
    )


def downgrade() -> None:
    # Postgres has no DROP VALUE; the 'pr_rejected' label is left in place.
    op.execute("DROP INDEX IF EXISTS uq_loop_runs_active_per_puskesmas")
