"""per-NIK scrape and merge jobs

Revision ID: 0009_per_nik_jobs
Revises: 0008_sync_jobs
Create Date: 2026-04-30 00:00:00

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009_per_nik_jobs"
down_revision: str | None = "0008_sync_jobs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # scrape_jobs: nullable patient_id + nullable date_filter (per-NIK ASIK has no date)
    op.add_column(
        "scrape_jobs",
        sa.Column(
            "patient_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("patients.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.alter_column("scrape_jobs", "date_filter", existing_type=sa.String(length=16), nullable=True)
    op.execute(
        "CREATE INDEX ix_scrape_jobs_patient_id ON scrape_jobs (patient_id) "
        "WHERE deleted_at IS NULL"
    )

    # Replace the single (puskesmas_id, kind) in-flight uniqueness with two indexes:
    #   ASIK: one slot per puskesmas regardless of patient_id (shared session dir).
    #   EPUS wide: one slot when patient_id IS NULL.
    #   EPUS per-NIK: one slot per (puskesmas, patient).
    op.execute("DROP INDEX IF EXISTS uq_scrape_jobs_active_per_puskesmas_kind")
    op.execute(
        "CREATE UNIQUE INDEX uq_scrape_jobs_active_asik_per_puskesmas "
        "ON scrape_jobs (puskesmas_id) "
        "WHERE kind = 'asik' AND status IN ('pending','running') AND deleted_at IS NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_scrape_jobs_active_epus_wide "
        "ON scrape_jobs (puskesmas_id) "
        "WHERE kind = 'epus' AND patient_id IS NULL "
        "AND status IN ('pending','running') AND deleted_at IS NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_scrape_jobs_active_epus_per_patient "
        "ON scrape_jobs (puskesmas_id, patient_id) "
        "WHERE kind = 'epus' AND patient_id IS NOT NULL "
        "AND status IN ('pending','running') AND deleted_at IS NULL"
    )

    # merge_jobs: nullable patient_id + nullable date_filter (per-NIK has no date)
    op.add_column(
        "merge_jobs",
        sa.Column(
            "patient_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("patients.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.alter_column("merge_jobs", "date_filter", existing_type=sa.String(length=16), nullable=True)
    op.execute(
        "CREATE INDEX ix_merge_jobs_patient_id ON merge_jobs (patient_id) "
        "WHERE deleted_at IS NULL"
    )

    op.execute("DROP INDEX IF EXISTS uq_merge_jobs_active_per_puskesmas_date")
    op.execute(
        "CREATE UNIQUE INDEX uq_merge_jobs_active_wide "
        "ON merge_jobs (puskesmas_id, date_filter) "
        "WHERE patient_id IS NULL AND status IN ('pending','running') AND deleted_at IS NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_merge_jobs_active_per_patient "
        "ON merge_jobs (puskesmas_id, patient_id) "
        "WHERE patient_id IS NOT NULL AND status IN ('pending','running') AND deleted_at IS NULL"
    )

    op.execute("ALTER TABLE scrape_jobs DROP COLUMN IF EXISTS full_output")


def downgrade() -> None:
    op.execute("ALTER TABLE scrape_jobs ADD COLUMN IF NOT EXISTS full_output BYTEA")

    op.execute("DROP INDEX IF EXISTS uq_merge_jobs_active_per_patient")
    op.execute("DROP INDEX IF EXISTS uq_merge_jobs_active_wide")
    op.execute(
        "CREATE UNIQUE INDEX uq_merge_jobs_active_per_puskesmas_date "
        "ON merge_jobs (puskesmas_id, date_filter) "
        "WHERE status IN ('pending','running') AND deleted_at IS NULL"
    )
    op.execute("DROP INDEX IF EXISTS ix_merge_jobs_patient_id")
    op.alter_column("merge_jobs", "date_filter", existing_type=sa.String(length=16), nullable=False)
    op.drop_column("merge_jobs", "patient_id")

    op.execute("DROP INDEX IF EXISTS uq_scrape_jobs_active_epus_per_patient")
    op.execute("DROP INDEX IF EXISTS uq_scrape_jobs_active_epus_wide")
    op.execute("DROP INDEX IF EXISTS uq_scrape_jobs_active_asik_per_puskesmas")
    op.execute(
        "CREATE UNIQUE INDEX uq_scrape_jobs_active_per_puskesmas_kind "
        "ON scrape_jobs (puskesmas_id, kind) "
        "WHERE status IN ('pending','running') AND deleted_at IS NULL"
    )
    op.execute("DROP INDEX IF EXISTS ix_scrape_jobs_patient_id")
    op.alter_column("scrape_jobs", "date_filter", existing_type=sa.String(length=16), nullable=False)
    op.drop_column("scrape_jobs", "patient_id")
