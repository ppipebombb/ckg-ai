"""cron_configs + cron_runs tables, extend triggerer_type, add cron_run_id to job tables

Revision ID: 0007_cron_config_and_run
Revises: 0006_job_resource_metrics
Create Date: 2026-04-28 00:00:00

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007_cron_config_and_run"
down_revision: str | None = "0006_job_resource_metrics"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


CRON_RUN_STATUS_VALUES = ("pending", "running", "success", "failed", "cancelled")
CRON_STEP_VALUES = ("asik", "epus", "merge")


def upgrade() -> None:
    bind = op.get_bind()

    # Postgres ALTER TYPE ADD VALUE cannot run inside a transaction block opened
    # implicitly by alembic, so commit before running it.
    op.execute("COMMIT")
    op.execute("ALTER TYPE triggerer_type ADD VALUE IF NOT EXISTS 'cron'")

    cron_run_status = postgresql.ENUM(
        *CRON_RUN_STATUS_VALUES, name="cron_run_status", create_type=False
    )
    cron_step = postgresql.ENUM(*CRON_STEP_VALUES, name="cron_step", create_type=False)
    cron_run_status.create(bind, checkfirst=True)
    cron_step.create(bind, checkfirst=True)

    op.create_table(
        "cron_configs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "puskesmas_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("puskesmas.id"),
            nullable=False,
        ),
        sa.Column("hour", sa.Integer(), nullable=False),
        sa.Column("minute", sa.Integer(), nullable=False),
        sa.Column(
            "target_offset_days",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column(
            "force_remerge",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_fired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("hour >= 0 AND hour <= 23", name="ck_cron_configs_hour"),
        sa.CheckConstraint(
            "minute >= 0 AND minute <= 59", name="ck_cron_configs_minute"
        ),
    )
    # Partial unique: only one LIVE cron_config per puskesmas. After soft-delete
    # the row no longer constrains, so the puskesmas can re-create one. Mirrors
    # the pattern used by uq_merge_jobs_active_per_puskesmas_date.
    op.execute(
        "CREATE UNIQUE INDEX uq_cron_configs_puskesmas_id "
        "ON cron_configs (puskesmas_id) "
        "WHERE deleted_at IS NULL"
    )
    # Predicate uses `IS TRUE` (not `= true`) so it matches the SQL emitted by
    # SQLAlchemy's `CronConfig.enabled.is_(True)` in tasks/cron.py::dispatch_due.
    # PG's predicate-implication check requires character-equivalent WHERE.
    op.execute(
        "CREATE INDEX ix_cron_configs_due ON cron_configs (next_run_at) "
        "WHERE deleted_at IS NULL AND enabled IS TRUE"
    )

    op.create_table(
        "cron_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "cron_config_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("cron_configs.id"),
            nullable=True,
        ),
        sa.Column(
            "puskesmas_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("puskesmas.id"),
            nullable=False,
        ),
        sa.Column("target_date", sa.Date(), nullable=False),
        sa.Column("status", cron_run_status, nullable=False),
        sa.Column("current_step", cron_step, nullable=True),
        sa.Column(
            "current_step_attempt",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("failed_step", cron_step, nullable=True),
        sa.Column(
            "asik_scrape_job_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("scrape_jobs.id"),
            nullable=True,
        ),
        sa.Column(
            "epus_scrape_job_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("scrape_jobs.id"),
            nullable=True,
        ),
        sa.Column(
            "merge_job_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("merge_jobs.id"),
            nullable=True,
        ),
        sa.Column(
            "triggered_by_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        "CREATE INDEX ix_cron_runs_pid_created ON cron_runs (puskesmas_id, created_at DESC) "
        "WHERE deleted_at IS NULL"
    )
    op.execute(
        "CREATE INDEX ix_cron_runs_status ON cron_runs (status) "
        "WHERE deleted_at IS NULL"
    )

    # No reverse index on (scrape|merge)_jobs.cron_run_id — current queries
    # walk parent-to-child via cron_runs.{asik,epus,merge}_*_id (PK lookups).
    # Add a partial index here only if a "list jobs by cron_run_id" query lands.
    op.add_column(
        "scrape_jobs",
        sa.Column(
            "cron_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("cron_runs.id"),
            nullable=True,
        ),
    )
    op.add_column(
        "merge_jobs",
        sa.Column(
            "cron_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("cron_runs.id"),
            nullable=True,
        ),
    )

    # Active-run guard: at most one PENDING/RUNNING cron_run per puskesmas.
    # Partial UNIQUE so DB rejects concurrent run-now / retry / dispatch_due
    # races at INSERT time — routes only need to translate IntegrityError → 409.
    # Doubles as the lookup index for the active-run pre-check.
    op.execute(
        "CREATE UNIQUE INDEX uq_cron_runs_active_per_pk ON cron_runs (puskesmas_id) "
        "WHERE status IN ('pending','running') AND deleted_at IS NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_cron_runs_active_per_pk")
    op.drop_column("merge_jobs", "cron_run_id")
    op.drop_column("scrape_jobs", "cron_run_id")

    op.execute("DROP INDEX IF EXISTS ix_cron_runs_status")
    op.execute("DROP INDEX IF EXISTS ix_cron_runs_pid_created")
    op.drop_table("cron_runs")

    op.execute("DROP INDEX IF EXISTS ix_cron_configs_due")
    op.drop_table("cron_configs")

    bind = op.get_bind()
    postgresql.ENUM(name="cron_step").drop(bind, checkfirst=True)
    postgresql.ENUM(name="cron_run_status").drop(bind, checkfirst=True)
    # Cannot remove an enum value in Postgres without recreating the type;
    # leaving 'cron' on triggerer_type is harmless on downgrade.
