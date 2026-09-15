"""Tests for GET /report-dashboards/totals (the per-puskesmas 'total pasien' card).

Runs fully offline: the puskesmas list query is mocked, the dashboard caches are a
stub redis, and request_warm is recorded instead of enqueuing Celery.
"""

import json
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.api.deps import Principal, get_dashboard_principal, get_db
from app.api.routes.gdp_report import _dashboard_cache_key as gdp_key
from app.api.routes.hipertensi_report import _registry_cache_key as ht_reg_key
from app.main import app

YEAR = 2026


@pytest.fixture
def totals_client(monkeypatch, stub_redis):
    """TestClient for the totals endpoint with two puskesmas (Alpha, Beta), a stub
    redis for the dashboard caches, and request_warm recorded. Yields
    (client, (p1, p2), warmed)."""
    p1, p2 = uuid.uuid4(), uuid.uuid4()
    rows = [SimpleNamespace(id=p1, name="Alpha"), SimpleNamespace(id=p2, name="Beta")]

    fake_db = MagicMock()
    fake_db.execute.return_value.all.return_value = rows
    app.dependency_overrides[get_db] = lambda: fake_db
    app.dependency_overrides[get_dashboard_principal] = lambda: Principal(
        "admin", uuid.uuid4(), None
    )

    import app.api.routes.report_dashboards as rd

    warmed: list[tuple[str, str]] = []
    monkeypatch.setattr(rd, "redis_client", lambda: stub_redis)
    monkeypatch.setattr(
        rd, "request_warm", lambda rc, key, rt, kw: warmed.append((key, rt))
    )

    with TestClient(app) as client:
        yield client, (p1, p2), warmed

    app.dependency_overrides.clear()


_NIKS = [
    {"nik": "1", "tandai_ckg": True},
    {"nik": "2", "tandai_ckg": True},
    {"nik": "3", "tandai_ckg": False},
]


def test_totals_counts_cached_and_warms_only_cold(totals_client, stub_redis):
    client, (p1, p2), warmed = totals_client
    # p1 warm (3 niks); p2 cold (no cache entry).
    stub_redis.set(gdp_key(p1, YEAR), json.dumps({"niks": _NIKS}))

    r = client.get(f"/report-dashboards/totals?disease=gdp&year={YEAR}")
    assert r.status_code == 200
    d = r.json()
    by = {i["puskesmas_id"]: i for i in d["items"]}

    assert by[str(p1)]["total"] == 3  # ckg_only default False → all niks
    assert by[str(p2)]["total"] is None  # cold → null
    assert d["grand_total"] == 3  # only the cached total
    assert d["computing"] is True  # p2 cold
    # Only the cold puskesmas gets a warm enqueued.
    assert (gdp_key(p2, YEAR), "gdp_dashboard") in warmed
    assert (gdp_key(p1, YEAR), "gdp_dashboard") not in warmed


def test_totals_ckg_only_filters_and_no_warm_when_all_cached(totals_client, stub_redis):
    client, (p1, p2), warmed = totals_client
    stub_redis.set(gdp_key(p1, YEAR), json.dumps({"niks": _NIKS}))
    stub_redis.set(gdp_key(p2, YEAR), json.dumps({"niks": []}))

    r = client.get(f"/report-dashboards/totals?disease=gdp&year={YEAR}&ckg_only=true")
    assert r.status_code == 200
    d = r.json()
    by = {i["puskesmas_id"]: i for i in d["items"]}

    assert by[str(p1)]["total"] == 2  # only the 2 ckg-flagged niks
    assert by[str(p2)]["total"] == 0  # cached-but-empty is a real 0, not cold
    assert d["grand_total"] == 2
    assert d["computing"] is False  # both cached → no warm
    assert warmed == []


_REG_PATIENTS = [
    {"nik": "1", "riwayat_ht": "Ya", "interpretasi": "Hipertensi"},
    {"nik": "2", "riwayat_ht": "Tidak", "interpretasi": "Hipertensi"},
    {"nik": "3", "riwayat_ht": "Tidak", "interpretasi": "Pre-Hipertensi"},
]


def test_totals_hipertensi_counts_registry_patients_and_warms_cold(
    totals_client, stub_redis
):
    client, (p1, p2), warmed = totals_client
    # Hipertensi reads the Registri Hipertensi CKG cache: p1 warm (3 patients),
    # p2 cold. Total = len(patients); ckg_only is a no-op for the registry.
    stub_redis.set(ht_reg_key(p1, YEAR), json.dumps({"patients": _REG_PATIENTS}))

    r = client.get(
        f"/report-dashboards/totals?disease=hipertensi&year={YEAR}&ckg_only=true"
    )
    assert r.status_code == 200
    d = r.json()
    by = {i["puskesmas_id"]: i for i in d["items"]}

    assert by[str(p1)]["total"] == 3
    # Interpretasi-band split of the total (2 Hipertensi + 1 Pre-Hipertensi).
    assert by[str(p1)]["total_hipertensi"] == 2
    assert by[str(p1)]["total_pre_hipertensi"] == 1
    assert by[str(p2)]["total"] is None  # cold → null
    assert by[str(p2)]["total_hipertensi"] is None  # bands null while cold
    assert by[str(p2)]["total_pre_hipertensi"] is None
    assert d["grand_total"] == 3
    assert d["computing"] is True  # p2 cold
    # Cold puskesmas warms the REGISTRY report (not the dashboard niks cache).
    assert (ht_reg_key(p2, YEAR), "hipertensi_registry") in warmed
    assert (ht_reg_key(p1, YEAR), "hipertensi_registry") not in warmed
