"""patients + scrape_jobs

Revision ID: 0003_patients_and_scrape_jobs
Revises: 0002_seed_admin
Create Date: 2026-04-25 00:00:00

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_patients_and_scrape_jobs"
down_revision: str | None = "0002_seed_admin"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


MATCH_STATUS_VALUES = ("asik_only", "epus_only", "matched")
SCRAPE_KIND_VALUES = ("asik", "epus")
SCRAPE_STATUS_VALUES = ("pending", "running", "success", "failed", "cancelled")
TRIGGERER_TYPE_VALUES = ("admin", "user")


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    match_status = postgresql.ENUM(*MATCH_STATUS_VALUES, name="match_status", create_type=False)
    scrape_kind = postgresql.ENUM(*SCRAPE_KIND_VALUES, name="scrape_kind", create_type=False)
    scrape_status = postgresql.ENUM(*SCRAPE_STATUS_VALUES, name="scrape_status", create_type=False)
    triggerer_type = postgresql.ENUM(*TRIGGERER_TYPE_VALUES, name="triggerer_type", create_type=False)

    bind = op.get_bind()
    match_status.create(bind, checkfirst=True)
    scrape_kind.create(bind, checkfirst=True)
    scrape_status.create(bind, checkfirst=True)
    triggerer_type.create(bind, checkfirst=True)

    op.create_table(
        "patients",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "puskesmas_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("puskesmas.id"),
            nullable=False,
        ),
        sa.Column("nik", sa.String(length=32), nullable=False),
        sa.Column("nama", sa.String(length=255), nullable=False),
        sa.Column("match_status", match_status, nullable=False),
        sa.Column("scraped_asik_data", sa.LargeBinary(), nullable=True),
        sa.Column("scraped_epus_data", sa.LargeBinary(), nullable=True),
        sa.Column(
            "filter_date",
            postgresql.ARRAY(sa.Date()),
            nullable=False,
            server_default=sa.text("'{}'::date[]"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("puskesmas_id", "nik", name="uq_patient_puskesmas_nik"),
    )
    op.execute(
        "CREATE INDEX ix_patients_pid_created ON patients (puskesmas_id, created_at DESC) "
        "WHERE deleted_at IS NULL"
    )
    op.execute(
        "CREATE INDEX ix_patients_pid_status ON patients (puskesmas_id, match_status) "
        "WHERE deleted_at IS NULL"
    )
    op.execute(
        "CREATE INDEX ix_patients_nik_active ON patients (nik) "
        "WHERE deleted_at IS NULL"
    )
    op.execute(
        "CREATE INDEX ix_patients_nama_trgm ON patients USING gin (nama gin_trgm_ops)"
    )
    op.execute(
        "CREATE INDEX ix_patients_filter_date ON patients USING gin (filter_date) "
        "WHERE deleted_at IS NULL"
    )

    op.create_table(
        "scrape_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "puskesmas_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("puskesmas.id"),
            nullable=False,
        ),
        sa.Column("triggered_by_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("triggered_by_type", triggerer_type, nullable=False),
        sa.Column("kind", scrape_kind, nullable=False),
        sa.Column("date_filter", sa.String(length=16), nullable=False),
        sa.Column("status", scrape_status, nullable=False),
        sa.Column("celery_task_id", sa.String(length=64), nullable=True),
        sa.Column("scraped_count", sa.Integer(), nullable=True),
        sa.Column("inserted_count", sa.Integer(), nullable=True),
        sa.Column("updated_count", sa.Integer(), nullable=True),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("full_output", sa.LargeBinary(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        "CREATE INDEX ix_scrape_jobs_pid_created ON scrape_jobs (puskesmas_id, created_at DESC) "
        "WHERE deleted_at IS NULL"
    )
    op.execute(
        "CREATE INDEX ix_scrape_jobs_pid_status ON scrape_jobs (puskesmas_id, status) "
        "WHERE deleted_at IS NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_scrape_jobs_active_per_puskesmas_kind "
        "ON scrape_jobs (puskesmas_id, kind) "
        "WHERE status IN ('pending','running') AND deleted_at IS NULL"
    )

def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_scrape_jobs_active_per_puskesmas_kind")
    op.execute("DROP INDEX IF EXISTS ix_scrape_jobs_pid_status")
    op.execute("DROP INDEX IF EXISTS ix_scrape_jobs_pid_created")
    op.drop_table("scrape_jobs")

    op.execute("DROP INDEX IF EXISTS ix_patients_filter_date")
    op.execute("DROP INDEX IF EXISTS ix_patients_nama_trgm")
    op.execute("DROP INDEX IF EXISTS ix_patients_nik_active")
    op.execute("DROP INDEX IF EXISTS ix_patients_pid_status")
    op.execute("DROP INDEX IF EXISTS ix_patients_pid_created")
    op.drop_table("patients")

    bind = op.get_bind()
    postgresql.ENUM(name="triggerer_type").drop(bind, checkfirst=True)
    postgresql.ENUM(name="scrape_status").drop(bind, checkfirst=True)
    postgresql.ENUM(name="scrape_kind").drop(bind, checkfirst=True)
    postgresql.ENUM(name="match_status").drop(bind, checkfirst=True)
