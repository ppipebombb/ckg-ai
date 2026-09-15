"""puskesmas.asik_default_alamat — default domicile for ASIK create-patient

The ASIK "create new patient" flow must fill a required step-2 "Alamat Domisili"
that is a 4-level Provinsi/Kota/Kecamatan/Kelurahan cascade, but ePus stores only
a free-text address. We store the puskesmas' own location (picked from ASIK's
teritorial-service list, so names match the cascade exactly) as the fallback
domicile. JSONB shape:
  {"provinsi": {"name","code"}, "kota": {...}, "kecamatan": {...}, "kelurahan": {...}}

Nullable: until a puskesmas is configured, the create-flow skips its patients
(it never guesses an address).

Revision ID: 0034_puskesmas_default_alamat
Revises: 0033_sync_job_cron_run_link
Create Date: 2026-08-06 12:00:00

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0034_puskesmas_default_alamat"
down_revision: str | None = "0033_sync_job_cron_run_link"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "puskesmas",
        sa.Column("asik_default_alamat", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("puskesmas", "asik_default_alamat")
