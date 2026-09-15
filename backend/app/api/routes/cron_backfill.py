import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, contains_eager, load_only

from app.api.deps import get_current_admin_id, get_db
from app.api.pagination import Page, PageParams, page_params, paginate
from app.celery_app import celery_app
from app.core.rate_limit import redis_client
from app.crud import cron_backfill as crud
from app.crud.cron_run import cancel_cron_run_and_children
from app.models.cron_backfill import CronBackfill, CronBackfillStatus
from app.models.cron_config import CronSourceScope, scopes_conflict
from app.models.cron_run import CronRun, CronRunStatus
from app.models.puskesmas import Puskesmas
from app.schemas.cron_backfill import (
    CronBackfillCreate,
    CronBackfillOut,
    cron_backfill_to_out,
)
from app.schemas.cron_run import CronRunOut, cron_run_to_out
from app.tasks.cron import backfill_cancel_key

router = APIRouter(tags=["cron"])

_BF_OUT_COLS = (
    CronBackfill.id,
    CronBackfill.puskesmas_id,
    CronBackfill.date_from,
    CronBackfill.date_to,
    CronBackfill.cursor_date,
    CronBackfill.status,
    CronBackfill.merge_mode,
    CronBackfill.source_scope,
    CronBackfill.mandiri_only,
    CronBackfill.sync_mode,
    CronBackfill.create_new,
    CronBackfill.triggered_by_id,
    CronBackfill.current_cron_run_id,
    CronBackfill.total_dates,
    CronBackfill.completed_dates,
    CronBackfill.failed_date,
    CronBackfill.error_message,
    CronBackfill.started_at,
    CronBackfill.finished_at,
    CronBackfill.created_at,
    CronBackfill.updated_at,
)

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


@router.post(
    "/admin/cron-backfills",
    response_model=CronBackfillOut,
    status_code=status.HTTP_201_CREATED,
)
def create_backfill(
    body: CronBackfillCreate,
    db: Session = Depends(get_db),
    admin_id: uuid.UUID = Depends(get_current_admin_id),
) -> CronBackfillOut:
    pk_name = db.scalar(
        select(Puskesmas.name).where(Puskesmas.id == body.puskesmas_id)
    )
    if pk_name is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Puskesmas not found")

    # Mandiri-only backfill only ever touches ASIK (it patches the ASIK blob and
    # re-merges) — force the scope server-side regardless of what the client
    # sent, so the conflict pre-checks + unique indexes serialize it correctly.
    effective_scope = (
        CronSourceScope.ASIK_ONLY if body.mandiri_only else body.source_scope
    )

    # Advisory pre-checks; the two partial UNIQUE indexes on cron_runs
    # (uq_cron_runs_active_epus / _asik) are the race-safe guards. Only a
    # backfill / run touching the SAME source conflicts — an EPUS_ONLY backfill
    # may run alongside an active ASIK_ONLY one for the same puskesmas.
    active_bf_scopes = db.scalars(
        select(CronBackfill.source_scope).where(
            CronBackfill.puskesmas_id == body.puskesmas_id,
            CronBackfill.status.in_(
                (CronBackfillStatus.PENDING, CronBackfillStatus.RUNNING)
            ),
        )
    ).all()
    if any(scopes_conflict(effective_scope, s) for s in active_bf_scopes):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "a backfill touching the same source is already in progress for "
            "this puskesmas",
        )

    active_run_scopes = db.scalars(
        select(CronRun.source_scope).where(
            CronRun.puskesmas_id == body.puskesmas_id,
            CronRun.status.in_(
                (CronRunStatus.PENDING, CronRunStatus.RUNNING)
            ),
        )
    ).all()
    if any(scopes_conflict(effective_scope, s) for s in active_run_scopes):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "a cron run touching the same source is already in progress for "
            "this puskesmas",
        )

    try:
        bf = crud.create(
            db,
            puskesmas_id=body.puskesmas_id,
            date_from=body.date_from,
            date_to=body.date_to,
            merge_mode=body.merge_mode,
            source_scope=effective_scope,
            mandiri_only=body.mandiri_only,
            sync_mode=body.sync_mode,
            create_new=body.create_new,
            triggered_by_id=admin_id,
        )
    except IntegrityError as e:
        db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "a backfill is already in progress for this puskesmas",
        ) from e

    try:
        celery_app.send_task(
            "cron.dispatch_backfill_next", args=[str(bf.id)]
        )
    except Exception as e:
        crud.mark_failed(
            db, bf, bf.date_from,
            f"broker unreachable: {e}", datetime.now(UTC),
        )
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "cron broker unavailable"
        ) from e

    return cron_backfill_to_out(bf, pk_name)


@router.get("/admin/cron-backfills", response_model=Page[CronBackfillOut])
def list_backfills(
    params: PageParams = Depends(page_params),
    puskesmas_id: uuid.UUID | None = Query(None),
    bf_status: CronBackfillStatus | None = Query(None, alias="status"),
    db: Session = Depends(get_db),
    _admin_id: uuid.UUID = Depends(get_current_admin_id),
) -> Page[CronBackfillOut]:
    stmt = (
        select(CronBackfill)
        .join(CronBackfill.puskesmas)
        .options(
            load_only(*_BF_OUT_COLS),
            contains_eager(CronBackfill.puskesmas).load_only(Puskesmas.name),
        )
        .order_by(CronBackfill.created_at.desc())
    )
    if puskesmas_id is not None:
        stmt = stmt.where(CronBackfill.puskesmas_id == puskesmas_id)
    if bf_status is not None:
        stmt = stmt.where(CronBackfill.status == bf_status)
    items, total, pages = paginate(db, stmt, params)
    return Page[CronBackfillOut](
        items=[cron_backfill_to_out(i, i.puskesmas.name) for i in items],
        total=total,
        page=params.page,
        size=params.size,
        pages=pages,
    )


@router.get(
    "/admin/cron-backfills/{backfill_id}", response_model=CronBackfillOut
)
def get_backfill(
    backfill_id: uuid.UUID,
    db: Session = Depends(get_db),
    _admin_id: uuid.UUID = Depends(get_current_admin_id),
) -> CronBackfillOut:
    obj = db.scalar(
        select(CronBackfill)
        .join(CronBackfill.puskesmas)
        .options(
            load_only(*_BF_OUT_COLS),
            contains_eager(CronBackfill.puskesmas).load_only(Puskesmas.name),
        )
        .where(CronBackfill.id == backfill_id)
    )
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Backfill not found")
    return cron_backfill_to_out(obj, obj.puskesmas.name)


@router.post(
    "/admin/cron-backfills/{backfill_id}/cancel",
    response_model=CronBackfillOut,
)
def cancel_backfill(
    backfill_id: uuid.UUID,
    db: Session = Depends(get_db),
    _admin_id: uuid.UUID = Depends(get_current_admin_id),
) -> CronBackfillOut:
    obj = db.scalar(
        select(CronBackfill)
        .join(CronBackfill.puskesmas)
        .options(
            load_only(*_BF_OUT_COLS),
            contains_eager(CronBackfill.puskesmas).load_only(Puskesmas.name),
        )
        .where(CronBackfill.id == backfill_id)
    )
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Backfill not found")
    if obj.status not in (
        CronBackfillStatus.PENDING, CronBackfillStatus.RUNNING
    ):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"backfill is {obj.status.value}, cannot cancel",
        )

    pk_name = obj.puskesmas.name
    rc = redis_client()
    rc.set(backfill_cancel_key(str(obj.id)), "1", ex=86400)

    current_id = obj.current_cron_run_id
    if current_id is not None:
        run = db.scalar(
            select(CronRun)
            .options(
                load_only(
                    CronRun.id,
                    CronRun.status,
                    CronRun.current_step,
                    CronRun.finished_at,
                    CronRun.asik_scrape_job_id,
                    CronRun.epus_scrape_job_id,
                    CronRun.merge_job_id,
                )
            )
            .where(CronRun.id == current_id)
        )
        if run is not None:
            cancel_cron_run_and_children(db, run)
        # The cancel cascade in cron.advance / handle_failure will mark the
        # backfill CANCELLED via _propagate_run_cancelled_to_backfill once the
        # in-flight task observes the flag. As belt-and-braces (e.g. the run
        # was already terminal), reach a terminal state here too.
        db.refresh(obj)
        if obj.status in (
            CronBackfillStatus.PENDING, CronBackfillStatus.RUNNING
        ):
            crud.mark_cancelled(db, obj)
    else:
        crud.mark_cancelled(db, obj)

    db.refresh(obj)
    return cron_backfill_to_out(obj, pk_name)


@router.get(
    "/admin/cron-backfills/{backfill_id}/cron-runs",
    response_model=Page[CronRunOut],
)
def list_backfill_runs(
    backfill_id: uuid.UUID,
    params: PageParams = Depends(page_params),
    db: Session = Depends(get_db),
    _admin_id: uuid.UUID = Depends(get_current_admin_id),
) -> Page[CronRunOut]:
    bf_exists = db.scalar(
        select(CronBackfill.id).where(CronBackfill.id == backfill_id)
    )
    if bf_exists is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Backfill not found")
    stmt = (
        select(CronRun)
        .join(CronRun.puskesmas)
        .options(
            load_only(*_RUN_OUT_COLS),
            contains_eager(CronRun.puskesmas).load_only(Puskesmas.name),
        )
        .where(CronRun.cron_backfill_id == backfill_id)
        .order_by(CronRun.target_date.asc())
    )
    items, total, pages = paginate(db, stmt, params)
    return Page[CronRunOut](
        items=[cron_run_to_out(i, i.puskesmas.name) for i in items],
        total=total,
        page=params.page,
        size=params.size,
        pages=pages,
    )
