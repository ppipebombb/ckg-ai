"""loop agent: loop_runs, loop_run_events, loop_config, llm_config loop flags, last_checked_at

The self-maintaining EPUS scraper/converter agent (PLAN §5, one migration for the
whole feature):
- llm_configs.is_active_loop_agent / is_active_loop_reviewer — same role-flag
  pattern as captcha/chatbot: exactly one active row per flag;
- loop_runs — one summary row per run against one puskesmas (kept forever);
- loop_run_events — the heavy per-event agent stream (persisted for replay,
  pruned by age);
- loop_config — singleton behaviour row (dashboard-editable);
- puskesmas.last_checked_at — stamped on covered/no_data; the nightly sweep
  picks only portals where this IS NULL (no cooldown, no auto-recheck).

Revision ID: 0036_loop_agent
Revises: 0035_cron_create_new
Create Date: 2026-08-30

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0036_loop_agent"
down_revision: str | None = "0035_cron_create_new"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


LOOP_TRIGGER_VALUES = ("manual", "nightly")
LOOP_RUN_STATUS_VALUES = (
    "pending", "running", "covered", "no_data", "needs_review", "merged",
    "bad_creds", "failed", "cancelled",
)
LOOP_MERGE_MODE_VALUES = ("manual", "auto")


def upgrade() -> None:
    bind = op.get_bind()

    # 1. llm_config loop role flags (same shape as is_active_chatbot).
    op.add_column(
        "llm_configs",
        sa.Column("is_active_loop_agent", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "llm_configs",
        sa.Column("is_active_loop_reviewer", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_llm_configs_one_active_loop_agent "
        "ON llm_configs (is_active_loop_agent) "
        "WHERE is_active_loop_agent IS TRUE AND deleted_at IS NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_llm_configs_one_active_loop_reviewer "
        "ON llm_configs (is_active_loop_reviewer) "
        "WHERE is_active_loop_reviewer IS TRUE AND deleted_at IS NULL"
    )

    # 2. Enum types.
    loop_trigger = postgresql.ENUM(*LOOP_TRIGGER_VALUES, name="loop_trigger", create_type=False)
    loop_trigger.create(bind, checkfirst=True)
    loop_run_status = postgresql.ENUM(*LOOP_RUN_STATUS_VALUES, name="loop_run_status", create_type=False)
    loop_run_status.create(bind, checkfirst=True)
    loop_merge_mode = postgresql.ENUM(*LOOP_MERGE_MODE_VALUES, name="loop_merge_mode", create_type=False)
    loop_merge_mode.create(bind, checkfirst=True)

    # 3. loop_runs — the permanent summary row.
    op.create_table(
        "loop_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("puskesmas_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("trigger", loop_trigger, nullable=False),
        sa.Column("triggered_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", loop_run_status, nullable=False),
        sa.Column("pin_ref", sa.String(length=64), nullable=True),
        sa.Column("container_name", sa.String(length=96), nullable=True),
        sa.Column("celery_task_id", sa.String(length=64), nullable=True),
        sa.Column("test_date", sa.String(length=16), nullable=True),
        sa.Column("live_count", sa.Integer(), nullable=True),
        sa.Column("scraped_count", sa.Integer(), nullable=True),
        sa.Column("decision", sa.String(length=32), nullable=True),
        sa.Column("gap_summary", sa.Text(), nullable=True),
        sa.Column("branch_name", sa.String(length=128), nullable=True),
        sa.Column("pr_url", sa.String(length=512), nullable=True),
        sa.Column("review_verdict", sa.String(length=16), nullable=True),
        sa.Column("review_comments", sa.Text(), nullable=True),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("event_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["puskesmas_id"], ["puskesmas.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_loop_runs_deleted_at", "loop_runs", ["deleted_at"])
    # List query: newest-first; also serves the stale-RUNNING watchdog scan.
    op.create_index("ix_loop_runs_status_created", "loop_runs", ["status", "created_at"])

    # 4. loop_run_events — disposable stream, pruned by created_at.
    op.create_table(
        "loop_run_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("loop_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["loop_run_id"], ["loop_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    # Replay in order for one run.
    op.create_index("ix_loop_run_events_run_seq", "loop_run_events", ["loop_run_id", "seq"])
    # Age-based pruning scan.
    op.create_index("ix_loop_run_events_created_at", "loop_run_events", ["created_at"])

    # 5. loop_config — singleton behaviour row (crud.get_or_create seeds it).
    op.create_table(
        "loop_config",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("merge_mode", loop_merge_mode, nullable=False, server_default="manual"),
        # Stored but NOT acted on in v1 — placeholder for the later auto-deploy
        # discussion. Never read by any code path yet.
        sa.Column("auto_deploy", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("nightly_budget", sa.Integer(), nullable=False, server_default=sa.text("20")),
        sa.Column("max_fix_iterations", sa.Integer(), nullable=False, server_default=sa.text("5")),
        sa.Column("max_review_iterations", sa.Integer(), nullable=False, server_default=sa.text("3")),
        sa.Column("nightly_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    # 6. puskesmas.last_checked_at — the "has been checked" marker.
    op.add_column(
        "puskesmas",
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Stalest-first ordering aid for the nightly selection query.
    op.create_index("ix_puskesmas_last_checked_at", "puskesmas", ["last_checked_at"])


def downgrade() -> None:
    op.drop_index("ix_puskesmas_last_checked_at", table_name="puskesmas")
    op.drop_column("puskesmas", "last_checked_at")

    op.drop_table("loop_config")

    op.drop_index("ix_loop_run_events_created_at", table_name="loop_run_events")
    op.drop_index("ix_loop_run_events_run_seq", table_name="loop_run_events")
    op.drop_table("loop_run_events")

    op.drop_index("ix_loop_runs_status_created", table_name="loop_runs")
    op.drop_index("ix_loop_runs_deleted_at", table_name="loop_runs")
    op.drop_table("loop_runs")

    postgresql.ENUM(name="loop_merge_mode").drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="loop_run_status").drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="loop_trigger").drop(op.get_bind(), checkfirst=True)

    op.execute("DROP INDEX IF EXISTS uq_llm_configs_one_active_loop_reviewer")
    op.execute("DROP INDEX IF EXISTS uq_llm_configs_one_active_loop_agent")
    op.drop_column("llm_configs", "is_active_loop_reviewer")
    op.drop_column("llm_configs", "is_active_loop_agent")
