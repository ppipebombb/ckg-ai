"""patient.ruangan column + uq(puskesmas_id, nik, filter_date, ruangan)

Revision ID: 0016_patient_ruangan
Revises: 0015_llm_config_captcha_active
Create Date: 2026-05-12 00:00:00

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016_patient_ruangan"
down_revision: str | None = "0015_llm_config_captcha_active"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "patients",
        sa.Column(
            "ruangan",
            sa.String(length=64),
            nullable=False,
            server_default="",
        ),
    )
    op.drop_constraint("uq_patient_puskesmas_nik_date", "patients", type_="unique")
    op.create_unique_constraint(
        "uq_patient_puskesmas_nik_date_ruangan",
        "patients",
        ["puskesmas_id", "nik", "filter_date", "ruangan"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_patient_puskesmas_nik_date_ruangan", "patients", type_="unique"
    )
    op.create_unique_constraint(
        "uq_patient_puskesmas_nik_date",
        "patients",
        ["puskesmas_id", "nik", "filter_date"],
    )
    op.drop_column("patients", "ruangan")
