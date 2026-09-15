"""patient.match_group_id — link cross-date ASIK/EPUS twins

Revision ID: 0017_patient_match_group_id
Revises: 0016_patient_ruangan
Create Date: 2026-05-18 00:00:00

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

revision: str = "0017_patient_match_group_id"
down_revision: str | None = "0016_patient_ruangan"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "patients",
        sa.Column("match_group_id", PG_UUID(as_uuid=True), nullable=True),
    )
    op.create_index(
        "ix_patients_match_group_id",
        "patients",
        ["match_group_id"],
        postgresql_where=sa.text("match_group_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_patients_match_group_id", table_name="patients")
    op.drop_column("patients", "match_group_id")
