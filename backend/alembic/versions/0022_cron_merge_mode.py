"""cron_configs/cron_backfills: force_remerge bool -> merge_mode enum

Replaces the force_remerge boolean on cron_configs and cron_backfills with a
3-way merge_mode enum (normal | force_remerge | no_merge). no_merge runs the
scrape steps (EPUS+ASIK) but skips the merge step entirely, so scraping can
continue while the LLM provider is down.

Revision ID: 0022_cron_merge_mode
Revises: 0021_llm_config_reasoning_effort
Create Date: 2026-06-13 00:01:00

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0022_cron_merge_mode"
down_revision: str | None = "0021_llm_config_reasoning_effort"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


CRON_MERGE_MODE_VALUES = ("normal", "force_remerge", "no_merge")
_TABLES = ("cron_configs", "cron_backfills")


def upgrade() -> None:
    bind = op.get_bind()
    merge_mode = postgresql.ENUM(
        *CRON_MERGE_MODE_VALUES, name="cron_merge_mode", create_type=False
    )
    merge_mode.create(bind, checkfirst=True)

    for table in _TABLES:
        op.add_column(
            table,
            sa.Column(
                "merge_mode",
                merge_mode,
                nullable=False,
                server_default="normal",
            ),
        )
        # Carry the old boolean forward: force_remerge=True -> 'force_remerge'.
        op.execute(
            f"UPDATE {table} SET merge_mode='force_remerge' "
            "WHERE force_remerge IS TRUE"
        )
        op.drop_column(table, "force_remerge")


def downgrade() -> None:
    for table in _TABLES:
        op.add_column(
            table,
            sa.Column(
                "force_remerge",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
        )
        op.execute(
            f"UPDATE {table} SET force_remerge=TRUE "
            "WHERE merge_mode='force_remerge'"
        )
        op.drop_column(table, "merge_mode")

    postgresql.ENUM(name="cron_merge_mode").drop(op.get_bind(), checkfirst=True)
