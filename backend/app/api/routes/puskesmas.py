import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session, load_only

from app.api.deps import (
    Principal,
    get_current_admin_id,
    get_dashboard_admin_id,
    get_db,
    get_principal,
)
from app.api.pagination import Page, PageParams, page_params, paginate
from app.core.rate_limit import enforce_decrypt_rate_limit
from app.crud import puskesmas as crud
from app.models.puskesmas import Puskesmas
from app.schemas.puskesmas import CredIn, CredOut, PuskesmasCreate, PuskesmasDetailOut, PuskesmasOut, PuskesmasUpdate

CredKind = Literal["epus", "asik"]

router = APIRouter(prefix="/puskesmas", tags=["puskesmas"])

_PUSKESMAS_OUT_COLS = (
    Puskesmas.id, Puskesmas.name, Puskesmas.epus_url, Puskesmas.asik_url,
    Puskesmas.asik_default_alamat, Puskesmas.created_at, Puskesmas.updated_at,
)


def _authorize_cred_access(principal: Principal, puskesmas_id: uuid.UUID) -> None:
    if principal.typ == "user" and principal.puskesmas_id != puskesmas_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Forbidden")


@router.get("", response_model=Page[PuskesmasOut])
def list_puskesmas(
    params: PageParams = Depends(page_params),
    name: str | None = Query(default=None),
    db: Session = Depends(get_db),
    _: uuid.UUID = Depends(get_dashboard_admin_id),
) -> Page[PuskesmasOut]:
    stmt = select(Puskesmas).options(load_only(*_PUSKESMAS_OUT_COLS)).order_by(Puskesmas.created_at.desc())
    if name:
        stmt = stmt.where(Puskesmas.name.ilike(f"%{name}%"))
    items, total, pages = paginate(db, stmt, params)
    return Page[PuskesmasOut](
        items=[PuskesmasOut.model_validate(i) for i in items],
        total=total,
        page=params.page,
        size=params.size,
        pages=pages,
    )


@router.post("", response_model=PuskesmasOut, status_code=status.HTTP_201_CREATED)
def create_puskesmas(
    data: PuskesmasCreate,
    db: Session = Depends(get_db),
    _: uuid.UUID = Depends(get_current_admin_id),
) -> PuskesmasOut:
    return PuskesmasOut.model_validate(crud.create(db, data))


@router.get("/{id}", response_model=PuskesmasDetailOut)
def get_puskesmas(
    id: uuid.UUID,
    db: Session = Depends(get_db),
    _: uuid.UUID = Depends(get_dashboard_admin_id),
) -> PuskesmasDetailOut:
    row = db.execute(
        select(
            Puskesmas,
            Puskesmas.epus_cred.isnot(None),
            Puskesmas.asik_cred.isnot(None),
        )
        .options(load_only(*_PUSKESMAS_OUT_COLS))
        .where(Puskesmas.id == id)
    ).one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Puskesmas not found")
    obj, has_epus, has_asik = row
    return PuskesmasDetailOut.model_validate(
        {**PuskesmasOut.model_validate(obj).model_dump(), "is_epus_cred_set": has_epus, "is_asik_cred_set": has_asik}
    )


@router.patch("/{id}", response_model=PuskesmasDetailOut)
def update_puskesmas(
    id: uuid.UUID,
    data: PuskesmasUpdate,
    db: Session = Depends(get_db),
    _: uuid.UUID = Depends(get_current_admin_id),
) -> PuskesmasDetailOut:
    obj = db.scalar(
        select(Puskesmas).options(load_only(*_PUSKESMAS_OUT_COLS)).where(Puskesmas.id == id)
    )
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Puskesmas not found")
    updated = crud.update(db, obj, data)
    has_epus, has_asik = db.execute(
        select(Puskesmas.epus_cred.isnot(None), Puskesmas.asik_cred.isnot(None))
        .where(Puskesmas.id == id)
    ).one()
    return PuskesmasDetailOut.model_validate(
        {**PuskesmasOut.model_validate(updated).model_dump(), "is_epus_cred_set": has_epus, "is_asik_cred_set": has_asik}
    )


@router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_puskesmas(
    id: uuid.UUID,
    db: Session = Depends(get_db),
    _: uuid.UUID = Depends(get_current_admin_id),
) -> None:
    obj = db.scalar(
        select(Puskesmas).options(load_only(Puskesmas.id)).where(Puskesmas.id == id)
    )
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Puskesmas not found")
    crud.soft_delete(db, obj)


@router.put("/{id}/credentials/{kind}", status_code=status.HTTP_204_NO_CONTENT)
def set_puskesmas_cred(
    id: uuid.UUID,
    kind: CredKind,
    data: CredIn,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> None:
    _authorize_cred_access(principal, id)
    cred_col = Puskesmas.epus_cred if kind == "epus" else Puskesmas.asik_cred
    obj = db.scalar(
        select(Puskesmas).options(load_only(Puskesmas.id, cred_col)).where(Puskesmas.id == id)
    )
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Puskesmas not found")
    crud.set_cred(db, obj, kind, data)


@router.delete("/{id}/credentials/{kind}", status_code=status.HTTP_204_NO_CONTENT)
def clear_puskesmas_cred(
    id: uuid.UUID,
    kind: CredKind,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> None:
    _authorize_cred_access(principal, id)
    cred_col = Puskesmas.epus_cred if kind == "epus" else Puskesmas.asik_cred
    obj = db.scalar(
        select(Puskesmas).options(load_only(Puskesmas.id, cred_col)).where(Puskesmas.id == id)
    )
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Puskesmas not found")
    crud.clear_cred(db, obj, kind)


@router.post("/{id}/credentials/{kind}/decrypt", response_model=CredOut)
def get_puskesmas_cred_decrypted(
    id: uuid.UUID,
    kind: CredKind,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> CredOut:
    _authorize_cred_access(principal, id)
    enforce_decrypt_rate_limit(principal.id, id)
    cred_col = Puskesmas.epus_cred if kind == "epus" else Puskesmas.asik_cred
    obj = db.scalar(
        select(Puskesmas).options(load_only(Puskesmas.id, cred_col)).where(Puskesmas.id == id)
    )
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Puskesmas not found")
    plain = crud.get_cred_decrypted(obj, kind)
    if plain is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Credential not set")
    return CredOut(**plain)
