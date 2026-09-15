"""llm_configs + llm_logs

Revision ID: 0004_llm_configs_and_logs
Revises: 0003_patients_and_scrape_jobs
Create Date: 2026-04-26 00:00:00

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_llm_configs_and_logs"
down_revision: str | None = "0003_patients_and_scrape_jobs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "llm_configs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("model", sa.String(128), nullable=False),
        sa.Column("base_url", sa.String(512), nullable=False),
        sa.Column("api_key_enc", sa.LargeBinary(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("label", sa.String(64), nullable=True),
        sa.Column("input_price_per_1m", sa.Numeric(10, 4), nullable=True),
        sa.Column("output_price_per_1m", sa.Numeric(10, 4), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_llm_configs_one_active ON llm_configs (is_active) "
        "WHERE is_active IS TRUE AND deleted_at IS NULL"
    )
    op.execute("CREATE INDEX ix_llm_configs_deleted_at ON llm_configs (deleted_at)")
    op.execute(
        "CREATE INDEX ix_llm_configs_created ON llm_configs (created_at DESC) "
        "WHERE deleted_at IS NULL"
    )
    op.execute(
        "CREATE INDEX ix_llm_configs_label_trgm ON llm_configs USING gin (label gin_trgm_ops)"
    )

    op.create_table(
        "llm_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "llm_config_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("llm_configs.id", ondelete="RESTRICT"), nullable=False,
        ),
        sa.Column(
            "scrape_job_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("scrape_jobs.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column("source", sa.String(64), nullable=False),
        sa.Column("model", sa.String(128), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("reasoning_tokens", sa.Integer(), nullable=True),
        sa.Column("total_tokens", sa.Integer(), nullable=True),
        sa.Column("prompt_cost", sa.Numeric(12, 6), nullable=True),
        sa.Column("completion_cost", sa.Numeric(12, 6), nullable=True),
        sa.Column("total_cost", sa.Numeric(12, 6), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("success", sa.Boolean(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.execute("CREATE INDEX ix_llm_logs_created_at ON llm_logs (created_at DESC)")
    op.execute("CREATE INDEX ix_llm_logs_source_created ON llm_logs (source, created_at DESC)")
    op.execute("CREATE INDEX ix_llm_logs_llm_config_id ON llm_logs (llm_config_id)")
    op.execute("CREATE INDEX ix_llm_logs_scrape_job_id ON llm_logs (scrape_job_id)")

    # Seed default config from env. Idempotent: pin ON CONFLICT to the
    # partial unique index by repeating its predicate, so this handler only
    # absorbs the "another active row exists" conflict and not anything else
    # that may be added later.
    from app.config import settings
    from app.core.security import encrypt_json

    if settings.OPENAI_API_KEY:
        enc = encrypt_json({"api_key": settings.OPENAI_API_KEY})
        bind = op.get_bind()
        bind.execute(
            sa.text(
                "INSERT INTO llm_configs "
                "(id, provider, model, base_url, api_key_enc, is_active, label, created_at, updated_at) "
                "VALUES (gen_random_uuid(), :p, :m, :b, :k, true, 'default', now(), now()) "
                "ON CONFLICT (is_active) WHERE is_active IS TRUE AND deleted_at IS NULL "
                "DO NOTHING"
            ),
            {
                "p": settings.LLM_PROVIDER,
                "m": settings.LLM_MODEL,
                "b": settings.LLM_BASE_URL,
                "k": enc,
            },
        )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_llm_logs_scrape_job_id")
    op.execute("DROP INDEX IF EXISTS ix_llm_logs_llm_config_id")
    op.execute("DROP INDEX IF EXISTS ix_llm_logs_source_created")
    op.execute("DROP INDEX IF EXISTS ix_llm_logs_created_at")
    op.drop_table("llm_logs")
    op.execute("DROP INDEX IF EXISTS ix_llm_configs_label_trgm")
    op.execute("DROP INDEX IF EXISTS ix_llm_configs_created")
    op.execute("DROP INDEX IF EXISTS ix_llm_configs_deleted_at")
    op.execute("DROP INDEX IF EXISTS uq_llm_configs_one_active")
    op.drop_table("llm_configs")
