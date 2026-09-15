"""Tests for GET /{gdp,hipertensi}-reports/dashboard/summary.

Covers the shared `dashboard_summary_response` helper: cold cache → computing,
warm cache → tallied counts, and the `computed_at` guard (a cached payload that
predates the field must NOT 500 — it's treated as a miss).
"""

import json
from datetime import UTC, datetime

from app.api.routes.gdp_report import _dashboard_cache_key as gdp_key
from app.api.routes.hipertensi_report import _dashboard_cache_key as ht_key

YEAR = 2026


def _payload(niks, monthly, with_computed_at=True):
    p = {"niks": niks, "monthly": monthly, "daily": {}}
    if with_computed_at:
        p["computed_at"] = datetime.now(UTC).isoformat()
    return json.dumps(p)


def test_gdp_summary_cold_cache_returns_computing(summary_client, warm_calls):
    client, pid = summary_client
    r = client.get(f"/gdp-reports/dashboard/summary?puskesmas_id={pid}&year={YEAR}")
    assert r.status_code == 200
    d = r.json()
    assert d["computing"] is True
    assert d["cache_hit"] is False
    assert d["computed_at"] is None
    assert warm_calls == [(gdp_key(pid, YEAR), "gdp_dashboard")]


def test_gdp_summary_missing_computed_at_does_not_500(summary_client, stub_redis, warm_calls):
    client, pid = summary_client
    # payload predates the computed_at field
    stub_redis.set(gdp_key(pid, YEAR), _payload([{"nik": "1"}], {}, with_computed_at=False))
    r = client.get(f"/gdp-reports/dashboard/summary?puskesmas_id={pid}&year={YEAR}")
    assert r.status_code == 200  # not a 500 KeyError
    d = r.json()
    assert d["computing"] is True  # treated as a miss → re-warm
    assert len(warm_calls) == 1


def test_gdp_summary_warm_cache_tallies(summary_client, stub_redis, warm_calls):
    client, pid = summary_client
    # NIKs with no first_epus_date classify as "" → tanpa_status
    niks = [{"nik": "1"}, {"nik": "2"}, {"nik": "3"}]
    stub_redis.set(gdp_key(pid, YEAR), _payload(niks, {}))
    r = client.get(f"/gdp-reports/dashboard/summary?puskesmas_id={pid}&year={YEAR}")
    assert r.status_code == 200
    d = r.json()
    assert d["computing"] is False
    assert d["cache_hit"] is True
    assert d["computed_at"] is not None
    assert d["total"] == 3
    assert d["tanpa_status"] == 3
    bucket_sum = (
        d["terkendali"]
        + d["tidak_terkendali"]
        + d["belum_3_bulan"]
        + d["tidak_ada_kunjungan"]
        + d["tanpa_status"]
    )
    assert bucket_sum == d["total"]
    assert warm_calls == []  # no re-warm on a hit


def test_hipertensi_summary_warm_cache_tallies(summary_client, stub_redis):
    client, pid = summary_client
    niks = [{"nik": "1"}, {"nik": "2"}]
    stub_redis.set(ht_key(pid, YEAR), _payload(niks, {}))
    r = client.get(f"/hipertensi-reports/dashboard/summary?puskesmas_id={pid}&year={YEAR}")
    assert r.status_code == 200
    d = r.json()
    assert d["computing"] is False
    assert d["cache_hit"] is True
    assert d["computed_at"] is not None
    assert d["total"] == 2


def test_hipertensi_summary_missing_computed_at_does_not_500(summary_client, stub_redis):
    client, pid = summary_client
    stub_redis.set(ht_key(pid, YEAR), _payload([{"nik": "1"}], {}, with_computed_at=False))
    r = client.get(f"/hipertensi-reports/dashboard/summary?puskesmas_id={pid}&year={YEAR}")
    assert r.status_code == 200
    assert r.json()["computing"] is True
