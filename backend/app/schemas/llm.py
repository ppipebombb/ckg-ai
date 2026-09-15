import ipaddress
import socket
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated
from urllib.parse import urlparse

from pydantic import AfterValidator, BaseModel, ConfigDict, model_validator

# base_url is fetched server-side via urllib (llm_chat.chat_complete), so an
# unvalidated value is SSRF: file:// reads local files, http://169.254.169.254
# hits cloud metadata, http://10.x reaches the intranet. Restrict to public
# http(s) endpoints.
_LLM_BLOCKED_HOSTS = frozenset({"localhost", "metadata", "metadata.google.internal"})
_LLM_INTERNAL_SUFFIXES = (
    ".local", ".localhost", ".internal", ".intranet", ".lan",
    ".home", ".corp", ".test", ".example", ".invalid",
)


def _host_to_ip(host: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    """Resolve a host string to an IP *literal* if it is one, defeating the
    classic SSRF-filter bypasses. ``ipaddress.ip_address`` only accepts canonical
    dotted/colon forms, but the resolver (glibc in the runtime image) also accepts
    legacy IPv4 encodings — decimal ``2130706433``, octal ``0177.0.0.1``, hex
    ``0x7f000001``, short ``127.1`` — all of which mean 127.0.0.1. ``inet_aton``
    normalizes every one of those. Returns None for real hostnames."""
    try:
        return ipaddress.ip_address(host)
    except ValueError:
        pass
    try:
        return ipaddress.IPv4Address(socket.inet_aton(host))
    except (OSError, ValueError):
        return None


def _is_blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    candidates = [ip]
    mapped = getattr(ip, "ipv4_mapped", None)  # ::ffff:127.0.0.1 → 127.0.0.1
    if mapped is not None:
        candidates.append(mapped)
    return any(
        c.is_private or c.is_loopback or c.is_link_local
        or c.is_reserved or c.is_multicast or c.is_unspecified
        for c in candidates
    )


def _validate_llm_base_url(v: str) -> str:
    parsed = urlparse(v)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("base_url must be an http(s) URL (with scheme)")
    host = (parsed.hostname or "").lower()
    if not host:
        raise ValueError("base_url must include a host")
    ip = _host_to_ip(host)
    if ip is not None:
        if _is_blocked_ip(ip):
            raise ValueError("base_url must not point at a private or reserved IP address")
    elif host in _LLM_BLOCKED_HOSTS or host.endswith(_LLM_INTERNAL_SUFFIXES):
        raise ValueError("base_url must not point at an internal/reserved hostname")
    return v


LlmBaseUrl = Annotated[str, AfterValidator(_validate_llm_base_url)]


def _enforce_2dp(v: Decimal | None) -> Decimal | None:
    if v is None:
        return v
    if not v.is_finite():
        raise ValueError("must be a finite number")
    if v < 0:
        raise ValueError("must be >= 0")
    if v.as_tuple().exponent < -2:
        raise ValueError("max 2 decimal places")
    return v.quantize(Decimal("0.01"))


UsdPrice = Annotated[Decimal | None, AfterValidator(_enforce_2dp)]


# Provider-agnostic reasoning effort, passed through to the endpoint VERBATIM
# (llm_chat maps it per model family). Free-form on purpose — accepted values
# differ by model: OpenAI low/medium/high/xhigh (+none/minimal on some), DeepSeek
# high/max, gpt-oss low/medium/high, etc. We do NOT allowlist (the Test-connection
# button is how you verify a value is accepted); we only trim, treat empty as
# "omit", and cap to the column width. Case is preserved (gateways may be
# case-sensitive).
_REASONING_EFFORT_MAX_LEN = 16


def _validate_reasoning_effort(v: str | None) -> str | None:
    if v is None:
        return None
    s = v.strip()
    if s == "":
        return None
    if len(s) > _REASONING_EFFORT_MAX_LEN:
        raise ValueError(
            f"reasoning_effort too long (max {_REASONING_EFFORT_MAX_LEN} chars)"
        )
    return s


ReasoningEffort = Annotated[str | None, AfterValidator(_validate_reasoning_effort)]


class LlmConfigCreate(BaseModel):
    provider: str = "openai"
    model: str
    base_url: LlmBaseUrl
    api_key: str
    is_active: bool = False
    is_active_captcha: bool = False
    is_active_chatbot: bool = False
    is_active_loop_agent: bool = False
    is_active_loop_reviewer: bool = False
    label: str | None = None
    reasoning_effort: ReasoningEffort = None
    route_order: str | None = None
    input_price_per_1m: UsdPrice = None
    output_price_per_1m: UsdPrice = None


class LlmConfigUpdate(BaseModel):
    provider: str | None = None
    model: str | None = None
    base_url: LlmBaseUrl | None = None
    api_key: str | None = None
    label: str | None = None
    reasoning_effort: ReasoningEffort = None
    route_order: str | None = None
    input_price_per_1m: UsdPrice = None
    output_price_per_1m: UsdPrice = None


class LlmConfigOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    provider: str
    model: str
    base_url: str
    is_active: bool
    is_active_captcha: bool
    is_active_chatbot: bool
    is_active_loop_agent: bool
    is_active_loop_reviewer: bool
    label: str | None
    reasoning_effort: str | None
    route_order: str | None
    input_price_per_1m: Decimal | None
    output_price_per_1m: Decimal | None
    created_at: datetime
    updated_at: datetime


class LlmConfigReveal(BaseModel):
    api_key: str


class LlmConfigTestIn(BaseModel):
    """Test an LLM endpoint without saving. Supply api_key for an inline/new
    config, or config_id to reuse a stored (encrypted) key — covers create
    (typed key), edit (stored key, blank field), and edit (new typed key)."""
    provider: str = "openai"
    model: str
    base_url: LlmBaseUrl
    reasoning_effort: ReasoningEffort = None
    route_order: str | None = None
    api_key: str | None = None
    config_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def _need_key_or_id(self) -> "LlmConfigTestIn":
        if not (self.api_key and self.api_key.strip()) and self.config_id is None:
            raise ValueError("provide api_key or config_id")
        return self


class LlmConfigTestOut(BaseModel):
    ok: bool
    model: str
    latency_ms: int | None = None
    reply: str | None = None
    error: str | None = None


class LlmLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    llm_config_id: uuid.UUID
    scrape_job_id: uuid.UUID | None
    merge_job_id: uuid.UUID | None = None
    patient_id: uuid.UUID | None = None
    puskesmas_id: uuid.UUID | None = None
    source: str
    model: str
    input_tokens: int | None
    output_tokens: int | None
    reasoning_tokens: int | None
    total_tokens: int | None
    prompt_cost: Decimal | None
    completion_cost: Decimal | None
    total_cost: Decimal | None
    latency_ms: int | None
    success: bool
    error: str | None
    created_at: datetime
    superseded_by_success: bool = False


class LlmLogRetryMergeIn(BaseModel):
    log_ids: list[uuid.UUID]


class LlmLogRetryMergeOut(BaseModel):
    triggered: int
    skipped: int
    skipped_reasons: list[str]
    job_ids: list[uuid.UUID]


class LlmUsageBucket(BaseModel):
    bucket: datetime
    calls: int
    input_tokens: int
    output_tokens: int
    prompt_cost: Decimal | None
    completion_cost: Decimal | None
    total_cost: Decimal | None
