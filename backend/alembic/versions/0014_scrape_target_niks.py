"""scrape_jobs.target_niks for batched per-NIK EPUS multi-date

Revision ID: 0014_scrape_target_niks
Revises: 0013_gdp_skip_asik_detail
Create Date: 2026-05-07 13:00:00

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014_scrape_target_niks"
down_revision: str | None = "0013_gdp_skip_asik_detail"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "scrape_jobs",
        sa.Column("target_niks", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("scrape_jobs", "target_niks")
