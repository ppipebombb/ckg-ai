"""llm_configs.route_order — per-config OpenRouter provider routing pin

Nullable free-text (comma-separated provider slugs, e.g. "z-ai"). When set,
requests through this config send OpenRouter's provider routing lock
(``provider.order`` + ``allow_fallbacks=false``) so the upstream is pinned
with no fallback. Verified per-config via Test-connection.

Revision ID: 0037_llm_route_order
Revises: 0036_loop_agent
Create Date: 2026-08-30

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0037_llm_route_order"
down_revision: str | None = "0036_loop_agent"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "llm_configs",
        sa.Column("route_order", sa.String(length=128), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("llm_configs", "route_order")
