"""Server-side JWT revocation backed by Redis.

JWTs are stateless, so a stolen or to-be-invalidated token would otherwise stay
valid until its ``exp``. Two revocation mechanisms close that gap, both checked
once in ``app.api.deps._decode`` (the single auth chokepoint for every request):

* **Per-token denylist (logout)** — a token's ``jti`` is stored until its own
  ``exp``; presenting it again is rejected.
* **Per-principal cutoff (password change / force-logout-all)** — a timestamp is
  stored; any token whose ``iat`` predates it is rejected. This invalidates every
  token a principal holds, not just one session.

Both checks **fail open** on a Redis error: a transient Redis outage must not
lock every user out. The residual risk is narrow — it only matters in the window
where Redis is down *and* an already-revoked token is being replayed.
"""

import uuid
from datetime import UTC, datetime

from app.config import settings
from app.core.rate_limit import redis_client

_DENY_PREFIX = "jwt:bl:"  # bl:<jti>           -> "1"  (single-token logout)
_CUTOFF_PREFIX = "jwt:rb:"  # rb:<typ>:<sub>   -> issued-at cutoff (revoke-all)


def _now_ts() -> int:
    return int(datetime.now(UTC).timestamp())


def revoke_token(jti: str, exp_ts: int) -> None:
    """Denylist a single token until its own expiry (logout)."""
    ttl = max(1, exp_ts - _now_ts())
    try:
        redis_client().set(f"{_DENY_PREFIX}{jti}", "1", ex=ttl)
    except Exception:
        pass


def revoke_all_for(principal_type: str, principal_id: uuid.UUID) -> None:
    """Invalidate every existing token for one principal (password change /
    account deletion). Tokens issued at or after now stay valid."""
    # Live at least as long as the longest-lived token could.
    ttl = settings.ACCESS_TOKEN_TTL_MINUTES * 60 + 60
    try:
        redis_client().set(f"{_CUTOFF_PREFIX}{principal_type}:{principal_id}", _now_ts(), ex=ttl)
    except Exception:
        pass


def is_revoked(payload: dict) -> bool:
    """True if the decoded token has been logged out or cut off. One Redis
    round-trip (MGET of both keys). Fails open on any Redis error."""
    jti = payload.get("jti")
    typ = payload.get("typ")
    sub = payload.get("sub")
    iat = payload.get("iat")

    deny_key = f"{_DENY_PREFIX}{jti}" if jti else None
    cutoff_key = f"{_CUTOFF_PREFIX}{typ}:{sub}" if (typ and sub) else None
    keys = [k for k in (deny_key, cutoff_key) if k]
    if not keys:
        return False

    try:
        values = dict(zip(keys, redis_client().mget(keys), strict=True))
    except Exception:
        return False

    if deny_key and values.get(deny_key) is not None:
        return True
    if cutoff_key and isinstance(iat, int):
        cutoff = values.get(cutoff_key)
        if cutoff is not None:
            try:
                return iat < int(cutoff)
            except (TypeError, ValueError):
                return False
    return False
