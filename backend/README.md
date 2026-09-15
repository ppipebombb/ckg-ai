# CKG Backend

FastAPI + SQLAlchemy + Postgres backend.

## Quickstart

### Local dev (backend on host, infra in Docker)

```bash
# from repo root: bring up Postgres + Redis
docker compose -f docker-compose.local.yml up -d

cd backend
cp .env.example .env
# ensure CRED_ENCRYPTION_KEY in .env — see scrapers/README.md §1-2 to generate
python3 -m venv .venv && source .venv/bin/activate
pip3 install -e ".[dev]"
playwright install chromium      # required by scraper Celery tasks
alembic upgrade head

# Terminal A — API
uvicorn app.main:app --reload

# Terminal B — Celery worker (handles /scrape/*, /merge/*, cron tasks)
celery -A app.celery_app.celery_app worker --loglevel=info --concurrency=4

# Terminal C — Celery beat (cron scheduler; singleton — only run one)
celery -A app.celery_app.celery_app beat --loglevel=info
```

API at http://localhost:8000. OpenAPI docs at /docs.

### Production-like stack (everything in Docker)

```bash
# from repo root — requires backend/.env to exist
cp backend/.env.example backend/.env  # edit values for prod
docker compose up --build -d
```

Backend container runs `alembic upgrade head` on start, then `uvicorn` with 4 workers (no reload).

## Auth

Login as the seeded admin:

```bash
curl -X POST http://localhost:8000/admin/auth/login \
  -H 'content-type: application/json' \
  -d '{"email":"admin@ckg.com","password":"Admin123!"}'
```

Use the returned `access_token` as `Authorization: Bearer <token>` for admin endpoints.

## Soft Delete

All tables carry `deleted_at`. ORM queries auto-exclude soft-deleted rows. No hard deletes.
