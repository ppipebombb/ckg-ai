import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_current_admin_id, get_db
from app.celery_app import celery_app
from app.core.rate_limit import redis_client
from app.crud import cron_backfill as cron_backfill_crud
from app.crud import cron_config as crud
from app.crud import cron_run as cron_run_crud
from app.models.cron_backfill import CronBackfill, CronBackfillStatus
from app.models.cron_config import CronConfig
from app.models.cron_run import CronRun, CronRunStatus, CronStep
from app.models.puskesmas import Puskesmas
from app.tasks.cron import backfill_cancel_key
from app.schemas.cron_config import (
    CronConfigCreate,
    CronConfigOut,
    CronConfigUpdate,
)
from app.schemas.cron_run import CronRunOut, cron_run_to_out

router = APIRouter(tags=["cron"])

_JKT = ZoneInfo("Asia/Jakarta")


def _to_out(obj: CronConfig) -> CronConfigOut:
    return CronConfigOut.model_validate(obj)


@router.post(
    "/admin/puskesmas/{puskesmas_id}/cron-config",
    response_model=CronConfigOut,
    status_code=status.HTTP_201_CREATED,
)
def create_cron_config(
    puskesmas_id: uuid.UUID,
    body: CronConfigCreate,
    db: Session = Depends(get_db),
    _admin_id: uuid.UUID = Depends(get_current_admin_id),
) -> CronConfigOut:
    pk = db.scalar(select(Puskesmas.id).where(Puskesmas.id == puskesmas_id))
    if pk is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Puskesmas not found")
    try:
        obj = crud.create(
            db,
            puskesmas_id=puskesmas_id,
            hour=body.hour,
            minute=body.minute,
            target_offset_days=body.target_offset_days,
            lookback_days=body.lookback_days,
            enabled=body.enabled,
            merge_mode=body.merge_mode,
            sync_mode=body.sync_mode,
            create_new=body.create_new,
        )
    except IntegrityError as e:
        db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, "cron config already exists for this puskesmas"
        ) from e
    return _to_out(obj)


@router.get(
    "/admin/puskesmas/{puskesmas_id}/cron-config",
    response_model=CronConfigOut,
)
def get_cron_config(
    puskesmas_id: uuid.UUID,
    db: Session = Depends(get_db),
    _admin_id: uuid.UUID = Depends(get_current_admin_id),
) -> CronConfigOut:
    obj = crud.get_by_puskesmas(db, puskesmas_id)
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Cron config not found")
    return _to_out(obj)


def _active_run_exists(db: Session, puskesmas_id: uuid.UUID) -> bool:
    """True iff a CronRun for this puskesmas is currently PENDING or RUNNING.
    Used to gate schedule-shaping field edits — changing hour / minute /
    target_offset_days / merge_mode mid-run is incoherent. Disable + delete
    no longer use this gate; they cancel the active run instead."""
    return (
        db.scalar(
            select(CronRun.id)
            .where(
                CronRun.puskesmas_id == puskesmas_id,
                CronRun.status.in_(
                    (CronRunStatus.PENDING, CronRunStatus.RUNNING)
                ),
            )
            .limit(1)
        )
        is not None
    )


def _has_schedule_change(obj: CronConfig, body: CronConfigUpdate) -> bool:
    if body.hour is not None and body.hour != obj.hour:
        return True
    if body.minute is not None and body.minute != obj.minute:
        return True
    if (
        body.target_offset_days is not None
        and body.target_offset_days != obj.target_offset_days
    ):
        return True
    if (
        body.lookback_days is not None
        and body.lookback_days != obj.lookback_days
    ):
        return True
    if (
        body.merge_mode is not None
        and body.merge_mode != obj.merge_mode
    ):
        return True
    if (
        body.sync_mode is not None
        and body.sync_mode != obj.sync_mode
    ):
        return True
    return False


def _cancel_active_runs_for_config(
    db: Session, cron_config_id: uuid.UUID
) -> None:
    """Fan-out cancel every in-flight unit of work under this config.
    Mirrors the per-run cancel route: marks run CANCELLED, sets Redis cancel
    flag (so cron.advance / handle_failure short-circuit), and cancels any
    in-flight scrape/merge child.

    Covers BOTH shapes: a direct CronRun (a run-now) AND a scheduled CronBackfill
    (dispatch_due spawns one carrying this config's id). A manual date-range
    backfill has cron_config_id=NULL, so it is never touched here."""
    runs = list(
        db.scalars(
            select(CronRun).where(
                CronRun.cron_config_id == cron_config_id,
                CronRun.status.in_(
                    (CronRunStatus.PENDING, CronRunStatus.RUNNING)
                ),
            )
        ).all()
    )
    for run in runs:
        cron_run_crud.cancel_cron_run_and_children(db, run)

    # Scheduled backfills spawned by this config — cancel like the backfill cancel
    # route (set the Redis flag so dispatch_backfill_next stops advancing the cursor,
    # cancel the in-flight per-date run + its children, then mark the backfill).
    bfs = list(
        db.scalars(
            select(CronBackfill).where(
                CronBackfill.cron_config_id == cron_config_id,
                CronBackfill.status.in_(
                    (CronBackfillStatus.PENDING, CronBackfillStatus.RUNNING)
                ),
            )
        ).all()
    )
    if bfs:
        rc = redis_client()
        for bf in bfs:
            rc.set(backfill_cancel_key(str(bf.id)), "1", ex=86400)
            if bf.current_cron_run_id is not None:
                crun = db.scalar(
                    select(CronRun).where(CronRun.id == bf.current_cron_run_id)
                )
                if crun is not None:
                    cron_run_crud.cancel_cron_run_and_children(db, crun)
            db.refresh(bf)
            if bf.status in (
                CronBackfillStatus.PENDING, CronBackfillStatus.RUNNING
            ):
                cron_backfill_crud.mark_cancelled(db, bf)


@router.patch(
    "/admin/puskesmas/{puskesmas_id}/cron-config",
    response_model=CronConfigOut,
)
def update_cron_config(
    puskesmas_id: uuid.UUID,
    body: CronConfigUpdate,
    db: Session = Depends(get_db),
    _admin_id: uuid.UUID = Depends(get_current_admin_id),
) -> CronConfigOut:
    obj = crud.get_by_puskesmas(db, puskesmas_id)
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Cron config not found")
    will_disable = body.enabled is False and obj.enabled is True
    if _has_schedule_change(obj, body) and _active_run_exists(db, puskesmas_id):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "cannot edit schedule fields while a cron run is in progress; "
            "cancel or wait for it to finish",
        )
    obj = crud.update(
        db, obj,
        hour=body.hour,
        minute=body.minute,
        target_offset_days=body.target_offset_days,
        lookback_days=body.lookback_days,
        enabled=body.enabled,
        merge_mode=body.merge_mode,
        sync_mode=body.sync_mode,
        create_new=body.create_new,
    )
    if will_disable:
        _cancel_active_runs_for_config(db, obj.id)
    return _to_out(obj)


@router.delete(
    "/admin/puskesmas/{puskesmas_id}/cron-config",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_cron_config(
    puskesmas_id: uuid.UUID,
    db: Session = Depends(get_db),
    _admin_id: uuid.UUID = Depends(get_current_admin_id),
) -> None:
    obj = crud.get_by_puskesmas(db, puskesmas_id)
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Cron config not found")
    config_id = obj.id
    crud.soft_delete(db, obj)
    _cancel_active_runs_for_config(db, config_id)


@router.post(
    "/admin/puskesmas/{puskesmas_id}/cron-config/run-now",
    response_model=CronRunOut,
    status_code=status.HTTP_201_CREATED,
)
def run_now(
    puskesmas_id: uuid.UUID,
    db: Session = Depends(get_db),
    admin_id: uuid.UUID = Depends(get_current_admin_id),
) -> CronRunOut:
    cfg = crud.get_by_puskesmas(db, puskesmas_id)
    if cfg is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Cron config not found")
    pk_name = db.scalar(select(Puskesmas.name).where(Puskesmas.id == puskesmas_id))
    if pk_name is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Puskesmas not found")

    # Pre-check is advisory; the lane partial UNIQUE indexes
    # (uq_cron_runs_active_epus / _asik) are the actual race-safe guard. run-now
    # is always source_scope=BOTH (occupies both lanes), so any active run
    # conflicts — this simple check stays correct.
    active = db.scalar(
        select(CronRun.id)
        .where(
            CronRun.puskesmas_id == puskesmas_id,
            CronRun.status.in_((CronRunStatus.PENDING, CronRunStatus.RUNNING)),
        )
        .limit(1)
    )
    if active is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "a cron run is already in progress for this puskesmas",
        )

    # A date-range backfill also owns this puskesmas' run lanes, but between its
    # dates there is a window with no active CronRun (the cursor is advancing).
    # A run-now started in that window creates a BOTH run that collides with the
    # backfill's next date and marks the backfill FAILED. Reject if a backfill is
    # active — matches create_backfill / dispatch_due, which both check this.
    active_bf = db.scalar(
        select(CronBackfill.id)
        .where(
            CronBackfill.puskesmas_id == puskesmas_id,
            CronBackfill.status.in_(
                (CronBackfillStatus.PENDING, CronBackfillStatus.RUNNING)
            ),
        )
        .limit(1)
    )
    if active_bf is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "a date-range backfill is in progress for this puskesmas",
        )

    today = datetime.now(_JKT).date()
    target_date = today + timedelta(days=cfg.target_offset_days)
    try:
        run = cron_run_crud.create(
            db,
            puskesmas_id=puskesmas_id,
            target_date=target_date,
            cron_config_id=cfg.id,
            triggered_by_id=admin_id,
        )
    except IntegrityError as e:
        db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "a cron run is already in progress for this puskesmas",
        ) from e
    try:
        celery_app.send_task("cron.advance", args=[str(run.id), CronStep.EPUS.value])
    except Exception as e:
        from app.crud import cron_run as cr
        cr.mark_failed(
            db, run, CronStep.EPUS,
            f"broker unreachable: {e}", datetime.now(UTC),
        )
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "cron broker unavailable"
        ) from e
    return cron_run_to_out(run, pk_name)
