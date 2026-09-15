---
name: ckg-deploy
description: >-
  Deploy the latest committed master to the CKG prod server (simpus-app-prd):
  git pull, rebuild ONLY the Docker images whose code changed, let migrations
  auto-run, and verify health. Use when asked to "deploy", "git pull and rebuild
  on prod", "ship to prod", "update the server", or to apply current master to
  simpus-app-prd. NEVER touches the Postgres container or its volume (prod data).
  Detects in-flight scrape / cron / backfill / merge work and CONFIRMS with the
  user (kill vs kill+resume) before disrupting it. Confirms before any env change
  or anything beyond a plain code rebuild.
---

# CKG prod deploy (simpus-app-prd)

Automates "git pull + rebuild" for this project on the prod box. Built from the
manually-validated deploy done 2026-06-13. The app's compose **bakes code into
images** (no code volumes) and the backend container **runs `alembic upgrade
head` on startup**, so a deploy = pull → build changed images → recreate, and
migrations apply themselves when the backend container restarts.

## HARD RULES (do not violate)

1. **Never touch Postgres or Redis.** Do not `build`, `stop`, `rm`, `restart`,
   `down`, or recreate `postgres` / `redis`. Their data volumes (`ckg_pg_data`,
   `ckg_redis_data`) are prod. Only ever name app services explicitly and use
   `--no-deps` so compose never recreates a dependency. After deploy, confirm
   `postgres` uptime is UNCHANGED (proof it wasn't touched).
2. **A plain code rebuild needs no extra confirmation. Everything else does.**
   STOP and confirm with the user before: changing any `.env`; killing in-flight
   work; a commit that changes `docker-compose*.yml`, any `Dockerfile`,
   `requirements*.txt` / `pyproject.toml` / `package.json` / `*-lock`, adds/renames
   a service, or anything you don't understand.
3. **`.env` is additive-only.** Only ADD keys that the repo template defines but
   the live file lacks. NEVER modify or remove an existing live value. Ignore
   keys compose injects via `environment:` (`DATABASE_URL`, `REDIS_URL`,
   `SCRAPER_SESSIONS_ROOT`) — they are intentionally absent from `.env`.
4. **Detect in-flight work BEFORE stopping anything.** If a scrape / cron run /
   backfill / merge is pending or running, save its state and ASK the user:
   (a) kill it entirely, (b) kill + resume after rebuild, (c) wait for it to
   finish first, or (d) abort. Never silently kill running work.

## Environment facts (verify with preflight; update here if they drift)

- Host: `ssh simpus-app-prd`, project dir `~/ckg-ai`, branch `master`.
- Remotes: server pulls `origin` = `Juxtalabs/ckg-ai`. (Dev's `akbarakma/ckg-ai`
  is a GitHub *redirect* to the same repo, so a dev push to either lands here.)
- Compose services: `postgres`, `redis`, `backend`, `celery_worker`,
  `celery_beat`, `frontend-internal` (:3000), `frontend-dashboard` (:3001).
  - `backend` build → image `ckg-backend:latest`, **also used by `celery_worker`
    and `celery_beat`** (they have no build section). Rebuilding `backend`
    updates the image; the celery services just need recreating to pick it up.
  - **Report caches are COMPUTED IN `celery_worker`, not the API process.**
    Registry / dashboard scans warm via `request_warm` → Celery `report.warm_one`
    (on cache miss) and the nightly `cron.warm_reports` → `scan_hipertensi_registry`
    / GDP / dashboard scans. So a change to ANY report scan/aggregate only takes
    effect once `celery_worker` runs the new image — recreating only `backend`
    leaves warms (and therefore the dashboards) on OLD code. **NEVER skip
    recreating celery for a report change just because it "looks API-only."**
    (Learned the hard way on the 2026-06-22 hipertensi deploy.)
  - `backend` command: `sh -c "alembic upgrade head && uvicorn ... --workers 4"`
    → **migrations run on container start.**
  - `frontend-internal` / `frontend-dashboard` each build their own image; the
    build needs `NEXT_PUBLIC_API_URL` (from the root `.env`).
- DB container: `ckg-ai-postgres-1`, user/db both `ckg_ai`
  (`docker exec ckg-ai-postgres-1 psql -U ckg_ai -d ckg_ai ...`).
- nginx (host, port 80, `server_name _`) reverse-proxies:
  `/` → `127.0.0.1:3000` (frontend-internal), the dashboard host → `:3001`,
  `/api`-style → `127.0.0.1:8000` (backend). Public TLS is upstream (Cloudflare);
  the origin only listens on :80. nginx config is under `/etc/nginx/` (use
  `sudo -n nginx -T` — passwordless sudo works for nginx).
- Admin API for kill/resume: base `http://127.0.0.1:8000`. Login
  `POST /admin/auth/login` `{email,password}` (creds = `ADMIN_EMAIL` /
  `ADMIN_PASSWORD` in `backend/.env`) → `{access_token}`. Use
  `Authorization: Bearer <token>`.

## Procedure

### Step 0 — Preflight (READ-ONLY)
Run the bundled audit on the server:

```
ssh simpus-app-prd 'bash -s' < .claude/skills/ckg-deploy/preflight.sh
```

It prints: current HEAD, incoming commits/files (`HEAD..origin/master`), the
**image rebuild set**, build/deps/compose-change WARNINGs, `.env` gaps (ignoring
compose-injected keys), disk headroom, `nginx -t`, and the **in-flight work
inventory with resume params**. Read it fully before acting.

### Step 1 — Confirm scope
- If preflight shows a `WARN:` (compose/Dockerfile/deps/new-service change) →
  describe it and CONFIRM before continuing (it's not a plain rebuild).
- If `.env` gaps are listed → CONFIRM, then add ONLY the missing keys to the live
  file (copy the example's line/default; for secrets, ask the user for the value
  or leave a clearly-marked placeholder). Never edit existing lines.
- If the in-flight inventory is non-empty → present it (see Step 5) and get the
  user's choice BEFORE building/stopping anything.

### Step 2 — Pull
```
ssh simpus-app-prd 'cd ~/ckg-ai && git pull --ff-only && git rev-parse --short HEAD'
```
Expect a clean fast-forward. If it is NOT ff (diverged / local changes other than
the known untracked `.env.bak*`) → STOP and report; do not force.

### Step 3 — Build only what changed
From the preflight rebuild set:
```
ssh simpus-app-prd 'cd ~/ckg-ai && docker compose build <backend?> <frontend-internal?> <frontend-dashboard?>'
```
Build failures are safe (running containers untouched). Skip a frontend whose
dir didn't change. If nothing under `backend/` `frontend-*/` changed (e.g. docs
only), no build/recreate is needed — say so and stop.

### Step 4 — Kill in-flight work (ONLY if user approved in Step 1/5)
Get a token; **first GET the backfill to snapshot its exact resume params**, then
cancel. `GET /admin/cron-backfills/{id}` returns `date_from`, `date_to`,
`cursor_date`, `merge_mode`, `source_scope`, `sync_mode`, `mandiri_only` —
capture **all of them** before cancelling
(preflight's range column shows `cursor_date..date_to`, the REMAINING range, not
the original `date_from`; you resume from `cursor_date` anyway, but grab the real
values so the resume POST in Step 7 is exact). Cancelling a **backfill** also
cancels its current cron run + child scrape/merge, so cancel at the backfill
level, not the children.
```
TOKEN=$(curl -s -X POST http://127.0.0.1:8000/admin/auth/login -H 'Content-Type: application/json' \
  -d "{\"email\":\"$ADMIN_EMAIL\",\"password\":\"$ADMIN_PASSWORD\"}" | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')
# backfill:   POST /admin/cron-backfills/{id}/cancel
# cron run:   POST /admin/cron-runs/{id}/cancel          (standalone runs only)
# scrape job: POST /scrape/jobs/{id}/cancel              (standalone only)
# merge job:  POST /merge/jobs/{id}/cancel               (standalone only)
```
(Run these `ssh simpus-app-prd '...'` with the creds sourced from
`~/ckg-ai/backend/.env`.) Confirm each target is `cancelled` before proceeding.

### Step 5 — Recreate (the safe sequence)
Stop schedulers/workers first so nothing queries mid-migration:
```
ssh simpus-app-prd 'cd ~/ckg-ai && \
  docker compose stop celery_worker celery_beat && \
  docker compose up -d --no-deps backend && sleep 14 && \
  docker compose logs backend --tail 40 | grep -iE "running upgrade|application startup|error|traceback"'
```
Verify migrations + boot: logs show each `Running upgrade ...` and `Application
startup complete`, no errors. Then:
```
ssh simpus-app-prd 'cd ~/ckg-ai && docker compose exec -T backend alembic current'   # == head
ssh simpus-app-prd 'cd ~/ckg-ai && docker compose up -d --no-deps celery_worker celery_beat <frontend-internal?> <frontend-dashboard?>'
```
**Always bring `celery_worker`/`celery_beat` back on the new image** — report
scans run there (see Environment facts), so leaving them on the old image serves
old-code dashboards. If in-flight work led the user to pick "don't disrupt
celery" AND the incoming change touches a report scan/aggregate, surface the
tradeoff explicitly: the report change will NOT appear until celery is recreated.
The clean path is the same as a normal kill+resume — cancel the in-flight work
(Step 4), recreate celery, then resume it (Step 7).

### Step 5.5 — ASIK sync runs K browsers in celery_worker now
Since the Phase C sync speedup, a cron SYNC batch runs `ASIK_SYNC_CONCURRENCY`
Chromium processes **at once inside `celery_worker`**, all sharing one ASIK login
(one bootstrap patient logs in per round; the rest are forbidden from logging in).
Two deploy-time consequences:

- **`docker-compose.yml` sets `shm_size: "2gb"` on `celery_worker`.** Chromium
  renderers thrash `/dev/shm` and Docker's 64 MB default kills them under a
  parallel pool — the failure reads like a flaky ASIK ("Target closed"), not an
  OOM. This is a compose-level change, so `docker compose up -d celery_worker`
  **recreates** the container even when the image is unchanged. That is expected.
- **Memory is the real ceiling, not ASIK.** The box is 4 vCPU / 7.9 GB with the
  worker alone at ~2.6 GB during a backfill; each extra Chromium is ~400-600 MB.
  `ASIK_SYNC_CONCURRENCY` defaults to **2** (unset in `.env` → the code default).
  K=3 is verified on the runner side but NOT on this box. To ramp, add the key to
  `~/ckg-ai/backend/.env` — an `.env` change, so **confirm with the user first**
  (HARD RULE 2) — and watch `free -m` plus the `sync_jobs` failure rate through a
  real batch before leaving it raised. Setting `1` restores strictly-sequential
  behaviour and is the instant rollback if the box struggles.

### Step 6 — Health check
```
ssh simpus-app-prd 'cd ~/ckg-ai && docker compose ps --format "{{.Name}}\t{{.Status}}" && \
  curl -so /dev/null -w "backend %{http_code}\n" http://127.0.0.1:8000/ ; \
  curl -so /dev/null -w "internal %{http_code}\n" http://127.0.0.1:3000/admin/login ; \
  curl -so /dev/null -w "dashboard %{http_code}\n" http://127.0.0.1:3001/ ; \
  docker compose logs celery_worker --tail 20 | grep -iE "ready|error" ; \
  sudo -n nginx -t 2>&1 | tail -1'
```
Healthy = all app containers `Up`; **`postgres` uptime UNCHANGED**; backend `/`
→ 404 (no root route — that's fine, it is serving); internal `/admin/login` →
200; dashboard `/` → 200; celery worker `... ready`; `nginx -t` ok.

If a sync backfill was resumed, also check memory headroom once it is actually
syncing (see Step 5.5) — this is the one health signal the container status does
not reveal:
```
ssh simpus-app-prd 'free -m | head -2; docker stats --no-stream --format "{{.Name}} {{.MemUsage}} {{.CPUPerc}}" | grep celery_worker'
```
Available under ~800 MB, or the worker climbing past ~4.5 GB, means drop
`ASIK_SYNC_CONCURRENCY` — do not wait for renderers to start dying.

### Step 6.5 — Rebuild report caches (ONLY if a report scan/aggregate changed)
Report payloads are cached ~30h; existing keys still hold OLD-code output until
cleared, so even with the new image live the dashboards serve stale data. After
`celery_worker` is on the new image, clear + re-warm the affected caches. The
`DELETE .../cache` endpoint deletes the key AND re-enqueues a warm (which now runs
new code in celery):
```
# registry key: hipertensi_registry:dashboard:{puskesmas_id}:{year}
# list live keys (read-only): docker exec ckg-ai-redis-1 redis-cli --scan --pattern 'hipertensi_registry:*'
for pk in <puskesmas_ids>; do
  curl -s -o /dev/null -w "$pk -> %{http_code}\n" -X DELETE \
    "http://127.0.0.1:8000/hipertensi-reports/registry/cache?puskesmas_id=$pk&year=<year>" \
    -H "Authorization: Bearer $TOKEN"; done   # 204 each
```
Each warm runs in `celery_worker` and takes minutes per puskesmas (heavy decrypt).
Verify a fresh payload carries the new fields by grepping the cached value for a
new marker — **counts only; it holds NIK/nama PII, never print the content**:
`docker exec ckg-ai-redis-1 redis-cli --no-raw GET '<key>' | grep -o '<marker>' | wc -l`.
Sibling caches if their scan changed: HT dashboard `hipertensi_report:dashboard:*`
and GD Puasa `gdp_*` keys have their own `DELETE .../dashboard/cache` endpoints.
The nightly `cron.warm_reports` also refreshes all of them with new code, so any
key you don't clear self-heals by the next nightly run.

### Step 7 — Resume killed work (ONLY if user chose "kill + resume")
Resume each saved item with the SAME params, picking up where it left off. For a
**backfill**, the saved `cursor_date` is the NEXT unprocessed date (NULL = not
started → use `date_from`); resume the remaining range with the same `merge_mode`
**AND** `source_scope` **AND** `sync_mode` **AND** `mandiri_only` (all surfaced by
preflight). **Every one of these silently defaults if you omit it, and the resumed
backfill then does the wrong work while still reporting success:**

| omitted | server default | what you silently lose |
|---|---|---|
| `source_scope` | `both` | an `asik_only`/`epus_only`/`none` backfill re-scrapes everything |
| `sync_mode` | `off` | **the ASIK sync step never runs** — the backfill merges and reports success having pushed nothing |
| `merge_mode` | `normal` | a `no_merge` scrape-only backfill starts merging; a `force_remerge` stops re-merging |
| `mandiri_only` | `false` | a Mandiri-only backfill re-reads Nakes + Tatalaksana |

The `sync_mode` case is the nastiest, because it fails **fast and green**: on a
`source_scope=none` sync-only backfill every merge is already a no-op, so a
resume that dropped `sync_mode` blasts through the remaining dates in seconds and
marks itself `success` having synced zero patients.
```
# new backfill = cursor_date(or date_from) .. date_to — carry ALL FOUR saved params
curl -s -X POST http://127.0.0.1:8000/admin/cron-backfills -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"puskesmas_id":"<pk>","date_from":"<cursor_or_date_from>","date_to":"<date_to>","merge_mode":"<saved>","source_scope":"<saved>","sync_mode":"<saved>","mandiri_only":<saved>}'
```
Example (user's): backfill 1..10 killed at cursor=4, scope `asik_only` → resume
`{date_from:"...-04", date_to:"...-10", merge_mode:"...", source_scope:"asik_only", sync_mode:"off", mandiri_only:false}`.
Sync-only backfill (`source_scope=none`, `sync_mode=normal`) killed at
cursor=2026-01-19 → resume
`{date_from:"2026-01-19", date_to:"2026-02-28", merge_mode:"normal", source_scope:"none", sync_mode:"normal", mandiri_only:false}`.
- **Standalone cron run** for one date → resume as a 1-day backfill
  (`date_from=date_to=target_date`, merge_mode from the puskesmas's cron config).
- **Standalone scrape** → `POST /scrape` `{kind, input:{date:<date_filter>}}`.
- **Merge (single patient)** → `POST /merge/patient/{patient_id}`. **Merge (date
  range)** → re-trigger the same date-range merge from the merge-with-ai flow.
Confirm each resume started, then report the new job/backfill ids.

### Step 8 — Report
Summarize: HEAD before→after, images rebuilt, migrations applied (alembic head),
health table, postgres-untouched confirmation, any report caches rebuilt + verified
(Step 6.5), and any work killed + resumed (with new ids).

## Notes
- gpt-oss LLM outages: with the fail-loud merge fix live, cron `merge` steps FAIL
  (and halt their backfill) while the provider is down — that's intended. To keep
  scraping cleanly meanwhile, set the cron config / backfill to **`no_merge`**
  mode; re-merge later (`backend/scripts/find_silent_merge_failures.py` lists what
  to re-merge).
- `docker compose` (v2) on this host. If a command errors with "no configuration
  file", ensure `cd ~/ckg-ai` first.
- The SSH banner prints a legal warning before output — ignore it / filter with
  `grep -vE '^=+$|WARNING|Unauthorized|Helpdesk|Kementerian'`.
