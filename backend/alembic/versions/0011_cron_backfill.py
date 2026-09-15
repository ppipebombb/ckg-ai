"""cron_backfills table + cron_runs.cron_backfill_id

Revision ID: 0011_cron_backfill
Revises: 0010_patient_filter_date_scalar
Create Date: 2026-05-05 00:00:00

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011_cron_backfill"
down_revision: str | None = "0010_patient_filter_date_scalar"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


CRON_BACKFILL_STATUS_VALUES = (
    "pending", "running", "success", "failed", "cancelled",
)


def upgrade() -> None:
    bind = op.get_bind()
    cron_backfill_status = postgresql.ENUM(
        *CRON_BACKFILL_STATUS_VALUES,
        name="cron_backfill_status",
        create_type=False,
    )
    cron_backfill_status.create(bind, checkfirst=True)

    op.create_table(
        "cron_backfills",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "puskesmas_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("puskesmas.id"),
            nullable=False,
        ),
        sa.Column("date_from", sa.Date(), nullable=False),
        sa.Column("date_to", sa.Date(), nullable=False),
        sa.Column("cursor_date", sa.Date(), nullable=True),
        sa.Column("status", cron_backfill_status, nullable=False),
        sa.Column(
            "force_remerge",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "triggered_by_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        # current_cron_run_id FK to cron_runs.id is added below as a separate
        # ALTER once cron_backfills exists, to avoid the circular FK chicken-egg.
        sa.Column(
            "current_cron_run_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column("total_dates", sa.Integer(), nullable=False),
        sa.Column(
            "completed_dates",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("failed_date", sa.Date(), nullable=True),
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
        sa.CheckConstraint(
            "date_from <= date_to", name="ck_cron_backfills_date_range"
        ),
    )

    # Active-backfill guard: at most one PENDING/RUNNING backfill per puskesmas.
    op.execute(
        "CREATE UNIQUE INDEX uq_cron_backfills_active_per_pk "
        "ON cron_backfills (puskesmas_id) "
        "WHERE status IN ('pending','running') AND deleted_at IS NULL"
    )
    op.execute(
        "CREATE INDEX ix_cron_backfills_pid_created "
        "ON cron_backfills (puskesmas_id, created_at DESC) "
        "WHERE deleted_at IS NULL"
    )

    op.add_column(
        "cron_runs",
        sa.Column(
            "cron_backfill_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("cron_backfills.id"),
            nullable=True,
        ),
    )
    op.execute(
        "CREATE INDEX ix_cron_runs_backfill_target "
        "ON cron_runs (cron_backfill_id, target_date) "
        "WHERE cron_backfill_id IS NOT NULL AND deleted_at IS NULL"
    )

    # Now safe to add the FK from cron_backfills.current_cron_run_id → cron_runs.id.
    op.create_foreign_key(
        "fk_cron_backfills_current_cron_run_id",
        "cron_backfills",
        "cron_runs",
        ["current_cron_run_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_cron_backfills_current_cron_run_id",
        "cron_backfills",
        type_="foreignkey",
    )
    op.execute("DROP INDEX IF EXISTS ix_cron_runs_backfill_target")
    op.drop_column("cron_runs", "cron_backfill_id")
    op.execute("DROP INDEX IF EXISTS ix_cron_backfills_pid_created")
    op.execute("DROP INDEX IF EXISTS uq_cron_backfills_active_per_pk")
    op.drop_table("cron_backfills")
    bind = op.get_bind()
    postgresql.ENUM(name="cron_backfill_status").drop(bind, checkfirst=True)
