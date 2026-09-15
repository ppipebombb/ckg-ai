import json
import uuid
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Any, Literal

import bcrypt
import jwt
from cryptography.fernet import Fernet

from app.config import settings

PrincipalType = Literal["admin", "user"]

BCRYPT_MAX_BYTES = 72


def _encode(password: str) -> bytes:
    encoded = password.encode("utf-8")
    if len(encoded) > BCRYPT_MAX_BYTES:
        raise ValueError(
            f"password exceeds bcrypt {BCRYPT_MAX_BYTES}-byte limit "
            f"(got {len(encoded)} bytes)"
        )
    return encoded


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(_encode(plain), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(_encode(plain), hashed.encode("utf-8"))
    except ValueError:
        return False


def create_access_token(subject: uuid.UUID, principal_type: PrincipalType) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": str(subject),
        "typ": principal_type,
        # Unique token id — enables single-token revocation (logout) via the
        # Redis denylist in app.core.token_revocation.
        "jti": uuid.uuid4().hex,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.ACCESS_TOKEN_TTL_MINUTES)).timestamp()),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any]:
    return jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])


@lru_cache(maxsize=1)
def _fernet() -> Fernet:
    return Fernet(settings.CRED_ENCRYPTION_KEY.encode("utf-8"))


def encrypt_cred(data: dict[str, str]) -> bytes:
    return _fernet().encrypt(json.dumps(data, separators=(",", ":")).encode("utf-8"))


def decrypt_cred(token: bytes) -> dict[str, str]:
    return json.loads(_fernet().decrypt(token).decode("utf-8"))


def encrypt_json(data: Any) -> bytes:
    return _fernet().encrypt(json.dumps(data, separators=(",", ":"), default=str).encode("utf-8"))


def decrypt_json(token: bytes) -> Any:
    return json.loads(_fernet().decrypt(bytes(token)).decode("utf-8"))
