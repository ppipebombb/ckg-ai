import uuid
from collections.abc import Iterator
from typing import Literal, NamedTuple

import jwt
from fastapi import Depends, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import decode_access_token
from app.core.token_revocation import is_revoked
from app.database import SessionLocal
from app.models.admin import Admin
from app.models.user import User

bearer_scheme = HTTPBearer(auto_error=True)


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _decode(creds: HTTPAuthorizationCredentials) -> dict:
    try:
        payload = decode_access_token(creds.credentials)
    except jwt.ExpiredSignatureError as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token expired") from e
    except jwt.InvalidTokenError as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token") from e
    # Single revocation chokepoint: every auth dep funnels through _decode, so
    # checking here covers admins, users, prod admins, and SSE-via-query alike.
    if is_revoked(payload):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token revoked")
    return payload


def get_token_payload(
    creds: HTTPAuthorizationCredentials = Depends(bearer_scheme),
) -> dict:
    """Verified token claims for the current request. Used by logout endpoints
    to denylist exactly the presented token (any valid principal type)."""
    return _decode(creds)


def _admin_id_with_scope(
    creds: HTTPAuthorizationCredentials, db: Session, *, scope: str | None
) -> uuid.UUID:
    """Resolve an admin token to its id, optionally requiring a login scope.

    A concrete ``scope`` ("internal"/"prod") is the DEFAULT-DENY path: a token
    from the other pool matches no row → 401, keeping the endpoint single-pool.
    ``scope=None`` accepts any admin and is reserved for the read-only dashboard
    endpoints the external frontend-dashboard app is explicitly allowlisted for.

    Existence is re-checked every request (soft-deleted admins auto-filtered);
    folding scope into that same query adds no extra round-trip.
    """
    payload = _decode(creds)
    if payload.get("typ") != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin token required")
    admin_id = uuid.UUID(payload["sub"])
    stmt = select(Admin.id).where(Admin.id == admin_id)
    if scope is not None:
        stmt = stmt.where(Admin.scope == scope)
    if db.scalar(stmt) is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Admin not found")
    return admin_id


def get_current_admin_id(
    creds: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> uuid.UUID:
    """Internal-admin-only — the default for every management / mutation
    endpoint. A prod-pool token is rejected (default-deny)."""
    return _admin_id_with_scope(creds, db, scope="internal")


def get_current_prod_admin_id(
    creds: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> uuid.UUID:
    """Only accepts scope="prod" admins (the frontend-dashboard login pool). Used for
    the /prod/auth/me session check."""
    return _admin_id_with_scope(creds, db, scope="prod")


def get_current_internal_admin_id(
    creds: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> uuid.UUID:
    """Only accepts scope="internal" admins. Used for the /admin/auth/me session
    check so a prod-pool token can't establish a session in the internal app."""
    return _admin_id_with_scope(creds, db, scope="internal")


def get_dashboard_admin_id(
    creds: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> uuid.UUID:
    """Accepts ANY admin scope (internal OR prod). ONLY for the read-only
    dashboard endpoints frontend-dashboard is allowlisted for (puskesmas list/detail,
    conflict summary). Never use on a mutation / management endpoint."""
    return _admin_id_with_scope(creds, db, scope=None)


def get_current_user_id(
    creds: HTTPAuthorizationCredentials = Depends(bearer_scheme),
) -> uuid.UUID:
    payload = _decode(creds)
    if payload.get("typ") != "user":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "User token required")
    return uuid.UUID(payload["sub"])


class Principal(NamedTuple):
    typ: Literal["admin", "user"]
    id: uuid.UUID
    puskesmas_id: uuid.UUID | None


def _principal_from_payload(
    payload: dict, db: Session, *, allow_prod: bool
) -> Principal:
    typ = payload.get("typ")
    sub = uuid.UUID(payload["sub"])
    if typ == "admin":
        stmt = select(Admin.id).where(Admin.id == sub)
        if not allow_prod:
            # Default-deny: a prod-pool admin token resolves to not-found on
            # every endpoint except the allowlisted read-only dashboards.
            stmt = stmt.where(Admin.scope == "internal")
        if db.scalar(stmt) is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Admin not found")
        return Principal(typ="admin", id=sub, puskesmas_id=None)
    if typ == "user":
        puskesmas_id = db.scalar(select(User.puskesmas_id).where(User.id == sub))
        if puskesmas_id is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found")
        return Principal(typ="user", id=sub, puskesmas_id=puskesmas_id)
    raise HTTPException(status.HTTP_403_FORBIDDEN, "Invalid token type")


def get_principal(
    creds: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> Principal:
    """Internal admin or puskesmas user. Default-deny for prod-pool admins."""
    return _principal_from_payload(_decode(creds), db, allow_prod=False)


def get_principal_from_query(
    token: str = Query(..., description="JWT access token (for SSE/EventSource clients)"),
    db: Session = Depends(get_db),
) -> Principal:
    """SSE/EventSource variant of get_principal (internal admin or user)."""
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    return _principal_from_payload(_decode(creds), db, allow_prod=False)


def get_dashboard_principal(
    creds: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> Principal:
    """Internal OR prod admin, or puskesmas user. ONLY for the read-only
    dashboard endpoints frontend-dashboard is allowlisted for."""
    return _principal_from_payload(_decode(creds), db, allow_prod=True)
