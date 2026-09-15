import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import distinct, or_, select
from sqlalchemy.orm import Session, load_only

from app.api.deps import (
    Principal,
    get_current_admin_id,
    get_dashboard_principal,
    get_db,
)
from app.api.pagination import Page, PageParams, page_params, paginate_execute
from app.core.rate_limit import enforce_decrypt_rate_limit
from app.core.security import decrypt_json
from app.crud import school_patient as crud
from app.models.school_patient import SchoolPatient, SchoolScreeningStatus
from app.schemas.school_patient import (
    SchoolFacet,
    SchoolFacetsOut,
    SchoolPatientDecryptedOut,
    SchoolPatientOut,
)

router = APIRouter(prefix="/school-patients", tags=["school-patients"])


def _authorize(principal: Principal, puskesmas_id: uuid.UUID) -> None:
    # Same-clinic 404 for foreign rows (no existence oracle), matching patients.
    if principal.typ == "user" and principal.puskesmas_id != puskesmas_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "School patient not found")


def _scope_puskesmas(
    principal: Principal, puskesmas_id: uuid.UUID | None
) -> uuid.UUID | None:
    """Force a puskesmas user onto its own clinic; admins (internal/prod) pass
    the explicit filter through. Mirrors routes/patients.py."""
    if principal.typ == "user":
        if puskesmas_id is None:
            return principal.puskesmas_id
        if puskesmas_id != principal.puskesmas_id:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Forbidden")
    return puskesmas_id


def _years_ago(d: date, years: int) -> date:
    """`d` shifted back `years`, clamping Feb-29 → Feb-28 in a non-leap target."""
    try:
        return d.replace(year=d.year - years)
    except ValueError:
        return d.replace(year=d.year - years, day=28)


@router.get("", response_model=Page[SchoolPatientOut])
def list_school_patients(
    params: PageParams = Depends(page_params),
    puskesmas_id: uuid.UUID | None = Query(None),
    screening_status: SchoolScreeningStatus | None = Query(None),
    school_name: str | None = Query(None, max_length=255),
    class_name: str | None = Query(None, max_length=64),
    school_year: int | None = Query(None),
    min_age: int | None = Query(None, ge=0, le=150),
    max_age: int | None = Query(None, ge=0, le=150),
    q: str | None = Query(None, max_length=64),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_dashboard_principal),
) -> Page[SchoolPatientOut]:
    puskesmas_id = _scope_puskesmas(principal, puskesmas_id)
    stmt = select(
        SchoolPatient.id,
        SchoolPatient.puskesmas_id,
        SchoolPatient.nik,
        SchoolPatient.nama,
        SchoolPatient.born_date,
        SchoolPatient.gender,
        SchoolPatient.school_year,
        SchoolPatient.school_name,
        SchoolPatient.class_name,
        SchoolPatient.klaster_name,
        SchoolPatient.screening_status,
        SchoolPatient.scraped_sekolah_data.isnot(None).label("has_data"),
        SchoolPatient.scraped_at,
        SchoolPatient.created_at,
        SchoolPatient.updated_at,
    ).order_by(SchoolPatient.created_at.desc())
    if puskesmas_id is not None:
        stmt = stmt.where(SchoolPatient.puskesmas_id == puskesmas_id)
    if screening_status is not None:
        stmt = stmt.where(SchoolPatient.screening_status == screening_status)
    if school_name:
        stmt = stmt.where(SchoolPatient.school_name == school_name)
    if class_name:
        stmt = stmt.where(SchoolPatient.class_name == class_name)
    if school_year is not None:
        stmt = stmt.where(SchoolPatient.school_year == school_year)
    # Umur = today − born_date. NULL born_date rows never match a bound.
    if min_age is not None or max_age is not None:
        today = date.today()
        if min_age is not None:
            stmt = stmt.where(SchoolPatient.born_date <= _years_ago(today, min_age))
        if max_age is not None:
            stmt = stmt.where(SchoolPatient.born_date > _years_ago(today, max_age + 1))
    if q:
        stmt = stmt.where(
            or_(SchoolPatient.nama.ilike(f"%{q}%"), SchoolPatient.nik.ilike(f"%{q}%"))
        )
    items, total, pages = paginate_execute(db, stmt, params)
    return Page[SchoolPatientOut](
        items=[SchoolPatientOut(**row._mapping) for row in items],
        total=total,
        page=params.page,
        size=params.size,
        pages=pages,
    )


@router.get("/facets", response_model=SchoolFacetsOut)
def school_facets(
    puskesmas_id: uuid.UUID | None = Query(None),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_dashboard_principal),
) -> SchoolFacetsOut:
    """Distinct schools (with their classes) + school years for the cascading
    filter dropdowns, scoped to the resolved puskesmas. Soft-delete auto-filter
    keeps deleted rows out (SELECT)."""
    puskesmas_id = _scope_puskesmas(principal, puskesmas_id)
    sc_stmt = select(
        distinct(SchoolPatient.school_name).label("school_name"),
        SchoolPatient.class_name,
    ).where(SchoolPatient.school_name.isnot(None))
    yr_stmt = select(distinct(SchoolPatient.school_year))
    if puskesmas_id is not None:
        sc_stmt = sc_stmt.where(SchoolPatient.puskesmas_id == puskesmas_id)
        yr_stmt = yr_stmt.where(SchoolPatient.puskesmas_id == puskesmas_id)

    by_school: dict[str, set[str]] = {}
    for school_name, class_name in db.execute(sc_stmt):
        classes = by_school.setdefault(school_name, set())
        if class_name:
            classes.add(class_name)
    schools = [
        SchoolFacet(name=name, classes=sorted(classes))
        for name, classes in sorted(by_school.items())
    ]
    years = sorted((row[0] for row in db.execute(yr_stmt)), reverse=True)
    return SchoolFacetsOut(schools=schools, school_years=years)


@router.post("/{id}/decrypt", response_model=SchoolPatientDecryptedOut)
def decrypt_school_patient(
    id: uuid.UUID,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_dashboard_principal),
) -> SchoolPatientDecryptedOut:
    obj = db.scalar(
        select(SchoolPatient)
        .options(load_only(
            SchoolPatient.id, SchoolPatient.puskesmas_id, SchoolPatient.nik,
            SchoolPatient.nama, SchoolPatient.school_year, SchoolPatient.school_name,
            SchoolPatient.class_name, SchoolPatient.klaster_name,
            SchoolPatient.screening_status, SchoolPatient.scraped_sekolah_data,
            SchoolPatient.scraped_at, SchoolPatient.created_at, SchoolPatient.updated_at,
        ))
        .where(SchoolPatient.id == id)
    )
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "School patient not found")
    _authorize(principal, obj.puskesmas_id)
    enforce_decrypt_rate_limit(principal.id, id)
    data = decrypt_json(obj.scraped_sekolah_data) if obj.scraped_sekolah_data else None
    return SchoolPatientDecryptedOut(
        id=obj.id,
        puskesmas_id=obj.puskesmas_id,
        nik=obj.nik,
        nama=obj.nama,
        school_year=obj.school_year,
        school_name=obj.school_name,
        class_name=obj.class_name,
        klaster_name=obj.klaster_name,
        screening_status=obj.screening_status,
        scraped_sekolah_data=data,
        scraped_at=obj.scraped_at,
        created_at=obj.created_at,
        updated_at=obj.updated_at,
    )


@router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_school_patient(
    id: uuid.UUID,
    db: Session = Depends(get_db),
    _: uuid.UUID = Depends(get_current_admin_id),
) -> None:
    obj = crud.get(db, id)
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "School patient not found")
    crud.soft_delete(db, obj)
