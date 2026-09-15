"""gdp_report_jobs.skip_asik_detail + scrape_jobs.asik_list_only

Revision ID: 0013_gdp_skip_asik_detail
Revises: 0012_gdp_report_jobs
Create Date: 2026-05-07 12:00:00

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013_gdp_skip_asik_detail"
down_revision: str | None = "0012_gdp_report_jobs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "gdp_report_jobs",
        sa.Column(
            "skip_asik_detail",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "scrape_jobs",
        sa.Column(
            "asik_list_only",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("scrape_jobs", "asik_list_only")
    op.drop_column("gdp_report_jobs", "skip_asik_detail")
