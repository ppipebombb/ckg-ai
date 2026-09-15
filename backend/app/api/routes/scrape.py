import time
import uuid
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
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
from app.crud import scrape_job as crud
from app.models.patient import Patient
from app.models.puskesmas import Puskesmas
from app.models.scrape_job import ScrapeJob, ScrapeKind, ScrapeStatus, TriggererType
from app.schemas.scrape_job import (
    PatientScrapeStart,
    ScrapeJobLogOut,
    ScrapeJobOut,
    ScrapeStart,
)

router = APIRouter(tags=["scrape"])

_JKT = ZoneInfo("Asia/Jakarta")
_LOG_BACKLOG_MAX = 500
_LOG_BACKLOG_DEFAULT = 200

_JOB_OUT_COLS = (
    ScrapeJob.id, ScrapeJob.puskesmas_id, ScrapeJob.patient_id,
    ScrapeJob.kind, ScrapeJob.date_filter, ScrapeJob.target_nik,
    ScrapeJob.status, ScrapeJob.triggered_by_id, ScrapeJob.triggered_by_type,
    ScrapeJob.celery_task_id, ScrapeJob.scraped_count, ScrapeJob.inserted_count,
    ScrapeJob.updated_count, ScrapeJob.duration_seconds,
    ScrapeJob.cpu_avg_pct, ScrapeJob.cpu_peak_pct,
    ScrapeJob.mem_avg_mb, ScrapeJob.mem_peak_mb, ScrapeJob.resource_samples,
    ScrapeJob.notes, ScrapeJob.started_at, ScrapeJob.finished_at, ScrapeJob.error_message,
    ScrapeJob.cron_run_id, ScrapeJob.parent_gdp_job_id,
    ScrapeJob.created_at, ScrapeJob.updated_at,
)


def _to_job_out(
    job: ScrapeJob,
    puskesmas_name: str,
    patient_nik: str | None = None,
    patient_name: str | None = None,
) -> ScrapeJobOut:
    return ScrapeJobOut(
        id=job.id,
        puskesmas_id=job.puskesmas_id,
        puskesmas_name=puskesmas_name,
        patient_id=job.patient_id,
        patient_nik=patient_nik,
        patient_name=patient_name,
        kind=job.kind,
        date_filter=job.date_filter,
        status=job.status,
        triggered_by_id=job.triggered_by_id,
        triggered_by_type=job.triggered_by_type,
        celery_task_id=job.celery_task_id,
        scraped_count=job.scraped_count,
        inserted_count=job.inserted_count,
        updated_count=job.updated_count,
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
        parent_gdp_job_id=job.parent_gdp_job_id,
        target_nik=job.target_nik,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


def _authorize(principal: Principal, puskesmas_id: uuid.UUID) -> None:
    if principal.typ == "user" and principal.puskesmas_id != puskesmas_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Forbidden")


def _authorize_job(principal: Principal, job: ScrapeJob) -> None:
    # Object-level: a foreign job returns the SAME 404 as a nonexistent one so
    # job ids in other clinics can't be probed (no 403-vs-404 oracle).
    if principal.typ == "user" and job.puskesmas_id != principal.puskesmas_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")


def _trigger_kind(principal: Principal) -> tuple[uuid.UUID, TriggererType]:
    if principal.typ == "admin":
        return principal.id, TriggererType.ADMIN
    return principal.id, TriggererType.USER


@router.post(
    "/puskesmas/{puskesmas_id}/scrape/{kind}",
    response_model=ScrapeJobOut,
    status_code=status.HTTP_201_CREATED,
)
def start_scrape(
    puskesmas_id: uuid.UUID,
    kind: ScrapeKind,
    body: ScrapeStart,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> ScrapeJobOut:
    _authorize(principal, puskesmas_id)
    cred_col = Puskesmas.epus_cred if kind == ScrapeKind.EPUS else Puskesmas.asik_cred
    url_col = Puskesmas.epus_url if kind == ScrapeKind.EPUS else Puskesmas.asik_url
    row = db.execute(
        select(cred_col.isnot(None), url_col, Puskesmas.name).where(Puskesmas.id == puskesmas_id)
    ).one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Puskesmas not found")
    has_cred, base_url, puskesmas_name = row
    if not has_cred:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"{kind.value} credentials not set")
    if not base_url:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"{kind.value}_url not set for this puskesmas",
        )

    # CKG Sekolah is date-less (filtered by school × class, walked dynamically).
    # The uq_scrape_jobs_active_per_puskesmas_kind index still serializes one
    # active asik_sekolah job per puskesmas regardless of date_filter being NULL.
    date_filter = None if kind == ScrapeKind.ASIK_SEKOLAH else (
        body.date or datetime.now(_JKT).date()
    ).isoformat()
    triggered_by_id, triggered_by_type = _trigger_kind(principal)
    try:
        job = crud.create(
            db,
            puskesmas_id=puskesmas_id,
            kind=kind,
            date_filter=date_filter,
            triggered_by_id=triggered_by_id,
            triggered_by_type=triggered_by_type,
        )
    except IntegrityError as e:
        db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"{kind.value} scrape already in progress for this puskesmas",
        ) from e

    try:
        celery_app.send_task(
            "scrape.run",
            args=[str(job.id), kind.value],
            kwargs={"headless": body.headless},
        )
    except Exception as e:
        crud.mark_failed(db, job, f"broker unreachable: {e}"[:2000], datetime.now(UTC))
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "scrape broker unavailable"
        ) from e
    return _to_job_out(job, puskesmas_name)


@router.post(
    "/patients/{patient_id}/scrape/{kind}",
    response_model=ScrapeJobOut,
    status_code=status.HTTP_201_CREATED,
)
def start_patient_scrape(
    patient_id: uuid.UUID,
    kind: ScrapeKind,
    body: PatientScrapeStart = PatientScrapeStart(),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> ScrapeJobOut:
    if kind == ScrapeKind.ASIK_SEKOLAH:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "per-patient CKG Sekolah scrape is not supported; run the "
            "puskesmas-wide asik_sekolah scrape instead",
        )
    patient = db.scalar(
        select(Patient).options(
            load_only(
                Patient.id, Patient.puskesmas_id, Patient.nik,
                Patient.nama, Patient.filter_date,
            )
        ).where(Patient.id == patient_id)
    )
    if patient is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Patient not found")
    # Object-level: hide a foreign patient behind the same 404 as a nonexistent one.
    if principal.typ == "user" and principal.puskesmas_id != patient.puskesmas_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Patient not found")

    cred_col = Puskesmas.epus_cred if kind == ScrapeKind.EPUS else Puskesmas.asik_cred
    url_col = Puskesmas.epus_url if kind == ScrapeKind.EPUS else Puskesmas.asik_url
    row = db.execute(
        select(cred_col.isnot(None), url_col, Puskesmas.name).where(
            Puskesmas.id == patient.puskesmas_id
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Puskesmas not found")
    has_cred, base_url, puskesmas_name = row
    if not has_cred:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"{kind.value} credentials not set")
    if not base_url:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"{kind.value}_url not set for this puskesmas",
        )

    iso_date = patient.filter_date.isoformat()

    triggered_by_id, triggered_by_type = _trigger_kind(principal)
    try:
        job = crud.create(
            db,
            puskesmas_id=patient.puskesmas_id,
            kind=kind,
            date_filter=iso_date,
            triggered_by_id=triggered_by_id,
            triggered_by_type=triggered_by_type,
            patient_id=patient.id,
        )
    except IntegrityError as e:
        db.rollback()
        if kind == ScrapeKind.ASIK:
            # ASIK shares one browser session per puskesmas, so only one
            # ASIK scrape (puskesmas-wide OR per-NIK) can run at a time.
            msg = (
                "another ASIK scrape is already running for this puskesmas "
                "(ASIK shares one session per puskesmas)"
            )
        else:
            msg = "ePus scrape already in progress for this patient"
        raise HTTPException(status.HTTP_409_CONFLICT, msg) from e

    try:
        celery_app.send_task(
            "scrape.run",
            args=[str(job.id), kind.value],
            kwargs={"headless": body.headless},
        )
    except Exception as e:
        crud.mark_failed(db, job, f"broker unreachable: {e}"[:2000], datetime.now(UTC))
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "scrape broker unavailable"
        ) from e
    return _to_job_out(job, puskesmas_name, patient.nik, patient.nama)


@router.get("/scrape/jobs", response_model=Page[ScrapeJobOut])
def list_jobs(
    params: PageParams = Depends(page_params),
    puskesmas_id: uuid.UUID | None = Query(None),
    job_status: ScrapeStatus | None = Query(None, alias="status"),
    kind: ScrapeKind | None = Query(None),
    scope: str = Query("all", pattern="^(all|puskesmas|patient)$"),
    patient_id: uuid.UUID | None = Query(None),
    parent_gdp_job_id: uuid.UUID | None = Query(None),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> Page[ScrapeJobOut]:
    if principal.typ == "user":
        if puskesmas_id is not None and puskesmas_id != principal.puskesmas_id:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Forbidden")
        puskesmas_id = principal.puskesmas_id
    stmt = (
        select(ScrapeJob)
        .join(ScrapeJob.puskesmas)
        .options(
            load_only(*_JOB_OUT_COLS),
            contains_eager(ScrapeJob.puskesmas).load_only(Puskesmas.name),
            joinedload(ScrapeJob.patient).load_only(Patient.id, Patient.nik, Patient.nama),
        )
        .order_by(ScrapeJob.created_at.desc())
    )
    if puskesmas_id is not None:
        stmt = stmt.where(ScrapeJob.puskesmas_id == puskesmas_id)
    if job_status is not None:
        stmt = stmt.where(ScrapeJob.status == job_status)
    if kind is not None:
        stmt = stmt.where(ScrapeJob.kind == kind)
    if scope == "puskesmas":
        stmt = stmt.where(ScrapeJob.patient_id.is_(None))
    elif scope == "patient":
        stmt = stmt.where(ScrapeJob.patient_id.isnot(None))
    if patient_id is not None:
        stmt = stmt.where(ScrapeJob.patient_id == patient_id)
    if parent_gdp_job_id is not None:
        stmt = stmt.where(ScrapeJob.parent_gdp_job_id == parent_gdp_job_id)
    items, total, pages = paginate(db, stmt, params)
    return Page[ScrapeJobOut](
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


@router.get("/scrape/jobs/{job_id}", response_model=ScrapeJobOut)
def get_job(
    job_id: uuid.UUID,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> ScrapeJobOut:
    obj = db.scalar(
        select(ScrapeJob)
        .join(ScrapeJob.puskesmas)
        .options(
            load_only(*_JOB_OUT_COLS),
            contains_eager(ScrapeJob.puskesmas).load_only(Puskesmas.name),
            joinedload(ScrapeJob.patient).load_only(Patient.id, Patient.nik, Patient.nama),
        )
        .where(ScrapeJob.id == job_id)
    )
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
    _authorize_job(principal, obj)
    return _to_job_out(
        obj, obj.puskesmas.name,
        obj.patient.nik if obj.patient else None,
        obj.patient.nama if obj.patient else None,
    )


@router.get("/scrape/jobs/{job_id}/log", response_model=ScrapeJobLogOut)
def get_job_log(
    job_id: uuid.UUID,
    tail: int = Query(_LOG_BACKLOG_DEFAULT, ge=1, le=_LOG_BACKLOG_MAX),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> ScrapeJobLogOut:
    obj = db.scalar(
        select(ScrapeJob)
        .join(ScrapeJob.puskesmas)
        .options(load_only(ScrapeJob.id, ScrapeJob.puskesmas_id))
        .where(ScrapeJob.id == job_id)
    )
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
    _authorize_job(principal, obj)
    lines = redis_client().lrange(f"scrape:job:{job_id}:log", -tail, -1) or []
    return ScrapeJobLogOut(lines=lines)


@router.get("/scrape/jobs/{job_id}/stream")
async def stream_job(
    job_id: uuid.UUID,
    backlog: int = Query(_LOG_BACKLOG_DEFAULT, ge=0, le=_LOG_BACKLOG_MAX),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal_from_query),
) -> StreamingResponse:
    obj = db.scalar(
        select(ScrapeJob)
        .join(ScrapeJob.puskesmas)
        .options(load_only(ScrapeJob.id, ScrapeJob.puskesmas_id))
        .where(ScrapeJob.id == job_id)
    )
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
    _authorize_job(principal, obj)

    chan = f"scrape:job:{job_id}:stream"
    log_key = f"scrape:job:{job_id}:log"

    async def event_gen():
        # Coalesce log lines into one SSE frame per FLUSH_S window — collapses
        # bursty per-line traffic into batched events. Multiple data: lines in
        # one event are joined with "\n" by the EventSource API on the client.
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


@router.post("/scrape/jobs/{job_id}/cancel", response_model=ScrapeJobOut)
def cancel_job(
    job_id: uuid.UUID,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> ScrapeJobOut:
    obj = db.scalar(
        select(ScrapeJob)
        .join(ScrapeJob.puskesmas)
        .options(
            load_only(*_JOB_OUT_COLS),
            contains_eager(ScrapeJob.puskesmas).load_only(Puskesmas.name),
            joinedload(ScrapeJob.patient).load_only(Patient.id, Patient.nik, Patient.nama),
        )
        .where(ScrapeJob.id == job_id)
    )
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
    _authorize_job(principal, obj)
    if obj.status not in (ScrapeStatus.PENDING, ScrapeStatus.RUNNING):
        raise HTTPException(status.HTTP_409_CONFLICT, f"job is {obj.status.value}, cannot cancel")
    puskesmas_name = obj.puskesmas.name
    patient_nik = obj.patient.nik if obj.patient else None
    patient_name = obj.patient.nama if obj.patient else None
    crud.mark_cancelled(db, obj)
    # Redis cancel-flag: worker polls this in its 2s loop so it does not
    # have to SELECT the job row from Postgres each tick (avoid N+1).
    redis_client().set(f"scrape:job:{job_id}:cancel", "1", ex=86400)
    if obj.celery_task_id:
        try:
            celery_app.control.revoke(obj.celery_task_id, terminate=False)
        except Exception:
            pass

    # If this job is part of a cron run, cancel the parent run too so its
    # downstream steps (next scrape kind, merge) do not kick off. cron.advance
    # / cron.handle_failure both bail when cron_run.status == CANCELLED.
    if obj.cron_run_id is not None:
        from app.crud.cron_run import cancel_cron_run_and_children
        from app.models.cron_run import CronRun
        run = db.scalar(select(CronRun).where(CronRun.id == obj.cron_run_id))
        if run is not None:
            cancel_cron_run_and_children(db, run, exclude_job_id=obj.id)

    # If this job is a child of a GDP report run, cascade-cancel the parent
    # and any sibling running children. Otherwise the orchestrator keeps
    # waiting on a vanished child or the next phase's child runs unattended.
    if obj.parent_gdp_job_id is not None:
        from app.crud import gdp_report_job as gdp_crud
        from app.models.gdp_report_job import GdpReportJob, GdpReportStatus
        from app.tasks.gdp_report import cancel_key as gdp_cancel_key
        rc = redis_client()
        gdp_run = db.scalar(
            select(GdpReportJob).where(GdpReportJob.id == obj.parent_gdp_job_id)
        )
        if gdp_run is not None and gdp_run.status in (
            GdpReportStatus.PENDING, GdpReportStatus.RUNNING,
        ):
            gdp_crud.mark_cancelled(db, gdp_run)
            try:
                rc.set(gdp_cancel_key(str(gdp_run.id)), "1", ex=86400)
            except Exception:
                pass
            if gdp_run.celery_task_id:
                try:
                    celery_app.control.revoke(
                        gdp_run.celery_task_id, terminate=False,
                    )
                except Exception:
                    pass
            siblings = db.scalars(
                select(ScrapeJob)
                .options(load_only(
                    ScrapeJob.id, ScrapeJob.status, ScrapeJob.celery_task_id,
                    ScrapeJob.finished_at,
                ))
                .where(
                    ScrapeJob.parent_gdp_job_id == gdp_run.id,
                    ScrapeJob.id != obj.id,
                    ScrapeJob.status.in_(
                        (ScrapeStatus.PENDING, ScrapeStatus.RUNNING),
                    ),
                )
            ).all()
            for sib in siblings:
                crud.mark_cancelled(db, sib)
                try:
                    rc.set(f"scrape:job:{sib.id}:cancel", "1", ex=86400)
                except Exception:
                    pass
                if sib.celery_task_id:
                    try:
                        celery_app.control.revoke(
                            sib.celery_task_id, terminate=False,
                        )
                    except Exception:
                        pass

    db.refresh(obj)
    return _to_job_out(obj, puskesmas_name, patient_nik, patient_name)


