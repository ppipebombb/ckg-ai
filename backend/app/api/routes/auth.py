import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session, contains_eager, load_only

from app.api.deps import get_current_user_id, get_db, get_token_payload
from app.api.routes.admin_auth_ops import logout
from app.core.rate_limit import enforce_login_rate_limit, record_failed_login_attempt
from app.core.security import create_access_token, verify_password
from app.models.puskesmas import Puskesmas
from app.models.user import User
from app.schemas.auth import LoginRequest, TokenResponse
from app.schemas.user import UserMeOut

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
def user_login(
    data: LoginRequest, request: Request, db: Session = Depends(get_db)
) -> TokenResponse:
    enforce_login_rate_limit(request, data.email)
    row = db.execute(
        select(User.id, User.password_hash).where(User.email == data.email)
    ).one_or_none()
    if row is None or not verify_password(data.password, row.password_hash):
        record_failed_login_attempt(request, data.email)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")
    return TokenResponse(access_token=create_access_token(row.id, "user"))


@router.post("/logout")
def user_logout(payload: dict = Depends(get_token_payload)) -> dict[str, str]:
    return logout(payload)


@router.get("/me", response_model=UserMeOut)
def user_me(
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> UserMeOut:
    user = db.scalar(
        select(User)
        .join(User.puskesmas)
        .options(
            load_only(User.id, User.email, User.full_name, User.puskesmas_id, User.created_at, User.updated_at),
            contains_eager(User.puskesmas).load_only(Puskesmas.name),
        )
        .where(User.id == user_id)
    )
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found")
    return UserMeOut(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        puskesmas_id=user.puskesmas_id,
        puskesmas_name=user.puskesmas.name,
        created_at=user.created_at,
        updated_at=user.updated_at,
    )
