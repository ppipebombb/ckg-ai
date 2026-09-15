"""llm_configs.is_active_captcha

Revision ID: 0015_llm_config_captcha_active
Revises: 0014_scrape_target_niks
Create Date: 2026-05-11 00:00:00

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015_llm_config_captcha_active"
down_revision: str | None = "0014_scrape_target_niks"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "llm_configs",
        sa.Column(
            "is_active_captcha",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_llm_configs_one_active_captcha "
        "ON llm_configs (is_active_captcha) "
        "WHERE is_active_captcha IS TRUE AND deleted_at IS NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_llm_configs_one_active_captcha")
    op.drop_column("llm_configs", "is_active_captcha")
