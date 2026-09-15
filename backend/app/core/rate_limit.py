import uuid
from functools import lru_cache

from fastapi import HTTPException, Request, status
from redis import Redis

from app.config import settings


@lru_cache(maxsize=1)
def _client() -> Redis:
    return Redis.from_url(settings.REDIS_URL, decode_responses=True)


def redis_client() -> Redis:
    """Public accessor for the singleton Redis client used by routes."""
    return _client()


def _client_ip(request: Request) -> str:
    """Resolve the real client IP for rate-limiting, accounting for trusted
    reverse proxies.

    Each trusted proxy appends exactly one entry to X-Forwarded-For, so the
    client IP is the ``TRUSTED_PROXY_COUNT``-th entry from the RIGHT. Reading
    from the right is un-spoofable: a client can prepend arbitrary entries but
    cannot push past the ones the proxies append. With 0 trusted proxies the
    header is ignored entirely and the socket peer is used (direct exposure).
    """
    n = settings.TRUSTED_PROXY_COUNT
    if n > 0:
        fwd = request.headers.get("x-forwarded-for")
        if fwd:
            parts = [p.strip() for p in fwd.split(",") if p.strip()]
            if len(parts) >= n:
                return parts[-n]
    return request.client.host if request.client else "unknown"


def _fixed_window_counts(keys: tuple[str, ...], window: int) -> tuple[int, ...]:
    # SET NX EX claims a TTL on first hit; INCR bumps the counter. Single
    # pipeline keeps both ops on the same connection so a failure between
    # them can never leave a counter without an expiry.
    pipe = _client().pipeline()
    for key in keys:
        pipe.set(key, 0, ex=window, nx=True)
        pipe.incr(key)
    results = pipe.execute()
    return tuple(int(results[i * 2 + 1]) for i in range(len(keys)))


def _login_rate_limit_keys(request: Request, email: str) -> tuple[str, str]:
    ip = _client_ip(request)
    return (f"rl:login:ip:{ip}", f"rl:login:email:{email.lower()}")


def enforce_login_rate_limit(request: Request, email: str) -> None:
    keys = _login_rate_limit_keys(request, email)
    values = _client().mget(keys)
    counts = [int(value) for value in values if value is not None]

    if counts and max(counts) >= settings.LOGIN_RATE_LIMIT_MAX:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Too many login attempts. Try again later.",
            headers={"Retry-After": str(settings.LOGIN_RATE_LIMIT_WINDOW_SECONDS)},
        )


def record_failed_login_attempt(request: Request, email: str) -> None:
    window = settings.LOGIN_RATE_LIMIT_WINDOW_SECONDS
    keys = _login_rate_limit_keys(request, email)

    counts = _fixed_window_counts(keys, window)

    if max(counts) > settings.LOGIN_RATE_LIMIT_MAX:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Too many login attempts. Try again later.",
            headers={"Retry-After": str(window)},
        )


DECRYPT_RATE_LIMIT_MAX = 30
DECRYPT_RATE_LIMIT_WINDOW_SECONDS = 60


def enforce_decrypt_rate_limit(
    principal_id: uuid.UUID, resource_id: uuid.UUID
) -> None:
    """Throttle decrypt-PII access per (principal, resource).

    Caller must already be authenticated. Resource-level cap protects against
    iteration over many resources by a compromised token.
    """
    window = DECRYPT_RATE_LIMIT_WINDOW_SECONDS
    pid_key = f"rl:decrypt:principal:{principal_id}"
    res_key = f"rl:decrypt:resource:{resource_id}"

    pid_count, res_count = _fixed_window_counts((pid_key, res_key), window)

    if pid_count > DECRYPT_RATE_LIMIT_MAX or res_count > DECRYPT_RATE_LIMIT_MAX:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Too many decrypt requests. Try again later.",
            headers={"Retry-After": str(window)},
        )


CONFLICTS_RATE_LIMIT_MAX = 30
CONFLICTS_RATE_LIMIT_WINDOW_SECONDS = 60


def enforce_conflicts_rate_limit(principal_id: uuid.UUID) -> None:
    """Throttle conflict-analysis reads per admin.

    Endpoint is expensive on cold cache (bulk decrypt + JSON walk) but
    returns no PII, so this is lighter than the decrypt-PII limit.
    """
    window = CONFLICTS_RATE_LIMIT_WINDOW_SECONDS
    pid_key = f"rl:conflicts:admin:{principal_id}"
    (count,) = _fixed_window_counts((pid_key,), window)
    if count > CONFLICTS_RATE_LIMIT_MAX:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Too many conflict-analysis requests. Try again later.",
            headers={"Retry-After": str(window)},
        )


LLM_TEST_RATE_LIMIT_MAX = 10
LLM_TEST_RATE_LIMIT_WINDOW_SECONDS = 60


def enforce_llm_test_rate_limit(principal_id: uuid.UUID) -> None:
    """Throttle LLM test-connection calls per admin.

    Each test decrypts a stored key and makes a real (billable) LLM call, so
    cap it like the chatbot — enough for iterating on a config, not for abuse.
    """
    window = LLM_TEST_RATE_LIMIT_WINDOW_SECONDS
    pid_key = f"rl:llmtest:admin:{principal_id}"
    (count,) = _fixed_window_counts((pid_key,), window)
    if count > LLM_TEST_RATE_LIMIT_MAX:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Too many test-connection requests. Try again later.",
            headers={"Retry-After": str(window)},
        )


CHATBOT_RATE_LIMIT_MAX = 10
CHATBOT_RATE_LIMIT_WINDOW_SECONDS = 60


def enforce_chatbot_rate_limit(principal_id: uuid.UUID) -> None:
    """Throttle explainer-chatbot calls per admin.

    Each call hits the LLM (token cost + latency), so cap it tighter than the
    read-only dashboard limits. Indonesian message — it surfaces verbatim in the
    frontend-dashboard chat widget.
    """
    window = CHATBOT_RATE_LIMIT_WINDOW_SECONDS
    pid_key = f"rl:chatbot:admin:{principal_id}"
    (count,) = _fixed_window_counts((pid_key,), window)
    if count > CHATBOT_RATE_LIMIT_MAX:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Terlalu banyak permintaan ke asisten. Coba lagi sebentar.",
            headers={"Retry-After": str(window)},
        )
