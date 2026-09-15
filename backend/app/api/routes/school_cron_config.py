import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_current_admin_id, get_db
from app.api.routes.scrape import _to_job_out
from app.celery_app import celery_app
from app.crud import scrape_job as scrape_job_crud
from app.crud import school_cron_config as crud
from app.models.puskesmas import Puskesmas
from app.models.scrape_job import ScrapeKind, TriggererType
from app.models.school_cron_config import SchoolCronConfig
from app.schemas.school_cron_config import (
    SchoolCronConfigCreate,
    SchoolCronConfigOut,
    SchoolCronConfigUpdate,
)
from app.schemas.scrape_job import ScrapeJobOut

router = APIRouter(tags=["school-cron"])


def _to_out(obj: SchoolCronConfig) -> SchoolCronConfigOut:
    return SchoolCronConfigOut.model_validate(obj)


@router.post(
    "/admin/puskesmas/{puskesmas_id}/school-cron-config",
    response_model=SchoolCronConfigOut,
    status_code=status.HTTP_201_CREATED,
)
def create_school_cron_config(
    puskesmas_id: uuid.UUID,
    body: SchoolCronConfigCreate,
    db: Session = Depends(get_db),
    _admin_id: uuid.UUID = Depends(get_current_admin_id),
) -> SchoolCronConfigOut:
    pk = db.scalar(select(Puskesmas.id).where(Puskesmas.id == puskesmas_id))
    if pk is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Puskesmas not found")
    try:
        obj = crud.create(
            db,
            puskesmas_id=puskesmas_id,
            hour=body.hour,
            minute=body.minute,
            enabled=body.enabled,
        )
    except IntegrityError as e:
        db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "school cron config already exists for this puskesmas",
        ) from e
    return _to_out(obj)


@router.get(
    "/admin/puskesmas/{puskesmas_id}/school-cron-config",
    response_model=SchoolCronConfigOut,
)
def get_school_cron_config(
    puskesmas_id: uuid.UUID,
    db: Session = Depends(get_db),
    _admin_id: uuid.UUID = Depends(get_current_admin_id),
) -> SchoolCronConfigOut:
    obj = crud.get_by_puskesmas(db, puskesmas_id)
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "School cron config not found")
    return _to_out(obj)


@router.patch(
    "/admin/puskesmas/{puskesmas_id}/school-cron-config",
    response_model=SchoolCronConfigOut,
)
def update_school_cron_config(
    puskesmas_id: uuid.UUID,
    body: SchoolCronConfigUpdate,
    db: Session = Depends(get_db),
    _admin_id: uuid.UUID = Depends(get_current_admin_id),
) -> SchoolCronConfigOut:
    obj = crud.get_by_puskesmas(db, puskesmas_id)
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "School cron config not found")
    obj = crud.update(
        db, obj, hour=body.hour, minute=body.minute, enabled=body.enabled
    )
    return _to_out(obj)


@router.delete(
    "/admin/puskesmas/{puskesmas_id}/school-cron-config",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_school_cron_config(
    puskesmas_id: uuid.UUID,
    db: Session = Depends(get_db),
    _admin_id: uuid.UUID = Depends(get_current_admin_id),
) -> None:
    obj = crud.get_by_puskesmas(db, puskesmas_id)
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "School cron config not found")
    crud.soft_delete(db, obj)


@router.post(
    "/admin/puskesmas/{puskesmas_id}/school-cron-config/run-now",
    response_model=ScrapeJobOut,
    status_code=status.HTTP_201_CREATED,
)
def run_now(
    puskesmas_id: uuid.UUID,
    db: Session = Depends(get_db),
    admin_id: uuid.UUID = Depends(get_current_admin_id),
) -> ScrapeJobOut:
    row = db.execute(
        select(
            Puskesmas.asik_cred.isnot(None), Puskesmas.asik_url, Puskesmas.name
        ).where(Puskesmas.id == puskesmas_id)
    ).one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Puskesmas not found")
    has_cred, base_url, puskesmas_name = row
    if not has_cred:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "asik credentials not set")
    if not base_url:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "asik_url not set for this puskesmas")
    try:
        job = scrape_job_crud.create(
            db,
            puskesmas_id=puskesmas_id,
            kind=ScrapeKind.ASIK_SEKOLAH,
            date_filter=None,
            triggered_by_id=admin_id,
            triggered_by_type=TriggererType.ADMIN,
        )
    except IntegrityError as e:
        db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "a CKG Sekolah scrape is already in progress for this puskesmas",
        ) from e
    try:
        celery_app.send_task(
            "scrape.run",
            args=[str(job.id), ScrapeKind.ASIK_SEKOLAH.value],
            kwargs={"headless": True},
        )
    except Exception as e:
        scrape_job_crud.mark_failed(
            db, job, f"broker unreachable: {e}"[:2000], datetime.now(UTC)
        )
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "scrape broker unavailable"
        ) from e
    return _to_job_out(job, puskesmas_name)
