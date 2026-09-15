import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, contains_eager, load_only

from app.api.deps import get_current_admin_id, get_db
from app.api.pagination import Page, PageParams, page_params, paginate
from app.celery_app import celery_app
from app.crud import cron_run as crud
from app.models.cron_run import CronRun, CronRunStatus, CronStep
from app.models.puskesmas import Puskesmas
from app.models.sync_job import SyncJob, SyncStatus
from app.schemas.cron_run import CronRunOut, CronRunSyncSummary, cron_run_to_out

router = APIRouter(tags=["cron"])

_RUN_OUT_COLS = (
    CronRun.id, CronRun.cron_config_id, CronRun.cron_backfill_id,
    CronRun.puskesmas_id,
    CronRun.target_date, CronRun.source_scope, CronRun.status, CronRun.current_step,
    CronRun.current_step_attempt, CronRun.failed_step,
    CronRun.asik_scrape_job_id, CronRun.epus_scrape_job_id, CronRun.merge_job_id,
    CronRun.triggered_by_id, CronRun.error_message,
    CronRun.started_at, CronRun.finished_at,
    CronRun.created_at, CronRun.updated_at,
)


_to_out = cron_run_to_out


@router.get("/admin/cron-runs", response_model=Page[CronRunOut])
def list_runs(
    params: PageParams = Depends(page_params),
    puskesmas_id: uuid.UUID | None = Query(None),
    run_status: CronRunStatus | None = Query(None, alias="status"),
    db: Session = Depends(get_db),
    _admin_id: uuid.UUID = Depends(get_current_admin_id),
) -> Page[CronRunOut]:
    stmt = (
        select(CronRun)
        .join(CronRun.puskesmas)
        .options(
            load_only(*_RUN_OUT_COLS),
            contains_eager(CronRun.puskesmas).load_only(Puskesmas.name),
        )
        .order_by(CronRun.created_at.desc())
    )
    if puskesmas_id is not None:
        stmt = stmt.where(CronRun.puskesmas_id == puskesmas_id)
    if run_status is not None:
        stmt = stmt.where(CronRun.status == run_status)
    items, total, pages = paginate(db, stmt, params)
    return Page[CronRunOut](
        items=[_to_out(i, i.puskesmas.name) for i in items],
        total=total,
        page=params.page,
        size=params.size,
        pages=pages,
    )


@router.get("/admin/cron-runs/{run_id}", response_model=CronRunOut)
def get_run(
    run_id: uuid.UUID,
    db: Session = Depends(get_db),
    _admin_id: uuid.UUID = Depends(get_current_admin_id),
) -> CronRunOut:
    obj = db.scalar(
        select(CronRun)
        .join(CronRun.puskesmas)
        .options(
            load_only(*_RUN_OUT_COLS),
            contains_eager(CronRun.puskesmas).load_only(Puskesmas.name),
        )
        .where(CronRun.id == run_id)
    )
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Cron run not found")
    return _to_out(obj, obj.puskesmas.name)


@router.get(
    "/admin/cron-runs/{run_id}/sync-summary", response_model=CronRunSyncSummary
)
def get_run_sync_summary(
    run_id: uuid.UUID,
    db: Session = Depends(get_db),
    _admin_id: uuid.UUID = Depends(get_current_admin_id),
) -> CronRunSyncSummary:
    """Per-patient sync progress for the run's SYNC step.

    One GROUP BY over the partial index ix_sync_jobs_cron_run_status, plus the
    run's stamped denominator. The page fetches it on load and on the run's SSE
    terminal event — no polling.
    """
    total = db.scalar(
        select(CronRun.sync_total).where(CronRun.id == run_id)
    )
    counts = dict(
        db.execute(
            select(SyncJob.status, func.count())
            .where(SyncJob.cron_run_id == run_id)
            .group_by(SyncJob.status)
        ).all()
    )
    return CronRunSyncSummary(
        total=total,
        pending=counts.get(SyncStatus.PENDING, 0),
        running=counts.get(SyncStatus.RUNNING, 0),
        success=counts.get(SyncStatus.SUCCESS, 0),
        failed=counts.get(SyncStatus.FAILED, 0),
        cancelled=counts.get(SyncStatus.CANCELLED, 0),
    )


@router.post("/admin/cron-runs/{run_id}/cancel", response_model=CronRunOut)
def cancel_run(
    run_id: uuid.UUID,
    db: Session = Depends(get_db),
    _admin_id: uuid.UUID = Depends(get_current_admin_id),
) -> CronRunOut:
    obj = db.scalar(
        select(CronRun)
        .join(CronRun.puskesmas)
        .options(
            load_only(*_RUN_OUT_COLS),
            contains_eager(CronRun.puskesmas).load_only(Puskesmas.name),
        )
        .where(CronRun.id == run_id)
    )
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Cron run not found")
    if obj.status not in (CronRunStatus.PENDING, CronRunStatus.RUNNING):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"cron run is {obj.status.value}, cannot cancel",
        )
    pk_name = obj.puskesmas.name
    crud.cancel_cron_run_and_children(db, obj)
    db.refresh(obj)
    return _to_out(obj, pk_name)


@router.post("/admin/cron-runs/{run_id}/retry", response_model=CronRunOut)
def retry_run(
    run_id: uuid.UUID,
    db: Session = Depends(get_db),
    admin_id: uuid.UUID = Depends(get_current_admin_id),
) -> CronRunOut:
    obj = db.scalar(
        select(CronRun)
        .join(CronRun.puskesmas)
        .options(load_only(*_RUN_OUT_COLS), contains_eager(CronRun.puskesmas).load_only(Puskesmas.name))
        .where(CronRun.id == run_id)
    )
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Cron run not found")
    if obj.status not in (CronRunStatus.FAILED, CronRunStatus.CANCELLED):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"cron run is {obj.status.value}, only failed/cancelled runs can be retried",
        )
    if obj.cron_backfill_id is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "this run belongs to a backfill; create a new backfill to continue",
        )
    pk_name = obj.puskesmas.name

    # Pre-check is advisory (nice 409 message); the lane partial UNIQUE indexes
    # (uq_cron_runs_active_epus / _asik) are the actual race-safe guard. Retry is
    # restricted to non-backfill runs (always source_scope=BOTH), and BOTH
    # occupies both lanes — so any active run conflicts. EPUS-first dispatch is
    # therefore always correct here.
    active = db.scalar(
        select(CronRun.id)
        .where(
            CronRun.puskesmas_id == obj.puskesmas_id,
            CronRun.status.in_((CronRunStatus.PENDING, CronRunStatus.RUNNING)),
        )
        .limit(1)
    )
    if active is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "a cron run is already in progress for this puskesmas",
        )

    try:
        new_run = crud.create(
            db,
            puskesmas_id=obj.puskesmas_id,
            target_date=obj.target_date,
            cron_config_id=obj.cron_config_id,
            triggered_by_id=admin_id,
            source_scope=obj.source_scope,
        )
    except IntegrityError as e:
        db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "a cron run is already in progress for this puskesmas",
        ) from e
    try:
        celery_app.send_task("cron.advance", args=[str(new_run.id), CronStep.EPUS.value])
    except Exception as e:
        crud.mark_failed(
            db, new_run, CronStep.EPUS,
            f"broker unreachable: {e}", datetime.now(UTC),
        )
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "cron broker unavailable"
        ) from e
    return _to_out(new_run, pk_name)


@router.get(
    "/admin/puskesmas/{puskesmas_id}/cron-runs",
    response_model=Page[CronRunOut],
)
def list_runs_for_puskesmas(
    puskesmas_id: uuid.UUID,
    params: PageParams = Depends(page_params),
    db: Session = Depends(get_db),
    _admin_id: uuid.UUID = Depends(get_current_admin_id),
) -> Page[CronRunOut]:
    stmt = (
        select(CronRun)
        .join(CronRun.puskesmas)
        .options(
            load_only(*_RUN_OUT_COLS),
            contains_eager(CronRun.puskesmas).load_only(Puskesmas.name),
        )
        .where(CronRun.puskesmas_id == puskesmas_id)
        .order_by(CronRun.created_at.desc())
    )
    items, total, pages = paginate(db, stmt, params)
    return Page[CronRunOut](
        items=[_to_out(i, i.puskesmas.name) for i in items],
        total=total,
        page=params.page,
        size=params.size,
        pages=pages,
    )
