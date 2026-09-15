"""Test fixtures.

Required settings are stubbed into the environment BEFORE app import so
``Settings()`` (instantiated at ``app.config`` import time) succeeds without a
real ``.env``. The summary tests run fully offline (mocked DB + stub redis); the
login-partition tests use a real Postgres and self-skip when one isn't reachable.
"""

import os

from cryptography.fernet import Fernet

os.environ.setdefault(
    "DATABASE_URL", "postgresql+psycopg://ckg:ckg@localhost:5432/ckg_test"
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("ADMIN_EMAIL", "admin@test.com")
os.environ.setdefault("ADMIN_PASSWORD", "Admin123!")
os.environ.setdefault("ADMIN_FULL_NAME", "Root Admin")
os.environ.setdefault("JWT_SECRET", "test-secret-key")
os.environ.setdefault("CRED_ENCRYPTION_KEY", Fernet.generate_key().decode())

import uuid  # noqa: E402
from unittest.mock import MagicMock  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.api.deps import (  # noqa: E402
    Principal,
    get_dashboard_principal,
    get_db,
)
from app.main import app  # noqa: E402


class StubRedis:
    """Minimal in-memory stand-in for the redis client used by the summary routes."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    def get(self, key):
        return self.store.get(key)

    def mget(self, keys):
        return [self.store.get(k) for k in keys]

    def set(self, key, value, **_kwargs):
        self.store[key] = value
        return True

    def delete(self, *keys):
        for k in keys:
            self.store.pop(k, None)


@pytest.fixture
def stub_redis():
    return StubRedis()


@pytest.fixture
def warm_calls():
    return []


@pytest.fixture
def summary_client(monkeypatch, stub_redis, warm_calls):
    """TestClient for the dashboard/summary endpoints with the DB existence-check
    mocked (puskesmas exists), an admin principal, a stub redis, and request_warm
    recorded instead of enqueuing a Celery task. Returns (client, puskesmas_id)."""
    pid = uuid.uuid4()

    fake_db = MagicMock()
    fake_db.scalar.return_value = pid  # Puskesmas.id exists

    app.dependency_overrides[get_db] = lambda: fake_db
    # Summary/terkendali endpoints authenticate via get_dashboard_principal
    # (the prod-allowlisted dep), so override that one.
    app.dependency_overrides[get_dashboard_principal] = lambda: Principal(
        "admin", uuid.uuid4(), None
    )

    import app.api.routes.gdp_report as gdp

    monkeypatch.setattr(gdp, "redis_client", lambda: stub_redis)
    monkeypatch.setattr(
        gdp,
        "request_warm",
        lambda rc, cache_key, report_type, kwargs: warm_calls.append(
            (cache_key, report_type)
        ),
    )

    with TestClient(app) as client:
        yield client, pid

    app.dependency_overrides.clear()
