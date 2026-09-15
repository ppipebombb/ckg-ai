"""Shared login + session-check logic for the two admin login pools.

The internal (`/admin/auth`) and external prod (`/prod/auth`) routers differ only
in the login ``scope`` and the `/me` scope dependency — every other line was
byte-identical, so it lives here once.
"""

import uuid

from fastapi import HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session, load_only

from app.core.rate_limit import enforce_login_rate_limit, record_failed_login_attempt
from app.core.security import create_access_token, hash_password, verify_password
from app.core.token_revocation import revoke_token
from app.models.admin import Admin
from app.schemas.admin import AdminOut
from app.schemas.auth import LoginRequest, TokenResponse

# Constant-time guard: a bcrypt verify always runs — even when the email is
# unknown — so an attacker can't use response timing to enumerate which emails
# are valid admins in a given pool.
_DUMMY_PASSWORD_HASH = hash_password("ckg-login-timing-equalizer")


def login_admin(
    data: LoginRequest, request: Request, db: Session, *, scope: str
) -> TokenResponse:
    """Authenticate an admin within one login pool (``scope``) and mint a token.

    A token from the other pool is impossible to obtain here because the email
    lookup is scoped — the partition is enforced at the moment of login.
    """
    enforce_login_rate_limit(request, data.email)
    row = db.execute(
        select(Admin.id, Admin.password_hash).where(
            Admin.email == data.email, Admin.scope == scope
        )
    ).one_or_none()
    password_hash = row.password_hash if row is not None else _DUMMY_PASSWORD_HASH
    if not verify_password(data.password, password_hash) or row is None:
        record_failed_login_attempt(request, data.email)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")
    return TokenResponse(access_token=create_access_token(row.id, "admin"))


def logout(payload: dict) -> dict[str, str]:
    """Denylist the presented token until its own expiry. Shared by all three
    login pools (internal admin, prod admin, user) — the token's own claims
    carry everything needed, so the pool doesn't matter."""
    jti = payload.get("jti")
    exp = payload.get("exp")
    if isinstance(jti, str) and isinstance(exp, int):
        revoke_token(jti, exp)
    return {"status": "ok"}


def get_admin_out(admin_id: uuid.UUID, db: Session) -> AdminOut:
    """Load the safe `/me` projection of an admin (no password hash / scope)."""
    admin = db.scalar(
        select(Admin)
        .options(
            load_only(
                Admin.id, Admin.email, Admin.full_name, Admin.created_at, Admin.updated_at
            )
        )
        .where(Admin.id == admin_id)
    )
    if admin is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Admin not found")
    return admin
