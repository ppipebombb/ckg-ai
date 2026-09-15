"""Login-partition tests: prod (scope="prod") and internal (scope="internal")
admins are separate pools — neither can log into the other's app.

These need a real, migrated Postgres (the `admins.scope` column). They run inside
a rolled-back transaction (no committed rows) and self-skip when no DB is reachable.
"""

import uuid

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from app.api.deps import get_db
from app.core.security import hash_password
from app.database import SessionLocal, engine
from app.main import app


def _db_available() -> bool:
    # Selecting `scope` also asserts the 0019 migration has been applied.
    try:
        with engine.connect() as conn:
            conn.execute(sa.text("SELECT scope FROM admins LIMIT 1"))
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _db_available(), reason="Postgres (migrated) not reachable"
)

PW = "Secret123!"


@pytest.fixture(autouse=True)
def _no_rate_limit(monkeypatch):
    # Login + rate-limit live in the shared admin_auth_ops module now.
    mod = "app.api.routes.admin_auth_ops"
    monkeypatch.setattr(f"{mod}.enforce_login_rate_limit", lambda *a, **k: None)
    monkeypatch.setattr(f"{mod}.record_failed_login_attempt", lambda *a, **k: None)


@pytest.fixture
def admins():
    """Insert one internal + one prod admin in a transaction the request shares,
    then roll back. Yields their emails."""
    conn = engine.connect()
    trans = conn.begin()
    session = SessionLocal(bind=conn)
    app.dependency_overrides[get_db] = lambda: session

    internal_email = f"internal-{uuid.uuid4()}@test.com"
    prod_email = f"prod-{uuid.uuid4()}@test.com"
    session.execute(
        sa.text(
            "INSERT INTO admins "
            "(id, email, password_hash, full_name, scope, created_at, updated_at) "
            "VALUES (:id, :email, :pw, :name, :scope, now(), now())"
        ),
        [
            {
                "id": uuid.uuid4(),
                "email": internal_email,
                "pw": hash_password(PW),
                "name": "Internal",
                "scope": "internal",
            },
            {
                "id": uuid.uuid4(),
                "email": prod_email,
                "pw": hash_password(PW),
                "name": "Prod",
                "scope": "prod",
            },
        ],
    )
    session.flush()
    try:
        yield {"internal": internal_email, "prod": prod_email}
    finally:
        app.dependency_overrides.clear()
        session.close()
        trans.rollback()
        conn.close()


def test_internal_account_rejected_at_prod_login(admins):
    with TestClient(app) as client:
        r = client.post(
            "/prod/auth/login", json={"email": admins["internal"], "password": PW}
        )
    assert r.status_code == 401


def test_prod_account_rejected_at_internal_login(admins):
    with TestClient(app) as client:
        r = client.post(
            "/admin/auth/login", json={"email": admins["prod"], "password": PW}
        )
    assert r.status_code == 401


def test_prod_account_accepted_at_prod_login(admins):
    with TestClient(app) as client:
        r = client.post(
            "/prod/auth/login", json={"email": admins["prod"], "password": PW}
        )
    assert r.status_code == 200
    assert r.json().get("access_token")


def test_internal_account_accepted_at_internal_login(admins):
    with TestClient(app) as client:
        r = client.post(
            "/admin/auth/login", json={"email": admins["internal"], "password": PW}
        )
    assert r.status_code == 200
    assert r.json().get("access_token")


# /me is pool-specific: a token from one pool must not validate a session in the
# other app, even though both tokens carry full data-endpoint access.
def _token(client, path, email):
    return client.post(path, json={"email": email, "password": PW}).json()[
        "access_token"
    ]


def test_prod_token_rejected_at_internal_me(admins):
    with TestClient(app) as client:
        tok = _token(client, "/prod/auth/login", admins["prod"])
        r = client.get("/admin/auth/me", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 401


def test_prod_token_accepted_at_prod_me(admins):
    with TestClient(app) as client:
        tok = _token(client, "/prod/auth/login", admins["prod"])
        r = client.get("/prod/auth/me", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200
    assert r.json()["email"] == admins["prod"]


def test_internal_token_rejected_at_prod_me(admins):
    with TestClient(app) as client:
        tok = _token(client, "/admin/auth/login", admins["internal"])
        r = client.get("/prod/auth/me", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 401


# ── Scope enforcement on the shared DATA layer (default-deny for prod) ────────
# A prod token is a valid admin token (typ="admin"), so the partition must hold
# beyond /login: management + PII endpoints reject it; only the read-only
# dashboards frontend-dashboard is allowlisted for accept it.


def _auth(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}"}


def test_prod_token_rejected_on_management_endpoint(admins):
    """get_current_admin_id is internal-only → prod can't reach /users etc."""
    with TestClient(app) as client:
        tok = _token(client, "/prod/auth/login", admins["prod"])
        r = client.get("/users", headers=_auth(tok))
    assert r.status_code == 401


# Patient READS were moved to the dashboard allowlist (get_dashboard_principal)
# so frontend-dashboard can show patient list + detail. Reads accept prod; every
# patient MUTATION stays internal-only (default-deny) — the IDOR guarantee.


def test_prod_token_allowed_on_patient_list(admins):
    """GET /patients now accepts prod (read-only dashboard surface)."""
    with TestClient(app) as client:
        tok = _token(client, "/prod/auth/login", admins["prod"])
        r = client.get("/patients", headers=_auth(tok))
    assert r.status_code == 200


def test_prod_token_reaches_patient_reads_as_404_not_401(admins):
    """A random id proves the dep lets prod THROUGH: not-found (404), not
    auth-rejected (401), on detail / decrypt / asik-preview."""
    rid = uuid.uuid4()
    with TestClient(app) as client:
        tok = _token(client, "/prod/auth/login", admins["prod"])
        for method, path in [
            ("get", f"/patients/{rid}"),
            ("post", f"/patients/{rid}/decrypt"),
            ("post", f"/patients/{rid}/asik-preview"),
        ]:
            r = getattr(client, method)(path, headers=_auth(tok))
            assert r.status_code == 404, (path, r.status_code)


def test_prod_token_rejected_on_every_patient_mutation(admins):
    """Every patient mutation stays internal-only → prod gets 401, even with a
    crafted/guessed patient id (no IDOR: a prod token can't scrape/merge/sync/
    delete any patient)."""
    rid = uuid.uuid4()
    cases = [
        ("post", f"/patients/{rid}/scrape/asik"),
        ("post", f"/patients/{rid}/scrape/epus"),
        ("post", f"/patients/{rid}/merge"),
        ("post", f"/patients/{rid}/sync-asik"),
        ("delete", f"/patients/{rid}"),
    ]
    with TestClient(app) as client:
        tok = _token(client, "/prod/auth/login", admins["prod"])
        for method, path in cases:
            r = getattr(client, method)(path, headers=_auth(tok))
            assert r.status_code == 401, (path, r.status_code)


def test_prod_token_allowed_on_allowlisted_dashboard_endpoint(admins):
    """get_dashboard_admin_id accepts prod → the puskesmas list must NOT be an
    auth rejection (it is the dashboard's puskesmas picker source)."""
    with TestClient(app) as client:
        tok = _token(client, "/prod/auth/login", admins["prod"])
        r = client.get("/puskesmas", headers=_auth(tok))
    assert r.status_code == 200


def test_internal_token_still_allowed_on_management_endpoint(admins):
    """Sanity: the default-deny flip didn't lock internal admins out."""
    with TestClient(app) as client:
        tok = _token(client, "/admin/auth/login", admins["internal"])
        r = client.get("/users", headers=_auth(tok))
    assert r.status_code == 200
