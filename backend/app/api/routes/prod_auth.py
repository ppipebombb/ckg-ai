import uuid

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.api.deps import get_current_prod_admin_id, get_db, get_token_payload
from app.api.routes.admin_auth_ops import get_admin_out, login_admin, logout
from app.schemas.admin import AdminOut
from app.schemas.auth import LoginRequest, TokenResponse

router = APIRouter(prefix="/prod/auth", tags=["prod-auth"])


@router.post("/login", response_model=TokenResponse)
def prod_login(
    data: LoginRequest, request: Request, db: Session = Depends(get_db)
) -> TokenResponse:
    return login_admin(data, request, db, scope="prod")


@router.post("/logout")
def prod_logout(payload: dict = Depends(get_token_payload)) -> dict[str, str]:
    return logout(payload)


@router.get("/me", response_model=AdminOut)
def prod_me(
    admin_id: uuid.UUID = Depends(get_current_prod_admin_id),
    db: Session = Depends(get_db),
) -> AdminOut:
    return get_admin_out(admin_id, db)
