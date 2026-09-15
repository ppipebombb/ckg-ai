"""Unit tests for provider-agnostic reasoning_effort payload assembly.

Verifies _build_chat_payload maps a single normalized reasoning_effort to each
model family's wire param and omits it where unsupported. Pure — no network.
"""
from app.integrations.llm_chat import _build_chat_payload


def _payload(model, *, reasoning_effort=None, thinking=None, max_tokens=100):
    return _build_chat_payload(
        "openai", None, model, "hi", max_tokens, None,
        reasoning_effort, None, thinking, False,
    )


def test_gpt_oss_always_sets_reasoning_effort():
    assert _payload("openai/gpt-oss-120b", reasoning_effort="high")["reasoning_effort"] == "high"
    # gpt-oss defaults to medium when none configured
    assert _payload("openai/gpt-oss-120b")["reasoning_effort"] == "medium"


def test_openai_reasoning_model_branch():
    p = _payload("o3", reasoning_effort="low")
    assert p["reasoning_effort"] == "low"
    # reasoning models use max_completion_tokens and omit temperature
    assert "max_completion_tokens" in p and "max_tokens" not in p
    assert "temperature" not in p
    # without an effort, none is emitted (unchanged behavior)
    assert "reasoning_effort" not in _payload("gpt-5")


def test_plain_chat_model_omits_reasoning():
    p = _payload("gpt-4o", reasoning_effort="high")
    assert "reasoning_effort" not in p
    assert p["temperature"] == 0
    assert p["max_tokens"] == 100


def test_deepseek_thinking_follows_effort():
    on = _payload("deepseek-v4-flash", reasoning_effort="medium")
    assert on["thinking"] == {"type": "enabled"} and on["reasoning_effort"] == "medium"
    # explicit thinking=True still enabled even without an effort (chatbot path)
    assert _payload("deepseek-v4-flash", thinking=True)["thinking"] == {"type": "enabled"}
    # no effort + no thinking -> disabled (merge's deterministic default)
    off = _payload("deepseek-v4-flash")
    assert off["thinking"] == {"type": "disabled"} and "reasoning_effort" not in off
