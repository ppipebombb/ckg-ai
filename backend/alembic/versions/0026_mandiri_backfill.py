"""Pemeriksaan Mandiri capture + Mandiri-only backfill flags

Additive booleans for the Pemeriksaan Mandiri feature (no enum changes):
- scrape_jobs.asik_mandiri_only — worker scrapes ONLY Mandiri forms + patches blob.
- cron_backfills.mandiri_only — date-range Mandiri-only backfill driver flag.
- patients.has_mandiri — denormalized "blob has non-empty pemeriksaan_mandiri[]"
  so the backfill can find missing-Mandiri NIKs without decrypting blobs.

Revision ID: 0026_mandiri_backfill
Revises: 0025_school_ckg
Create Date: 2026-06-30 00:00:00

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0026_mandiri_backfill"
down_revision: str | None = "0025_school_ckg"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "scrape_jobs",
        sa.Column(
            "asik_mandiri_only",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "cron_backfills",
        sa.Column(
            "mandiri_only",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "patients",
        sa.Column(
            "has_mandiri",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    # Partial index for the backfill NIK-gather: live ASIK rows still missing
    # Mandiri, scoped per puskesmas + date.
    op.execute(
        "CREATE INDEX ix_patients_missing_mandiri "
        "ON patients (puskesmas_id, filter_date) "
        "WHERE has_mandiri = false AND scraped_asik_data IS NOT NULL "
        "AND deleted_at IS NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_patients_missing_mandiri")
    op.drop_column("patients", "has_mandiri")
    op.drop_column("cron_backfills", "mandiri_only")
    op.drop_column("scrape_jobs", "asik_mandiri_only")
