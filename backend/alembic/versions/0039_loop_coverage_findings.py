"""loop agent: per-run ASIK coverage findings (the coverage-mission redesign)

loop_runs.coverage_findings holds the agent's per-run coverage report — one
JSON list of {form, frm_code, status: mapped|absent|candidate, ...} objects
from .check_result.json. Nullable: runs without a portal capture
(bad_login / no_data / error) and all pre-redesign runs stay NULL, which the
dashboard reads as "not hunted", never as "nothing found".

Revision ID: 0039_loop_coverage_findings
Revises: 0038_loop_pr_rejected
Create Date: 2026-09-11

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0039_loop_coverage_findings"
down_revision: str | None = "0038_loop_pr_rejected"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("loop_runs", sa.Column("coverage_findings", JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("loop_runs", "coverage_findings")
