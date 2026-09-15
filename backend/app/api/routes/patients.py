import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import Select, or_, select
from sqlalchemy.orm import Session, load_only

from app.api.deps import (
    Principal,
    get_current_admin_id,
    get_dashboard_principal,
    get_db,
)
from app.api.pagination import Page, PageParams, page_params, paginate_execute
from app.core.rate_limit import enforce_decrypt_rate_limit
from app.crud import patient as crud
from app.models.patient import MatchStatus, Patient
from app.models.scrape_job import ScrapeKind
from app.schemas.patient import AsikPreviewOut, PatientDecryptedOut, PatientOut
from app.services.epus_to_asik import epus_to_asik

router = APIRouter(prefix="/patients", tags=["patients"])


def _authorize(principal: Principal, puskesmas_id: uuid.UUID) -> None:
    # Object-level access: a user touching another clinic's patient gets the SAME
    # 404 as a nonexistent one, so it can't be used to probe which patient ids
    # exist in other clinics (no 403-vs-404 existence oracle).
    if principal.typ == "user" and principal.puskesmas_id != puskesmas_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Patient not found")


def _years_ago(d: date, years: int) -> date:
    """`d` shifted back `years`, clamping a Feb-29 source to Feb-28 in a
    non-leap target year (conventional legal-age behavior)."""
    try:
        return d.replace(year=d.year - years)
    except ValueError:
        return d.replace(year=d.year - years, day=28)


def _patient_list_stmt(
    puskesmas_id: uuid.UUID | None,
    match_status: MatchStatus | None,
    filter_date: date | None,
    q: str | None,
    merged: bool | None,
    min_age: int | None,
    max_age: int | None,
) -> Select:
    stmt = select(
        Patient.id,
        Patient.puskesmas_id,
        Patient.nik,
        Patient.nama,
        Patient.match_status,
        Patient.scraped_asik_data.isnot(None).label("has_asik_data"),
        Patient.scraped_epus_data.isnot(None).label("has_epus_data"),
        Patient.merged_data.isnot(None).label("has_merged_data"),
        Patient.merged_at,
        Patient.filter_date,
        Patient.ruangan,
        Patient.birth_date,
        Patient.epus_tandai_ckg,
        Patient.match_group_id,
        Patient.created_at,
        Patient.updated_at,
    ).order_by(Patient.created_at.desc())
    if puskesmas_id is not None:
        stmt = stmt.where(Patient.puskesmas_id == puskesmas_id)
    if match_status is not None:
        stmt = stmt.where(Patient.match_status == match_status)
    if q:
        stmt = stmt.where(
            or_(Patient.nama.ilike(f"%{q}%"), Patient.nik.ilike(f"%{q}%"))
        )
    if filter_date is not None:
        stmt = stmt.where(Patient.filter_date == filter_date)
    if merged is True:
        # Hits partial index ix_patients_merged_at (WHERE merged_at IS NOT NULL).
        stmt = stmt.where(Patient.merged_at.isnot(None))
    elif merged is False:
        stmt = stmt.where(Patient.merged_at.is_(None))
    # Age (umur) = current age = today - birth_date. NULL birth_date rows are
    # excluded by these range predicates (unknown age never matches a bound).
    if min_age is not None or max_age is not None:
        today = date.today()
        if min_age is not None:
            stmt = stmt.where(Patient.birth_date <= _years_ago(today, min_age))
        if max_age is not None:
            stmt = stmt.where(Patient.birth_date > _years_ago(today, max_age + 1))
    return stmt


@router.get("", response_model=Page[PatientOut])
def list_patients(
    params: PageParams = Depends(page_params),
    puskesmas_id: uuid.UUID | None = Query(None),
    match_status: MatchStatus | None = Query(None),
    filter_date: date | None = Query(None),
    q: str | None = Query(None, max_length=64),
    merged: bool | None = Query(None),
    min_age: int | None = Query(None, ge=0, le=150),
    max_age: int | None = Query(None, ge=0, le=150),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_dashboard_principal),
) -> Page[PatientOut]:
    if principal.typ == "user":
        if puskesmas_id is None:
            puskesmas_id = principal.puskesmas_id
        elif puskesmas_id != principal.puskesmas_id:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Forbidden")
    stmt = _patient_list_stmt(
        puskesmas_id, match_status, filter_date, q, merged, min_age, max_age
    )
    items, total, pages = paginate_execute(db, stmt, params)
    return Page[PatientOut](
        items=[PatientOut(**row._mapping) for row in items],
        total=total,
        page=params.page,
        size=params.size,
        pages=pages,
    )


@router.get("/{id}", response_model=PatientOut)
def get_patient(
    id: uuid.UUID,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_dashboard_principal),
) -> PatientOut:
    row = db.execute(
        select(
            Patient.id,
            Patient.puskesmas_id,
            Patient.nik,
            Patient.nama,
            Patient.match_status,
            Patient.scraped_asik_data.isnot(None).label("has_asik_data"),
            Patient.scraped_epus_data.isnot(None).label("has_epus_data"),
            Patient.merged_data.isnot(None).label("has_merged_data"),
            Patient.merged_at,
            Patient.filter_date,
            Patient.ruangan,
            Patient.birth_date,
            Patient.epus_tandai_ckg,
            Patient.match_group_id,
            Patient.created_at,
            Patient.updated_at,
        ).where(Patient.id == id)
    ).one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Patient not found")
    _authorize(principal, row.puskesmas_id)
    return PatientOut(**row._mapping)


@router.post("/{id}/decrypt", response_model=PatientDecryptedOut)
def decrypt_patient(
    id: uuid.UUID,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_dashboard_principal),
) -> PatientDecryptedOut:
    # TODO(audit): record decrypt access in audit_logs once that table lands.
    obj = db.scalar(
        select(Patient)
        .options(load_only(
            Patient.id, Patient.puskesmas_id, Patient.nik, Patient.nama,
            Patient.match_status, Patient.scraped_asik_data, Patient.scraped_epus_data,
            Patient.merged_data, Patient.merged_at, Patient.match_group_id,
            Patient.filter_date, Patient.created_at, Patient.updated_at,
        ))
        .where(Patient.id == id)
    )
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Patient not found")
    _authorize(principal, obj.puskesmas_id)
    # Rate-limit after authorize so unauth probes don't burn the requester's budget on foreign IDs.
    enforce_decrypt_rate_limit(principal.id, id)
    return PatientDecryptedOut(
        id=obj.id,
        puskesmas_id=obj.puskesmas_id,
        nik=obj.nik,
        nama=obj.nama,
        match_status=obj.match_status,
        scraped_asik_data=crud.decrypt_field(obj, ScrapeKind.ASIK),
        scraped_epus_data=crud.decrypt_field(obj, ScrapeKind.EPUS),
        merged_data=crud.decrypt_merged(obj),
        merged_at=obj.merged_at,
        filter_date=obj.filter_date,
        match_group_id=obj.match_group_id,
        created_at=obj.created_at,
        updated_at=obj.updated_at,
    )


@router.post("/{id}/asik-preview", response_model=AsikPreviewOut)
def asik_preview(
    id: uuid.UUID,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_dashboard_principal),
) -> AsikPreviewOut:
    obj = db.scalar(
        select(Patient)
        .options(load_only(
            Patient.id, Patient.puskesmas_id, Patient.scraped_epus_data,
        ))
        .where(Patient.id == id)
    )
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Patient not found")
    _authorize(principal, obj.puskesmas_id)
    if obj.scraped_epus_data is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Patient has no scraped_epus_data to convert",
        )
    enforce_decrypt_rate_limit(principal.id, id)
    epus = crud.decrypt_field(obj, ScrapeKind.EPUS)
    return AsikPreviewOut(id=obj.id, forms=epus_to_asik(epus or {}))


@router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_patient(
    id: uuid.UUID,
    db: Session = Depends(get_db),
    _: uuid.UUID = Depends(get_current_admin_id),
) -> None:
    obj = db.scalar(
        select(Patient).options(load_only(Patient.id)).where(Patient.id == id)
    )
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Patient not found")
    crud.soft_delete(db, obj)
