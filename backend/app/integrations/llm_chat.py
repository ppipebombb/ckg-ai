"""Chat-completion helper using stdlib urllib (no SDK deps).

Targets OpenAI-compatible `/chat/completions` endpoints. The same wire format
is exposed by OpenAI, Groq, OpenRouter, DeepSeek, vLLM, Ollama (OpenAI-compat
mode), and most third-party gateways. `provider` is currently informational —
all dispatch routes through the chat-completions path. Add branches here if a
provider that doesn't speak this wire format is required.
"""
import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass


@dataclass
class ChatResult:
    text: str
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    reasoning_tokens: int | None
    latency_ms: int
    # OpenAI-compat: "stop" | "length" | "content_filter" | "tool_calls" | None.
    # "length" means the model hit max_tokens — output is truncated and any
    # downstream JSON parse will fail. Merge retry uses this to decide whether
    # bumping max_tokens has a chance of helping.
    finish_reason: str | None = None


_DEFAULT_BASE_URL = "https://api.openai.com/v1"
_TIMEOUT_SECONDS = 300
# Transient transport-failure retry (DNS/connection/timeout — no token spend).
_TRANSPORT_MAX_ATTEMPTS = 3
_TRANSPORT_BACKOFF_SECONDS = 1.5
# HTTP statuses worth retrying: gateway/server-side and rate-limit. None of
# these return a completion, so no tokens are billed and the same call may
# succeed moments later. 5xx incl. Cloudflare 520/522/524; 429 = rate limit.
_RETRYABLE_HTTP_STATUS = frozenset({429, 500, 502, 503, 504, 520, 522, 524})


def chat_complete(
    *,
    provider: str,
    base_url: str,
    api_key: str,
    model: str,
    prompt: str,
    max_tokens: int | None = None,
    response_format: dict | None = None,
    reasoning_effort: str | None = None,
    messages: list[dict] | None = None,
    thinking: bool | None = None,
    route_order: str | None = None,
) -> ChatResult:
    # When `messages` is given (e.g. the chatbot's system + history + user turn)
    # it is sent verbatim, giving the model a real system-role instruction
    # hierarchy. When it is None the legacy single-user-message path is used
    # (merge / captcha callers) — kept byte-identical.
    # `thinking` opts a DeepSeek model into reasoning mode (default off, so merge
    # stays deterministic); ignored for non-DeepSeek models.
    return _openai_compat_chat(
        provider, base_url, api_key, model, prompt, max_tokens, response_format,
        reasoning_effort, messages, thinking, route_order,
    )


_BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def _is_riset(provider: str) -> bool:
    # Match "riset", "riset.ai", "riset_ai", etc. so config-storage variants
    # don't silently miss the provider quirks (api-key header, browser UA, streaming).
    return (provider or "").strip().lower().startswith("riset")


def _auth_headers(provider: str, api_key: str) -> dict[str, str]:
    # riset.ai uses a custom `api-key` header instead of Bearer auth.
    if _is_riset(provider):
        return {"api-key": api_key}
    return {"Authorization": f"Bearer {api_key}"}


def _extra_headers(provider: str) -> dict[str, str]:
    # Always send a browser UA: any Cloudflare-fronted OpenAI-compat gateway
    # (riset.ai, ocr.juxtalabs.io, …) rejects the default Python-urllib UA with
    # CF 1010 / HTTP 403. Harmless to the real OpenAI API, which ignores UA.
    return {"User-Agent": _BROWSER_UA, "Accept": "application/json"}


def _wants_streaming(provider: str, base_url: str | None) -> bool:
    # Cloudflare-fronted gateways enforce a 120s origin-read timeout — any
    # single response that takes longer 524s. Big merge prompts + local /
    # reasoning models routinely cross that line. Streaming keeps bytes
    # flowing so CF doesn't kill the connection.
    # Known CF-fronted gateways: riset.ai (provider name), and every
    # *.juxtalabs.io endpoint (local.juxtalabs.io = gpt-oss-20b,
    # ocr.juxtalabs.io = captcha/OCR models). Match base_url for the latter
    # since their provider field is the generic "openai".
    if _is_riset(provider):
        return True
    return ".juxtalabs.io" in (base_url or "").lower()


def _is_openai_reasoning_model(model: str) -> bool:
    # gpt-5.x / o1 / o3 / o4 reject `max_tokens` (require `max_completion_tokens`)
    # and only accept the default temperature (1).
    m = (model or "").strip().lower()
    return m.startswith(("gpt-5", "o1", "o3", "o4"))


def _is_deepseek(model: str) -> bool:
    return (model or "").strip().lower().startswith("deepseek")


def _is_gpt_oss(model: str) -> bool:
    # openai/gpt-oss-20b (local.juxtalabs.io) and any gpt-oss-* variant.
    return "gpt-oss" in (model or "").strip().lower()


def _build_chat_payload(
    provider: str,
    base_url: str | None,
    model: str,
    prompt: str,
    max_tokens: int | None,
    response_format: dict | None,
    reasoning_effort: str | None,
    messages: list[dict] | None,
    thinking: bool | None,
    stream: bool,
    route_order: str | None = None,
) -> dict:
    """Assemble the OpenAI-compatible /chat/completions request body.

    Provider quirks are selected by MODEL-prefix sniffing (not the provider
    string), so a single normalized ``reasoning_effort`` maps to whatever each
    model family expects and is omitted for models that don't support it. Pure
    and side-effect-free so it can be unit-tested without the network.
    """
    is_reasoning = _is_openai_reasoning_model(model)
    # riset.ai rejects temperature == 0; near-zero keeps output near-deterministic.
    temperature = 0.01 if _is_riset(provider) else 0
    payload: dict = {
        "model": model,
        "messages": messages if messages is not None else [{"role": "user", "content": prompt}],
    }
    # gpt-5/o1/o3 only accept default temperature (1) — omit the field entirely.
    if not is_reasoning:
        payload["temperature"] = temperature
    if max_tokens is not None:
        # gpt-5/o1/o3 require `max_completion_tokens`; everything else uses
        # `max_tokens`. Caller supplies the per-model cap.
        key = "max_completion_tokens" if is_reasoning else "max_tokens"
        payload[key] = max_tokens
    if response_format is not None:
        # OpenAI `{"type":"json_object"}` enables constrained decoding. Many
        # OpenAI-compat gateways accept/ignore unknown values; caller must also
        # have the word "json" in the prompt (OpenAI 400s otherwise).
        payload["response_format"] = response_format
    if _is_deepseek(model):
        # DeepSeek v4 (and deepseek-chat/-reasoner aliases) default to thinking
        # mode, spending a reasoning_content budget before the answer. Enable it
        # when the caller asks (thinking=True) OR when a reasoning_effort is
        # configured — so a config-driven effort actually takes effect for a
        # DeepSeek config. Merge passes thinking=None + no effort → disabled
        # (deterministic JSON, no truncation). DeepSeek-only: other gateways 400
        # on an unknown `thinking` field.
        want_thinking = bool(thinking) or bool(reasoning_effort)
        payload["thinking"] = {"type": "enabled" if want_thinking else "disabled"}
        if want_thinking and reasoning_effort:
            payload["reasoning_effort"] = reasoning_effort
    elif _is_gpt_oss(model):
        # gpt-oss (harmony format) spends output tokens on a reasoning channel
        # BEFORE the JSON answer. Default to "medium"; caller/config may override.
        # vLLM on local.juxtalabs.io honours OpenAI-compat reasoning_effort.
        payload["reasoning_effort"] = reasoning_effort or "medium"
    elif is_reasoning and reasoning_effort:
        # OpenAI reasoning models accept reasoning_effort (low/medium/high, plus
        # none/minimal/xhigh depending on the model). Passed through verbatim;
        # only sent when the config sets one, so blank configs are unchanged.
        payload["reasoning_effort"] = reasoning_effort
    if stream:
        payload["stream"] = True
        # OpenAI-compat: ask the server to emit a final usage chunk.
        payload["stream_options"] = {"include_usage": True}
    if route_order:
        # OpenRouter provider routing lock: pin the upstream (comma-separated
        # slug list, e.g. "z-ai") and forbid fallbacks. Other gateways may
        # reject the unknown `provider` body field — an operator sets this only
        # on configs whose endpoint accepts it, verified via Test-connection.
        payload["provider"] = {
            "order": [x.strip() for x in route_order.split(",") if x.strip()],
            "allow_fallbacks": False,
        }
    return payload


def _openai_compat_chat(
    provider: str,
    base_url: str,
    api_key: str,
    model: str,
    prompt: str,
    max_tokens: int | None = None,
    response_format: dict | None = None,
    reasoning_effort: str | None = None,
    messages: list[dict] | None = None,
    thinking: bool | None = None,
    route_order: str | None = None,
) -> ChatResult:
    url = f"{(base_url or _DEFAULT_BASE_URL).rstrip('/')}/chat/completions"
    stream = _wants_streaming(provider, base_url)
    payload = _build_chat_payload(
        provider, base_url, model, prompt, max_tokens, response_format,
        reasoning_effort, messages, thinking, stream, route_order,
    )
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            **_auth_headers(provider, api_key),
            **_extra_headers(provider),
        },
    )

    # Transport / transient-HTTP retry. Anything that returns no completion
    # costs no tokens, so a transient blip shouldn't permanently fail the
    # caller. Two failure families, retried up to _TRANSPORT_MAX_ATTEMPTS:
    #   * OSError — subsumes URLError (DNS / TLS / connection-refused),
    #     TimeoutError (read timeout), and ConnectionError /
    #     RemoteDisconnected (peer dropped before/mid response).
    #   * HTTPError with a status in _RETRYABLE_HTTP_STATUS (5xx gateway /
    #     server, 429 rate-limit). Any other HTTP status (401/403/400/404…)
    #     is a request-level error the same call won't fix — fail fast.
    # HTTPError is a subclass of OSError, so its handler MUST come first.
    raw = ""
    t0 = time.monotonic()
    for _attempt in range(1, _TRANSPORT_MAX_ATTEMPTS + 1):
        t0 = time.monotonic()
        try:
            with urllib.request.urlopen(req, timeout=_TIMEOUT_SECONDS) as resp:
                if stream:
                    try:
                        return _consume_stream(resp, t0)
                    except (urllib.error.URLError, OSError) as exc:
                        raise RuntimeError(f"LLM stream error: {exc}") from exc
                raw = resp.read().decode("utf-8")
            break
        except urllib.error.HTTPError as exc:
            if exc.code in _RETRYABLE_HTTP_STATUS and _attempt < _TRANSPORT_MAX_ATTEMPTS:
                time.sleep(_TRANSPORT_BACKOFF_SECONDS * _attempt)
                continue
            detail = exc.read().decode("utf-8", errors="replace")[:1000]
            raise RuntimeError(f"LLM HTTP {exc.code}: {detail}") from exc
        except OSError:
            if _attempt < _TRANSPORT_MAX_ATTEMPTS:
                time.sleep(_TRANSPORT_BACKOFF_SECONDS * _attempt)
                continue
            raise
    latency_ms = int((time.monotonic() - t0) * 1000)

    data = json.loads(raw)
    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError(f"LLM returned no choices: {raw[:500]}")
    text = (choices[0].get("message") or {}).get("content") or ""
    text = text.strip()
    finish_reason = choices[0].get("finish_reason")

    usage = data.get("usage") or {}
    in_tok = usage.get("prompt_tokens")
    out_tok = usage.get("completion_tokens")
    total = usage.get("total_tokens")
    reasoning = None
    details = usage.get("completion_tokens_details") or {}
    if isinstance(details, dict):
        reasoning = details.get("reasoning_tokens")

    return ChatResult(
        text=text,
        input_tokens=in_tok if isinstance(in_tok, int) else None,
        output_tokens=out_tok if isinstance(out_tok, int) else None,
        total_tokens=total if isinstance(total, int) else None,
        reasoning_tokens=reasoning if isinstance(reasoning, int) else None,
        latency_ms=latency_ms,
        finish_reason=finish_reason if isinstance(finish_reason, str) else None,
    )


def _consume_stream(resp, t0: float) -> ChatResult:
    """Consume an OpenAI-compatible SSE stream and accumulate the final ChatResult."""
    text_parts: list[str] = []
    in_tok: int | None = None
    out_tok: int | None = None
    total: int | None = None
    reasoning: int | None = None
    finish_reason: str | None = None

    for raw_line in resp:
        line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
        if not line or not line.startswith("data:"):
            continue
        data_str = line[5:].lstrip()
        if data_str == "[DONE]":
            break
        try:
            chunk = json.loads(data_str)
        except json.JSONDecodeError:
            continue

        for choice in chunk.get("choices") or []:
            delta = choice.get("delta") or {}
            content = delta.get("content")
            if isinstance(content, str):
                text_parts.append(content)
            fr = choice.get("finish_reason")
            if isinstance(fr, str):
                finish_reason = fr

        usage = chunk.get("usage")
        if isinstance(usage, dict):
            in_tok = usage.get("prompt_tokens") if isinstance(usage.get("prompt_tokens"), int) else in_tok
            out_tok = usage.get("completion_tokens") if isinstance(usage.get("completion_tokens"), int) else out_tok
            total = usage.get("total_tokens") if isinstance(usage.get("total_tokens"), int) else total
            details = usage.get("completion_tokens_details") or {}
            if isinstance(details, dict) and isinstance(details.get("reasoning_tokens"), int):
                reasoning = details["reasoning_tokens"]

    latency_ms = int((time.monotonic() - t0) * 1000)
    text = "".join(text_parts).strip()
    if not text:
        raise RuntimeError("LLM stream produced no content")
    return ChatResult(
        text=text,
        input_tokens=in_tok,
        output_tokens=out_tok,
        total_tokens=total,
        reasoning_tokens=reasoning,
        latency_ms=latency_ms,
        finish_reason=finish_reason,
    )
