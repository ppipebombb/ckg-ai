import json
import logging
import uuid
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import redis
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, load_only

from app.celery_app import celery_app
from app.config import settings
from app.crud import cron_backfill as cron_backfill_crud
from app.crud import cron_config as cron_config_crud
from app.crud import cron_run as cron_run_crud
from app.crud import merge_job as merge_job_crud
from app.crud import scrape_job as scrape_job_crud
from app.database import SessionLocal
from app.models.cron_backfill import CronBackfill, CronBackfillStatus
from app.models.cron_config import (
    CronConfig,
    CronMergeMode,
    CronSourceScope,
    CronSyncMode,
    scopes_conflict,
)
from app.models.cron_run import CronRun, CronRunStatus, CronStep
from app.models.patient import Patient
from app.models.school_cron_config import SchoolCronConfig
from app.models.scrape_job import ScrapeJob, ScrapeKind, ScrapeStatus, TriggererType

log = logging.getLogger(__name__)

MAX_ATTEMPTS = 3
RETRY_BASE_SECONDS = 60


def cancel_key(cron_run_id: str) -> str:
    return f"cron_run:{cron_run_id}:cancel"


def backfill_cancel_key(cron_backfill_id: str) -> str:
    return f"cron_backfill:{cron_backfill_id}:cancel"


_BF_TERMINAL = (
    CronBackfillStatus.SUCCESS,
    CronBackfillStatus.FAILED,
    CronBackfillStatus.CANCELLED,
)

_BF_TASK_COLS = (
    CronBackfill.id,
    CronBackfill.puskesmas_id,
    CronBackfill.date_from,
    CronBackfill.date_to,
    CronBackfill.cursor_date,
    CronBackfill.status,
    CronBackfill.merge_mode,
    CronBackfill.source_scope,
    CronBackfill.triggered_by_id,
    CronBackfill.current_cron_run_id,
    CronBackfill.total_dates,
    CronBackfill.completed_dates,
    CronBackfill.started_at,
    CronBackfill.finished_at,
)


def _load_active_backfill(
    db: Session, cron_backfill_id: uuid.UUID
) -> CronBackfill | None:
    bf = db.scalar(
        select(CronBackfill)
        .options(load_only(*_BF_TASK_COLS))
        .where(CronBackfill.id == cron_backfill_id)
    )
    if bf is None or bf.status in _BF_TERMINAL:
        return None
    return bf


def _propagate_run_failed_to_backfill(
    db: Session, run: CronRun, error_message: str, finished_at: datetime
) -> None:
    if run.cron_backfill_id is None:
        return
    bf = _load_active_backfill(db, run.cron_backfill_id)
    if bf is None:
        return
    cron_backfill_crud.mark_failed(
        db, bf, run.target_date, error_message, finished_at
    )


def _propagate_run_cancelled_to_backfill(db: Session, run: CronRun) -> None:
    if run.cron_backfill_id is None:
        return
    bf = _load_active_backfill(db, run.cron_backfill_id)
    if bf is None:
        return
    cron_backfill_crud.mark_cancelled(db, bf)


def _redis() -> "redis.Redis":
    return redis.from_url(settings.REDIS_URL, decode_responses=True)


def _is_cancelled(rc: "redis.Redis", cron_run_id: str) -> bool:
    try:
        return rc.get(cancel_key(cron_run_id)) == "1"
    except Exception:
        return False


def _resolve_source_scope(run: CronRun) -> CronSourceScope:
    """Scope is stored on the run itself (copied from the backfill at creation;
    BOTH for config/run-now runs), so no extra query is needed."""
    return run.source_scope or CronSourceScope.BOTH


def _first_step(scope: CronSourceScope) -> CronStep:
    # NONE scrapes nothing → start at MERGE (sync-only: merge any matched-but-
    # unmerged patients from existing data, then the SYNC step pushes to ASIK).
    # ASIK_ONLY starts at ASIK; BOTH/EPUS_ONLY start at EPUS (which, for BOTH,
    # runs first so its (nik, ruangan) rows are seeded before ASIK fans out).
    if scope is CronSourceScope.NONE:
        return CronStep.MERGE
    return CronStep.ASIK if scope is CronSourceScope.ASIK_ONLY else CronStep.EPUS


def _next_step(
    step: CronStep, scope: CronSourceScope, run_sync: bool, run_create: bool = False
) -> str:
    # Flow per scope ([SYNC] appended when run_sync; [CREATE] after SYNC when run_create,
    # which is itself gated on run_sync):
    #   BOTH:      EPUS → ASIK → MERGE → [SYNC] → [CREATE] → done
    #   EPUS_ONLY: EPUS → MERGE → [SYNC] → [CREATE] → done   (skip ASIK)
    #   ASIK_ONLY: ASIK → MERGE → [SYNC] → [CREATE] → done   (skip EPUS)
    if step == CronStep.EPUS:
        return (
            CronStep.ASIK.value
            if scope is CronSourceScope.BOTH
            else CronStep.MERGE.value
        )
    if step == CronStep.ASIK:
        return CronStep.MERGE.value
    if step == CronStep.MERGE:
        return CronStep.SYNC.value if run_sync else "done"
    if step == CronStep.SYNC:
        return CronStep.CREATE.value if run_create else "done"
    # step == CREATE → done
    return "done"


def _resolve_target_date(offset_days: int, now_utc: datetime | None = None) -> date:
    base = (now_utc or datetime.now(UTC)).astimezone(ZoneInfo("Asia/Jakarta")).date()
    return base + timedelta(days=offset_days)


@celery_app.task(name="cron.dispatch_due")
def dispatch_due() -> int:
    """Beat-driven sweeper. Atomically claims due cron_config rows, advances each
    one's next_run_at, and spawns a CronBackfill covering its rolling LOOKBACK
    window ([target - (lookback-1) .. target]). Returns count of backfills spawned.

    Why a backfill window: late-arriving EPUS/ASIK only match a past date once BOTH
    sides land, so re-scraping + re-merging the last few days each run is how late
    matches are picked up. The backfill runs the existing sequential per-date pipeline
    (scrape → merge → [sync]); merge/sync NORMAL modes make the re-work incremental.

    Claim + next_run_at update happen in ONE transaction so FOR UPDATE SKIP LOCKED
    protects the claim. Backfill creation + dispatch happen AFTER commit. A config
    backfill is BOTH-scope → it is skipped when another run/backfill is already active
    for that puskesmas (this fire is dropped; next_run_at already advanced, so it
    retries at the next scheduled time)."""
    fired = 0
    # (cron_config_id, puskesmas_id, date_from, date_to, merge_mode, sync_mode, create_new)
    pending: list[tuple] = []
    now = datetime.now(UTC)

    # Pull just the ids without locking — locking happens per-cfg below in its
    # own transaction so a failure on one cfg doesn't trash the others.
    db_ids: Session = SessionLocal()
    try:
        cfg_ids = list(
            db_ids.scalars(
                select(CronConfig.id).where(
                    CronConfig.enabled.is_(True),
                    CronConfig.next_run_at <= now,
                )
            ).all()
        )
    finally:
        db_ids.close()

    for cfg_id in cfg_ids:
        db: Session = SessionLocal()
        try:
            cfg = db.scalar(
                select(CronConfig)
                .where(CronConfig.id == cfg_id)
                .with_for_update(skip_locked=True)
            )
            if cfg is None or not cfg.enabled or cfg.next_run_at > now:
                # Another beat replica or a writer beat us; harmless skip.
                continue
            target_date = _resolve_target_date(cfg.target_offset_days, now)
            lookback = max(1, cfg.lookback_days or 1)
            date_from = target_date - timedelta(days=lookback - 1)
            params = (
                cfg.id, cfg.puskesmas_id, date_from, target_date,
                cfg.merge_mode, cfg.sync_mode, cfg.create_new,
            )
            cfg.next_run_at = cron_config_crud.compute_next_run_at(
                cfg.hour, cfg.minute, from_=now
            )
            cfg.last_fired_at = now
            db.commit()
            pending.append(params)
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    # Spawn each backfill outside the claim txn. A config backfill is BOTH-scope, so
    # it conflicts with ANY active run/backfill for that puskesmas — skip this fire
    # if one is in progress (next_run_at already advanced → retries next tick).
    for cfg_id, pk_id, date_from, date_to, merge_mode, sync_mode, create_new in pending:
        db2: Session = SessionLocal()
        try:
            active_run = db2.scalar(
                select(CronRun.id).where(
                    CronRun.puskesmas_id == pk_id,
                    CronRun.status.in_((CronRunStatus.PENDING, CronRunStatus.RUNNING)),
                ).limit(1)
            )
            active_bf = db2.scalar(
                select(CronBackfill.id).where(
                    CronBackfill.puskesmas_id == pk_id,
                    CronBackfill.status.in_(
                        (CronBackfillStatus.PENDING, CronBackfillStatus.RUNNING)
                    ),
                ).limit(1)
            )
            if active_run is not None or active_bf is not None:
                log.info(
                    "cron: skip scheduled backfill for pk=%s — run/backfill active", pk_id
                )
                continue
            bf = cron_backfill_crud.create(
                db2,
                puskesmas_id=pk_id,
                date_from=date_from,
                date_to=date_to,
                merge_mode=merge_mode,
                source_scope=CronSourceScope.BOTH,
                mandiri_only=False,
                sync_mode=sync_mode,
                create_new=create_new,
                triggered_by_id=None,  # beat-fired: no human triggerer
                cron_config_id=cfg_id,  # link so config disable/delete can cancel it
            )
            try:
                celery_app.send_task(
                    "cron.dispatch_backfill_next", args=[str(bf.id)]
                )
                fired += 1
            except Exception as exc:
                cron_backfill_crud.mark_failed(
                    db2, bf, date_from,
                    f"broker unreachable: {exc}", datetime.now(UTC),
                )
        except Exception as exc:
            db2.rollback()
            log.warning(
                "cron: failed to spawn scheduled backfill for pk=%s: %s", pk_id, exc
            )
        finally:
            db2.close()
    return fired


@celery_app.task(name="cron.dispatch_school_due")
def dispatch_school_due() -> int:
    """Beat-driven sweeper for the date-less CKG-Sekolah schedule.

    Far simpler than dispatch_due: a school config has no step machine, date,
    or merge. Each due config just spawns one asik_sekolah ScrapeJob (the job
    itself walks every school × class). The uq_scrape_jobs_active_per_puskesmas_kind
    index serializes one active asik_sekolah job per puskesmas — an IntegrityError
    means one is already running, so we only advance next_run_at and skip.
    """
    fired = 0
    pending: list[uuid.UUID] = []  # scrape_job ids to dispatch after commit
    now = datetime.now(UTC)

    db_ids: Session = SessionLocal()
    try:
        cfg_ids = list(
            db_ids.scalars(
                select(SchoolCronConfig.id).where(
                    SchoolCronConfig.enabled.is_(True),
                    SchoolCronConfig.next_run_at <= now,
                )
            ).all()
        )
    finally:
        db_ids.close()

    for cfg_id in cfg_ids:
        db: Session = SessionLocal()
        try:
            cfg = db.scalar(
                select(SchoolCronConfig)
                .where(SchoolCronConfig.id == cfg_id)
                .with_for_update(skip_locked=True)
            )
            if cfg is None or not cfg.enabled or cfg.next_run_at > now:
                continue
            cfg.next_run_at = cron_config_crud.compute_next_run_at(
                cfg.hour, cfg.minute, from_=now
            )
            job = ScrapeJob(
                puskesmas_id=cfg.puskesmas_id,
                kind=ScrapeKind.ASIK_SEKOLAH,
                date_filter=None,
                triggered_by_id=cfg.puskesmas_id,
                triggered_by_type=TriggererType.CRON,
                status=ScrapeStatus.PENDING,
            )
            db.add(job)
            try:
                db.flush()
            except IntegrityError:
                # Active asik_sekolah job already covers this puskesmas. Skip the
                # spawn but still advance next_run_at so we don't re-fire every minute.
                db.rollback()
                cfg2 = db.scalar(
                    select(SchoolCronConfig)
                    .where(SchoolCronConfig.id == cfg_id)
                    .with_for_update(skip_locked=True)
                )
                if cfg2 is not None:
                    cfg2.next_run_at = cron_config_crud.compute_next_run_at(
                        cfg2.hour, cfg2.minute, from_=now
                    )
                db.commit()
                continue
            cfg.last_fired_at = now
            job_id = job.id
            db.commit()
            pending.append(job_id)
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    for job_id in pending:
        try:
            celery_app.send_task(
                "scrape.run",
                args=[str(job_id), ScrapeKind.ASIK_SEKOLAH.value],
                kwargs={"headless": True},
            )
            fired += 1
        except Exception as exc:
            log.warning("school scrape broker unreachable for job=%s: %s", job_id, exc)
            db2: Session = SessionLocal()
            try:
                job = db2.scalar(select(ScrapeJob).where(ScrapeJob.id == job_id))
                if job is not None:
                    scrape_job_crud.mark_failed(
                        db2, job, f"broker unreachable: {exc}", datetime.now(UTC)
                    )
            finally:
                db2.close()
    return fired


def _resolve_merge_mode(db: Session, run: CronRun) -> CronMergeMode:
    """Read the merge_mode for this run from its backfill or config. Bypasses
    the soft-delete auto-filter (include_deleted) so a soft-deleted parent still
    supplies the flag during retry of a historical run. Defaults to NORMAL."""
    mode = None
    if run.cron_backfill_id is not None:
        mode = db.scalar(
            select(CronBackfill.merge_mode)
            .where(CronBackfill.id == run.cron_backfill_id)
            .execution_options(include_deleted=True)
        )
    elif run.cron_config_id is not None:
        mode = db.scalar(
            select(CronConfig.merge_mode)
            .where(CronConfig.id == run.cron_config_id)
            .execution_options(include_deleted=True)
        )
    return mode or CronMergeMode.NORMAL


def _resolve_sync_mode(db: Session, run: CronRun) -> CronSyncMode:
    """Read the sync_mode for this run from its backfill or config. Bypasses the
    soft-delete auto-filter (include_deleted) so a soft-deleted parent still
    supplies the flag during retry of a historical run. Defaults to OFF."""
    mode = None
    if run.cron_backfill_id is not None:
        mode = db.scalar(
            select(CronBackfill.sync_mode)
            .where(CronBackfill.id == run.cron_backfill_id)
            .execution_options(include_deleted=True)
        )
    elif run.cron_config_id is not None:
        mode = db.scalar(
            select(CronConfig.sync_mode)
            .where(CronConfig.id == run.cron_config_id)
            .execution_options(include_deleted=True)
        )
    return mode or CronSyncMode.OFF


def _resolve_create_new(db: Session, run: CronRun) -> bool:
    """True when this run's backfill/config has create_new set (the ASIK CREATE step
    after sync). Bypasses the soft-delete auto-filter (include_deleted) so a retried
    historical run still reads the flag. Defaults to False."""
    val = None
    if run.cron_backfill_id is not None:
        val = db.scalar(
            select(CronBackfill.create_new)
            .where(CronBackfill.id == run.cron_backfill_id)
            .execution_options(include_deleted=True)
        )
    elif run.cron_config_id is not None:
        val = db.scalar(
            select(CronConfig.create_new)
            .where(CronConfig.id == run.cron_config_id)
            .execution_options(include_deleted=True)
        )
    return bool(val)


def _resolve_mandiri_only(db: Session, run: CronRun) -> bool:
    """True when this run belongs to a Mandiri-only backfill. Configs are never
    mandiri-only, so only the backfill path is checked. Bypasses the soft-delete
    auto-filter so a retried historical run still reads the flag."""
    if run.cron_backfill_id is None:
        return False
    return bool(
        db.scalar(
            select(CronBackfill.mandiri_only)
            .where(CronBackfill.id == run.cron_backfill_id)
            .execution_options(include_deleted=True)
        )
    )


def _gather_mandiri_niks(
    db: Session, puskesmas_id: uuid.UUID, target_date: date
) -> list[str]:
    """NIKs already in our DB for this puskesmas+date that have ASIK data but
    still lack Pemeriksaan Mandiri (has_mandiri=False). These are the only rows
    the Mandiri-only backfill needs to re-scrape."""
    rows = db.execute(
        select(Patient.nik)
        .where(
            Patient.puskesmas_id == puskesmas_id,
            Patient.filter_date == target_date,
            Patient.scraped_asik_data.isnot(None),
            Patient.has_mandiri.is_(False),
        )
        .distinct()
    ).all()
    return [r.nik for r in rows]


def _create_child_job(
    db: Session,
    run: CronRun,
    step: CronStep,
) -> uuid.UUID:
    iso_date = run.target_date.isoformat()
    # triggered_by_id is NOT NULL on (scrape|merge)_jobs. Prefer the human admin
    # who triggered the cron run (run-now / retry); fall back to puskesmas_id
    # for beat-fired runs where there is no human triggerer.
    triggered_by = run.triggered_by_id or run.puskesmas_id
    if step == CronStep.MERGE:
        # NO_MERGE never reaches here — advance() short-circuits to 'done'
        # before the merge child is created (see advance()).
        mode = _resolve_merge_mode(db, run)
        job = merge_job_crud.create(
            db,
            puskesmas_id=run.puskesmas_id,
            date_filter=iso_date,
            triggered_by_id=triggered_by,
            triggered_by_type=TriggererType.CRON,
            force_remerge=(mode is CronMergeMode.FORCE_REMERGE),
            cron_run_id=run.id,
        )
        return job.id
    kind = ScrapeKind.ASIK if step == CronStep.ASIK else ScrapeKind.EPUS
    mandiri_only = step == CronStep.ASIK and _resolve_mandiri_only(db, run)
    target_niks: str | None = None
    if mandiri_only:
        # Restrict the scrape to NIKs still missing Mandiri for this date. An
        # empty allowlist means there's nothing to backfill — the scraper still
        # runs but deep-scrapes no rows (fast no-op), and the MERGE step is a
        # no-op re-merge. Encoded as a JSON list (worker emits --niks).
        target_niks = json.dumps(
            _gather_mandiri_niks(db, run.puskesmas_id, run.target_date)
        )
    job = scrape_job_crud.create(
        db,
        puskesmas_id=run.puskesmas_id,
        kind=kind,
        date_filter=iso_date,
        triggered_by_id=triggered_by,
        triggered_by_type=TriggererType.CRON,
        cron_run_id=run.id,
        asik_mandiri_only=mandiri_only,
        target_niks=target_niks,
    )
    return job.id


def _dispatch_child(
    cron_run_id: str,
    step: CronStep,
    job_id: uuid.UUID | None,
    scope: CronSourceScope,
    run_sync: bool,
    run_create: bool = False,
) -> None:
    next_step = _next_step(step, scope, run_sync, run_create)
    link = celery_app.signature(
        "cron.advance",
        args=[cron_run_id, next_step],
        immutable=True,
    )
    link_error = celery_app.signature(
        "cron.handle_failure",
        args=[cron_run_id, step.value],
        immutable=True,
    )
    if step in (CronStep.SYNC, CronStep.CREATE):
        # No per-step job row: the batch task fans out per-patient jobs for this
        # puskesmas+date in one ASIK session (SYNC → SyncJobs; CREATE → register each
        # epus_only patient, then fill via a SyncJob). It RAISES on a fatal
        # (session/creds) failure → link_error; per-patient failures are recorded on
        # their own job and don't fail the whole step.
        celery_app.send_task(
            "sync.run_cron_batch" if step == CronStep.SYNC else "create.run_cron_batch",
            args=[cron_run_id],
            link=link,
            link_error=link_error,
        )
    elif step == CronStep.MERGE:
        celery_app.send_task(
            "merge.run",
            args=[str(job_id)],
            link=link,
            link_error=link_error,
        )
    else:
        celery_app.send_task(
            "scrape.run",
            args=[str(job_id), step.value],
            link=link,
            link_error=link_error,
        )


def _prev_step_of(
    step: str, scope: CronSourceScope, run_sync: bool, run_create: bool = False
) -> CronStep | None:
    """The step that must have SUCCEEDED before advancing into `step`, given the
    run's source scope. Returns None when `step` is the first step (no
    predecessor to check)."""
    if step == CronStep.ASIK.value:
        # ASIK is a successor only in BOTH (EPUS→ASIK). In ASIK_ONLY it is the
        # first step → no predecessor.
        return CronStep.EPUS if scope is CronSourceScope.BOTH else None
    if step == CronStep.MERGE.value:
        # NONE scrapes nothing → MERGE is the first step, no predecessor to gate.
        if scope is CronSourceScope.NONE:
            return None
        # MERGE's predecessor is the single scrape that ran for this scope.
        return (
            CronStep.EPUS
            if scope is CronSourceScope.EPUS_ONLY
            else CronStep.ASIK
        )
    if step == CronStep.SYNC.value:
        return CronStep.MERGE
    if step == CronStep.CREATE.value:
        return CronStep.SYNC
    if step == "done":
        # Last step before 'done': CREATE if enabled, else SYNC, else MERGE.
        if run_create:
            return CronStep.CREATE
        return CronStep.SYNC if run_sync else CronStep.MERGE
    return None  # step == EPUS → always the first step when present


def _previous_step_failed(
    db: Session, run: CronRun, step: str, scope: CronSourceScope,
    run_sync: bool, run_create: bool = False,
) -> CronStep | None:
    """When advancing into `step`, verify the previous step's child job ended
    in SUCCESS. Returns the previous CronStep enum if it did NOT succeed (so
    the caller routes to handle_failure); returns None if previous succeeded
    or there is no previous step to check."""
    from app.models.merge_job import MergeJob, MergeStatus
    from app.models.scrape_job import ScrapeJob, ScrapeStatus

    prev = _prev_step_of(step, scope, run_sync, run_create)
    if prev is None:
        return None
    if prev in (CronStep.SYNC, CronStep.CREATE):
        # The sync/create batch RAISES on a fatal failure → link_error → handle_failure,
        # so reaching the next step means its `link` fired = success. No job row to check
        # (per-patient failures live on individual Sync/Scrape jobs, not the step).
        return None
    if prev == CronStep.EPUS:
        job_id = run.epus_scrape_job_id
        status = (
            db.scalar(select(ScrapeJob.status).where(ScrapeJob.id == job_id))
            if job_id else None
        )
        return None if status == ScrapeStatus.SUCCESS else prev
    if prev == CronStep.ASIK:
        job_id = run.asik_scrape_job_id
        status = (
            db.scalar(select(ScrapeJob.status).where(ScrapeJob.id == job_id))
            if job_id else None
        )
        return None if status == ScrapeStatus.SUCCESS else prev
    # prev == MERGE (we're going to 'done')
    job_id = run.merge_job_id
    status = (
        db.scalar(select(MergeJob.status).where(MergeJob.id == job_id))
        if job_id else None
    )
    return None if status == MergeStatus.SUCCESS else prev


@celery_app.task(name="cron.advance")
def advance(cron_run_id: str, step: str) -> None:
    """Drive the cron run forward to `step`. Either kicks off a child task
    (asik/epus/merge) or finalizes when step == 'done'."""
    db: Session = SessionLocal()
    rc = _redis()
    try:
        run_uuid = uuid.UUID(cron_run_id)
        run = db.scalar(select(CronRun).where(CronRun.id == run_uuid))
        if run is None:
            return
        if run.status in (CronRunStatus.FAILED, CronRunStatus.CANCELLED):
            return

        if _is_cancelled(rc, cron_run_id):
            cron_run_crud.mark_cancelled(db, run)
            _propagate_run_cancelled_to_backfill(db, run)
            return

        # Parent cron_config soft-deleted or disabled — kill the chain even if
        # this task was queued before the config change (survives broker
        # restarts) or fired via a link callback mid-chain. include_deleted
        # so we observe the soft-delete state, not have it filtered away.
        if run.cron_config_id is not None:
            cfg = db.scalar(
                select(CronConfig)
                .where(CronConfig.id == run.cron_config_id)
                .execution_options(include_deleted=True)
            )
            if cfg is None or cfg.deleted_at is not None or not cfg.enabled:
                cron_run_crud.cancel_cron_run_and_children(db, run)
                _propagate_run_cancelled_to_backfill(db, run)
                return

        scope = _resolve_source_scope(run)
        # Whether this run appends a SYNC step after MERGE (sync_mode != OFF).
        # NO_MERGE runs never reach SYNC (short-circuited to 'done' below), so a
        # NO_MERGE + sync combination is inertly a no-op.
        run_sync = _resolve_sync_mode(db, run) is not CronSyncMode.OFF
        # CREATE step after SYNC — gated on sync being on (create-only would be a no-op).
        run_create = run_sync and _resolve_create_new(db, run)

        # Existing scrape.run / merge.run can call mark_failed without re-raising
        # (e.g. bad credentials, exit code != 0) — Celery still fires `link` in
        # that case. Verify previous step succeeded before advancing, otherwise
        # route to handle_failure for retry/fail-out.
        bad_prev = _previous_step_failed(db, run, step, scope, run_sync, run_create)
        if bad_prev is not None:
            handle_failure.apply_async(args=[cron_run_id, bad_prev.value])
            return

        # NO_MERGE mode: the scoped scrape(s) have run (and the previous-step
        # success check above already gated a failed scrape). Skip the merge step
        # entirely and finalize the run as success — patients stay merged_at=NULL
        # for a later normal/force run or a date-range merge. No merge child is
        # created.
        if (
            step == CronStep.MERGE.value
            and _resolve_merge_mode(db, run) is CronMergeMode.NO_MERGE
        ):
            step = "done"

        if step == "done":
            cron_run_crud.mark_success(db, run, datetime.now(UTC))
            if run.cron_backfill_id is not None:
                bf = _load_active_backfill(db, run.cron_backfill_id)
                if bf is not None:
                    bf_id = str(bf.id)
                    # Check cancel BEFORE advancing the cursor so a cancelled
                    # backfill doesn't record a phantom cursor advance.
                    if rc.get(backfill_cancel_key(bf_id)) == "1":
                        cron_backfill_crud.set_current_run(db, bf, None)
                        cron_backfill_crud.mark_cancelled(db, bf)
                    else:
                        next_cursor = run.target_date + timedelta(days=1)
                        cron_backfill_crud.advance_cursor(db, bf, next_cursor)
                        cron_backfill_crud.set_current_run(db, bf, None)
                        try:
                            celery_app.send_task(
                                "cron.dispatch_backfill_next", args=[bf_id]
                            )
                        except Exception as exc:
                            cron_backfill_crud.mark_failed(
                                db, bf, next_cursor,
                                f"broker unreachable: {exc}",
                                datetime.now(UTC),
                            )
            return

        try:
            current = CronStep(step)
        except ValueError:
            log.warning("cron.advance: unknown step %r for run=%s", step, cron_run_id)
            return

        if run.status == CronRunStatus.PENDING:
            won = cron_run_crud.mark_running(db, run, datetime.now(UTC))
            if not won:
                # Concurrent cancel/fail beat us. Refresh-checked above; bail.
                return

        attempt = (
            run.current_step_attempt + 1
            if run.current_step == current
            else 1
        )

        # SYNC and CREATE have no per-step DB job row — each fans out its own
        # per-patient jobs. Every other step creates a scrape/merge child up front.
        job_id: uuid.UUID | None = None
        if current not in (CronStep.SYNC, CronStep.CREATE):
            try:
                job_id = _create_child_job(db, run, current)
            except IntegrityError as exc:
                db.rollback()
                err = f"conflict creating {current.value} job: {exc}"
                now = datetime.now(UTC)
                cron_run_crud.mark_failed(db, run, current, err, now)
                _propagate_run_failed_to_backfill(db, run, err, now)
                return
            except Exception as exc:
                db.rollback()
                now = datetime.now(UTC)
                cron_run_crud.mark_failed(db, run, current, str(exc), now)
                _propagate_run_failed_to_backfill(db, run, str(exc), now)
                return

        cron_run_crud.set_step(db, run, current, attempt=attempt, job_id=job_id)

        # Re-check cancel after writing the child id. cancel_cron_run_and_children
        # may have run BEFORE we wrote *_scrape_job_id / merge_job_id and
        # therefore did not cancel the just-created child. Catch that window here.
        db.refresh(run)
        if run.status == CronRunStatus.CANCELLED or _is_cancelled(rc, cron_run_id):
            from app.models.merge_job import MergeJob, MergeStatus
            from app.models.scrape_job import ScrapeJob, ScrapeStatus

            if current in (CronStep.SYNC, CronStep.CREATE):
                # No child job created yet — returning here means the batch is
                # never dispatched. (If it were already dispatched, it polls the
                # run cancel signal itself.)
                pass
            elif current == CronStep.MERGE:
                mj = db.scalar(select(MergeJob).where(MergeJob.id == job_id))
                if mj is not None and mj.status in (
                    MergeStatus.PENDING, MergeStatus.RUNNING
                ):
                    merge_job_crud.mark_cancelled(db, mj)
            else:
                sj = db.scalar(select(ScrapeJob).where(ScrapeJob.id == job_id))
                if sj is not None and sj.status in (
                    ScrapeStatus.PENDING, ScrapeStatus.RUNNING
                ):
                    scrape_job_crud.mark_cancelled(db, sj)
            _propagate_run_cancelled_to_backfill(db, run)
            return

        try:
            _dispatch_child(cron_run_id, current, job_id, scope, run_sync, run_create)
        except Exception as exc:
            err = f"broker unreachable: {exc}"
            now = datetime.now(UTC)
            cron_run_crud.mark_failed(db, run, current, err, now)
            _propagate_run_failed_to_backfill(db, run, err, now)
    finally:
        db.close()


@celery_app.task(name="cron.handle_failure")
def handle_failure(cron_run_id: str, step: str) -> None:
    """link_error callback. Decides whether to retry the step (with exponential
    backoff) or mark the cron run FAILED. Called when scrape.run / merge.run
    raised an uncaught exception OR the child job ended in FAILED state."""
    db: Session = SessionLocal()
    rc = _redis()
    try:
        run_uuid = uuid.UUID(cron_run_id)
        run = db.scalar(select(CronRun).where(CronRun.id == run_uuid))
        if run is None:
            return
        if run.status in (CronRunStatus.FAILED, CronRunStatus.CANCELLED):
            return
        if _is_cancelled(rc, cron_run_id):
            cron_run_crud.mark_cancelled(db, run)
            _propagate_run_cancelled_to_backfill(db, run)
            return

        try:
            failed = CronStep(step)
        except ValueError:
            return

        # Merge step: fail fast, NO cron-level retry. merge.run already retried
        # the still-failing patient subset internally up to its round budget;
        # retrying the whole step just hammers a down LLM provider and delays the
        # "stop" signal. Mark the run FAILED (surfacing the merge job's reason)
        # and let _propagate_run_failed_to_backfill halt the backfill. ASIK/EPUS
        # keep their retry below.
        if failed is CronStep.MERGE:
            err = "merge step failed"
            try:
                from app.models.merge_job import MergeJob

                if run.merge_job_id:
                    err = (
                        db.scalar(
                            select(MergeJob.error_message).where(
                                MergeJob.id == run.merge_job_id
                            )
                        )
                        or err
                    )
            except Exception:
                pass
            now = datetime.now(UTC)
            cron_run_crud.mark_failed(db, run, failed, err, now)
            _propagate_run_failed_to_backfill(db, run, err, now)
            return

        attempt = run.current_step_attempt
        if attempt < MAX_ATTEMPTS:
            countdown = RETRY_BASE_SECONDS * (2 ** (attempt - 1))
            try:
                celery_app.signature(
                    "cron.advance",
                    args=[cron_run_id, failed.value],
                    immutable=True,
                ).apply_async(countdown=countdown)
            except Exception as exc:
                err = f"retry dispatch failed: {exc}"
                now = datetime.now(UTC)
                cron_run_crud.mark_failed(db, run, failed, err, now)
                _propagate_run_failed_to_backfill(db, run, err, now)
            return

        # Pull the child's error_message so the cron run surfaces the root cause.
        err = "max retries exhausted"
        try:
            from app.models.merge_job import MergeJob
            from app.models.scrape_job import ScrapeJob

            if failed == CronStep.MERGE and run.merge_job_id:
                err = (
                    db.scalar(
                        select(MergeJob.error_message).where(
                            MergeJob.id == run.merge_job_id
                        )
                    )
                    or err
                )
            elif failed == CronStep.ASIK and run.asik_scrape_job_id:
                err = (
                    db.scalar(
                        select(ScrapeJob.error_message).where(
                            ScrapeJob.id == run.asik_scrape_job_id
                        )
                    )
                    or err
                )
            elif failed == CronStep.EPUS and run.epus_scrape_job_id:
                err = (
                    db.scalar(
                        select(ScrapeJob.error_message).where(
                            ScrapeJob.id == run.epus_scrape_job_id
                        )
                    )
                    or err
                )
        except Exception:
            pass
        now = datetime.now(UTC)
        cron_run_crud.mark_failed(db, run, failed, err, now)
        _propagate_run_failed_to_backfill(db, run, err, now)
    finally:
        db.close()


@celery_app.task(name="cron.dispatch_backfill_next")
def dispatch_backfill_next(cron_backfill_id: str) -> None:
    """Pick the next date for a backfill, spawn a CronRun bound to it, and
    kick off its first step (`_first_step(scope)` — EPUS/ASIK for a scrape scope,
    MERGE for the sync-only NONE scope). Honors the backfill cancel Redis flag
    and bails when the backfill is already terminal."""
    db: Session = SessionLocal()
    rc = _redis()
    try:
        bf_uuid = uuid.UUID(cron_backfill_id)
        bf = db.scalar(
            select(CronBackfill)
            .options(load_only(*_BF_TASK_COLS))
            .where(CronBackfill.id == bf_uuid)
        )
        if bf is None or bf.status in _BF_TERMINAL:
            return

        if rc.get(backfill_cancel_key(cron_backfill_id)) == "1":
            cron_backfill_crud.mark_cancelled(db, bf)
            return

        next_date = bf.cursor_date or bf.date_from
        if next_date > bf.date_to:
            cron_backfill_crud.mark_success(db, bf, datetime.now(UTC))
            return

        # Defend against a lane-conflicting active CronRun for this puskesmas
        # (one that touches the same source). The two partial UNIQUE indexes
        # (uq_cron_runs_active_epus / _asik) would catch it at INSERT, but we
        # surface a clean failure on the backfill instead of an opaque
        # IntegrityError. A non-conflicting run (e.g. an EPUS_ONLY run while this
        # backfill is ASIK_ONLY) is allowed to proceed concurrently.
        active_scopes = db.scalars(
            select(CronRun.source_scope).where(
                CronRun.puskesmas_id == bf.puskesmas_id,
                CronRun.status.in_(
                    (CronRunStatus.PENDING, CronRunStatus.RUNNING)
                ),
            )
        ).all()
        if any(scopes_conflict(bf.source_scope, s) for s in active_scopes):
            cron_backfill_crud.mark_failed(
                db, bf, next_date,
                "another cron run touching the same source is already in "
                "progress for this puskesmas",
                datetime.now(UTC),
            )
            return

        if bf.status == CronBackfillStatus.PENDING:
            won = cron_backfill_crud.mark_running(db, bf, datetime.now(UTC))
            if not won:
                # Concurrent cancel/fail/soft-delete beat us. Bail without
                # spawning a CronRun for an already-terminal backfill.
                return

        # Final cancel gate before spawning this date's run. The mark_running CAS
        # above only guards the PENDING (first-date) case; on later dates the backfill
        # is already RUNNING, so without this a config disable / backfill cancel that
        # landed after the top-of-task check would run one MORE full date — including a
        # live ASIK sync — past "stop" (between dates current_cron_run_id is None, so
        # the cancel cascade finds no run to cancel). Re-read fresh status + the flag.
        db.refresh(bf, ["status"])
        if (
            bf.status in _BF_TERMINAL
            or rc.get(backfill_cancel_key(cron_backfill_id)) == "1"
        ):
            if bf.status not in _BF_TERMINAL:
                cron_backfill_crud.mark_cancelled(db, bf)
            return

        try:
            run = cron_run_crud.create(
                db,
                puskesmas_id=bf.puskesmas_id,
                target_date=next_date,
                cron_config_id=None,
                triggered_by_id=bf.triggered_by_id,
                cron_backfill_id=bf.id,
                source_scope=bf.source_scope,
            )
        except IntegrityError as exc:
            db.rollback()
            cron_backfill_crud.mark_failed(
                db, bf, next_date,
                f"conflict creating cron run: {exc}",
                datetime.now(UTC),
            )
            return

        cron_backfill_crud.set_current_run(db, bf, run.id)

        first_step = _first_step(bf.source_scope)
        try:
            celery_app.send_task(
                "cron.advance", args=[str(run.id), first_step.value]
            )
        except Exception as exc:
            err = f"broker unreachable: {exc}"
            now = datetime.now(UTC)
            cron_run_crud.mark_failed(db, run, first_step, err, now)
            cron_backfill_crud.mark_failed(db, bf, next_date, err, now)
    finally:
        db.close()


# Warm value lives longer than the 24h gap between runs so it never expires
# before the next 5am run overwrites it. (Live on-miss sets keep their own 24h.)
WARM_TTL_SECONDS = 30 * 3600


@celery_app.task(name="cron.warm_reports")
def warm_reports() -> dict:
    """Daily (5am Asia/Jakarta) pre-warm of the Conflict Analysis, GD Puasa and
    Hipertensi dashboard Redis caches, so users hit a warm cache instead of
    paying the O(N) decrypt scan on a cold cache.

    Recomputes from the raw encrypted blobs (single source of truth). The GD
    Puasa + Hipertensi dashboards share one decrypt pass per puskesmas (they read
    the same EPUS blobs); both write the same aggregate the on-miss endpoint path
    does (same shared scanner). Per-target try/except: one puskesmas failing must
    not abort the whole run.
    """
    # Imported here, not at module top, to avoid route<->task import cycles.
    import json

    from app.api.routes.dm_report import warm_dm_charts, warm_dm_registry
    from app.api.routes.gdp_report import GDP_SPEC, _extract_tertatalaksana
    from app.api.routes.gdp_report import _dashboard_cache_key as _gdp_dash_key
    from app.api.routes.hipertensi_report import HT_SPEC
    from app.api.routes.hipertensi_report import _dashboard_cache_key as _ht_dash_key
    from app.api.routes.hipertensi_report import warm_hipertensi_bundle
    from app.api.routes.bayi_report import warm_bayi_registry
    from app.api.routes.lipid_report import warm_lipid_registry
    from app.api.routes.merge_conflicts import warm_conflict_summary
    from app.api.routes.obesitas_report import warm_obesitas_registry
    from app.api.routes.report import warm_gdp_source_quality
    from app.core.rate_limit import redis_client
    from app.models.puskesmas import Puskesmas
    from app.services.dashboard_scan import scan_dashboard_payloads

    rc = redis_client()
    # NX lock so overlapping beat replicas don't double-run the scan.
    try:
        if not rc.set("report_warm:lock", "1", nx=True, ex=3600):
            log.info("warm_reports: another run holds the lock, skipping")
            return {"skipped": True}
    except Exception as exc:
        log.warning("warm_reports: redis lock failed (%s), proceeding", exc)

    year = datetime.now(ZoneInfo("Asia/Jakarta")).year
    # Warm every year-keyed cache from the CKG start (2025) through the current
    # year, so the app never hits a cold cache when the year selector changes.
    years_to_warm = list(range(2025, year + 1))
    warmed = 0
    failed = 0

    def _warm(label: str, fn) -> None:
        """Run one warm target in its OWN session so a DB error (which aborts
        the transaction) can't poison the targets that follow. Mirrors the
        per-item-session isolation in dispatch_due."""
        nonlocal warmed, failed
        db: Session = SessionLocal()
        try:
            fn(db)
            warmed += 1
        except Exception:
            failed += 1
            log.exception("warm_reports: %s failed", label)
        finally:
            db.close()

    def _warm_both_dashboards(db: Session, p, yr: int) -> None:
        """One decrypt pass → BOTH the GD Puasa and Hipertensi caches for one
        year. The two reports read the SAME EPUS blobs, so decrypting once and
        feeding both extractors halves the cron's heaviest cost (blob decryption)."""
        payloads = scan_dashboard_payloads(
            db,
            p,
            yr,
            {"gdp": GDP_SPEC, "hipertensi": HT_SPEC},
            extract_tertatalaksana=_extract_tertatalaksana,
        )
        for key, payload in (
            (_gdp_dash_key(p, yr), payloads["gdp"]),
            (_ht_dash_key(p, yr), payloads["hipertensi"]),
        ):
            try:
                rc.set(key, json.dumps(payload), ex=WARM_TTL_SECONDS)
            except Exception as exc:
                log.warning("warm_reports: redis set failed for %s: %s", key, exc)

    try:
        _warm("conflict summary (all)", lambda db: warm_conflict_summary(db, rc, None, WARM_TTL_SECONDS))
        _warm("gdp source quality (all)", lambda db: warm_gdp_source_quality(db, rc, None, WARM_TTL_SECONDS))

        # Enumerate active puskesmas in its own short session.
        db_ids: Session = SessionLocal()
        try:
            pids = list(db_ids.scalars(select(Puskesmas.id)).all())
        finally:
            db_ids.close()

        for pid in pids:
            _warm(f"conflict summary {pid}", lambda db, p=pid: warm_conflict_summary(db, rc, p, WARM_TTL_SECONDS))
            # GD Puasa + Hipertensi dashboards for every warmed year (one decrypt
            # pass per year).
            for yr in years_to_warm:
                _warm(
                    f"both dashboards {pid}/{yr}",
                    lambda db, p=pid, y=yr: _warm_both_dashboards(db, p, y),
                )
            _warm(f"gdp source quality {pid}", lambda db, p=pid: warm_gdp_source_quality(db, rc, p, WARM_TTL_SECONDS))
            # ONE cross-year EPUS+ASIK decrypt pass → the Registri Hipertensi cache
            # for every warmed year PLUS the dashboard-charts cache.
            _warm(
                f"hipertensi bundle {pid}",
                lambda db, p=pid: warm_hipertensi_bundle(
                    db, rc, p, WARM_TTL_SECONDS, tuple(years_to_warm)
                ),
            )
            # Registri Diabetes Melitus + Dislipidemia + Obesitas, per year.
            #
            # COST, stated plainly because it is now by far the largest thing
            # this cron does: unlike the hipertensi bundle above (ONE cross-year
            # decrypt pass feeding registry+charts), each of these re-decrypts
            # the SAME EPUS blobs once per puskesmas PER YEAR. With 2 warmed
            # years that is 6 extra full passes per puskesmas on top of the
            # hipertensi bundle.
            #
            # ⚠ THE FOLD IS NOW OVERDUE. The previous comment here said: "If a
            # FOURTH registry lands, do the fold first — a cross-registry
            # scan_registry_payloads(db, pk, years, {...}) mirroring
            # scan_dashboard_payloads — instead of appending another loop here."
            # Obesitas IS that fourth registry, and this loop was appended
            # anyway, deliberately and with the trade-off stated rather than
            # hidden: the fold means restructuring dm_registry_scan and
            # lipid_registry_scan (both chatbot-pinned) so they can be driven
            # from rows somebody else already decrypted, and that refactor does
            # not belong in the same change as a new registry.
            #
            # Do it before a FIFTH registry lands. The shape: one pass over
            # ``dm_registry_scan._blob_query``, decrypt each EPUS blob once,
            # feed every registry's per-NIK candidate builder from the shared
            # blob, then one batched ASIK fetch over the union of baselines.
            # The scans already share ``_blob_query`` / ``_fetch_asik_by_id`` /
            # the identitas helpers, so what has to move is only each module's
            # ``_decode_group`` + ``scan_*`` entry point.
            for yr in years_to_warm:
                _warm(
                    f"dm registry {pid}/{yr}",
                    lambda db, p=pid, y=yr: warm_dm_registry(
                        db, rc, p, y, WARM_TTL_SECONDS
                    ),
                )
                _warm(
                    f"lipid registry {pid}/{yr}",
                    lambda db, p=pid, y=yr: warm_lipid_registry(
                        db, rc, p, y, WARM_TTL_SECONDS
                    ),
                )
                _warm(
                    f"obesitas registry {pid}/{yr}",
                    lambda db, p=pid, y=yr: warm_obesitas_registry(
                        db, rc, p, y, WARM_TTL_SECONDS
                    ),
                )
                _warm(
                    f"bayi registry {pid}/{yr}",
                    lambda db, p=pid, y=yr: warm_bayi_registry(
                        db, rc, p, y, WARM_TTL_SECONDS
                    ),
                )
            # Dashboard Diabetes Melitus charts — a rolling cross-year aggregate,
            # so ONE pass per puskesmas (not per year), like the hipertensi
            # charts. Standalone (not folded into the DM registry warm) for the
            # same reason the fold above is deferred.
            _warm(
                f"dm charts {pid}",
                lambda db, p=pid: warm_dm_charts(db, rc, p, WARM_TTL_SECONDS),
            )
    finally:
        # Release the lock so manual re-runs (debugging) aren't blocked for an hour.
        try:
            rc.delete("report_warm:lock")
        except Exception:
            pass

    log.info("warm_reports: warmed=%s failed=%s year=%s", warmed, failed, year)
    return {"warmed": warmed, "failed": failed, "year": year}


def _cache_fresh(rc, cache_key: str) -> bool:
    """True if ``cache_key`` is already populated → the on-miss warm can skip the
    decrypt (another warm — or the nightly cron — filled it first). Fail-safe: a
    Redis error returns False so we proceed with the warm rather than skip a
    genuinely-needed one. Only used by ``warm_one_report`` (the on-miss/manual
    path); the nightly ``warm_reports`` never checks this, so its intentional
    force-refresh always recomputes."""
    try:
        return bool(rc.exists(cache_key))
    except Exception:
        return False


@celery_app.task(name="report.warm_one")
def warm_one_report(report_type: str, kwargs: dict) -> dict:
    """Recompute ONE report cache in the background (manual refresh or cold
    miss). Dispatched by app.core.report_warm.request_warm so the heavy decrypt
    scan never blocks an HTTP request. Always clears the `:warming` flag at the
    end so the GET stops returning `computing`."""
    # Imported here, not at module top, to avoid route<->task import cycles.
    import uuid as _uuid

    from app.api.routes.gdp_report import _dashboard_cache_key, warm_gdp_dashboard
    from app.api.routes.merge_conflicts import _cache_key as _conflict_key
    from app.api.routes.merge_conflicts import warm_conflict_summary
    from app.api.routes.report import _gdp_quality_cache_key, warm_gdp_source_quality
    from app.core.rate_limit import redis_client
    from app.core.report_warm import progress_key, warming_key

    rc = redis_client()
    db: Session = SessionLocal()
    cache_key: str | None = None
    ok = False
    try:
        if report_type == "gdp_dashboard":
            pid = _uuid.UUID(kwargs["puskesmas_id"])
            year = int(kwargs["year"])
            cache_key = _dashboard_cache_key(pid, year)
            if not _cache_fresh(rc, cache_key):
                warm_gdp_dashboard(db, rc, pid, year, WARM_TTL_SECONDS)
            ok = True
        elif report_type == "hipertensi_dashboard":
            from app.api.routes.hipertensi_report import (
                _dashboard_cache_key as _ht_key,
            )
            from app.api.routes.hipertensi_report import warm_hipertensi_dashboard

            pid = _uuid.UUID(kwargs["puskesmas_id"])
            year = int(kwargs["year"])
            cache_key = _ht_key(pid, year)
            if not _cache_fresh(rc, cache_key):
                warm_hipertensi_dashboard(db, rc, pid, year, WARM_TTL_SECONDS)
            ok = True
        elif report_type == "hipertensi_registry":
            from app.api.routes.hipertensi_report import (
                _registry_cache_key,
                warm_hipertensi_registry,
            )

            pid = _uuid.UUID(kwargs["puskesmas_id"])
            year = int(kwargs["year"])
            cache_key = _registry_cache_key(pid, year)
            if not _cache_fresh(rc, cache_key):
                warm_hipertensi_registry(db, rc, pid, year, WARM_TTL_SECONDS)
            ok = True
        elif report_type == "dm_registry":
            from app.api.routes.dm_report import (
                _registry_cache_key as _dm_key,
            )
            from app.api.routes.dm_report import warm_dm_registry

            pid = _uuid.UUID(kwargs["puskesmas_id"])
            year = int(kwargs["year"])
            cache_key = _dm_key(pid, year)
            if not _cache_fresh(rc, cache_key):
                warm_dm_registry(db, rc, pid, year, WARM_TTL_SECONDS)
            ok = True
        elif report_type == "dm_charts":
            from app.api.routes.dm_report import (
                _charts_cache_key as _dm_charts_key,
            )
            from app.api.routes.dm_report import warm_dm_charts

            pid = _uuid.UUID(kwargs["puskesmas_id"])
            cache_key = _dm_charts_key(pid)
            if not _cache_fresh(rc, cache_key):
                warm_dm_charts(db, rc, pid, WARM_TTL_SECONDS)
            ok = True
        elif report_type == "lipid_registry":
            from app.api.routes.lipid_report import (
                _registry_cache_key as _lipid_key,
            )
            from app.api.routes.lipid_report import warm_lipid_registry

            pid = _uuid.UUID(kwargs["puskesmas_id"])
            year = int(kwargs["year"])
            cache_key = _lipid_key(pid, year)
            if not _cache_fresh(rc, cache_key):
                warm_lipid_registry(db, rc, pid, year, WARM_TTL_SECONDS)
            ok = True
        elif report_type == "obesitas_registry":
            from app.api.routes.obesitas_report import (
                _registry_cache_key as _obesitas_key,
            )
            from app.api.routes.obesitas_report import warm_obesitas_registry

            pid = _uuid.UUID(kwargs["puskesmas_id"])
            year = int(kwargs["year"])
            cache_key = _obesitas_key(pid, year)
            if not _cache_fresh(rc, cache_key):
                warm_obesitas_registry(db, rc, pid, year, WARM_TTL_SECONDS)
            ok = True
        elif report_type == "bayi_registry":
            from app.api.routes.bayi_report import (
                _registry_cache_key as _bayi_key,
            )
            from app.api.routes.bayi_report import warm_bayi_registry

            pid = _uuid.UUID(kwargs["puskesmas_id"])
            year = int(kwargs["year"])
            cache_key = _bayi_key(pid, year)
            if not _cache_fresh(rc, cache_key):
                warm_bayi_registry(db, rc, pid, year, WARM_TTL_SECONDS)
            ok = True
        elif report_type == "hipertensi_charts":
            from app.api.routes.hipertensi_report import (
                _charts_cache_key,
                warm_hipertensi_charts,
            )

            pid = _uuid.UUID(kwargs["puskesmas_id"])
            cache_key = _charts_cache_key(pid)
            if not _cache_fresh(rc, cache_key):
                warm_hipertensi_charts(db, rc, pid, WARM_TTL_SECONDS)
            ok = True
        elif report_type == "conflict":
            pid = _uuid.UUID(kwargs["puskesmas_id"]) if kwargs.get("puskesmas_id") else None
            cache_key = _conflict_key(pid)
            if not _cache_fresh(rc, cache_key):
                warm_conflict_summary(db, rc, pid, WARM_TTL_SECONDS)
            ok = True
        elif report_type == "gdp_source_quality":
            pid = _uuid.UUID(kwargs["puskesmas_id"]) if kwargs.get("puskesmas_id") else None
            cache_key = _gdp_quality_cache_key(pid)
            if not _cache_fresh(rc, cache_key):
                warm_gdp_source_quality(db, rc, pid, WARM_TTL_SECONDS)
            ok = True
        else:
            log.warning("warm_one_report: unknown report_type %r", report_type)
    except Exception:
        log.exception("warm_one_report failed: %s %s", report_type, kwargs)
    finally:
        # Clear the flag so the next GET serves the fresh cache (or, on failure,
        # re-enqueues a retry instead of looping on `computing` forever).
        if cache_key is not None:
            try:
                rc.delete(warming_key(cache_key))
            except Exception:
                pass
            # Clear the progress blob too so a stale bar doesn't linger past the
            # warm (on success the fresh cache serves; on failure the next GET
            # re-enqueues and re-seeds progress).
            try:
                rc.delete(progress_key(cache_key))
            except Exception:
                pass
        db.close()
    return {"ok": ok, "report_type": report_type}
