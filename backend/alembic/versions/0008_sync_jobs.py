"""sync_jobs table for ASIK form-fill sync

Revision ID: 0008_sync_jobs
Revises: 0007_cron_config_and_run
Create Date: 2026-04-29 00:00:00

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008_sync_jobs"
down_revision: str | None = "0007_cron_config_and_run"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


SYNC_STATUS_VALUES = ("pending", "running", "success", "failed", "cancelled")


def upgrade() -> None:
    sync_status = postgresql.ENUM(*SYNC_STATUS_VALUES, name="sync_status", create_type=False)
    triggerer_type = postgresql.ENUM(name="triggerer_type", create_type=False)

    bind = op.get_bind()
    sync_status.create(bind, checkfirst=True)

    op.create_table(
        "sync_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "puskesmas_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("puskesmas.id"),
            nullable=False,
        ),
        sa.Column(
            "patient_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("patients.id"),
            nullable=False,
        ),
        sa.Column("triggered_by_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("triggered_by_type", triggerer_type, nullable=False),
        sa.Column("status", sync_status, nullable=False),
        sa.Column("celery_task_id", sa.String(length=64), nullable=True),
        sa.Column("forms_total", sa.Integer(), nullable=True),
        sa.Column("forms_succeeded", sa.Integer(), nullable=True),
        sa.Column("forms_failed", sa.Integer(), nullable=True),
        sa.Column("forms_skipped", sa.Integer(), nullable=True),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.Column("cpu_avg_pct", sa.Float(), nullable=True),
        sa.Column("cpu_peak_pct", sa.Float(), nullable=True),
        sa.Column("mem_avg_mb", sa.Float(), nullable=True),
        sa.Column("mem_peak_mb", sa.Float(), nullable=True),
        sa.Column("resource_samples", sa.Integer(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        "CREATE INDEX ix_sync_jobs_pid_created ON sync_jobs (puskesmas_id, created_at DESC) "
        "WHERE deleted_at IS NULL"
    )
    op.execute(
        "CREATE INDEX ix_sync_jobs_patient_id ON sync_jobs (patient_id) "
        "WHERE deleted_at IS NULL"
    )
    op.execute(
        "CREATE INDEX ix_sync_jobs_pid_status ON sync_jobs (puskesmas_id, status) "
        "WHERE deleted_at IS NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_sync_jobs_active_per_patient "
        "ON sync_jobs (patient_id) "
        "WHERE status IN ('pending','running') AND deleted_at IS NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_sync_jobs_active_per_patient")
    op.execute("DROP INDEX IF EXISTS ix_sync_jobs_pid_status")
    op.execute("DROP INDEX IF EXISTS ix_sync_jobs_patient_id")
    op.execute("DROP INDEX IF EXISTS ix_sync_jobs_pid_created")
    op.drop_table("sync_jobs")

    bind = op.get_bind()
    postgresql.ENUM(name="sync_status").drop(bind, checkfirst=True)
