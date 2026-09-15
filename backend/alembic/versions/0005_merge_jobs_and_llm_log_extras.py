"""merge_jobs + patient.merged_data + llm_logs extras

Revision ID: 0005_merge_jobs_and_llm_log_extras
Revises: 0004_llm_configs_and_logs
Create Date: 2026-04-28 00:00:00

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005_merge_jobs"
down_revision: str | None = "0004_llm_configs_and_logs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


MERGE_STATUS_VALUES = ("pending", "running", "success", "failed", "cancelled")


def upgrade() -> None:
    merge_status = postgresql.ENUM(*MERGE_STATUS_VALUES, name="merge_status", create_type=False)
    triggerer_type = postgresql.ENUM(name="triggerer_type", create_type=False)

    bind = op.get_bind()
    merge_status.create(bind, checkfirst=True)

    op.create_table(
        "merge_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "puskesmas_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("puskesmas.id"),
            nullable=False,
        ),
        sa.Column("triggered_by_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("triggered_by_type", triggerer_type, nullable=False),
        sa.Column("date_filter", sa.String(length=16), nullable=False),
        sa.Column("status", merge_status, nullable=False),
        sa.Column("celery_task_id", sa.String(length=64), nullable=True),
        sa.Column(
            "force_remerge",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("total_count", sa.Integer(), nullable=True),
        sa.Column("processed_count", sa.Integer(), nullable=True),
        sa.Column("succeeded_count", sa.Integer(), nullable=True),
        sa.Column("failed_count", sa.Integer(), nullable=True),
        sa.Column("skipped_count", sa.Integer(), nullable=True),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        "CREATE INDEX ix_merge_jobs_pid_created ON merge_jobs (puskesmas_id, created_at DESC) "
        "WHERE deleted_at IS NULL"
    )
    op.execute(
        "CREATE INDEX ix_merge_jobs_pid_status ON merge_jobs (puskesmas_id, status) "
        "WHERE deleted_at IS NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_merge_jobs_active_per_puskesmas_date "
        "ON merge_jobs (puskesmas_id, date_filter) "
        "WHERE status IN ('pending','running') AND deleted_at IS NULL"
    )
    op.add_column("patients", sa.Column("merged_data", sa.LargeBinary(), nullable=True))
    op.add_column(
        "patients",
        sa.Column("merged_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        "CREATE INDEX ix_patients_merged_at ON patients (merged_at) "
        "WHERE deleted_at IS NULL AND merged_at IS NOT NULL"
    )

    op.add_column(
        "llm_logs",
        sa.Column(
            "merge_job_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("merge_jobs.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "llm_logs",
        sa.Column(
            "patient_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("patients.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "llm_logs",
        sa.Column(
            "puskesmas_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("puskesmas.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    # Backfill puskesmas_id on pre-existing llm_logs rows from their job ref.
    op.execute(
        "UPDATE llm_logs l SET puskesmas_id = s.puskesmas_id "
        "FROM scrape_jobs s WHERE l.scrape_job_id = s.id AND l.puskesmas_id IS NULL"
    )
    op.execute("CREATE INDEX ix_llm_logs_merge_job_id ON llm_logs (merge_job_id)")
    op.execute("CREATE INDEX ix_llm_logs_patient_id ON llm_logs (patient_id)")
    op.execute("CREATE INDEX ix_llm_logs_puskesmas_id ON llm_logs (puskesmas_id)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_llm_logs_puskesmas_id")
    op.execute("DROP INDEX IF EXISTS ix_llm_logs_patient_id")
    op.execute("DROP INDEX IF EXISTS ix_llm_logs_merge_job_id")
    op.drop_column("llm_logs", "puskesmas_id")
    op.drop_column("llm_logs", "patient_id")
    op.drop_column("llm_logs", "merge_job_id")

    op.execute("DROP INDEX IF EXISTS ix_patients_merged_at")
    op.drop_column("patients", "merged_at")
    op.drop_column("patients", "merged_data")

    op.execute("DROP INDEX IF EXISTS uq_merge_jobs_active_per_puskesmas_date")
    op.execute("DROP INDEX IF EXISTS ix_merge_jobs_pid_status")
    op.execute("DROP INDEX IF EXISTS ix_merge_jobs_pid_created")
    op.drop_table("merge_jobs")

    bind = op.get_bind()
    postgresql.ENUM(name="merge_status").drop(bind, checkfirst=True)
