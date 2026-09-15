"""Adversarial tests for the pentest-hardening changes.

Each block attacks one fix the way an external tester would, then confirms the
guard holds at the boundary. No DB needed; Redis is faked where touched.
"""

import os
from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet
from pydantic import ValidationError

# conftest stubs the required env before app import.
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://ckg:ckg@localhost:5432/ckg_test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")


# ───────────────────────── merge date-range DoS cap ──────────────────────────

from app.schemas.merge_job import MAX_MERGE_RANGE_DAYS, MergeStart  # noqa: E402


def test_merge_range_within_cap_ok():
    base = date(2025, 1, 1)
    m = MergeStart(date_from=base, date_to=base + timedelta(days=MAX_MERGE_RANGE_DAYS - 1))
    assert m.date_from is not None


def test_merge_range_exactly_at_cap_ok():
    base = date(2025, 1, 1)
    # span == MAX (inclusive) is allowed; span == MAX+1 is not.
    MergeStart(date_from=base, date_to=base + timedelta(days=MAX_MERGE_RANGE_DAYS - 1))


def test_merge_range_over_cap_rejected():
    base = date(1900, 1, 1)
    with pytest.raises(ValidationError, match="date range too large"):
        MergeStart(date_from=base, date_to=date(2100, 1, 1))


def test_merge_range_one_over_cap_rejected():
    base = date(2025, 1, 1)
    with pytest.raises(ValidationError, match="date range too large"):
        MergeStart(date_from=base, date_to=base + timedelta(days=MAX_MERGE_RANGE_DAYS))


def test_merge_single_date_unaffected():
    MergeStart(date=date(2025, 6, 1))
    MergeStart()  # defaults to today server-side


def test_merge_reversed_range_rejected():
    with pytest.raises(ValidationError, match="must be <="):
        MergeStart(date_from=date(2025, 6, 2), date_to=date(2025, 6, 1))


# ───────────────────── SSRF: puskesmas epus/asik base domain ──────────────────

from app.schemas.puskesmas import PuskesmasCreate, _validate_base_url  # noqa: E402


@pytest.mark.parametrize("good", ["sik.kemkes.go.id", "epuskesmas.example.com", "a.b.c.id"])
def test_puskesmas_url_public_domain_ok(good):
    assert _validate_base_url(good) == good


@pytest.mark.parametrize(
    "bad",
    [
        "169.254.169.254",          # link-local / cloud metadata (IPv4 literal)
        "127.0.0.1",                # loopback literal
        "10.0.0.5",                 # private literal
        "localhost",                # no-dot internal
        "metadata.google.internal", # GCP metadata
        "vault.internal",           # intranet suffix
        "host.local",               # mDNS / k8s
        "https://evil.com",         # scheme included
        "evil.com/login",           # path included
        "evil.com:8080",            # port included
        "foo .com",                 # space
        "",                         # empty
    ],
)
def test_puskesmas_url_ssrf_and_malformed_rejected(bad):
    with pytest.raises(ValueError):
        _validate_base_url(bad)


def test_puskesmas_create_rejects_internal_url():
    with pytest.raises(ValidationError):
        PuskesmasCreate(name="x", epus_url="metadata.google.internal", asik_url="a.b.id")


# ───────────────────────── SSRF: LLM base_url (full URL) ──────────────────────

from app.schemas.llm import LlmConfigCreate, _validate_llm_base_url  # noqa: E402


@pytest.mark.parametrize(
    "good",
    [
        "https://api.openai.com/v1",
        "http://local.juxtalabs.io/v1",   # 'local' in name but public .io TLD
        "https://riset.ai",
        "https://8.8.8.8/v1",             # public IP literal is allowed
    ],
)
def test_llm_base_url_public_ok(good):
    assert _validate_llm_base_url(good) == good


@pytest.mark.parametrize(
    "bad",
    [
        "file:///etc/passwd",                 # local file read
        "gopher://127.0.0.1:6379/_",          # redis via gopher
        "ftp://internal/x",                   # non-http scheme
        "http://169.254.169.254/latest/meta", # cloud metadata
        "http://127.0.0.1:11434/v1",          # loopback (local ollama)
        "http://10.1.2.3/v1",                 # private
        "http://192.168.1.1/v1",              # private
        "http://[::1]/v1",                    # IPv6 loopback
        "http://localhost/v1",                # blocked host
        "http://metadata.google.internal/",   # metadata host
        "http://db.internal/v1",              # intranet suffix
        "api.openai.com/v1",                  # no scheme
        "",                                    # empty
    ],
)
def test_llm_base_url_ssrf_rejected(bad):
    with pytest.raises(ValueError):
        _validate_llm_base_url(bad)


def test_llm_config_create_rejects_metadata_url():
    with pytest.raises(ValidationError):
        LlmConfigCreate(model="gpt-4o", base_url="http://169.254.169.254/v1", api_key="k")


@pytest.mark.parametrize(
    "bypass",
    [
        "http://2130706433/v1",            # decimal-encoded 127.0.0.1
        "http://0x7f000001/v1",            # hex-encoded 127.0.0.1
        "http://0177.0.0.1/v1",            # octal-encoded 127.0.0.1
        "http://127.1/v1",                 # short-form 127.0.0.1
        "http://[::ffff:127.0.0.1]/v1",    # IPv4-mapped IPv6 loopback
        "http://[::ffff:169.254.169.254]/", # IPv4-mapped IPv6 metadata
    ],
)
def test_llm_base_url_ip_encoding_bypasses_rejected(bypass):
    # These all resolve to loopback/link-local but evade a naive ip_address()
    # check — inet_aton + ipv4_mapped normalization must catch them.
    with pytest.raises(ValueError):
        _validate_llm_base_url(bypass)


# ─────────────────── X-Forwarded-For client-IP de-spoofing ────────────────────

from app.core import rate_limit  # noqa: E402


def _req(xff=None, peer="203.0.113.9"):
    headers = {}
    if xff is not None:
        headers["x-forwarded-for"] = xff
    return SimpleNamespace(
        headers=SimpleNamespace(get=headers.get),
        client=SimpleNamespace(host=peer),
    )


def test_xff_one_proxy_takes_rightmost(monkeypatch):
    # nginx appends the real client last; a spoofed prefix must be ignored.
    monkeypatch.setattr(rate_limit.settings, "TRUSTED_PROXY_COUNT", 1)
    assert rate_limit._client_ip(_req("1.1.1.1, 2.2.2.2")) == "2.2.2.2"
    assert rate_limit._client_ip(_req("9.9.9.9")) == "9.9.9.9"
    assert rate_limit._client_ip(_req(None, peer="8.8.8.8")) == "8.8.8.8"


def test_xff_spoof_attempt_cannot_win(monkeypatch):
    monkeypatch.setattr(rate_limit.settings, "TRUSTED_PROXY_COUNT", 1)
    # Attacker stuffs many fake entries; nginx still appends the true peer last.
    spoof = "evil, 1.2.3.4, 5.6.7.8, 6.6.6.6, 10.0.0.1"
    assert rate_limit._client_ip(_req(spoof)) == "10.0.0.1"


def test_xff_zero_proxies_ignores_header(monkeypatch):
    monkeypatch.setattr(rate_limit.settings, "TRUSTED_PROXY_COUNT", 0)
    assert rate_limit._client_ip(_req("1.1.1.1, 2.2.2.2", peer="8.8.8.8")) == "8.8.8.8"


def test_xff_two_proxies_indexes_from_right(monkeypatch):
    monkeypatch.setattr(rate_limit.settings, "TRUSTED_PROXY_COUNT", 2)
    assert rate_limit._client_ip(_req("client, cdn")) == "client"
    assert rate_limit._client_ip(_req("a, b, c")) == "b"
    # Fewer entries than trusted hops → fall back to socket peer, never a guess.
    assert rate_limit._client_ip(_req("only-one", peer="8.8.8.8")) == "8.8.8.8"


# ──────────────────────────── JWT revocation ─────────────────────────────────

from app.core import token_revocation as tr  # noqa: E402


class _FakeRedis:
    def __init__(self):
        self.store: dict[str, str] = {}

    def set(self, k, v, ex=None):
        self.store[k] = str(v)
        return True

    def mget(self, keys):
        return [self.store.get(k) for k in keys]


class _FailingRedis:
    def set(self, *a, **k):
        raise ConnectionError("redis down")

    def mget(self, *a, **k):
        raise ConnectionError("redis down")


def _payload(jti="j1", typ="user", sub="u1", iat=1000):
    return {"jti": jti, "typ": typ, "sub": sub, "iat": iat}


def test_fresh_token_not_revoked(monkeypatch):
    fake = _FakeRedis()
    monkeypatch.setattr(tr, "redis_client", lambda: fake)
    assert tr.is_revoked(_payload()) is False


def test_logout_denylists_single_token(monkeypatch):
    fake = _FakeRedis()
    monkeypatch.setattr(tr, "redis_client", lambda: fake)
    p = _payload(jti="abc")
    tr.revoke_token("abc", exp_ts=tr._now_ts() + 3600)
    assert tr.is_revoked(p) is True
    # A different token (different jti) for the same user stays valid.
    assert tr.is_revoked(_payload(jti="xyz")) is False


def test_revoke_all_invalidates_old_tokens_only(monkeypatch):
    fake = _FakeRedis()
    monkeypatch.setattr(tr, "redis_client", lambda: fake)
    import uuid
    uid = uuid.uuid4()
    cutoff = tr._now_ts()
    tr.revoke_all_for("user", uid)
    old = _payload(jti="o", typ="user", sub=str(uid), iat=cutoff - 10)
    new = _payload(jti="n", typ="user", sub=str(uid), iat=cutoff + 10)
    assert tr.is_revoked(old) is True       # issued before password change
    assert tr.is_revoked(new) is False      # issued after → still valid
    # Different user is unaffected.
    assert tr.is_revoked(_payload(sub="other", iat=cutoff - 10)) is False


def test_token_without_jti_still_cutoff_checked(monkeypatch):
    fake = _FakeRedis()
    monkeypatch.setattr(tr, "redis_client", lambda: fake)
    import uuid
    uid = uuid.uuid4()
    tr.revoke_all_for("admin", uid)
    p = {"typ": "admin", "sub": str(uid), "iat": tr._now_ts() - 5}  # legacy token, no jti
    assert tr.is_revoked(p) is True


def test_revocation_fails_open_on_redis_error(monkeypatch):
    monkeypatch.setattr(tr, "redis_client", lambda: _FailingRedis())
    # Must not lock everyone out if Redis is unreachable.
    assert tr.is_revoked(_payload()) is False
    tr.revoke_token("j", exp_ts=tr._now_ts() + 60)  # must not raise
    import uuid
    tr.revoke_all_for("user", uuid.uuid4())          # must not raise


def test_revoke_token_past_exp_clamps_ttl(monkeypatch):
    fake = _FakeRedis()
    monkeypatch.setattr(tr, "redis_client", lambda: fake)
    tr.revoke_token("j", exp_ts=tr._now_ts() - 999)  # already expired → ttl>=1, no crash
    assert fake.store.get("jwt:bl:j") == "1"


# ──────────────────────── Excel formula injection ────────────────────────────

from app.services.gdp_export import _formula_safe as gdp_safe  # noqa: E402
from app.services.hipertensi_export import _formula_safe as hyp_safe  # noqa: E402


@pytest.mark.parametrize("fn", [gdp_safe, hyp_safe])
@pytest.mark.parametrize(
    "raw,expected",
    [
        ("=HYPERLINK(\"http://evil\")", "'=HYPERLINK(\"http://evil\")"),
        ("+1+1", "'+1+1"),
        ("-2+3", "'-2+3"),
        ("@SUM(A1)", "'@SUM(A1)"),
        ("\tx", "'\tx"),
        ("\rx", "'\rx"),
        ("Budi Santoso", "Budi Santoso"),   # normal name untouched
        ("a=b", "a=b"),                       # trigger only matters at position 0
        ("", ""),                             # empty safe
    ],
)
def test_formula_safe(fn, raw, expected):
    assert fn(raw) == expected


# ───────── payload / parameter tampering (Network-tab editing the request) ────

import uuid as _uuid  # noqa: E402

from app.api.pagination import MAX_PAGE_SIZE, PageParams  # noqa: E402


def test_pagination_size_cannot_be_inflated():
    # Attacker edits ?size=999999 to mass-extract / DoS — must be rejected.
    PageParams(page=1, size=MAX_PAGE_SIZE)  # boundary OK
    for bad in (MAX_PAGE_SIZE + 1, 10_000, 1_000_000):
        with pytest.raises(ValidationError):
            PageParams(page=1, size=bad)
    for bad in (0, -1):  # page/size must be >= 1
        with pytest.raises(ValidationError):
            PageParams(page=bad, size=20)
        with pytest.raises(ValidationError):
            PageParams(page=1, size=bad)


def test_job_start_schemas_drop_server_owned_and_unknown_fields():
    # Attacker adds tenant/identity/status fields to the body hoping they're
    # written. Pydantic (extra='ignore') must drop everything not declared.
    from app.schemas.scrape_job import ScrapeStart
    from app.schemas.sync_job import SyncStart

    attack = {
        "headless": True,
        "puskesmas_id": str(_uuid.uuid4()),       # try to override tenant
        "patient_id": str(_uuid.uuid4()),
        "triggered_by_id": str(_uuid.uuid4()),    # try to forge the triggerer
        "triggered_by_type": "ADMIN",
        "status": "SUCCEEDED",                     # try to pre-set state
        "scraped_count": 999999,
        "is_admin": True,
        "evil": "x",
    }
    assert set(ScrapeStart.model_validate({**attack, "date": None}).model_dump()) == {
        "date",
        "headless",
    }
    assert set(SyncStart.model_validate(attack).model_dump()) == {"headless"}


def test_merge_start_only_exposes_date_and_force():
    m = MergeStart.model_validate(
        {"date": "2025-06-01", "force": True, "puskesmas_id": str(_uuid.uuid4()), "status": "X"}
    )
    assert set(m.model_dump()) == {"date", "date_from", "date_to", "force"}


def test_usercreate_ignores_privilege_escalation_fields():
    from app.schemas.user import UserCreate

    m = UserCreate.model_validate(
        {
            "email": "a@b.com",
            "password": "password123",
            "full_name": "X",
            "puskesmas_id": str(_uuid.uuid4()),
            "is_admin": True,        # no such field → dropped
            "scope": "internal",     # cannot self-assign admin scope
            "password_hash": "$2b$forged",
            "deleted_at": None,
        }
    )
    d = m.model_dump()
    assert "is_admin" not in d
    assert "scope" not in d
    assert "password_hash" not in d
    assert "deleted_at" not in d


def test_report_totals_scopes_user_to_own_puskesmas(monkeypatch, stub_redis):
    # BOLA via the Network tab: a puskesmas user calling /report-dashboards/totals
    # must see ONLY their own clinic, never every clinic's counts.
    import json
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    from fastapi.testclient import TestClient

    from app.api.deps import Principal, get_dashboard_principal, get_db
    from app.api.routes.gdp_report import _dashboard_cache_key as gdp_key
    import app.api.routes.report_dashboards as rd

    year = 2026
    p1, p2 = _uuid.uuid4(), _uuid.uuid4()
    rows = [SimpleNamespace(id=p1, name="Alpha"), SimpleNamespace(id=p2, name="Beta")]

    def _execute(stmt, *a, **k):
        # Honor the WHERE the handler adds for users: when it scopes with
        # .where(Puskesmas.id == principal.puskesmas_id), return only that row;
        # an admin statement has no whereclause → all rows.
        res = MagicMock()
        where = getattr(stmt, "whereclause", None)
        if where is not None:
            wanted = where.right.value  # the bound puskesmas UUID
            res.all.return_value = [r for r in rows if r.id == wanted]
        else:
            res.all.return_value = list(rows)
        return res

    fake_db = MagicMock()
    fake_db.execute.side_effect = _execute
    app.dependency_overrides[get_db] = lambda: fake_db
    # USER token scoped to p1 (the attacker's own clinic).
    app.dependency_overrides[get_dashboard_principal] = lambda: Principal("user", _uuid.uuid4(), p1)
    monkeypatch.setattr(rd, "redis_client", lambda: stub_redis)
    monkeypatch.setattr(rd, "request_warm", lambda *a, **k: None)
    stub_redis.set(gdp_key(p1, year), json.dumps({"niks": [{"nik": "1"}]}))
    stub_redis.set(gdp_key(p2, year), json.dumps({"niks": [{"nik": "2"}, {"nik": "3"}]}))

    try:
        with TestClient(app) as client:
            r = client.get(f"/report-dashboards/totals?disease=gdp&year={year}")
    finally:
        app.dependency_overrides.clear()

    assert r.status_code == 200
    ids = {i["puskesmas_id"] for i in r.json()["items"]}
    assert ids == {str(p1)}, "user must not see other clinics' totals"


# ───────────────────── production secret-strength guard ───────────────────────

from app.config import Settings  # noqa: E402

_STRONG_JWT = "x" * 48
_VALID_FERNET = Fernet.generate_key().decode()


def _settings(**over):
    base = dict(
        APP_ENV="production",
        DATABASE_URL="postgresql+psycopg://ckg:ckg@localhost:5432/ckg",
        REDIS_URL="redis://localhost:6379/0",
        ADMIN_EMAIL="a@b.com",
        ADMIN_PASSWORD="pw",
        JWT_SECRET=_STRONG_JWT,
        CRED_ENCRYPTION_KEY=_VALID_FERNET,
    )
    base.update(over)
    return Settings(_env_file=None, **base)


def test_production_strong_secrets_ok():
    s = _settings()
    assert s.is_production


def test_production_short_jwt_rejected():
    with pytest.raises(ValidationError, match="JWT_SECRET"):
        _settings(JWT_SECRET="too-short")


def test_production_placeholder_jwt_rejected():
    with pytest.raises(ValidationError, match="JWT_SECRET"):
        _settings(JWT_SECRET="replace-with-32-byte-random-secret-string-here")


def test_production_invalid_fernet_rejected():
    with pytest.raises(ValidationError, match="CRED_ENCRYPTION_KEY"):
        _settings(CRED_ENCRYPTION_KEY="not-a-valid-fernet-key")


# ───── frontend-dashboard least privilege: prod token's reachable surface ──────────

from fastapi import HTTPException  # noqa: E402
from fastapi.routing import APIRoute  # noqa: E402

from app.api import deps  # noqa: E402
from app.api.routes import gdp_report as _gdp  # noqa: E402
from app.api.routes import merge as _merge  # noqa: E402
from app.api.routes import patients as _patients  # noqa: E402
from app.api.routes import scrape as _scrape  # noqa: E402
from app.api.routes import sync as _sync  # noqa: E402

# Deps that accept a prod-scope admin token (the external dashboard pool).
_PROD_DATA_DEPS = {
    deps.get_dashboard_admin_id,
    deps.get_dashboard_principal,
    deps.get_current_prod_admin_id,
}

# The COMPLETE set a prod token may reach: the read-only dashboard endpoints +
# the prod session check + the one deliberate write (the explainer chatbot,
# which mutates no patient/business data). If a new endpoint appears here, it
# was accidentally exposed to the external team — this test fails until it's
# deliberate.
_EXPECTED_PROD_SURFACE = {
    "GET /puskesmas",
    "GET /puskesmas/{id}",
    "GET /merge-conflicts/summary",
    "DELETE /merge-conflicts/cache",
    "GET /gdp-reports/dashboard",
    "GET /gdp-reports/dashboard/export",
    "GET /gdp-reports/dashboard/diagnose-export",
    "DELETE /gdp-reports/dashboard/cache",
    "GET /gdp-reports/dashboard/summary",
    "GET /gdp-reports/dashboard/terkendali",
    "GET /hipertensi-reports/dashboard",
    "GET /hipertensi-reports/dashboard/export",
    "GET /hipertensi-reports/dashboard/diagnose-export",
    "DELETE /hipertensi-reports/dashboard/cache",
    "GET /hipertensi-reports/dashboard/summary",
    "GET /hipertensi-reports/dashboard/terkendali",
    "GET /hipertensi-reports/registry",
    "GET /hipertensi-reports/registry/summary",
    "GET /hipertensi-reports/registry/export",
    "DELETE /hipertensi-reports/registry/cache",
    "GET /hipertensi-reports/charts",
    "DELETE /hipertensi-reports/charts/cache",
    # Gap Tatalaksana — the per-patient drill-down behind the Tertatalaksana
    # chart. Read-only, and scoped by the SAME _authorize(principal,
    # puskesmas_id) as the registry it is derived from, so a prod token still
    # only ever sees its own puskesmas. It carries contact details (no telp /
    # alamat) — no more than "GET /hipertensi-reports/registry" already does.
    "GET /hipertensi-reports/charts/gap",
    "GET /hipertensi-reports/charts/gap/export",
    # Registri Diabetes Melitus — same read-only shape as the Hipertensi
    # registry above, for the client-facing dashboard page.
    "GET /dm-reports/registry",
    "GET /dm-reports/registry/summary",
    "GET /dm-reports/registry/export",
    "DELETE /dm-reports/registry/cache",
    # Registri Dislipidemia — same read-only shape again.
    "GET /lipid-reports/registry",
    "GET /lipid-reports/registry/summary",
    "GET /lipid-reports/registry/export",
    "DELETE /lipid-reports/registry/cache",
    # Registri Obesitas — same read-only shape again. The DELETE is a cache
    # rebuild (Redis only), not a data mutation, exactly as in the three
    # registries above.
    "GET /obesitas-reports/registry",
    "GET /obesitas-reports/registry/summary",
    "GET /obesitas-reports/registry/export",
    "DELETE /obesitas-reports/registry/cache",
    "GET /report-dashboards/totals",
    # School-patients (CKG Sekolah) read-only dashboard page. decrypt is POST by
    # convention (PII in the body, never the URL) but mutates nothing.
    "GET /school-patients",
    "GET /school-patients/facets",
    "POST /school-patients/{id}/decrypt",
    # Patient list + detail (read-only) for the dashboard's Patients page.
    # decrypt / asik-preview are POST by convention (PII rides in the body, never
    # the URL) but mutate nothing — they only read + decrypt / convert.
    "GET /patients",
    "GET /patients/{id}",
    "POST /patients/{id}/decrypt",
    "POST /patients/{id}/asik-preview",
    "GET /prod/auth/me",
    # The explainer chatbot — the one deliberate prod-reachable write (POST).
    "POST /chatbot/messages",
}


def _dep_calls(dependant):
    out = set()
    for sub in dependant.dependencies:
        if sub.call is not None:
            out.add(sub.call)
        out |= _dep_calls(sub)
    return out


def _prod_reachable_surface() -> set[str]:
    surface: set[str] = set()
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        if _dep_calls(route.dependant) & _PROD_DATA_DEPS:
            for m in route.methods:
                if m in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
                    surface.add(f"{m} {route.path}")
    return surface


def test_prod_token_data_surface_is_exactly_the_allowlist():
    # Default-deny: every endpoint NOT on the allowlist must reject a prod token.
    assert _prod_reachable_surface() == _EXPECTED_PROD_SURFACE


# The explainer chatbot is the one deliberate prod-reachable POST: it mutates no
# patient/business data (only writes an llm_logs usage row) and sends zero
# patient data to the LLM. See app/api/routes/chatbot.py.
# POSTs reachable by prod that mutate NO patient/business data:
#  - the explainer chatbot (writes only an llm_logs usage row)
#  - patient decrypt / asik-preview: read-only in effect; POST only so PII
#    travels in the request body, never the URL / query / access logs.
_PROD_WRITE_EXCEPTIONS = {
    "POST /chatbot/messages",
    "POST /patients/{id}/decrypt",
    "POST /patients/{id}/asik-preview",
    "POST /school-patients/{id}/decrypt",
}


def test_prod_surface_is_read_only_or_cache_clear():
    # No data mutation reachable: only GETs, plus DELETE on derived /cache keys,
    # plus the explicitly-allowlisted chatbot POST.
    for entry in _prod_reachable_surface():
        if entry in _PROD_WRITE_EXCEPTIONS:
            continue
        method, path = entry.split(" ", 1)
        assert method in {"GET", "DELETE"}, f"prod can mutate via {entry}"
        if method == "DELETE":
            assert path.endswith("/cache"), f"prod DELETE on real resource: {entry}"


def test_prod_login_is_rate_limited():
    # prod_login routes through login_admin, which must call the rate limiter
    # BEFORE doing the (DB) auth — same guard as internal + user login.
    import app.api.routes.admin_auth_ops as ops
    from unittest.mock import MagicMock

    from app.schemas.auth import LoginRequest

    enforced: list[str] = []
    monkeypatch_calls = []
    orig_enforce = ops.enforce_login_rate_limit
    orig_record = ops.record_failed_login_attempt
    ops.enforce_login_rate_limit = lambda req, email: enforced.append(email)
    ops.record_failed_login_attempt = lambda req, email: monkeypatch_calls.append(email)
    try:
        fake_db = MagicMock()
        fake_db.execute.return_value.one_or_none.return_value = None  # no such admin
        with pytest.raises(HTTPException) as ei:
            ops.login_admin(
                LoginRequest(email="attacker@x.com", password="guess"),
                MagicMock(),
                fake_db,
                scope="prod",
            )
        assert ei.value.status_code == 401
        assert enforced == ["attacker@x.com"]  # rate limit ran first
    finally:
        ops.enforce_login_rate_limit = orig_enforce
        ops.record_failed_login_attempt = orig_record


# ───────── object-level authz hides existence (403→404 oracle fix) ────────────


def test_object_level_authz_returns_404_not_403():
    from types import SimpleNamespace

    other = _uuid.uuid4()
    user = deps.Principal("user", _uuid.uuid4(), _uuid.uuid4())  # different clinic
    job = SimpleNamespace(puskesmas_id=other)
    cases = [
        (lambda: _patients._authorize(user, other), "Patient not found"),
        (lambda: _sync._authorize(user, other), "Patient not found"),
        (lambda: _sync._authorize_job(user, job), "Job not found"),
        (lambda: _scrape._authorize_job(user, job), "Job not found"),
        (lambda: _merge._authorize_job(user, job), "Job not found"),
        (lambda: _gdp._authorize_job(user, other), "Job not found"),
    ]
    for fn, detail in cases:
        with pytest.raises(HTTPException) as ei:
            fn()
        assert ei.value.status_code == 404, detail
        assert ei.value.detail == detail


def test_puskesmas_scope_checks_stay_403():
    # These run before the resource fetch → foreign==nonexistent==403 already,
    # so there's no existence oracle and they must NOT be softened to 404.
    other = _uuid.uuid4()
    user = deps.Principal("user", _uuid.uuid4(), _uuid.uuid4())
    for fn in (
        lambda: _merge._authorize(user, other),
        lambda: _scrape._authorize(user, other),
        lambda: _gdp._authorize(user, other),
    ):
        with pytest.raises(HTTPException) as ei:
            fn()
        assert ei.value.status_code == 403


def test_admin_principal_bypasses_object_authz():
    admin = deps.Principal("admin", _uuid.uuid4(), None)
    _patients._authorize(admin, _uuid.uuid4())  # must not raise
    _gdp._authorize_job(admin, _uuid.uuid4())   # must not raise


# ───────────────────── security response headers (e2e) ───────────────────────

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


def test_security_headers_present_on_api():
    # /health has no deps, so this exercises the middleware fully offline.
    with TestClient(app) as client:
        r = client.get("/health")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["referrer-policy"] == "no-referrer"
    assert r.headers["content-security-policy"] == "default-src 'none'; frame-ancestors 'none'"


def test_docs_paths_are_csp_exempt():
    # Swagger needs to load assets, so the strict CSP must not apply there —
    # but the anti-framing / anti-sniffing headers still should.
    with TestClient(app) as client:
        r = client.get("/openapi.json")
    assert r.status_code == 200
    assert "content-security-policy" not in r.headers
    assert r.headers["x-content-type-options"] == "nosniff"


def test_local_env_skips_secret_guard():
    # Weak secrets are fine in local/dev — the guard is production-only.
    s = Settings(
        _env_file=None,
        APP_ENV="local",
        DATABASE_URL="postgresql+psycopg://ckg:ckg@localhost:5432/ckg",
        REDIS_URL="redis://localhost:6379/0",
        ADMIN_EMAIL="a@b.com",
        ADMIN_PASSWORD="pw",
        JWT_SECRET="short",
        CRED_ENCRYPTION_KEY="not-a-valid-fernet-key",
    )
    assert not s.is_production
