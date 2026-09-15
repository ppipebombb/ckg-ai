"""patients.birth_date (denormalized birth date for the umur/age filter)

Adds a nullable birth_date column denormalized from the encrypted blobs
(scraped_epus_data "Tempat/Tgl Lahir" with EPUS-wins, else scraped_asik_data
data_individu "Tanggal Lahir") so the patient list can filter by age without
decrypting every row. Populated going forward by the scrape write-path and
once for existing rows by scripts/backfill_patient_birth_date.py.

Revision ID: 0024_patient_birth_date
Revises: 0023_cron_source_scope
Create Date: 2026-06-23 00:00:00

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0024_patient_birth_date"
down_revision: str | None = "0023_cron_source_scope"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "patients",
        sa.Column("birth_date", sa.Date(), nullable=True),
    )
    op.execute(
        "CREATE INDEX ix_patients_birth_date ON patients (birth_date) "
        "WHERE birth_date IS NOT NULL AND deleted_at IS NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_patients_birth_date")
    op.drop_column("patients", "birth_date")
