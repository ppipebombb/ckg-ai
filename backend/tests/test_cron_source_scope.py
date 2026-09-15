"""Source-scope state machine + lane-conflict rules for date-range backfills.

The pure-function tests (scope → step transitions, predecessor gating, lane
conflict) run fully offline. The lane-index behavior test needs a real, migrated
Postgres (the cron_runs.source_scope column + uq_cron_runs_active_epus/_asik
partial indexes) and self-skips when one isn't reachable.
"""

import uuid
from datetime import date

import pytest
import sqlalchemy as sa

from app.models.cron_config import CronSourceScope, scopes_conflict
from app.models.cron_run import CronStep
from app.tasks.cron import _first_step, _next_step, _prev_step_of

S = CronSourceScope


# ───────────────────────── pure-function rules ──────────────────────────────


def test_scopes_conflict_truth_table():
    # BOTH occupies both lanes → conflicts with everything.
    assert scopes_conflict(S.BOTH, S.BOTH)
    assert scopes_conflict(S.BOTH, S.EPUS_ONLY)
    assert scopes_conflict(S.BOTH, S.ASIK_ONLY)
    # Same single source conflicts with itself.
    assert scopes_conflict(S.EPUS_ONLY, S.EPUS_ONLY)
    assert scopes_conflict(S.ASIK_ONLY, S.ASIK_ONLY)
    # Different single sources DO NOT conflict — the whole point of the feature.
    assert not scopes_conflict(S.EPUS_ONLY, S.ASIK_ONLY)
    assert not scopes_conflict(S.ASIK_ONLY, S.EPUS_ONLY)


def test_scopes_conflict_none_blocks_everything():
    # NONE (sync-only) occupies both lanes → mutually exclusive with every scope,
    # including another NONE run for the same puskesmas. No KeyError on the enum.
    for other in (S.BOTH, S.EPUS_ONLY, S.ASIK_ONLY, S.NONE):
        assert scopes_conflict(S.NONE, other)
        assert scopes_conflict(other, S.NONE)


def test_first_step_per_scope():
    assert _first_step(S.BOTH) is CronStep.EPUS
    assert _first_step(S.EPUS_ONLY) is CronStep.EPUS
    assert _first_step(S.ASIK_ONLY) is CronStep.ASIK
    # NONE scrapes nothing → starts straight at MERGE.
    assert _first_step(S.NONE) is CronStep.MERGE


def test_next_step_both_is_full_chain():
    # run_sync=False: MERGE ends the chain.
    assert _next_step(CronStep.EPUS, S.BOTH, False) == CronStep.ASIK.value
    assert _next_step(CronStep.ASIK, S.BOTH, False) == CronStep.MERGE.value
    assert _next_step(CronStep.MERGE, S.BOTH, False) == "done"


def test_next_step_single_source_skips_the_other_scrape():
    # EPUS_ONLY: EPUS → MERGE (no ASIK).
    assert _next_step(CronStep.EPUS, S.EPUS_ONLY, False) == CronStep.MERGE.value
    assert _next_step(CronStep.MERGE, S.EPUS_ONLY, False) == "done"
    # ASIK_ONLY: ASIK → MERGE (no EPUS).
    assert _next_step(CronStep.ASIK, S.ASIK_ONLY, False) == CronStep.MERGE.value
    assert _next_step(CronStep.MERGE, S.ASIK_ONLY, False) == "done"


def test_next_step_appends_sync_when_enabled():
    # run_sync=True: MERGE → SYNC → done, for every scope.
    for scope in (S.BOTH, S.EPUS_ONLY, S.ASIK_ONLY):
        assert _next_step(CronStep.MERGE, scope, True) == CronStep.SYNC.value
        assert _next_step(CronStep.SYNC, scope, True) == "done"
    # The scrape/merge transitions are unaffected by run_sync.
    assert _next_step(CronStep.EPUS, S.BOTH, True) == CronStep.ASIK.value
    assert _next_step(CronStep.ASIK, S.BOTH, True) == CronStep.MERGE.value


def test_prev_step_of_is_scope_aware():
    # First steps have no predecessor.
    assert _prev_step_of("epus", S.BOTH, False) is None
    assert _prev_step_of("epus", S.EPUS_ONLY, False) is None
    assert _prev_step_of("asik", S.ASIK_ONLY, False) is None  # ASIK is first here
    # ASIK is a successor only in BOTH.
    assert _prev_step_of("asik", S.BOTH, False) is CronStep.EPUS
    # MERGE's predecessor is the single scrape that ran for the scope.
    assert _prev_step_of("merge", S.BOTH, False) is CronStep.ASIK
    assert _prev_step_of("merge", S.ASIK_ONLY, False) is CronStep.ASIK
    assert _prev_step_of("merge", S.EPUS_ONLY, False) is CronStep.EPUS
    # Without sync, done is gated on MERGE.
    assert _prev_step_of("done", S.BOTH, False) is CronStep.MERGE


def test_prev_step_of_with_sync_enabled():
    # SYNC's predecessor is MERGE; done's predecessor becomes SYNC.
    assert _prev_step_of("sync", S.BOTH, True) is CronStep.MERGE
    assert _prev_step_of("done", S.BOTH, True) is CronStep.SYNC
    assert _prev_step_of("done", S.ASIK_ONLY, True) is CronStep.SYNC


def test_none_scope_step_machine_is_merge_then_sync():
    # NONE flow: (no scrape) → MERGE → SYNC → done. MERGE is the first step, so it
    # has no predecessor to gate (returning ASIK here would fail the run at once).
    assert _prev_step_of("merge", S.NONE, True) is None
    assert _next_step(CronStep.MERGE, S.NONE, True) == CronStep.SYNC.value
    assert _next_step(CronStep.SYNC, S.NONE, True) == "done"
    # SYNC's predecessor is MERGE; done's is SYNC (sync is always on for NONE).
    assert _prev_step_of("sync", S.NONE, True) is CronStep.MERGE
    assert _prev_step_of("done", S.NONE, True) is CronStep.SYNC


def test_backfill_create_none_validation():
    from pydantic import ValidationError

    from app.models.cron_config import CronMergeMode, CronSyncMode
    from app.schemas.cron_backfill import CronBackfillCreate

    base = dict(
        puskesmas_id=uuid.uuid4(),
        date_from=date(2025, 1, 1),
        date_to=date(2025, 1, 31),
    )

    # Valid: none + sync on + merge normal (default) + no mandiri.
    ok = CronBackfillCreate(**base, source_scope=S.NONE, sync_mode=CronSyncMode.NORMAL)
    assert ok.source_scope is S.NONE

    # none + sync off → rejected (the run would do nothing).
    with pytest.raises(ValidationError, match="requires sync_mode on"):
        CronBackfillCreate(**base, source_scope=S.NONE, sync_mode=CronSyncMode.OFF)

    # none + no_merge → rejected (short-circuits before sync).
    with pytest.raises(ValidationError, match="no_merge"):
        CronBackfillCreate(
            **base,
            source_scope=S.NONE,
            sync_mode=CronSyncMode.NORMAL,
            merge_mode=CronMergeMode.NO_MERGE,
        )

    # none + mandiri_only → rejected (mandiri forces an ASIK scrape).
    with pytest.raises(ValidationError, match="mandiri_only"):
        CronBackfillCreate(
            **base,
            source_scope=S.NONE,
            sync_mode=CronSyncMode.NORMAL,
            mandiri_only=True,
        )


# ───────────────────── lane partial-unique index (DB) ────────────────────────


def _db_available() -> bool:
    # Casting 'none' asserts migration 0032 (added the value + extended the lane
    # indexes this test probes) has been applied — and 0023 transitively, since
    # the cron_source_scope type/column exist by then.
    try:
        from app.database import engine

        with engine.connect() as conn:
            conn.execute(sa.text("SELECT 'none'::cron_source_scope"))
        return True
    except Exception:
        return False


@pytest.mark.skipif(
    not _db_available(), reason="Postgres (migrated to 0032) not reachable"
)
def test_lane_indexes_allow_epus_plus_asik_but_block_same_lane():
    """EPUS_ONLY ∥ ASIK_ONLY active runs for one puskesmas are allowed; a second
    run sharing a lane (or any BOTH run) is rejected by the partial indexes.

    Uses an explicit connection + transaction (the repo's DB-test pattern in
    test_prod_login.py) so everything rolls back and nothing is committed. Each
    index probe runs inside a SAVEPOINT (begin_nested) so the expected
    IntegrityError only unwinds that probe, not the seeded puskesmas.
    """
    from app.database import SessionLocal, engine
    from app.models.cron_run import CronRun, CronRunStatus
    from app.models.puskesmas import Puskesmas

    pid = uuid.uuid4()

    def _mk(scope: CronSourceScope) -> CronRun:
        return CronRun(
            puskesmas_id=pid,
            target_date=date(2026, 1, 1),
            source_scope=scope,
            status=CronRunStatus.RUNNING,
            current_step_attempt=0,
        )

    conn = engine.connect()
    trans = conn.begin()
    db = SessionLocal(bind=conn)
    try:
        # cron_runs.puskesmas_id is a FK; seed a puskesmas so the inserts exercise
        # only the lane indexes, not the FK.
        db.add(Puskesmas(id=pid, name="Test PKM (source-scope index)"))
        # Different lanes → both insert fine.
        db.add(_mk(S.EPUS_ONLY))
        db.add(_mk(S.ASIK_ONLY))
        db.flush()

        # A second EPUS-touching run collides on uq_cron_runs_active_epus.
        with db.begin_nested():
            db.add(_mk(S.EPUS_ONLY))
            with pytest.raises(sa.exc.IntegrityError):
                db.flush()

        # A second ASIK-touching run collides on uq_cron_runs_active_asik.
        with db.begin_nested():
            db.add(_mk(S.ASIK_ONLY))
            with pytest.raises(sa.exc.IntegrityError):
                db.flush()

        # A BOTH run occupies both lanes → collides with the existing runs.
        with db.begin_nested():
            db.add(_mk(S.BOTH))
            with pytest.raises(sa.exc.IntegrityError):
                db.flush()

        # A NONE (sync-only) run also occupies both lanes → collides with the
        # existing EPUS_ONLY / ASIK_ONLY runs on both partial indexes. This is
        # the DB-level half of the mutual-exclusion guard 0032 added; without
        # 'none' in both index WHERE clauses this insert would slip through.
        with db.begin_nested():
            db.add(_mk(S.NONE))
            with pytest.raises(sa.exc.IntegrityError):
                db.flush()
    finally:
        db.close()
        trans.rollback()
        conn.close()
