import logging
import time
import uuid
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, contains_eager, joinedload, load_only

from app.api.deps import (
    Principal,
    get_db,
    get_principal,
    get_principal_from_query,
)
from app.api.pagination import Page, PageParams, page_params, paginate
from app.celery_app import celery_app
from app.config import settings
from app.core.rate_limit import redis_client
from app.crud import merge_job as crud
from app.models.merge_job import MergeJob, MergeStatus
from app.models.patient import MatchStatus, Patient
from app.models.puskesmas import Puskesmas
from app.models.scrape_job import TriggererType
from app.schemas.merge_job import (
    MergeJobLogOut,
    MergeJobOut,
    MergePreviewOut,
    MergeStart,
)

router = APIRouter(tags=["merge"])

log = logging.getLogger(__name__)

_JKT = ZoneInfo("Asia/Jakarta")
_LOG_BACKLOG_MAX = 500
_LOG_BACKLOG_DEFAULT = 200

_JOB_OUT_COLS = (
    MergeJob.id, MergeJob.puskesmas_id, MergeJob.patient_id,
    MergeJob.date_filter, MergeJob.status,
    MergeJob.triggered_by_id, MergeJob.triggered_by_type, MergeJob.celery_task_id,
    MergeJob.force_remerge, MergeJob.total_count, MergeJob.processed_count,
    MergeJob.succeeded_count, MergeJob.failed_count, MergeJob.skipped_count,
    MergeJob.duration_seconds,
    MergeJob.cpu_avg_pct, MergeJob.cpu_peak_pct,
    MergeJob.mem_avg_mb, MergeJob.mem_peak_mb, MergeJob.resource_samples,
    MergeJob.notes, MergeJob.started_at, MergeJob.finished_at, MergeJob.error_message,
    MergeJob.cron_run_id, MergeJob.created_at, MergeJob.updated_at,
)


def _to_job_out(
    job: MergeJob,
    puskesmas_name: str,
    patient_nik: str | None = None,
    patient_name: str | None = None,
) -> MergeJobOut:
    return MergeJobOut(
        id=job.id,
        puskesmas_id=job.puskesmas_id,
        puskesmas_name=puskesmas_name,
        patient_id=job.patient_id,
        patient_nik=patient_nik,
        patient_name=patient_name,
        date_filter=job.date_filter,
        status=job.status,
        triggered_by_id=job.triggered_by_id,
        triggered_by_type=job.triggered_by_type,
        celery_task_id=job.celery_task_id,
        force_remerge=job.force_remerge,
        total_count=job.total_count,
        processed_count=job.processed_count,
        succeeded_count=job.succeeded_count,
        failed_count=job.failed_count,
        skipped_count=job.skipped_count,
        duration_seconds=job.duration_seconds,
        cpu_avg_pct=job.cpu_avg_pct,
        cpu_peak_pct=job.cpu_peak_pct,
        mem_avg_mb=job.mem_avg_mb,
        mem_peak_mb=job.mem_peak_mb,
        resource_samples=job.resource_samples,
        notes=job.notes,
        started_at=job.started_at,
        finished_at=job.finished_at,
        error_message=job.error_message,
        cron_run_id=job.cron_run_id,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


def _authorize(principal: Principal, puskesmas_id: uuid.UUID) -> None:
    if principal.typ == "user" and principal.puskesmas_id != puskesmas_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Forbidden")


def _authorize_job(principal: Principal, job: MergeJob) -> None:
    # Object-level: a foreign job returns the SAME 404 as a nonexistent one so
    # job ids in other clinics can't be probed (no 403-vs-404 oracle).
    if principal.typ == "user" and job.puskesmas_id != principal.puskesmas_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")


def _trigger_kind(principal: Principal) -> tuple[uuid.UUID, TriggererType]:
    if principal.typ == "admin":
        return principal.id, TriggererType.ADMIN
    return principal.id, TriggererType.USER


@router.get(
    "/puskesmas/{puskesmas_id}/merge/preview",
    response_model=MergePreviewOut,
)
def merge_preview(
    puskesmas_id: uuid.UUID,
    target: date = Query(..., alias="date"),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> MergePreviewOut:
    _authorize(principal, puskesmas_id)
    base_filter = (
        Patient.puskesmas_id == puskesmas_id,
        Patient.match_status == MatchStatus.MATCHED,
        Patient.filter_date == target,
    )
    matched = db.scalar(select(func.count()).select_from(Patient).where(*base_filter)) or 0
    already = db.scalar(
        select(func.count()).select_from(Patient).where(
            *base_filter, Patient.merged_at.isnot(None)
        )
    ) or 0
    pending = matched - already
    return MergePreviewOut(
        matched_count=matched,
        pending_count=pending,
        already_merged_count=already,
    )


@router.post(
    "/puskesmas/{puskesmas_id}/merge",
    response_model=list[MergeJobOut],
    status_code=status.HTTP_201_CREATED,
)
def start_merge(
    puskesmas_id: uuid.UUID,
    body: MergeStart,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> list[MergeJobOut]:
    """Start one MergeJob per date.

    Single-date mode (one of: `date` set, or no date fields → defaults to today):
    enforces the existing eligibility check (404 if 0 matched, 400 if 0 pending
    without `force`). Returns a 1-element list.

    Range mode (`date_from` + `date_to` set, inclusive): creates one MergeJob
    per day and dispatches them as a Celery `chain` (sequential — each task's
    completion fires the next). Eligibility is NOT pre-checked per day; days
    with zero matched patients complete as no-op merges (total_count=0).
    Returns the list in date order.
    """
    _authorize(principal, puskesmas_id)
    row = db.execute(
        select(Puskesmas.name).where(Puskesmas.id == puskesmas_id)
    ).one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Puskesmas not found")
    (puskesmas_name,) = row

    if body.date_from is not None and body.date_to is not None:
        # Range mode: inclusive on both ends.
        span = (body.date_to - body.date_from).days + 1
        target_dates: list[date] = [
            body.date_from + timedelta(days=i) for i in range(span)
        ]
    else:
        single = body.date or datetime.now(_JKT).date()
        target_dates = [single]
        # Pre-flight eligibility check applies to single-date mode only — keeps
        # the existing UX where the button is gated by the preview endpoint and
        # the API rejects "nothing to do" up-front. Range mode skips this so
        # one empty day in a long range doesn't 400 the whole request.
        base_filter = (
            Patient.puskesmas_id == puskesmas_id,
            Patient.match_status == MatchStatus.MATCHED,
            Patient.filter_date == single,
        )
        matched_count = db.scalar(
            select(func.count()).select_from(Patient).where(*base_filter)
        ) or 0
        if matched_count == 0:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "No matched patients on this date for this puskesmas",
            )
        if not body.force:
            pending_count = db.scalar(
                select(func.count())
                .select_from(Patient)
                .where(*base_filter, Patient.merged_at.is_(None))
            ) or 0
            if pending_count == 0:
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST,
                    "All matched patients on this date are already merged. "
                    "Toggle force to re-merge.",
                )

    triggered_by_id, triggered_by_type = _trigger_kind(principal)
    jobs: list[MergeJob] = []
    try:
        for d in target_dates:
            job = crud.create(
                db,
                puskesmas_id=puskesmas_id,
                date_filter=d.isoformat(),
                triggered_by_id=triggered_by_id,
                triggered_by_type=triggered_by_type,
                force_remerge=body.force,
            )
            jobs.append(job)
    except IntegrityError as e:
        db.rollback()
        # Cleanup of the rows committed before the conflict (each crud.create
        # commits its own row — see backend/app/crud/merge_job.py). ONE bulk
        # UPDATE, deliberately not a per-row loop.
        #
        # The old loop called crud.mark_cancelled (which commits) per job inside a
        # bare `except Exception: pass`. A single failed commit leaves the Session
        # needing rollback, so EVERY later commit raises PendingRollbackError —
        # swallowed silently — stranding the tail of the range in PENDING with no
        # celery_task_id. Nothing reaps those rows, and because
        # uq_merge_jobs_active_wide covers (puskesmas_id, date_filter) for
        # pending/running, they then 409 every retry of those dates.
        # Seen on prod 2026-07-27: a 2026-01-01..07-18 Tebet range conflicted on
        # the last date, cancelled 35 of 198, and stranded 163.
        #
        # deleted_at IS NULL is explicit: the soft-delete listener only rewrites
        # SELECTs, never UPDATEs (see backend/app/core/soft_delete.py).
        if jobs:
            try:
                db.execute(
                    update(MergeJob)
                    .where(
                        MergeJob.id.in_([j.id for j in jobs]),
                        MergeJob.status == MergeStatus.PENDING,
                        MergeJob.deleted_at.is_(None),
                    )
                    .values(
                        status=MergeStatus.CANCELLED,
                        finished_at=datetime.now(UTC),
                    )
                )
                db.commit()
            except Exception:
                db.rollback()
                log.exception(
                    "merge range cleanup failed to cancel %d job(s) for pk=%s",
                    len(jobs), puskesmas_id,
                )
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "merge already in progress for this puskesmas/date",
        ) from e

    # Dispatch each date's job as an INDEPENDENT task (one small broker message
    # each), NOT a single Celery chain. A chain of up to a year of immutable
    # signatures is embedded in one first-task message that silently fails to
    # reach the broker for large ranges, orphaning every row in PENDING forever
    # (seen on prod: 365- and 125-date ranges, no traceback / no 503). Each
    # run_merge records its own celery_task_id when it starts, and a per-job
    # failure never strands the rest — run_merge's outer handler re-raises, which
    # would halt a chain and orphan the tail.
    #
    # Trade-off vs the old chain: dates now merge with worker-level concurrency
    # instead of strictly one-at-a-time. That matches how independent single-date
    # / single-patient merges already behave; the cron backfill remains the
    # strictly-sequential date-range path.
    dispatched = 0
    broker_err: str | None = None
    for j in jobs:
        try:
            celery_app.send_task("merge.run", args=[str(j.id)])
        except Exception as e:
            broker_err = f"broker unreachable: {e}"[:2000]
            break
        dispatched += 1
    if broker_err is not None:
        # Fail only the jobs we could NOT enqueue (the tail); any already sent
        # keep running. In practice the broker is up (all send) or down (the
        # first send fails → all failed) — a partial dispatch is a rare edge.
        #
        # One bulk UPDATE for the same reason as the IntegrityError cleanup above:
        # a per-row loop of committing calls inside `except Exception: pass`
        # strands every row after the first failed commit in PENDING forever.
        stranded = jobs[dispatched:]
        if stranded:
            try:
                db.execute(
                    update(MergeJob)
                    .where(
                        MergeJob.id.in_([j.id for j in stranded]),
                        MergeJob.status == MergeStatus.PENDING,
                        MergeJob.deleted_at.is_(None),
                    )
                    .values(
                        status=MergeStatus.FAILED,
                        error_message=broker_err,
                        finished_at=datetime.now(UTC),
                    )
                )
                db.commit()
            except Exception:
                db.rollback()
                log.exception(
                    "merge range dispatch failed to mark %d job(s) failed for pk=%s",
                    len(stranded), puskesmas_id,
                )
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "merge broker unavailable"
        )
    return [_to_job_out(j, puskesmas_name) for j in jobs]


@router.post(
    "/patients/{patient_id}/merge",
    response_model=MergeJobOut,
    status_code=status.HTTP_201_CREATED,
)
def start_patient_merge(
    patient_id: uuid.UUID,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> MergeJobOut:
    prow = db.execute(
        select(
            Patient.id,
            Patient.puskesmas_id,
            Patient.nik,
            Patient.nama,
            Patient.scraped_asik_data.isnot(None).label("has_asik"),
            Patient.scraped_epus_data.isnot(None).label("has_epus"),
        ).where(Patient.id == patient_id)
    ).one_or_none()
    if prow is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Patient not found")
    p_id, p_puskesmas_id, p_nik, p_nama, has_asik, has_epus = prow
    # Object-level: hide a foreign patient behind the same 404 as a nonexistent one.
    if principal.typ == "user" and principal.puskesmas_id != p_puskesmas_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Patient not found")
    if not (has_asik and has_epus):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "patient missing scraped data on one or both sides — run scrapes first",
        )

    row = db.execute(
        select(Puskesmas.name).where(Puskesmas.id == p_puskesmas_id)
    ).one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Puskesmas not found")
    (puskesmas_name,) = row

    triggered_by_id, triggered_by_type = _trigger_kind(principal)
    try:
        job = crud.create(
            db,
            puskesmas_id=p_puskesmas_id,
            date_filter=None,
            triggered_by_id=triggered_by_id,
            triggered_by_type=triggered_by_type,
            force_remerge=True,
            patient_id=p_id,
        )
    except IntegrityError as e:
        db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, "merge already in progress for this patient"
        ) from e

    try:
        celery_app.send_task("merge.run", args=[str(job.id)])
    except Exception as e:
        crud.mark_failed(db, job, f"broker unreachable: {e}"[:2000], datetime.now(UTC))
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "merge broker unavailable"
        ) from e
    return _to_job_out(job, puskesmas_name, p_nik, p_nama)


@router.get("/merge/jobs", response_model=Page[MergeJobOut])
def list_jobs(
    params: PageParams = Depends(page_params),
    puskesmas_id: uuid.UUID | None = Query(None),
    job_status: MergeStatus | None = Query(None, alias="status"),
    date_filter: str | None = Query(None),
    scope: str = Query("all", pattern="^(all|puskesmas|patient)$"),
    patient_id: uuid.UUID | None = Query(None),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> Page[MergeJobOut]:
    if principal.typ == "user":
        if puskesmas_id is not None and puskesmas_id != principal.puskesmas_id:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Forbidden")
        puskesmas_id = principal.puskesmas_id
    stmt = (
        select(MergeJob)
        .join(MergeJob.puskesmas)
        .options(
            load_only(*_JOB_OUT_COLS),
            contains_eager(MergeJob.puskesmas).load_only(Puskesmas.name),
            joinedload(MergeJob.patient).load_only(Patient.id, Patient.nik, Patient.nama),
        )
        .order_by(MergeJob.created_at.desc())
    )
    if puskesmas_id is not None:
        stmt = stmt.where(MergeJob.puskesmas_id == puskesmas_id)
    if job_status is not None:
        stmt = stmt.where(MergeJob.status == job_status)
    if date_filter:
        stmt = stmt.where(MergeJob.date_filter == date_filter)
    if scope == "puskesmas":
        stmt = stmt.where(MergeJob.patient_id.is_(None))
    elif scope == "patient":
        stmt = stmt.where(MergeJob.patient_id.isnot(None))
    if patient_id is not None:
        stmt = stmt.where(MergeJob.patient_id == patient_id)
    items, total, pages = paginate(db, stmt, params)
    return Page[MergeJobOut](
        items=[
            _to_job_out(
                i, i.puskesmas.name,
                i.patient.nik if i.patient else None,
                i.patient.nama if i.patient else None,
            )
            for i in items
        ],
        total=total,
        page=params.page,
        size=params.size,
        pages=pages,
    )


@router.get("/merge/jobs/{job_id}", response_model=MergeJobOut)
def get_job(
    job_id: uuid.UUID,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> MergeJobOut:
    obj = db.scalar(
        select(MergeJob)
        .join(MergeJob.puskesmas)
        .options(
            load_only(*_JOB_OUT_COLS),
            contains_eager(MergeJob.puskesmas).load_only(Puskesmas.name),
            joinedload(MergeJob.patient).load_only(Patient.id, Patient.nik, Patient.nama),
        )
        .where(MergeJob.id == job_id)
    )
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
    _authorize_job(principal, obj)
    return _to_job_out(
        obj, obj.puskesmas.name,
        obj.patient.nik if obj.patient else None,
        obj.patient.nama if obj.patient else None,
    )


@router.get("/merge/jobs/{job_id}/log", response_model=MergeJobLogOut)
def get_job_log(
    job_id: uuid.UUID,
    tail: int = Query(_LOG_BACKLOG_DEFAULT, ge=1, le=_LOG_BACKLOG_MAX),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> MergeJobLogOut:
    obj = db.scalar(
        select(MergeJob)
        .join(MergeJob.puskesmas)
        .options(load_only(MergeJob.id, MergeJob.puskesmas_id))
        .where(MergeJob.id == job_id)
    )
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
    _authorize_job(principal, obj)
    lines = redis_client().lrange(f"merge:job:{job_id}:log", -tail, -1) or []
    return MergeJobLogOut(lines=lines)


@router.get("/merge/jobs/{job_id}/stream")
async def stream_job(
    job_id: uuid.UUID,
    backlog: int = Query(_LOG_BACKLOG_DEFAULT, ge=0, le=_LOG_BACKLOG_MAX),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal_from_query),
) -> StreamingResponse:
    obj = db.scalar(
        select(MergeJob)
        .join(MergeJob.puskesmas)
        .options(load_only(MergeJob.id, MergeJob.puskesmas_id))
        .where(MergeJob.id == job_id)
    )
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
    _authorize_job(principal, obj)

    chan = f"merge:job:{job_id}:stream"
    log_key = f"merge:job:{job_id}:log"

    async def event_gen():
        FLUSH_S = 1.0
        KEEPALIVE_S = 15.0
        client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        try:
            if backlog > 0:
                history = await client.lrange(log_key, -backlog, -1)
                if history:
                    block = "\n".join(f"data: {line}" for line in history)
                    yield f"event: line\n{block}\n\n"

            pubsub = client.pubsub()
            await pubsub.subscribe(chan)
            try:
                buf: list[str] = []
                last_flush = time.monotonic()
                last_keepalive = last_flush
                terminal: str | None = None
                while True:
                    msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=FLUSH_S)
                    now = time.monotonic()
                    if msg is not None:
                        data = msg.get("data")
                        if isinstance(data, str):
                            if data in ("__done__", "__failed__", "__cancelled__"):
                                terminal = data
                            else:
                                buf.append(data)
                    if buf and (terminal is not None or (now - last_flush) >= FLUSH_S):
                        block = "\n".join(f"data: {line}" for line in buf)
                        yield f"event: line\n{block}\n\n"
                        buf.clear()
                        last_flush = now
                        last_keepalive = now
                    if terminal is not None:
                        yield f"event: {terminal.strip('_')}\ndata: {terminal}\n\n"
                        return
                    if not buf and (now - last_keepalive) >= KEEPALIVE_S:
                        yield ": keepalive\n\n"
                        last_keepalive = now
            finally:
                await pubsub.unsubscribe(chan)
                await pubsub.close()
        finally:
            await client.aclose()

    return StreamingResponse(event_gen(), media_type="text/event-stream")


@router.post("/merge/jobs/{job_id}/cancel", response_model=MergeJobOut)
def cancel_job(
    job_id: uuid.UUID,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> MergeJobOut:
    obj = db.scalar(
        select(MergeJob)
        .join(MergeJob.puskesmas)
        .options(
            load_only(*_JOB_OUT_COLS),
            contains_eager(MergeJob.puskesmas).load_only(Puskesmas.name),
            joinedload(MergeJob.patient).load_only(Patient.id, Patient.nik, Patient.nama),
        )
        .where(MergeJob.id == job_id)
    )
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
    _authorize_job(principal, obj)
    if obj.status not in (MergeStatus.PENDING, MergeStatus.RUNNING):
        raise HTTPException(status.HTTP_409_CONFLICT, f"job is {obj.status.value}, cannot cancel")
    puskesmas_name = obj.puskesmas.name
    patient_nik = obj.patient.nik if obj.patient else None
    patient_name = obj.patient.nama if obj.patient else None
    crud.mark_cancelled(db, obj)
    # Redis cancel-flag: worker polls this each iteration so it does not
    # have to SELECT the job row from Postgres on every patient (avoid N+1).
    redis_client().set(f"merge:job:{job_id}:cancel", "1", ex=86400)
    if obj.celery_task_id:
        try:
            celery_app.control.revoke(obj.celery_task_id, terminate=False)
        except Exception:
            pass

    # Cron run is the only step left; cancelling merge cancels the run.
    if obj.cron_run_id is not None:
        from app.crud.cron_run import cancel_cron_run_and_children
        from app.models.cron_run import CronRun
        run = db.scalar(select(CronRun).where(CronRun.id == obj.cron_run_id))
        if run is not None:
            cancel_cron_run_and_children(db, run, exclude_job_id=obj.id)

    db.refresh(obj)
    return _to_job_out(obj, puskesmas_name, patient_nik, patient_name)
