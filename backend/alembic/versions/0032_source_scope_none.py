"""cron_source_scope enum: add 'none' + extend lane indexes to cover it

'none' = a sync-only date-range backfill: skip ALL scraping, run MERGE (merge any
matched-but-unmerged patients from data already on disk) then the ASIK sync step.
A 'none' run writes merged_data and pushes to the one-account ASIK session, so it
must be mutually exclusive with every other active run for the puskesmas — it
occupies BOTH lanes, so 'none' is added to each cron_runs partial unique index.

Postgres enum ADD VALUE cannot run inside a transaction block → autocommit; the
value is committed there before the index DDL below casts 'none' to the enum.

Revision ID: 0032_source_scope_none
Revises: 0031_backfill_cron_config_link
Create Date: 2026-07-21 00:02:00

"""
from collections.abc import Sequence

from alembic import op

revision: str = "0032_source_scope_none"
down_revision: str | None = "0031_backfill_cron_config_link"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ADD VALUE cannot run inside a transaction block; autocommit_block exits the
    # migration's transaction for just this statement, committing 'none' before
    # the index DDL below references it. IF NOT EXISTS makes it idempotent.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE cron_source_scope ADD VALUE IF NOT EXISTS 'none'")

    # A 'none' run touches both lanes (it's mutually exclusive with everything) —
    # add it to both partial unique indexes so the race-safe DB guard covers it,
    # matching _SCOPE_LANES[NONE] = {epus, asik}. The partial indexes only cover
    # active (pending/running) rows, so this rebuild is tiny and fast.
    op.execute("DROP INDEX IF EXISTS uq_cron_runs_active_epus")
    op.execute("DROP INDEX IF EXISTS uq_cron_runs_active_asik")
    op.execute(
        "CREATE UNIQUE INDEX uq_cron_runs_active_epus ON cron_runs (puskesmas_id) "
        "WHERE deleted_at IS NULL AND status IN ('pending','running') "
        "AND source_scope IN ('both','epus_only','none')"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_cron_runs_active_asik ON cron_runs (puskesmas_id) "
        "WHERE deleted_at IS NULL AND status IN ('pending','running') "
        "AND source_scope IN ('both','asik_only','none')"
    )


def downgrade() -> None:
    # Restore the pre-'none' index WHERE clauses. The enum value itself can't be
    # dropped (Postgres has no DROP VALUE for enums); leaving it is harmless.
    # CAVEAT: after this downgrade the 'none' value still exists and app code may
    # still create 'none' backfills, but the lane indexes no longer serialize
    # them — pair a downgrade with a code revert, or 'none' runs lose their
    # race-safe mutual-exclusion guard.
    op.execute("DROP INDEX IF EXISTS uq_cron_runs_active_epus")
    op.execute("DROP INDEX IF EXISTS uq_cron_runs_active_asik")
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
