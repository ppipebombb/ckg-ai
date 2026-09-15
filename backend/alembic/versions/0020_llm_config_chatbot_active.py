"""llm_configs.is_active_chatbot

Revision ID: 0020_llm_config_chatbot_active
Revises: 0019_admin_scope
Create Date: 2026-06-12 00:00:00

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0020_llm_config_chatbot_active"
down_revision: str | None = "0019_admin_scope"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "llm_configs",
        sa.Column(
            "is_active_chatbot",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_llm_configs_one_active_chatbot "
        "ON llm_configs (is_active_chatbot) "
        "WHERE is_active_chatbot IS TRUE AND deleted_at IS NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_llm_configs_one_active_chatbot")
    op.drop_column("llm_configs", "is_active_chatbot")
