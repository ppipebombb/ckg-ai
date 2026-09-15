"""patients.epus_tandai_ckg (denormalized CKG flag) + drop patients.gdp_mg_dl

Adds the indexed boolean epus_tandai_ckg column (CKG "sudah CKG" flag
denormalized from scraped_epus_data["ckg"]["sudah_ckg"]) and drops the now-
unused gdp_mg_dl column + its index (the GDP report reads GDP from the blob).

Revision ID: 0018_patient_epus_tandai_ckg
Revises: 0017_patient_match_group_id
Create Date: 2026-05-21 00:00:00

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018_patient_epus_tandai_ckg"
down_revision: str | None = "0017_patient_match_group_id"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "patients",
        sa.Column("epus_tandai_ckg", sa.Boolean(), nullable=True),
    )
    op.execute(
        "CREATE INDEX ix_patients_epus_tandai_ckg ON patients (epus_tandai_ckg) "
        "WHERE epus_tandai_ckg IS NOT NULL AND deleted_at IS NULL"
    )

    # Drop gdp_mg_dl — write-only column, GDP report reads from the blob.
    op.execute("DROP INDEX IF EXISTS ix_patients_gdp_pid_date")
    op.drop_column("patients", "gdp_mg_dl")


def downgrade() -> None:
    op.add_column(
        "patients",
        sa.Column("gdp_mg_dl", sa.Numeric(6, 2), nullable=True),
    )
    op.execute(
        "CREATE INDEX ix_patients_gdp_pid_date "
        "ON patients (puskesmas_id, filter_date) "
        "WHERE gdp_mg_dl IS NOT NULL AND deleted_at IS NULL"
    )

    op.execute("DROP INDEX IF EXISTS ix_patients_epus_tandai_ckg")
    op.drop_column("patients", "epus_tandai_ckg")
