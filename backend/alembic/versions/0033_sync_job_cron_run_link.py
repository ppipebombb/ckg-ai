"""sync_jobs.cron_run_id + cron_runs.sync_total — cron-run sync progress

The cron-run detail page can show scrape and merge progress but goes dark during
SYNC, which is the longest step of a sync-only backfill. Two columns fix that:

- `sync_jobs.cron_run_id` attributes each per-patient SyncJob to the run that
  spawned it (NULL for manual syncs from the patient detail page).
- `cron_runs.sync_total` is the DENOMINATOR, stamped once when the sync step
  starts. It cannot be derived by counting SyncJobs: they are created lazily,
  one per patient as the batch reaches it, precisely so a crash does not leave
  N pre-created PENDING rows wedged behind uq_sync_jobs_active_per_patient.
  Without it, progress would read "3/3 done" when 3 of 200 had started.

The index is partial on cron_run_id IS NOT NULL — manual syncs are the majority
of rows over time and never participate in this lookup.

Revision ID: 0033_sync_job_cron_run_link
Revises: 0032_source_scope_none
Create Date: 2026-07-22 16:40:00

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0033_sync_job_cron_run_link"
down_revision: str | None = "0032_source_scope_none"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "sync_jobs",
        sa.Column("cron_run_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_sync_jobs_cron_run_id", "sync_jobs", "cron_runs", ["cron_run_id"], ["id"]
    )
    op.execute(
        "CREATE INDEX ix_sync_jobs_cron_run_status "
        "ON sync_jobs (cron_run_id, status) "
        "WHERE cron_run_id IS NOT NULL AND deleted_at IS NULL"
    )
    op.add_column("cron_runs", sa.Column("sync_total", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("cron_runs", "sync_total")
    op.execute("DROP INDEX IF EXISTS ix_sync_jobs_cron_run_status")
    op.drop_constraint("fk_sync_jobs_cron_run_id", "sync_jobs", type_="foreignkey")
    op.drop_column("sync_jobs", "cron_run_id")
