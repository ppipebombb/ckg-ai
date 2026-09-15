"""Endpoint test for POST /llm-configs/test.

Confirms the diagnostic contract: HTTP 200 for BOTH a good config (ok=true +
reply) and a reachable-but-broken one (ok=false + error). chat_complete and the
rate limiter are monkeypatched on the route module; with an inline api_key the
handler never touches the DB.
"""
import uuid

import pytest
from fastapi.testclient import TestClient

import app.api.routes.llm as llm_routes
from app.api.deps import get_current_admin_id, get_db
from app.integrations.llm_chat import ChatResult
from app.main import app

_BODY = {
    "provider": "openai",
    "model": "gpt-4o",
    "base_url": "https://api.openai.com/v1",
    "api_key": "sk-test",
}


@pytest.fixture
def client(monkeypatch):
    app.dependency_overrides[get_current_admin_id] = lambda: uuid.uuid4()
    app.dependency_overrides[get_db] = lambda: None  # unused with inline api_key
    monkeypatch.setattr(llm_routes, "enforce_llm_test_rate_limit", lambda *_a, **_k: None)
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_ok(client, monkeypatch):
    monkeypatch.setattr(
        llm_routes, "chat_complete",
        lambda **_k: ChatResult(
            text="OK", input_tokens=1, output_tokens=1, total_tokens=2,
            reasoning_tokens=None, latency_ms=12,
        ),
    )
    r = client.post("/llm-configs/test", json=_BODY)
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["reply"] == "OK"
    assert body["latency_ms"] == 12


def test_failure_returns_200_with_error(client, monkeypatch):
    def _boom(**_k):
        raise RuntimeError("LLM HTTP 530: origin is unreachable")

    monkeypatch.setattr(llm_routes, "chat_complete", _boom)
    r = client.post("/llm-configs/test", json=_BODY)
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert "530" in body["error"]


def test_empty_reply_is_failure(client, monkeypatch):
    monkeypatch.setattr(
        llm_routes, "chat_complete",
        lambda **_k: ChatResult(
            text="   ", input_tokens=1, output_tokens=0, total_tokens=1,
            reasoning_tokens=None, latency_ms=5,
        ),
    )
    r = client.post("/llm-configs/test", json=_BODY)
    assert r.status_code == 200
    assert r.json()["ok"] is False


def test_missing_key_and_id_is_422(client):
    body = {k: v for k, v in _BODY.items() if k != "api_key"}
    r = client.post("/llm-configs/test", json=body)
    assert r.status_code == 422
