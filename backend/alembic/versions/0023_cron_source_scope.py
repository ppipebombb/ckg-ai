"""cron_backfills/cron_runs: add source_scope + lane-aware active-run indexes

Adds a 3-way source_scope enum (both | epus_only | asik_only) to cron_backfills
(user-set on a date-range backfill) and cron_runs (copied from the parent at
creation; BOTH for config/run-now runs).

Replaces the single per-puskesmas active-run guard (uq_cron_runs_active_per_pk)
with two "lane" partial unique indexes so one EPUS-touching run and one
ASIK-touching run can be active per puskesmas at the same time (EPUS_ONLY ∥
ASIK_ONLY allowed; BOTH conflicts with everything). This mirrors the per-source
scrape serialization (each source shares one browser session per puskesmas).

Revision ID: 0023_cron_source_scope
Revises: 0022_cron_merge_mode
Create Date: 2026-06-17 00:01:00

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0023_cron_source_scope"
down_revision: str | None = "0022_cron_merge_mode"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


CRON_SOURCE_SCOPE_VALUES = ("both", "epus_only", "asik_only")
_TABLES = ("cron_backfills", "cron_runs")


def upgrade() -> None:
    bind = op.get_bind()
    source_scope = postgresql.ENUM(
        *CRON_SOURCE_SCOPE_VALUES, name="cron_source_scope", create_type=False
    )
    source_scope.create(bind, checkfirst=True)

    for table in _TABLES:
        op.add_column(
            table,
            sa.Column(
                "source_scope",
                source_scope,
                nullable=False,
                server_default="both",
            ),
        )

    # Replace the single active-run guard with two lane indexes. A run occupies
    # the EPUS lane when its scope touches EPUS (both | epus_only) and the ASIK
    # lane when it touches ASIK (both | asik_only). At most one active run per
    # lane per puskesmas → BOTH blocks all; EPUS_ONLY ∥ ASIK_ONLY is allowed.
    op.execute("DROP INDEX IF EXISTS uq_cron_runs_active_per_pk")
    op.execute(
        "CREATE UNIQUE INDEX uq_cron_runs_active_epus ON cron_runs (puskesmas_id) "
        "WHERE deleted_at IS NULL AND status IN ('pending','running') "
        "AND source_scope IN ('both','epus_only')"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_cron_runs_active_asik ON cron_runs (puskesmas_id) "
        "WHERE deleted_at IS NULL AND status IN ('pending','running') "
        "AND source_scope IN ('both','asik_only')"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_cron_runs_active_asik")
    op.execute("DROP INDEX IF EXISTS uq_cron_runs_active_epus")
    op.execute(
        "CREATE UNIQUE INDEX uq_cron_runs_active_per_pk ON cron_runs (puskesmas_id) "
        "WHERE status IN ('pending','running') AND deleted_at IS NULL"
    )

    for table in _TABLES:
        op.drop_column(table, "source_scope")

    postgresql.ENUM(name="cron_source_scope").drop(op.get_bind(), checkfirst=True)
