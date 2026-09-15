import time
import uuid
from datetime import UTC, datetime

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, contains_eager, load_only

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
from app.crud import sync_job as crud
from app.models.patient import MatchStatus, Patient
from app.models.puskesmas import Puskesmas
from app.models.scrape_job import TriggererType
from app.models.sync_job import SyncJob, SyncStatus
from app.schemas.sync_job import SyncJobLogOut, SyncJobOut, SyncStart
from app.tasks.sync import ALLOW_EPUS_ONLY_SYNC

router = APIRouter(tags=["sync"])

_LOG_BACKLOG_MAX = 500
_LOG_BACKLOG_DEFAULT = 200

_JOB_OUT_COLS = (
    SyncJob.id, SyncJob.puskesmas_id, SyncJob.patient_id, SyncJob.status,
    SyncJob.triggered_by_id, SyncJob.triggered_by_type, SyncJob.celery_task_id,
    SyncJob.forms_total, SyncJob.forms_succeeded, SyncJob.forms_failed,
    SyncJob.forms_skipped, SyncJob.duration_seconds,
    SyncJob.cpu_avg_pct, SyncJob.cpu_peak_pct,
    SyncJob.mem_avg_mb, SyncJob.mem_peak_mb, SyncJob.resource_samples,
    SyncJob.notes, SyncJob.started_at, SyncJob.finished_at, SyncJob.error_message,
    SyncJob.created_at, SyncJob.updated_at,
)


def _to_job_out(job: SyncJob, *, puskesmas_name: str, patient_name: str, patient_nik: str) -> SyncJobOut:
    return SyncJobOut(
        id=job.id,
        puskesmas_id=job.puskesmas_id,
        puskesmas_name=puskesmas_name,
        patient_id=job.patient_id,
        patient_name=patient_name,
        patient_nik=patient_nik,
        status=job.status,
        triggered_by_id=job.triggered_by_id,
        triggered_by_type=job.triggered_by_type,
        celery_task_id=job.celery_task_id,
        forms_total=job.forms_total,
        forms_succeeded=job.forms_succeeded,
        forms_failed=job.forms_failed,
        forms_skipped=job.forms_skipped,
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
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


def _authorize(principal: Principal, puskesmas_id: uuid.UUID) -> None:
    # Called after the patient is fetched, so hide existence with a 404 that
    # matches the not-found case (no 403-vs-404 oracle on patient ids).
    if principal.typ == "user" and principal.puskesmas_id != puskesmas_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Patient not found")


def _authorize_job(principal: Principal, job: SyncJob) -> None:
    # Same: a foreign job is indistinguishable from a nonexistent one.
    if principal.typ == "user" and job.puskesmas_id != principal.puskesmas_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")


def _trigger_kind(principal: Principal) -> tuple[uuid.UUID, TriggererType]:
    if principal.typ == "admin":
        return principal.id, TriggererType.ADMIN
    return principal.id, TriggererType.USER


@router.post(
    "/patients/{patient_id}/sync-asik",
    response_model=SyncJobOut,
    status_code=status.HTTP_201_CREATED,
)
def start_sync(
    patient_id: uuid.UUID,
    body: SyncStart = SyncStart(),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> SyncJobOut:
    patient = db.scalar(
        select(Patient)
        .options(load_only(
            Patient.id, Patient.puskesmas_id, Patient.nik, Patient.nama,
            Patient.match_status, Patient.merged_data, Patient.merged_at,
            Patient.scraped_epus_data,
        ))
        .where(Patient.id == patient_id)
    )
    if patient is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Patient not found")
    _authorize(principal, patient.puskesmas_id)
    has_merged = patient.merged_data is not None
    # EPUS-only fallback is disabled by scope: sync requires matched + AI-merged data.
    # Kept behind ALLOW_EPUS_ONLY_SYNC so it can be restored later (see tasks/sync.py).
    epus_only_eligible = (
        ALLOW_EPUS_ONLY_SYNC
        and patient.match_status == MatchStatus.EPUS_ONLY
        and patient.scraped_epus_data is not None
    )
    if not has_merged and not epus_only_eligible:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Patient has no merged_data — sync requires matched + AI-merged data",
        )

    row = db.execute(
        select(
            Puskesmas.name,
            Puskesmas.asik_cred.isnot(None),
            Puskesmas.asik_url,
        ).where(Puskesmas.id == patient.puskesmas_id)
    ).one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Puskesmas not found")
    puskesmas_name, has_cred, base_url = row
    if not has_cred:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "ASIK credentials not set")
    if not base_url:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "asik_url not set for this puskesmas",
        )

    triggered_by_id, triggered_by_type = _trigger_kind(principal)
    try:
        job = crud.create(
            db,
            puskesmas_id=patient.puskesmas_id,
            patient_id=patient.id,
            triggered_by_id=triggered_by_id,
            triggered_by_type=triggered_by_type,
        )
    except IntegrityError as e:
        db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "sync already in progress for this patient",
        ) from e

    try:
        celery_app.send_task(
            "sync.run",
            args=[str(job.id)],
            kwargs={"headless": body.headless},
        )
    except Exception as e:
        crud.mark_failed(db, job, f"broker unreachable: {e}"[:2000], datetime.now(UTC))
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "sync broker unavailable"
        ) from e
    return _to_job_out(
        job,
        puskesmas_name=puskesmas_name,
        patient_name=patient.nama,
        patient_nik=patient.nik,
    )


@router.post(
    "/patients/{patient_id}/create-asik",
    response_model=SyncJobOut,
    status_code=status.HTTP_201_CREATED,
)
def start_create(
    patient_id: uuid.UUID,
    body: SyncStart = SyncStart(),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> SyncJobOut:
    """Register ONE `epus_only + tandai_ckg` patient into ASIK from scratch, then fill —
    the manual per-patient trigger for the ASIK create feature. Tracked on a SyncJob so it
    streams to the SAME sync-jobs log/history UI as a normal sync (celery `create.run_one`).
    Requires the puskesmas to have a default ASIK alamat configured (the mandatory 4-level
    domicile cascade the create flow fills)."""
    patient = db.scalar(
        select(Patient)
        .options(load_only(
            Patient.id, Patient.puskesmas_id, Patient.nik, Patient.nama,
            Patient.match_status, Patient.epus_tandai_ckg, Patient.scraped_epus_data,
        ))
        .where(Patient.id == patient_id)
    )
    if patient is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Patient not found")
    _authorize(principal, patient.puskesmas_id)
    if not (
        patient.match_status == MatchStatus.EPUS_ONLY
        and patient.epus_tandai_ckg
        and patient.scraped_epus_data is not None
    ):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Create requires an epus_only + Tandai-CKG patient with ePus data",
        )

    row = db.execute(
        select(
            Puskesmas.name,
            Puskesmas.asik_cred.isnot(None),
            Puskesmas.asik_url,
            Puskesmas.asik_default_alamat,
        ).where(Puskesmas.id == patient.puskesmas_id)
    ).one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Puskesmas not found")
    puskesmas_name, has_cred, base_url, default_alamat = row
    if not has_cred:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "ASIK credentials not set")
    if not base_url:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "asik_url not set for this puskesmas"
        )
    if not default_alamat:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "puskesmas has no default ASIK alamat configured — set it in the "
            "puskesmas form first",
        )

    triggered_by_id, triggered_by_type = _trigger_kind(principal)
    try:
        job = crud.create(
            db,
            puskesmas_id=patient.puskesmas_id,
            patient_id=patient.id,
            triggered_by_id=triggered_by_id,
            triggered_by_type=triggered_by_type,
        )
    except IntegrityError as e:
        db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "a sync or create is already in progress for this patient",
        ) from e

    try:
        celery_app.send_task(
            "create.run_one",
            args=[str(job.id)],
            kwargs={"headless": body.headless},
        )
    except Exception as e:
        crud.mark_failed(db, job, f"broker unreachable: {e}"[:2000], datetime.now(UTC))
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "create broker unavailable"
        ) from e
    return _to_job_out(
        job,
        puskesmas_name=puskesmas_name,
        patient_name=patient.nama,
        patient_nik=patient.nik,
    )


@router.get("/sync/jobs", response_model=Page[SyncJobOut])
def list_jobs(
    params: PageParams = Depends(page_params),
    puskesmas_id: uuid.UUID | None = Query(None),
    patient_id: uuid.UUID | None = Query(None),
    job_status: SyncStatus | None = Query(None, alias="status"),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> Page[SyncJobOut]:
    if principal.typ == "user":
        if puskesmas_id is not None and puskesmas_id != principal.puskesmas_id:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Forbidden")
        puskesmas_id = principal.puskesmas_id
    stmt = (
        select(SyncJob)
        .join(SyncJob.puskesmas)
        .join(SyncJob.patient)
        .options(
            load_only(*_JOB_OUT_COLS),
            contains_eager(SyncJob.puskesmas).load_only(Puskesmas.name),
            contains_eager(SyncJob.patient).load_only(Patient.nama, Patient.nik),
        )
        .order_by(SyncJob.created_at.desc())
    )
    if puskesmas_id is not None:
        stmt = stmt.where(SyncJob.puskesmas_id == puskesmas_id)
    if patient_id is not None:
        stmt = stmt.where(SyncJob.patient_id == patient_id)
    if job_status is not None:
        stmt = stmt.where(SyncJob.status == job_status)
    items, total, pages = paginate(db, stmt, params)
    return Page[SyncJobOut](
        items=[
            _to_job_out(
                i,
                puskesmas_name=i.puskesmas.name,
                patient_name=i.patient.nama,
                patient_nik=i.patient.nik,
            )
            for i in items
        ],
        total=total,
        page=params.page,
        size=params.size,
        pages=pages,
    )


@router.get("/sync/jobs/{job_id}", response_model=SyncJobOut)
def get_job(
    job_id: uuid.UUID,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> SyncJobOut:
    obj = db.scalar(
        select(SyncJob)
        .join(SyncJob.puskesmas)
        .join(SyncJob.patient)
        .options(
            load_only(*_JOB_OUT_COLS),
            contains_eager(SyncJob.puskesmas).load_only(Puskesmas.name),
            contains_eager(SyncJob.patient).load_only(Patient.nama, Patient.nik),
        )
        .where(SyncJob.id == job_id)
    )
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
    _authorize_job(principal, obj)
    return _to_job_out(
        obj,
        puskesmas_name=obj.puskesmas.name,
        patient_name=obj.patient.nama,
        patient_nik=obj.patient.nik,
    )


@router.get("/sync/jobs/{job_id}/log", response_model=SyncJobLogOut)
def get_job_log(
    job_id: uuid.UUID,
    tail: int = Query(_LOG_BACKLOG_DEFAULT, ge=1, le=_LOG_BACKLOG_MAX),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> SyncJobLogOut:
    obj = db.scalar(
        select(SyncJob)
        .options(load_only(SyncJob.id, SyncJob.puskesmas_id))
        .where(SyncJob.id == job_id)
    )
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
    _authorize_job(principal, obj)
    lines = redis_client().lrange(f"sync:job:{job_id}:log", -tail, -1) or []
    return SyncJobLogOut(lines=lines)


@router.get("/sync/jobs/{job_id}/stream")
async def stream_job(
    job_id: uuid.UUID,
    backlog: int = Query(_LOG_BACKLOG_DEFAULT, ge=0, le=_LOG_BACKLOG_MAX),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal_from_query),
) -> StreamingResponse:
    obj = db.scalar(
        select(SyncJob)
        .options(load_only(SyncJob.id, SyncJob.puskesmas_id))
        .where(SyncJob.id == job_id)
    )
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
    _authorize_job(principal, obj)

    chan = f"sync:job:{job_id}:stream"
    log_key = f"sync:job:{job_id}:log"

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


@router.post("/sync/jobs/{job_id}/cancel", response_model=SyncJobOut)
def cancel_job(
    job_id: uuid.UUID,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> SyncJobOut:
    obj = db.scalar(
        select(SyncJob)
        .join(SyncJob.puskesmas)
        .join(SyncJob.patient)
        .options(
            load_only(*_JOB_OUT_COLS),
            contains_eager(SyncJob.puskesmas).load_only(Puskesmas.name),
            contains_eager(SyncJob.patient).load_only(Patient.nama, Patient.nik),
        )
        .where(SyncJob.id == job_id)
    )
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
    _authorize_job(principal, obj)
    if obj.status not in (SyncStatus.PENDING, SyncStatus.RUNNING):
        raise HTTPException(status.HTTP_409_CONFLICT, f"job is {obj.status.value}, cannot cancel")
    puskesmas_name = obj.puskesmas.name
    patient_name = obj.patient.nama
    patient_nik = obj.patient.nik
    crud.mark_cancelled(db, obj)
    redis_client().set(f"sync:job:{job_id}:cancel", "1", ex=86400)
    if obj.celery_task_id:
        try:
            celery_app.control.revoke(obj.celery_task_id, terminate=False)
        except Exception:
            pass
    db.refresh(obj)
    return _to_job_out(
        obj,
        puskesmas_name=puskesmas_name,
        patient_name=patient_name,
        patient_nik=patient_nik,
    )
