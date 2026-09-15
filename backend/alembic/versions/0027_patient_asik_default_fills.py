"""patients.asik_default_fills — log of default values pushed to ASIK

When the sync fills a REQUIRED ASIK question we had no data for, it writes a safe
default and records {layanan, question, value, kind} here so dashboards/reports can
separate real measurements from auto-filled placeholders. Unencrypted on purpose —
it is metadata about what we auto-filled, not patient clinical data.

Revision ID: 0027_asik_default_fills
Revises: 0026_mandiri_backfill
Create Date: 2026-07-20 00:00:00

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0027_asik_default_fills"
down_revision: str | None = "0026_mandiri_backfill"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "patients",
        sa.Column(
            "asik_default_fills",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("patients", "asik_default_fills")
