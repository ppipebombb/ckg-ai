"""patient.filter_date scalar + uq(puskesmas_id, nik, filter_date)

Revision ID: 0010_patient_filter_date_scalar
Revises: 0009_per_nik_jobs
Create Date: 2026-05-05 00:00:00

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010_patient_filter_date_scalar"
down_revision: str | None = "0009_per_nik_jobs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("uq_patient_puskesmas_nik", "patients", type_="unique")
    op.execute("DROP INDEX IF EXISTS ix_patients_filter_date")
    op.drop_column("patients", "filter_date")
    op.add_column(
        "patients",
        sa.Column("filter_date", sa.Date(), nullable=False),
    )
    op.execute(
        "CREATE INDEX ix_patients_pid_filter_date ON patients "
        "(puskesmas_id, filter_date) WHERE deleted_at IS NULL"
    )
    op.create_unique_constraint(
        "uq_patient_puskesmas_nik_date",
        "patients",
        ["puskesmas_id", "nik", "filter_date"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_patient_puskesmas_nik_date", "patients", type_="unique")
    op.execute("DROP INDEX IF EXISTS ix_patients_pid_filter_date")
    op.drop_column("patients", "filter_date")
    op.add_column(
        "patients",
        sa.Column(
            "filter_date",
            postgresql.ARRAY(sa.Date()),
            nullable=False,
            server_default=sa.text("'{}'::date[]"),
        ),
    )
    op.execute(
        "CREATE INDEX ix_patients_filter_date ON patients USING gin (filter_date) "
        "WHERE deleted_at IS NULL"
    )
    op.create_unique_constraint(
        "uq_patient_puskesmas_nik", "patients", ["puskesmas_id", "nik"]
    )
