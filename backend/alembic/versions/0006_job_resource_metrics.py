"""Add CPU/RAM resource metric columns to scrape_jobs and merge_jobs

Revision ID: 0006_job_resource_metrics
Revises: 0005_merge_jobs
Create Date: 2026-04-28 00:00:00

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_job_resource_metrics"
down_revision: str | None = "0005_merge_jobs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for table in ("scrape_jobs", "merge_jobs"):
        op.add_column(table, sa.Column("cpu_avg_pct", sa.Float(), nullable=True))
        op.add_column(table, sa.Column("cpu_peak_pct", sa.Float(), nullable=True))
        op.add_column(table, sa.Column("mem_avg_mb", sa.Float(), nullable=True))
        op.add_column(table, sa.Column("mem_peak_mb", sa.Float(), nullable=True))
        op.add_column(table, sa.Column("resource_samples", sa.Integer(), nullable=True))

    # Capacity stats endpoints aggregate by (status, finished_at) over a
    # rolling window. Without these indexes the queries full-scan job tables.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_scrape_jobs_status_finished_at "
        "ON scrape_jobs (status, finished_at) WHERE deleted_at IS NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_merge_jobs_status_finished_at "
        "ON merge_jobs (status, finished_at) WHERE deleted_at IS NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_merge_jobs_status_finished_at")
    op.execute("DROP INDEX IF EXISTS ix_scrape_jobs_status_finished_at")

    for table in ("scrape_jobs", "merge_jobs"):
        op.drop_column(table, "resource_samples")
        op.drop_column(table, "mem_peak_mb")
        op.drop_column(table, "mem_avg_mb")
        op.drop_column(table, "cpu_peak_pct")
        op.drop_column(table, "cpu_avg_pct")
