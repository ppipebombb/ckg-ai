"""gdp_report_jobs + patients.gdp_mg_dl + scrape_jobs.target_nik / parent_gdp_job_id

Revision ID: 0012_gdp_report_jobs
Revises: 0011_cron_backfill
Create Date: 2026-05-07 00:00:00

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0012_gdp_report_jobs"
down_revision: str | None = "0011_cron_backfill"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


GDP_REPORT_STATUS_VALUES = (
    "pending", "running", "success", "failed", "cancelled",
)
GDP_REPORT_PHASE_VALUES = (
    "pending", "asik", "epus", "done",
)


def upgrade() -> None:
    bind = op.get_bind()

    op.add_column(
        "patients",
        sa.Column("gdp_mg_dl", sa.Numeric(6, 2), nullable=True),
    )
    op.execute(
        "CREATE INDEX ix_patients_gdp_pid_date "
        "ON patients (puskesmas_id, filter_date) "
        "WHERE gdp_mg_dl IS NOT NULL AND deleted_at IS NULL"
    )

    gdp_report_status = postgresql.ENUM(
        *GDP_REPORT_STATUS_VALUES,
        name="gdp_report_status",
        create_type=False,
    )
    gdp_report_status.create(bind, checkfirst=True)
    gdp_report_phase = postgresql.ENUM(
        *GDP_REPORT_PHASE_VALUES,
        name="gdp_report_phase",
        create_type=False,
    )
    gdp_report_phase.create(bind, checkfirst=True)

    op.create_table(
        "gdp_report_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "puskesmas_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("puskesmas.id"),
            nullable=False,
        ),
        sa.Column("date_from", sa.Date(), nullable=False),
        sa.Column("date_to", sa.Date(), nullable=False),
        sa.Column("triggered_by_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "triggered_by_type",
            postgresql.ENUM(name="triggerer_type", create_type=False),
            nullable=False,
        ),
        sa.Column("status", gdp_report_status, nullable=False),
        sa.Column(
            "phase",
            gdp_report_phase,
            nullable=False,
            server_default=sa.text("'pending'::gdp_report_phase"),
        ),
        sa.Column("celery_task_id", sa.String(64), nullable=True),
        sa.Column("nik_total", sa.Integer(), nullable=True),
        sa.Column("nik_done", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("dates_total", sa.Integer(), nullable=False),
        sa.Column("dates_done", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("epus_jobs_total", sa.Integer(), nullable=True),
        sa.Column("epus_jobs_done", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("epus_jobs_failed", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("date_from <= date_to", name="ck_gdp_report_jobs_date_range"),
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_gdp_report_jobs_active_per_puskesmas "
        "ON gdp_report_jobs (puskesmas_id) "
        "WHERE status IN ('pending','running') AND deleted_at IS NULL"
    )
    op.execute(
        "CREATE INDEX ix_gdp_report_jobs_pid_created "
        "ON gdp_report_jobs (puskesmas_id, created_at DESC) "
        "WHERE deleted_at IS NULL"
    )

    op.add_column(
        "scrape_jobs",
        sa.Column("target_nik", sa.String(32), nullable=True),
    )
    op.add_column(
        "scrape_jobs",
        sa.Column(
            "parent_gdp_job_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("gdp_report_jobs.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    # JSON list of ISO dates. When non-null on an ASIK puskesmas-wide scrape,
    # the worker invokes the ASIK scraper with --dates (one browser session,
    # walks every date). Mutually exclusive with date_filter for ASIK.
    op.add_column(
        "scrape_jobs",
        sa.Column("date_filters", sa.Text(), nullable=True),
    )
    op.execute(
        "CREATE INDEX ix_scrape_jobs_parent_gdp "
        "ON scrape_jobs (parent_gdp_job_id) "
        "WHERE parent_gdp_job_id IS NOT NULL AND deleted_at IS NULL"
    )
    # Per-NIK without patient_id: enforce no duplicate in-flight (puskesmas, nik, date).
    op.execute(
        "CREATE UNIQUE INDEX uq_scrape_jobs_active_epus_target_nik "
        "ON scrape_jobs (puskesmas_id, target_nik, date_filter) "
        "WHERE kind = 'epus' AND patient_id IS NULL AND target_nik IS NOT NULL "
        "AND status IN ('pending','running') AND deleted_at IS NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_scrape_jobs_active_epus_target_nik")
    op.execute("DROP INDEX IF EXISTS ix_scrape_jobs_parent_gdp")
    op.drop_column("scrape_jobs", "date_filters")
    op.drop_column("scrape_jobs", "parent_gdp_job_id")
    op.drop_column("scrape_jobs", "target_nik")

    op.execute("DROP INDEX IF EXISTS ix_gdp_report_jobs_pid_created")
    op.execute("DROP INDEX IF EXISTS uq_gdp_report_jobs_active_per_puskesmas")
    op.drop_table("gdp_report_jobs")

    bind = op.get_bind()
    postgresql.ENUM(name="gdp_report_phase").drop(bind, checkfirst=True)
    postgresql.ENUM(name="gdp_report_status").drop(bind, checkfirst=True)

    op.execute("DROP INDEX IF EXISTS ix_patients_gdp_pid_date")
    op.drop_column("patients", "gdp_mg_dl")
