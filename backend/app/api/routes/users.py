import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, contains_eager, load_only

from app.api.deps import get_current_admin_id, get_db
from app.api.pagination import Page, PageParams, page_params, paginate
from app.core.token_revocation import revoke_all_for
from app.crud import user as crud
from app.models.puskesmas import Puskesmas
from app.models.user import User
from app.schemas.user import UserCreate, UserOut, UserUpdate

router = APIRouter(prefix="/users", tags=["users"])

_USER_OUT_COLS = (
    User.id, User.email, User.full_name, User.puskesmas_id, User.created_at, User.updated_at
)


def _to_user_out(u: User, puskesmas_name: str) -> UserOut:
    return UserOut(
        id=u.id,
        email=u.email,
        full_name=u.full_name,
        puskesmas_id=u.puskesmas_id,
        puskesmas_name=puskesmas_name,
        created_at=u.created_at,
        updated_at=u.updated_at,
    )


@router.get("", response_model=Page[UserOut])
def list_users(
    params: PageParams = Depends(page_params),
    full_name: str | None = Query(default=None),
    puskesmas_id: uuid.UUID | None = Query(None),
    db: Session = Depends(get_db),
    _: uuid.UUID = Depends(get_current_admin_id),
) -> Page[UserOut]:
    stmt = (
        select(User)
        .join(User.puskesmas)
        .options(
            load_only(*_USER_OUT_COLS),
            contains_eager(User.puskesmas).load_only(Puskesmas.name),
        )
        .order_by(User.created_at.desc())
    )
    if full_name:
        stmt = stmt.where(User.full_name.ilike(f"%{full_name}%"))
    if puskesmas_id is not None:
        stmt = stmt.where(User.puskesmas_id == puskesmas_id)
    items, total, pages = paginate(db, stmt, params)
    return Page[UserOut](
        items=[_to_user_out(i, i.puskesmas.name) for i in items],
        total=total,
        page=params.page,
        size=params.size,
        pages=pages,
    )


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_user(
    data: UserCreate,
    db: Session = Depends(get_db),
    _: uuid.UUID = Depends(get_current_admin_id),
) -> UserOut:
    pk_name = db.scalar(select(Puskesmas.name).where(Puskesmas.id == data.puskesmas_id))
    if pk_name is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "puskesmas_id does not exist")
    taken = db.scalar(select(User.id).where(User.email == data.email))
    if taken is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "email already in use")
    try:
        obj = crud.create(db, data)
        return _to_user_out(obj, pk_name)
    except IntegrityError as e:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "constraint violation") from e


@router.get("/{id}", response_model=UserOut)
def get_user(
    id: uuid.UUID,
    db: Session = Depends(get_db),
    _: uuid.UUID = Depends(get_current_admin_id),
) -> UserOut:
    obj = db.scalar(
        select(User)
        .join(User.puskesmas)
        .options(
            load_only(*_USER_OUT_COLS),
            contains_eager(User.puskesmas).load_only(Puskesmas.name),
        )
        .where(User.id == id)
    )
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    return _to_user_out(obj, obj.puskesmas.name)


@router.patch("/{id}", response_model=UserOut)
def update_user(
    id: uuid.UUID,
    data: UserUpdate,
    db: Session = Depends(get_db),
    _: uuid.UUID = Depends(get_current_admin_id),
) -> UserOut:
    obj = db.scalar(
        select(User)
        .join(User.puskesmas)
        .options(
            load_only(*_USER_OUT_COLS),
            contains_eager(User.puskesmas).load_only(Puskesmas.name),
        )
        .where(User.id == id)
    )
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    if data.puskesmas_id is not None and data.puskesmas_id != obj.puskesmas_id:
        new_pk_name = db.scalar(
            select(Puskesmas.name).where(Puskesmas.id == data.puskesmas_id)
        )
        if new_pk_name is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "puskesmas_id does not exist")
        pk_name = new_pk_name
    else:
        pk_name = obj.puskesmas.name
    if data.email is not None and data.email != obj.email:
        taken = db.scalar(select(User.id).where(User.email == data.email))
        if taken is not None:
            raise HTTPException(status.HTTP_409_CONFLICT, "email already in use")
    try:
        updated = crud.update(db, obj, data)
    except IntegrityError as e:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "constraint violation") from e
    # A password change must invalidate the user's existing sessions: a stolen
    # token otherwise stays valid until exp despite the credential rotation.
    if data.password is not None:
        revoke_all_for("user", id)
    return _to_user_out(updated, pk_name)


@router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(
    id: uuid.UUID,
    db: Session = Depends(get_db),
    _: uuid.UUID = Depends(get_current_admin_id),
) -> None:
    obj = db.scalar(
        select(User).options(load_only(User.id)).where(User.id == id)
    )
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    crud.soft_delete(db, obj)
    # get_principal re-checks existence (soft-delete auto-filter) on data
    # endpoints, but /auth/me only decodes the token — revoke so a deleted
    # user's outstanding tokens stop working everywhere immediately.
    revoke_all_for("user", id)
