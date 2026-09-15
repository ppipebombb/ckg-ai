# Scrapers + encrypted patient store

The `asik/` and `epus/` scrapers can be invoked two ways:

1. **From the terminal**, as before — see `SCRAPE.md`.
2. **Via the backend API**, dispatched to a Celery worker. The worker writes the
   result into Postgres (table `patients`, one row per NIK). Patient blobs are
   Fernet-encrypted with the env var `CRED_ENCRYPTION_KEY`.

This document covers the API path: how to set the encryption key, how to run a
scrape, and how to debug by decrypting blobs manually with psql + Python.

---

## 1. Generate the encryption key

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

This prints a 44-character base64 string ending with `=`. Copy it.

## 2. Store it in the backend env

In `backend/.env`:

```
CRED_ENCRYPTION_KEY=<paste the key>
```

The same key encrypts:

- `puskesmas.epus_cred` / `puskesmas.asik_cred` (login creds)
- `patients.scraped_asik_data` / `patients.scraped_epus_data` (per-patient slice)

**Lose the key, lose access to all three.** Back it up in a secrets vault.

Rotation: there is no automatic re-encrypt step. Rotating the key requires a
maintenance script that decrypts every blob with the old key and re-encrypts
with the new one.

## 3. Trigger a scrape via API

```bash
# 1. Login as admin → get $TOKEN
curl -X POST http://localhost:8000/admin/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@ckg.com","password":"Admin123!"}'

# 2. Set creds for the puskesmas (one-time, encrypted at rest)
curl -X PUT http://localhost:8000/puskesmas/$PUSKESMAS_ID/credentials/asik \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"email":"<scraper-username>","password":"<scraper-password>"}'

# 3. Start the scrape
curl -X POST http://localhost:8000/puskesmas/$PUSKESMAS_ID/scrape/asik \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"date":"2026-04-21"}'
# → returns { "id": "<JOB_ID>", "status": "pending", ... }

# 4. Poll status
curl http://localhost:8000/scrape/jobs/$JOB_ID \
  -H "Authorization: Bearer $TOKEN"

# 5. Watch live progress (mirrors the terminal output)
curl "http://localhost:8000/scrape/jobs/$JOB_ID/log?tail=200" \
  -H "Authorization: Bearer $TOKEN"
# or stream via SSE:
curl -N http://localhost:8000/scrape/jobs/$JOB_ID/stream \
  -H "Authorization: Bearer $TOKEN"

# 6. Cancel a running job (cooperative; subprocess shut down within ~3s)
curl -X POST http://localhost:8000/scrape/jobs/$JOB_ID/cancel \
  -H "Authorization: Bearer $TOKEN"
```

A puskesmas can have at most **one active scrape job at a time** across both
`asik` and `epus`. A second start while one is running returns `409`.

## 4. Decrypt patient data via API

```bash
# List patients (filter by name, indexed)
curl "http://localhost:8000/patients?puskesmas_id=$PUSKESMAS_ID&nama=ARMA" \
  -H "Authorization: Bearer $TOKEN"

# Get one patient's encrypted scrape data, decrypted on the server
curl -X POST http://localhost:8000/patients/$PATIENT_ID/decrypt \
  -H "Authorization: Bearer $TOKEN"
```

Auth: admin can access any puskesmas; a user can only access their own
`puskesmas_id`.

## 5. Manual decryption from the database (debugging)

When the API path is not an option (e.g. inspecting prod data from a bastion
or debugging a corrupted row), you can decrypt blobs directly. The same key
works for every encrypted column.

```python
import json
import psycopg
from cryptography.fernet import Fernet

KEY = "PASTE_CRED_ENCRYPTION_KEY_HERE"  # from backend/.env
PUSKESMAS_ID = "..."                     # uuid
NIK = "..."                              # patient NIK

f = Fernet(KEY.encode())

with psycopg.connect("postgresql://ckg:ckg@localhost:5432/ckg") as conn:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT nama, scraped_asik_data, scraped_epus_data "
            "FROM patients "
            "WHERE puskesmas_id = %s AND nik = %s "
            "  AND deleted_at IS NULL",
            (PUSKESMAS_ID, NIK),
        )
        row = cur.fetchone()
        if row is None:
            raise SystemExit("not found")
        nama, asik_blob, epus_blob = row
        print("nama:", nama)
        if asik_blob:
            print("asik:", json.dumps(json.loads(f.decrypt(bytes(asik_blob))), indent=2))
        if epus_blob:
            print("epus:", json.dumps(json.loads(f.decrypt(bytes(epus_blob))), indent=2))
```

Same recipe for `puskesmas.epus_cred` / `puskesmas.asik_cred` — those decrypt
to `{"email": "...", "password": "..."}`.

### Caveats

- The Fernet key is byte-equality sensitive — any whitespace in the env file
  will break decryption.
- psycopg returns `bytea` columns as `memoryview`. Wrap in `bytes(...)` before
  passing to `f.decrypt(...)`.
- Never log the decrypted output to a shared system — it is patient PII.
- `created_at` / `updated_at` on the rows reflect when the row was written,
  not when the scrape happened. The scrape time is on `scrape_jobs.started_at`
  / `finished_at`.

## 7. Architecture notes

- The Celery worker runs each scrape as a subprocess (`python scraper.py`),
  with a per-task `tempfile.TemporaryDirectory` for config, output, session,
  and screenshots. Concurrent scrapes for different puskesmas don't collide.
- Path overrides into the scraper are passed via env vars
  (`SCRAPER_CONFIG`, `SCRAPER_OUTPUT_DIR`, `SCRAPER_SESSION_DIR`,
  `SCRAPER_SCREENSHOT_DIR`) — see `asik/helpers/constants.py` and
  `epus/helpers/constants.py`.
- The subprocess's `stdout` is streamed line-by-line into a Redis ringbuffer
  (`scrape:job:{id}:log`, last 500 lines, 24h TTL) and a pubsub channel
  (`scrape:job:{id}:stream`), exposed via `GET /scrape/jobs/{id}/log` and
  `GET /scrape/jobs/{id}/stream` (SSE).
- Cancellation is cooperative: the cancel endpoint flips
  `scrape_jobs.status = 'cancelled'`, the running task polls that field every
  2s and `SIGTERM`s its subprocess.
