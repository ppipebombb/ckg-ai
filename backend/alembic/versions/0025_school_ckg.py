"""CKG Sekolah: school_patients, school_cron_configs, patients.is_ckg_sekolah

Adds the date-less CKG-Sekolah program, kept fully separate from the date-keyed
CKG-Umum patients/merge pipeline:

- new ScrapeKind value 'asik_sekolah' (same ASIK portal, school × class filter);
- patients.is_ckg_sekolah — cheap cross-reference flag set when a school NIK
  matches an existing CKG-Umum patient row;
- school_patients — the student records (NIK-keyed per school_year);
- school_cron_configs — the minimal date-less scheduler for the school scrape.

Revision ID: 0025_school_ckg
Revises: 0024_patient_birth_date
Create Date: 2026-06-29 00:01:00

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0025_school_ckg"
down_revision: str | None = "0024_patient_birth_date"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


SCHOOL_SCREENING_STATUS_VALUES = ("belum", "sedang", "selesai")


def upgrade() -> None:
    bind = op.get_bind()

    # 1. Extend the existing scrape_kind enum. Safe inside the migration txn on
    #    PG 12+ because the new value is not USED in this same migration.
    op.execute("ALTER TYPE scrape_kind ADD VALUE IF NOT EXISTS 'asik_sekolah'")

    # 2. Cross-reference flag on patients (orthogonal to match_status).
    op.add_column("patients", sa.Column("is_ckg_sekolah", sa.Boolean(), nullable=True))

    # 3. school_patients
    screening_status = postgresql.ENUM(
        *SCHOOL_SCREENING_STATUS_VALUES,
        name="school_screening_status",
        create_type=False,
    )
    screening_status.create(bind, checkfirst=True)

    op.create_table(
        "school_patients",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("puskesmas_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("nik", sa.String(length=32), nullable=False),
        sa.Column("nama", sa.String(length=255), nullable=False),
        sa.Column("born_date", sa.Date(), nullable=True),
        sa.Column("gender", sa.String(length=16), nullable=True),
        sa.Column("school_year", sa.Integer(), nullable=False),
        sa.Column("reg_id", sa.String(length=64), nullable=True),
        sa.Column("ticket_number", sa.String(length=32), nullable=True),
        sa.Column("school_code", sa.String(length=32), nullable=True),
        sa.Column("school_name", sa.String(length=255), nullable=True),
        sa.Column("category_code", sa.String(length=16), nullable=True),
        sa.Column("class_name", sa.String(length=64), nullable=True),
        sa.Column("klaster_code", sa.String(length=32), nullable=True),
        sa.Column("klaster_name", sa.String(length=128), nullable=True),
        sa.Column("screening_status", screening_status, nullable=False),
        sa.Column("scraped_sekolah_data", sa.LargeBinary(), nullable=True),
        sa.Column("scraped_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["puskesmas_id"], ["puskesmas.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "puskesmas_id", "nik", "school_year",
            name="uq_school_patient_puskesmas_nik_year",
        ),
    )
    op.create_index(
        "ix_school_patients_deleted_at", "school_patients", ["deleted_at"]
    )
    # NIK lookup for the cross-link + list filtering (live rows only).
    op.execute(
        "CREATE INDEX ix_school_patients_puskesmas_nik ON school_patients "
        "(puskesmas_id, nik) WHERE deleted_at IS NULL"
    )

    # 4. school_cron_configs (one live config per puskesmas).
    op.create_table(
        "school_cron_configs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("puskesmas_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("hour", sa.Integer(), nullable=False),
        sa.Column("minute", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_fired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["puskesmas_id"], ["puskesmas.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_school_cron_configs_deleted_at", "school_cron_configs", ["deleted_at"]
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_school_cron_configs_per_pk ON school_cron_configs "
        "(puskesmas_id) WHERE deleted_at IS NULL"
    )


def downgrade() -> None:
    op.drop_index("ix_school_cron_configs_deleted_at", table_name="school_cron_configs")
    op.execute("DROP INDEX IF EXISTS uq_school_cron_configs_per_pk")
    op.drop_table("school_cron_configs")

    op.execute("DROP INDEX IF EXISTS ix_school_patients_puskesmas_nik")
    op.drop_index("ix_school_patients_deleted_at", table_name="school_patients")
    op.drop_table("school_patients")
    postgresql.ENUM(name="school_screening_status").drop(op.get_bind(), checkfirst=True)

    op.drop_column("patients", "is_ckg_sekolah")
    # The 'asik_sekolah' value is left on the scrape_kind enum — PostgreSQL has
    # no transactional DROP VALUE, and removing it would break any historical
    # asik_sekolah scrape_jobs rows.
