"""llm_configs.reasoning_effort

Revision ID: 0021_llm_config_reasoning_effort
Revises: 0020_llm_config_chatbot_active
Create Date: 2026-06-13 00:00:00

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0021_llm_config_reasoning_effort"
down_revision: str | None = "0020_llm_config_chatbot_active"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Normalized reasoning effort (None | minimal | low | medium | high).
    # Nullable with no default → existing configs keep current behavior (omit).
    op.add_column(
        "llm_configs",
        sa.Column("reasoning_effort", sa.String(length=16), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("llm_configs", "reasoning_effort")
