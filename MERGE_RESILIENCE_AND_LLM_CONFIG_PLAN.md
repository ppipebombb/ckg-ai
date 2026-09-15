# Merge Resilience + Cron No-Merge Mode + LLM Config Hardening — Implementation Brief

> **Read this whole file before writing any code.** It is written as a self-contained
> brief for the implementing agent. Every file path and line number below was verified
> against the current tree. Line numbers drift as you edit — re-grep before trusting an
> offset, but the *function/symbol names* are stable anchors.
>
> **House rules that apply to everything here** (from `CLAUDE.md`):
> - §2 Simplicity, §3 Surgical changes — touch only what the task needs.
> - §5 `load_only(...)` on every ORM query; never `SELECT *`.
> - §6 Soft-delete: SELECTs auto-filter; **UPDATE/DELETE must add `deleted_at IS NULL` explicitly**.
> - §7 Frontend: cache-update over invalidate, RHF+zod, query-key factories. **The internal
>   admin app lives in `frontend-internal/` — the `/frontend` path in CLAUDE.md §7 is STALE.**
>   The read-only client app is `frontend-dashboard/` and is NOT touched by this work.
> - §8 No N+1 queries.
> - §10 Chatbot knowledge packs: do **not** edit `chatbot/knowledge/*.md` unless you change a
>   pinned source file in `chatbot/knowledge.lock.json`. None of this work touches those sources,
>   so leave the packs alone.
> - **Celery restart rule (project memory):** any change under `backend/app/` (tasks/crud/models)
>   requires restarting the `ckg-ai-celery_worker` and `ckg-ai-celery_beat` containers to take
>   effect. Call this out in your final summary.

---

## 0. Background — why we are doing this

On **2026-06-11 ~03:18 UTC** the self-hosted `openai/gpt-oss-120b` endpoint (used by the
`merge_patient_data` LLM source) started returning Cloudflare **HTTP 530** and has been down since.
During the outage the daily cron + force-remerge backfills kept running. Every merge job since
then reports **`status = success` with `succeeded_count = 0` and `failed_count > 0`** — i.e. it
*looks* done but **no patient was actually merged**. In prod this silently produced **171 jobs /
~2,479 patient-merges that never happened**, across 3 puskesmas, and the backfill cursors kept
advancing past dates where nothing merged.

Root cause (verified): the per-patient merge loop swallows each patient's exception, bumps
`failed_count`, and continues; the task then **unconditionally** calls `mark_success` at the end.
The cron layer only checks `MergeJob.status == SUCCESS`, so the bad status propagates up and the
backfill advances.

This brief fixes that and adds operational controls so an LLM outage is **flagged, retried, and
stops the pipeline loudly** instead of silently — plus lets the operator keep scraping while the
LLM is down, and configure/verify LLM endpoints from the UI.

### Decisions already made (do not re-litigate)
1. **Cron mode** is stored as a new **enum `merge_mode` = {`normal`, `force_remerge`, `no_merge`}**
   on `cron_configs` and `cron_backfills` (replaces the `force_remerge` bool). Invalid combos
   impossible by construction.
2. **Incomplete merge** (any eligible patient still unmerged after retries) → reuse the existing
   **`FAILED`** status with a descriptive `error_message`. No new merge_status value.
3. **No cron-level merge retry.** The merge task retries the failed subset internally; if still
   incomplete it marks the job `FAILED` and the cron run **fails fast and halts the backfill**.
   ASIK/EPUS step retries stay unchanged.

---

## 1. Goals (what "done" means)

| # | Feature | Verifiable success criterion |
|---|---------|------------------------------|
| A | **Merge never lies.** A merge job that didn't merge every eligible patient ends `FAILED`, not `success`. | Unit test: loop where N patients fail → job status `FAILED`, `failed_count=N`, `succeeded_count` correct, `error_message` set. |
| B | **Per-patient retry within a run.** Retry only the failed subset, up to 4 rounds, shrinking each round. All merged → success; else → `FAILED` + stop. | Unit test: patient fails round 1 then succeeds round 2 → counted as 1 success, 0 fail, no double-count. Patient fails all rounds → 1 fail, job `FAILED`. |
| C | **Cron `no_merge` mode.** Run EPUS+ASIK scrape, skip merge entirely. | Cron run in `no_merge` mode creates ASIK+EPUS scrape jobs, **no** merge job, run ends `success`, backfill cursor advances. |
| D | **`reasoning_effort` on LlmConfig.** Settable on create/edit; provider-agnostic; flows into every LLM call. | A config with `reasoning_effort='high'` emits the correct wire param for gpt-oss / o-series / deepseek; omitted for models that don't support it. |
| E | **Test-connection.** Button on the LLM form sends a minimal prompt using the config (incl. reasoning) and reports clear success/error. | Endpoint returns `{ok:true, reply, latency_ms}` on a good config and `{ok:false, error:"LLM HTTP 530: ..."}` on a bad one; button shows both inline. |
| F | **Reclaim the silently-missed merges.** Identify the historical mismarked jobs so they can be re-driven. | A query/script lists `(puskesmas, date_filter)` for jobs with `status=success AND failed_count>0`. |

### Non-goals
- Do **not** change the deterministic converter logic (`app/services/*_to_asik.py`) or merge field
  rules (CLAUDE.md §9).
- Do **not** add multi-provider SDKs. The integration is OpenAI-compatible `urllib` and stays that way.
- Do **not** touch `frontend-dashboard/`, the chatbot knowledge packs, or unrelated dead code.
- Pre-existing nits noticed but **out of scope** (mention, don't fix): backend `LlmConfigUpdate`
  lacks `is_active_chatbot`; frontend `LlmConfigCreate` zod lacks `is_active_chatbot`.

---

## 2. Codebase map (the files you will touch + why)

### Backend — merge
- `backend/app/tasks/merge.py`
  - Task `run_merge(self, job_id)` — `merge.py:1180`. Loads `MergeJob`, reads `puskesmas_id`,
    `force_remerge`, `patient_id`, `date_filter` off the row (`:1252-1260`).
  - Target selection — `:1282-1296` (`not force` adds `Patient.merged_at.is_(None)`).
  - Per-patient loop — `:1308-1542`. LLM call is `_chat_and_parse_with_retry(...)` at `:1394`
    (defined `:1102`, calls `chat_complete` at `:1138`). **Every non-skipped patient calls the LLM
    unconditionally** — so when the LLM is down, ALL patients fail.
  - Per-patient `except` — `:1484-1542`: rollback, record failed `llm_log`, `bump_counters(failed=1)`,
    `continue`. (This is where the swallow happens.)
  - **Finalization (the bug)** — `:1544-1567`: unconditional `merge_job_crud.mark_success(...)`.
  - Cancel key `merge:job:{id}:cancel` — `_cancel_key` `:941`, checked `:1311-1316`.
  - Constants near top: `_MERGE_MAX_ATTEMPTS = 3` (JSON-parse retries, distinct from our new round retry).
- `backend/app/crud/merge_job.py`
  - `mark_success` / `mark_failed` — `:66-93` (status setters; no counter logic today).
  - `bump_counters` — `:107-123`.
  - `mark_running` sets `total_count` — invoked from `merge.py:1301-1303`.
- `backend/app/models/merge_job.py` — `MergeStatus` enum `:20-25`; counter columns `:54-58`.

### Backend — cron
- `backend/app/tasks/cron.py`
  - `_next_step(step)` — `:107-115` (EPUS→ASIK→MERGE→done).
  - `advance(cron_run_id, step)` — `:356-493` (the state machine; dispatches one child, chains via link).
  - `_dispatch_child` — `:283-312` (maps MERGE→`merge.run`, else→`scrape.run`).
  - `_previous_step_failed` — `:315-353`; MERGE→done branch checks `MergeJob.status == SUCCESS` `:347-353`.
    **This is the gate that already halts the run when merge is FAILED — once the merge task marks
    FAILED correctly, the halt is automatic.**
  - `handle_failure` — `:496-575` (`MAX_ATTEMPTS=3`, exp backoff `:26-27`). Retries the failed step.
  - `_create_child_job` — `:230-280`; **force_remerge resolution `:240-259`** (reads `CronBackfill`/
    `CronConfig` with `include_deleted=True`). This is where mode is read for merge.
  - Backfill success advance — `:399-424` (`advance_cursor` + `dispatch_backfill_next`).
  - `_propagate_run_failed_to_backfill` — `:74-84` → `cron_backfill_crud.mark_failed` halts the
    whole backfill (this is the desired "stop" behavior).
  - `dispatch_backfill_next` — `:578-663`.
- `backend/app/models/cron_run.py` — `CronStep` `:30-33`, `CronRunStatus` `:22-27`, `current_step_attempt` `:68`.
- `backend/app/models/cron_config.py` — `force_remerge` `:32`.
- `backend/app/models/cron_backfill.py` — `force_remerge` `:53-55`; `CronBackfillStatus` `:20-25`.
- `backend/app/crud/cron_config.py`, `backend/app/crud/cron_backfill.py`, `backend/app/crud/cron_run.py`.
- `backend/app/schemas/cron_config.py` (`CronConfigCreate/Update` `:7-21`), `backend/app/schemas/cron_backfill.py` (`CronBackfillCreate` `:9-19`).
- `backend/app/api/routes/cron_config.py` (create/update/run-now `:189-249`), `backend/app/api/routes/cron_backfill.py` (`:60-138`).

### Backend — LLM integration & config
- `backend/app/integrations/llm_chat.py`
  - `chat_complete(...)` — `:42-64` (already accepts `reasoning_effort` and `thinking`).
  - `_openai_compat_chat(...)` — `:123-258`; **payload assembly `:135-185`** (the single extension point).
  - Provider sniffers — `_is_openai_reasoning_model` `:107-111`, `_is_deepseek` `:114-115`,
    `_is_gpt_oss` `:118-120`, `_is_riset` `:73-76`.
  - Retry set `_RETRYABLE_HTTP_STATUS` `:32-39` — **note 530 is NOT in it** (fails fast).
  - Error string `RuntimeError(f"LLM HTTP {code}: {detail}")` — `:225`.
- `backend/app/models/llm_config.py` — columns `:10-22` (no `reasoning_effort` today).
- `backend/app/crud/llm_config.py` — `get_active` `:23-32`, `get_active_for_captcha` `:35-47`,
  `get_active_for_chatbot` `:50-63` (**each has a `load_only(...)` list you must extend**); `reveal` `:237-246`.
- `backend/app/schemas/llm.py` — `LlmConfigCreate` `:85-95`, `LlmConfigUpdate` `:98-105`,
  `LlmConfigOut` `:108-122`, `LlmBaseUrl` validator `:51-67`, `UsdPrice` `:70-82`.
- `backend/app/api/routes/llm.py` — endpoint list `:51-406` (no test endpoint exists).
- `backend/app/core/security.py` — `encrypt_json` / `decrypt_json` (Fernet). api_key stored as
  `encrypt_json({"api_key": ...})`, read as `decrypt_json(obj.api_key_enc)["api_key"]`.
- Callers of `chat_complete`: merge `merge.py:1138-1146` (passes neither reasoning nor thinking
  today), chatbot `backend/app/api/routes/chatbot.py:94-107` (hardcodes `reasoning_effort="high",
  thinking=True`).

### Backend — migrations / celery / tests
- `backend/alembic/versions/` — numbering `NNNN_snake.py`; **HEAD = `0020_llm_config_chatbot_active`**
  (so new files are `0021_...`, `0022_...` with `down_revision` chained).
  - Add-column pattern: `0020_llm_config_chatbot_active.py:19-33`, `0019_admin_scope.py:29-34`.
  - **Enum ADD VALUE pattern (transaction caveat): `0007_cron_config_and_run.py:24-30`** —
    `op.execute("COMMIT")` then `op.execute("ALTER TYPE ... ADD VALUE IF NOT EXISTS '...'")`.
  - New enum type pattern: `0007:20-37` (`postgresql.ENUM(*VALUES, name=..., create_type=False)` then `.create(bind, checkfirst=True)`).
- `backend/app/celery_app.py` — task `include` list `:10-16`; beat schedule `:32-43`
  (`cron.dispatch_due` every 60s). No new task module needed for this work.
- `backend/app/config.py` — LLM fallbacks `:57-60`; no retry/timeout settings (those live in code).
- `backend/tests/` — `conftest.py` stubs env + `StubRedis`; two strategies (mocked-DB `summary_client`;
  real-PG rolled-back `test_prod_login.py`). **No LLM mocking exists yet — you will add monkeypatch points.**

### Frontend (`frontend-internal/`)
- LLM form: `components/llm/llm-config-form-dialog.tsx` (schema `:23-26`, defaults `:41-54`,
  2-col grid form `:121`, footer `:164-176`). Free-text provider/model; **no `<Select>` imported yet**.
- LLM page: `app/(dashboard)/llm-configs/page.tsx`.
- LLM zod: `lib/api/types.ts` (`LlmConfigCreate` `:137`, block `:112-159`).
- LLM hook: `lib/hooks/use-llm.ts` (`llmConfigKeys` `:32-36`, cache-update mutations).
- LLM API: `lib/api/llm.ts`.
- Cron config form (force-remerge checkbox `:188-203`): `components/cron/cron-config-form-dialog.tsx`.
- Backfill form (force-remerge checkbox `:153-168`): `components/cron/cron-backfill-form-dialog.tsx`.
- Cron config card (run-now confirm): `components/cron/cron-config-card.tsx`.
- Cron API/hooks: `lib/api/cron.ts`, `lib/api/cron-backfill.ts`, `lib/hooks/use-cron-config.ts`, `lib/hooks/use-cron-backfill.ts`.
- Controlled-`<Select>` pattern to copy: `components/cron/cron-config-form-dialog.tsx:159-174`.
- **`frontend-internal/AGENTS.md` warns this is a customized Next.js — read `node_modules/next/dist/docs/` before writing frontend code.**

---

## 3. Feature A + B — Merge never lies + per-patient retry

This is the core fix. All of it lives in `backend/app/tasks/merge.py` + `crud/merge_job.py`. **No
cron change is needed for the halt** — once the merge job ends `FAILED`, `_previous_step_failed`
(`cron.py:347-353`) already routes the run to failure and `_propagate_run_failed_to_backfill`
halts the backfill. (Feature C below adds a guard so cron does *not* retry the merge step.)

### B.1 — Refactor the per-patient body into a callable

Extract the existing per-patient try/except body (`merge.py:1366-1542`) into a helper, e.g.:

```python
def _merge_one_patient(db, rc, job, pid, *, cfg, prompt_template, force, log_key, chan, ...) -> str:
    """Attempt one patient. Returns one of: 'merged' | 'skipped' | 'failed'.
    On 'merged': writes merged_data, success llm_log, bump_counters(processed=1, succeeded=1), commit.
    On 'skipped': bump_counters(processed=1, skipped=1), commit  (missing row / already-merged / twin handled here).
    On 'failed':  rollback, write failed llm_log, NO counter bump (caller decides after all rounds).
    """
```

Keep the existing logic verbatim inside — just change the failure path to **not** call
`bump_counters(failed=1)` (the caller does that once, at the end, for patients that never merged).
Skips/twins stay terminal (they never enter the retry set). Success still bumps + commits inline so
the SSE live log keeps showing `[ok]` progress.

> **Why not bump `failed` inline?** Because a patient that fails round 1 and succeeds round 2 must
> count as exactly one success and zero failures. Counting failures only at the end (set-based)
> guarantees `processed = succeeded + failed + skipped` with no double-count. This is the single
> trickiest correctness point — get it right and unit-test it.

### B.2 — Wrap the loop in a shrinking round-retry

Replace the single `for pid in target_ids` loop (`merge.py:1308-1542`) with:

```python
_MERGE_ROUND_MAX = 4            # total passes over the still-failing set (1 initial + 3 retries).
                               # User asked for "retry 4 times" — tune here; keep it a named const.
_MERGE_ROUND_BACKOFF_SECONDS = 5  # short pause between rounds to dodge a momentary blip; NOT meant
                                  # to wait out a full outage (that's what fail-fast + re-run is for).

remaining = list(target_ids)
cancelled = False
for round_no in range(1, _MERGE_ROUND_MAX + 1):
    if not remaining:
        break
    if round_no > 1:
        _publish_line(rc, log_key, chan, f"[retry {round_no}/{_MERGE_ROUND_MAX}] {len(remaining)} patient(s)")
        time.sleep(_MERGE_ROUND_BACKOFF_SECONDS)   # bounded; worker is held — keep small
    still_failed = []
    for pid in remaining:
        if rc.get(cancel_key) == "1":
            cancelled = True
            break
        outcome = _merge_one_patient(db, rc, job, pid, ...)   # 'merged' | 'skipped' | 'failed'
        if outcome == "failed":
            still_failed.append(pid)
    if cancelled:
        break
    remaining = still_failed
```

Notes:
- Skips/twins resolve on round 1 and never re-enter (they don't return `'failed'`).
- A failed patient never set `merged_at`, so the `not force` skip-guard won't fire on retry — it gets
  a genuine fresh attempt. ✅ idempotent under both `force` and non-`force`.
- The cancel flag is checked every iteration **and** the loop breaks between rounds — preserve the
  existing cancel semantics (`merge.py:1311-1316`).
- Each real attempt still writes its own `llm_log` row (success or failure), so `llm_logs` naturally
  records every attempt — useful for the next outage post-mortem.

### B.3 — Decide status from the final state (the bug fix)

Factor the decision into a **pure function** so it's trivially unit-testable:

```python
def _final_merge_status(succeeded: int, failed: int, total: int, rounds: int) -> tuple[MergeStatus, str | None]:
    if failed > 0:
        # classify: if every failed patient's last llm_log error was an HTTP/transport error,
        # it's a provider outage; otherwise it's data/parse ("poison patient"). See §3.4.
        return MergeStatus.FAILED, f"merge incomplete: {failed}/{total} patient(s) unmerged after {rounds} round(s)"
    return MergeStatus.SUCCESS, None
```

Then replace the finalization block (`merge.py:1544-1567`):

```python
if cancelled:
    ... # unchanged: persist resource metrics, publish __cancelled__, return

# bump failed counters once, for everyone still unmerged
for _pid in remaining:
    merge_job_crud.bump_counters(db, job, processed=1, failed=1)
db.commit()

status, err = _final_merge_status(job.succeeded_count, job.failed_count, job.total_count, _MERGE_ROUND_MAX)
if status is MergeStatus.FAILED:
    merge_job_crud.mark_failed(db, job, duration, datetime.now(UTC), error_message=err, metrics=resource_metrics)
    _publish_line(rc, log_key, chan, f"done(FAILED): succeeded={job.succeeded_count} failed={job.failed_count} ...")
    rc.publish(chan, "__failed__")   # check existing SSE event vocabulary; merge SSE may expect __done__/__failed__
else:
    merge_job_crud.mark_success(db, job, duration, datetime.now(UTC), metrics=resource_metrics)
    rc.publish(chan, "__done__")
```

- Check `mark_failed`'s signature in `crud/merge_job.py:80-93` — confirm it accepts
  `error_message` + `metrics`; extend it if not (surgically).
- Check the SSE event the frontend listens for on a failed merge (grep `__failed__` / `__done__` in
  `frontend-internal` and in `routes/merge.py` SSE stream). Reuse the existing terminal-event name —
  do **not** invent a new SSE token the frontend doesn't handle.

### B.4 — Edge case: "poison patient" vs provider outage (foolproofing)

The user's spec is strict: **any** unmerged eligible patient after retries → `FAILED` + stop. That's
correct for an LLM outage (all patients fail with `LLM HTTP ...`). But a *single* patient with
malformed source data could fail forever and would then halt **every** backfill permanently.

**Mitigation (recommended, low-cost):** classify the failure in `error_message` so the operator can
tell the two apart at a glance, without changing control flow:
- If the last error for **all** still-failing patients matches `^LLM HTTP \d+` / transport
  (`RuntimeError` from `llm_chat.py:225`) → `error_message = "LLM provider unreachable: ... (N/total)"`.
- If at least one still-failing patient's last error is a parse/data error
  (`json.JSONDecodeError`/`ValueError` exhausted in `_chat_and_parse_with_retry`) →
  `error_message = "merge incomplete incl. non-transport error on patient <nik>: ..."`.

Keep the failure capture per patient (last error string) in a small dict during the loop. Surface
the classification in `error_message` only — control flow stays "any failure → FAILED". This gives
the operator a clear "this is the provider, retry later" vs "this is a bad record, investigate"
signal. **Flag this to the user in the PR description**; if they want poison patients to *not* halt
the run, that's a one-line policy change (treat non-transport single failures as `skipped`+logged),
but it's explicitly deferred per the chosen "strict" semantics.

### B.5 — Feature F: reclaim the already-mismarked jobs

Add a small **read-only ops script** (not a migration) at
`backend/scripts/find_silent_merge_failures.py` that prints, grouped by puskesmas, the
`(date_filter)` ranges of jobs that were silently mismarked:

```sql
SELECT m.puskesmas_id, p.name,
       min(m.date_filter), max(m.date_filter),
       count(*) AS jobs, sum(m.failed_count) AS patients_missed
FROM merge_jobs m JOIN puskesmas p ON p.id = m.puskesmas_id
WHERE m.deleted_at IS NULL          -- §6: explicit on non-SELECT? this is a SELECT, auto-filtered; keep for clarity
  AND m.status = 'success'
  AND m.succeeded_count = 0
  AND m.failed_count > 0
GROUP BY m.puskesmas_id, p.name
ORDER BY p.name;
```

The operator feeds those ranges into the existing **force-remerge backfill** (or the
`merge-with-ai` date-range flow) once the LLM is healthy. **Optional, ask before doing:** an UPDATE
to relabel historical rows `status='failed'` — if you do it, you MUST add
`WHERE ... AND deleted_at IS NULL` explicitly (§6) and confirm whether `MergeJob` is registered in
`backend/app/core/soft_delete.py` (the §6 list names ScrapeJob but `merge_jobs` carries `deleted_at`
and `WHERE deleted_at IS NULL` indexes — verify before relying on auto-filter for SELECTs). Default:
**don't rewrite history**; just report and re-merge.

---

## 4. Feature C — Cron `no_merge` mode (+ the `merge_mode` enum)

### C.1 — Data model (decision: enum, replaces `force_remerge`)

New PG enum `cron_merge_mode = ('normal', 'force_remerge', 'no_merge')`. Add a `merge_mode` column
(`NOT NULL DEFAULT 'normal'`) to **both** `cron_configs` and `cron_backfills`, and **drop the
`force_remerge` bool** from both after data-migrating it.

**Migration `0021_cron_merge_mode.py`** (follow `0007` for enum creation + the COMMIT caveat):

```python
def upgrade():
    bind = op.get_bind()
    mode = postgresql.ENUM("normal", "force_remerge", "no_merge", name="cron_merge_mode", create_type=False)
    mode.create(bind, checkfirst=True)
    for table in ("cron_configs", "cron_backfills"):
        op.add_column(table, sa.Column("merge_mode", mode, nullable=False, server_default="normal"))
        # data-migrate existing rows: force_remerge=True -> 'force_remerge'
        op.execute(f"UPDATE {table} SET merge_mode='force_remerge' WHERE force_remerge IS TRUE")
        op.drop_column(table, "force_remerge")

def downgrade():
    for table in ("cron_configs", "cron_backfills"):
        op.add_column(table, sa.Column("force_remerge", sa.Boolean(), nullable=False, server_default=sa.false()))
        op.execute(f"UPDATE {table} SET force_remerge=TRUE WHERE merge_mode='force_remerge'")
        op.drop_column(table, "merge_mode")
    postgresql.ENUM(name="cron_merge_mode").drop(op.get_bind(), checkfirst=True)
```

> No COMMIT dance needed here because we **create a brand-new type** (that's the `0007:20-37`
> pattern). The COMMIT-before-ALTER caveat (`0007:24-30`) only applies to `ALTER TYPE ... ADD VALUE`
> on an existing enum — which we are *not* doing.

Define the enum in Python at `backend/app/models/cron_config.py` (or a shared spot) so both models
import it:

```python
class CronMergeMode(str, enum.Enum):
    NORMAL = "normal"
    FORCE_REMERGE = "force_remerge"
    NO_MERGE = "no_merge"
```

Replace `force_remerge: Mapped[bool]` with `merge_mode: Mapped[CronMergeMode]` on both
`CronConfig` (`cron_config.py:32`) and `CronBackfill` (`cron_backfill.py:53-55`), using
`postgresql.ENUM(..., name="cron_merge_mode", create_type=False)` as the column type.

### C.2 — Schemas

- `CronConfigCreate` / `CronConfigUpdate` (`schemas/cron_config.py:7-21`): replace `force_remerge:
  bool` with `merge_mode: CronMergeMode = CronMergeMode.NORMAL` (Update: `| None = None`).
- `CronBackfillCreate` (`schemas/cron_backfill.py:9-19`): same.
- `*Out` schemas: expose `merge_mode`.
- The model-level enum makes invalid combos impossible — no extra validator needed.

### C.3 — Backend behavior

There are exactly two threading points; both read the parent's mode the same way `force` is read today.

1. **Resolve mode in `_create_child_job` (`cron.py:240-259`).** Today it derives a `force` bool from
   `CronBackfill.force_remerge` / `CronConfig.force_remerge`. Change it to read `merge_mode` and map:
   - `force_remerge` → create merge job with `force_remerge=True`.
   - `normal` → `force_remerge=False`.
   - `no_merge` → **this branch is never reached for the MERGE step** (see point 2).

   Factor a helper `_resolve_merge_mode(db, run) -> CronMergeMode` (mirror the existing
   `include_deleted=True` lookups) and use it in both places.

2. **Skip the merge step in `cron.advance` when mode is `no_merge`.** In `advance(...)`
   (`cron.py:356-493`), when the incoming `step == CronStep.MERGE.value`, resolve the mode first; if
   `no_merge`, **do not create/dispatch a merge child** — instead fall straight into the existing
   `step == "done"` finalization branch (`cron.py:399-424`): `mark_success` the run, and if it's a
   backfill, `advance_cursor` + `dispatch_backfill_next`. Cleanest shape:

   ```python
   if step == CronStep.MERGE.value and _resolve_merge_mode(db, run) is CronMergeMode.NO_MERGE:
       step = "done"   # fall through to the done branch below; EPUS+ASIK already ran
   ```

   Put this **after** the `_previous_step_failed` check (so a failed ASIK step still halts) and
   **before** the `if step == "done":` block. Result: EPUS→ASIK run normally, merge is skipped, the
   run/ backfill complete as success, patients are scraped with `merged_at` left NULL (ready for a
   later normal/force merge or the date-range `merge-with-ai` flow). ✅ composes with the operator's
   "scrape now, merge after the LLM is back" workflow.

3. **Run-now** (`routes/cron_config.py:189-249`) takes no body and inherits the config's mode — no
   change beyond the model swap. **Daily beat** path inherits config mode automatically.

### C.4 — Cron must NOT retry the merge step (decision 3)

Because the merge task now retries internally and marks `FAILED` on a real outage, cron's
`handle_failure` (`cron.py:496-575`) must **fail fast** for the merge step instead of its 3x retry:

```python
# in handle_failure, after resolving `failed = CronStep(step)`:
if failed is CronStep.MERGE:
    # merge.run already retried the failed-patient subset internally; another step-level
    # retry just hammers a down provider and delays the stop signal.
    err = <pull MergeJob.error_message>   # reuse the existing "max retries exhausted" error-pull block
    cron_run_crud.mark_failed(db, run, failed, err, now)
    _propagate_run_failed_to_backfill(db, run, err, now)
    return
# else: existing attempt < MAX_ATTEMPTS retry logic for ASIK/EPUS, unchanged
```

ASIK/EPUS keep their 3x retry. The backfill halts at the failed date (existing
`_propagate_run_failed_to_backfill` behavior) — exactly the desired "stop, something's wrong with
the LLM" outcome. The operator resumes by creating a fresh backfill after fixing the provider
(existing behavior — `cron_run.py:132-136` blocks retrying a backfill-owned run).

### C.5 — Frontend (3-way mode select)

Replace the lone `force_remerge` checkbox in **both** cron dialogs with a controlled `<Select>`
(copy the pattern at `cron-config-form-dialog.tsx:159-174`):

- Options: `Normal` / `Force re-merge` / `No merge (scrape only)`, mapping 1:1 to the enum.
- `components/cron/cron-config-form-dialog.tsx`: swap checkbox `:188-203`; update `FormValues`
  `:32-38`, `KNOWN_FIELDS` `:40-46`, and the zod `CronConfigCreate` (`types.ts:441-447`) from
  `force_remerge: z.boolean()` to `merge_mode: z.enum(["normal","force_remerge","no_merge"])`.
- `components/cron/cron-backfill-form-dialog.tsx`: swap checkbox `:153-168`; update zod
  `CronBackfillCreate` (`types.ts:489-499`) the same way; keep the `date_from <= date_to` refine.
- API modules `lib/api/cron.ts`, `lib/api/cron-backfill.ts`: send `merge_mode` instead of
  `force_remerge`. Hooks `use-cron-config.ts` / `use-cron-backfill.ts`: keep the cache-update
  pattern (§7.1) — just carry the new field.
- Run-now confirm copy (`cron-config-card.tsx:201-211`): update the description to reflect the
  config's mode (e.g. "No-merge: scrape only" when applicable).

---

## 5. Feature D — `reasoning_effort` on LlmConfig (provider-agnostic)

### D.1 — The provider-agnostic principle

Store **one normalized field** `reasoning_effort` on the config. `llm_chat.py` already maps a
normalized effort to each provider's wire format by **model-prefix sniffing** — extend that, don't
branch on `provider`. Mapping table (implement in `_openai_compat_chat` payload block `:135-185`):

| Model family (sniffer) | Wire param emitted | Notes |
|---|---|---|
| gpt-oss (`_is_gpt_oss`) | `reasoning_effort: <effort>` | already does this (`:173-180`), default "medium" |
| OpenAI o-series / gpt-5 (`_is_openai_reasoning_model`) | `reasoning_effort: <effort>` | **ADD this branch** — today none is emitted. gpt-5 also accepts `"minimal"`. |
| DeepSeek (`_is_deepseek`) | `thinking:{type:enabled}` + `reasoning_effort: <effort>` | already does this when `thinking` (`:160-172`); derive `thinking = effort not in (None,"none")` |
| anything else (plain chat model) | *(omit)* | unsupported → no-op, exactly today's behavior |

Allowed normalized values: `null` (=omit / provider default), `"low"`, `"medium"`, `"high"`, and
`"minimal"` (gpt-5 only; pass through — non-supporting providers simply ignore or you gate it).
Keep it a free-ish short string with an allowlist validator so new providers' levels are easy to add.

> If you want maximum tidiness, extract the payload assembly (`:135-185`) into a pure
> `_build_chat_payload(...) -> dict` helper so you can unit-test the per-provider mapping without
> hitting the network. Recommended — it also de-risks the new o-series branch.

### D.2 — Column + plumbing

1. **Migration `0022_llm_config_reasoning_effort.py`** — simple add-column (copy `0019:29-34`):
   ```python
   op.add_column("llm_configs", sa.Column("reasoning_effort", sa.String(length=16), nullable=True))
   ```
   (Nullable, no default → existing configs keep current behavior = "omit".)
2. **Model** `models/llm_config.py:10-22`: add `reasoning_effort: Mapped[str | None] = mapped_column(String(16), nullable=True)`.
3. **crud `load_only` lists** — add `LlmConfig.reasoning_effort` to **all three**: `get_active`
   `:23-32`, `get_active_for_captcha` `:35-47`, `get_active_for_chatbot` `:50-63`. **If you forget
   one, the field silently loads as unset at that call site.** (This is the easiest thing to miss.)
4. **Schemas** `schemas/llm.py`: add `reasoning_effort` to `LlmConfigCreate` `:85-95`,
   `LlmConfigUpdate` `:98-105`, `LlmConfigOut` `:108-122`. Add an `AfterValidator` allowlisting
   `{None,"minimal","low","medium","high"}` (mirror the `UsdPrice`/`LlmBaseUrl` validator style `:51-82`).
5. **Callers**:
   - Merge `merge.py:1138-1146`: pass `reasoning_effort=cfg.reasoning_effort`. (Today it passes
     neither; gpt-oss defaults to "medium". Passing `None` keeps that default — no behavior change
     until the operator sets a value.)
   - Chatbot `chatbot.py:94-107`: replace the hardcoded `reasoning_effort="high"` with
     `cfg.reasoning_effort or "high"` (preserve current chatbot behavior when unset). Keep
     `thinking=True` for chatbot or derive it; don't regress the explainer's answer quality.

### D.3 — Frontend

- Add a `reasoning_effort` `<Select>` to `llm-config-form-dialog.tsx` (options: Default/None, Low,
  Medium, High; the form has no `<Select>` import yet — add `@/components/ui/select` and use the
  controlled `form.watch`/`form.setValue` pattern). Place it as a half-width field near the prices
  (`:144-163`) or a `col-span-2` row above the footer.
- Add `reasoning_effort` to the zod `LlmConfigCreate`/`LlmConfigUpdate` (`types.ts:112-159`) as
  `z.enum([...]).nullish()`, to the form `defaultValues` (`:41-54`), and to the submit payload
  (`:74-108`) for both create and update.

---

## 6. Feature E — Test-connection

### E.1 — Backend endpoint

Add **one** endpoint to `routes/llm.py`, admin-gated like the rest:

```
POST /llm-configs/test
body: LlmConfigTestIn { provider, base_url, model, reasoning_effort?, api_key?, config_id? }
```

- Validation (`schemas/llm.py`): `base_url` reuses `LlmBaseUrl` (SSRF guard). Require **`api_key`
  OR `config_id`** (model_validator). If `api_key` is omitted and `config_id` is given, load that
  config and `decrypt_json(obj.api_key_enc)["api_key"]` (the `reveal` pattern `:237-246`). This
  single endpoint covers all three UI cases: create (typed key), edit (stored key, blank field),
  edit (new typed key).
- Handler: call `chat_complete(provider=..., base_url=..., api_key=..., model=...,
  prompt="Reply with exactly: OK", reasoning_effort=..., thinking=<derive>, max_tokens=512)`.
  - **`max_tokens` must be generous (≈512), NOT tiny.** Reasoning models spend tokens on hidden
    reasoning before emitting content; with `max_tokens=16` + `reasoning_effort=high` you get empty
    content and a false failure. This is a real footgun — document it inline.
  - Success ⇔ `chat_complete` returns non-empty `text`.
- Response `LlmConfigTestOut` `{ ok: bool, latency_ms: int | None, model: str, reply: str | None,
  error: str | None }`. **Return HTTP 200 for both ok and not-ok** — a reachable-but-misconfigured
  endpoint is a *test result*, not an API error, and the UI wants to render both inline without
  catch-noise. Reserve non-2xx (`{detail}`, §7.7) for actual misuse: bad body, unknown `config_id`,
  auth failure. On `chat_complete` raising `RuntimeError("LLM HTTP 530: ...")`, catch it and return
  `{ok:false, error:str(exc)[:1000]}`.
- **Do not write a billed `llm_log` row** for the test (keeps usage stats clean). If you want
  attribution, log with a distinct `source="llm_test"` so it's filterable — operator's call; default
  is no log.
- **Rate-limit** it (it decrypts a secret + makes an external call). Reuse the decrypt limiter
  pattern from `reveal` (`crud/llm_config.py:238`, `app/core/rate_limit.py`) or add a modest per-admin limit.

### E.2 — Frontend

- `lib/api/llm.ts`: add `testLlmConnection(body)` → `POST /llm-configs/test`, parse via
  `LlmConfigTestOut`.
- `lib/hooks/use-llm.ts`: add `useTestLlmConnection()` — a **plain mutation, no cache writes**
  (like `useRevealLlmConfigKey`).
- `llm-config-form-dialog.tsx`: add a **"Test connection"** `<Button type="button">` in the
  `<DialogFooter>` (`:164-176`), left of Cancel so it never submits the form. On click, call the
  mutation with `form.getValues()` (provider, base_url, model, reasoning_effort, `api_key` if typed,
  `config_id={config?.id}` when editing). Render the result inline: pending spinner → green "OK
  (123ms): <reply>" or red error (use `asApiError` only for true non-2xx; for `{ok:false}` show
  `result.error`). Don't `toast` per the inline pattern, or toast once — your call, keep it one event.

---

## 7. Test plan (`backend/tests/`)

There is no LLM mocking today — add it by monkeypatching at the **task/route module level** (mirror
how `conftest.py`'s `summary_client` monkeypatches `redis_client`/`request_warm`).

1. **`test_merge_status.py` (new)** — the highest-value tests:
   - Unit-test the pure `_final_merge_status(...)`: `(0,5,5)→FAILED`, `(5,0,5)→SUCCESS`, `(3,2,5)→FAILED`.
   - Round-retry accounting: monkeypatch `_merge_one_patient` (or the `chat_complete` it calls) to
     fail patient X on round 1 and succeed on round 2 → assert final `succeeded` counts X once,
     `failed=0`, status `SUCCESS`, and `processed == succeeded + failed + skipped`.
   - Total outage: make every patient fail every round → status `FAILED`, `failed_count==total`,
     `error_message` matches the "LLM provider unreachable" classification.
   - Cancel mid-round: set the cancel flag → job not marked success/failed (cancel branch).
2. **`test_cron_no_merge.py` (new)** — assert that with `merge_mode=no_merge`, `cron.advance` on the
   MERGE step does **not** call `_create_child_job` for merge and routes to the done/finalize path
   (run `success`, backfill cursor advances). Monkeypatch `_resolve_merge_mode` + Celery `send_task`
   to capture dispatches; assert `merge.run` is never sent.
3. **`test_llm_payload.py` (new)** — unit-test `_build_chat_payload(...)` (the extracted helper):
   gpt-oss → `reasoning_effort` present; o-series → present (regression for the new branch) +
   `max_completion_tokens` not `max_tokens` + no temperature; deepseek → `thinking` + effort; plain
   gpt-4o → neither.
4. **`test_llm_test_endpoint.py` (new)** — monkeypatch `chat_complete` on the route module:
   returns a `ChatResult` → 200 `{ok:true, reply:"OK"}`; raises `RuntimeError("LLM HTTP 530: x")` →
   200 `{ok:false, error:"LLM HTTP 530: x"}`. Unknown `config_id` → non-2xx `{detail}`.

Use the **real-PG rolled-back** strategy (`test_prod_login.py`) for anything that needs DB rows;
the **mocked-DB** strategy (`summary_client`) for pure logic. Gate DB tests with the same
`_db_available()` skip guard so the suite stays green without a migrated DB.

---

## 8. Execution checklist (do in this order; verify at each gate)

**Backend — merge (Features A, B, F):**
1. Extract `_merge_one_patient(...)`; move the failure path to *not* bump `failed`. → verify: existing single-patient path still merges one patient in a quick manual run.
2. Add round-retry loop + `_final_merge_status(...)` + corrected finalization. → verify: `test_merge_status.py` passes.
3. Extend `crud/merge_job.mark_failed` for `error_message`/`metrics` if needed. → verify: unit test.
4. Add `backend/scripts/find_silent_merge_failures.py`. → verify: runs locally, prints the grouped report.

**Backend — cron (Feature C):**
5. Migration `0021_cron_merge_mode` (create enum, add column to both tables, data-migrate, drop bool). → verify: `alembic upgrade head` then `alembic downgrade -1` then `upgrade head` round-trips clean on a scratch DB.
6. Models + schemas swap `force_remerge`→`merge_mode` (`CronConfig`, `CronBackfill`, their Create/Update/Out). → verify: app imports, `pytest` collects.
7. `_resolve_merge_mode` helper; update `_create_child_job` force resolution; add the `no_merge` skip in `cron.advance`; add the merge-step fail-fast in `handle_failure`. → verify: `test_cron_no_merge.py` passes.

**Backend — LLM (Features D, E):**
8. Migration `0022_llm_config_reasoning_effort` (add nullable column). → verify: round-trips.
9. Model + 3× `load_only` + schemas + validator; thread `reasoning_effort` into merge & chatbot callers. → verify: app imports.
10. Extract `_build_chat_payload`, add o-series `reasoning_effort` branch. → verify: `test_llm_payload.py` passes.
11. `POST /llm-configs/test` endpoint + `LlmConfigTestIn/Out` + rate-limit. → verify: `test_llm_test_endpoint.py` passes.

**Frontend (`frontend-internal/`):**
12. Read `frontend-internal/AGENTS.md` + the bundled Next docs first.
13. LLM form: add `reasoning_effort` Select + "Test connection" button + `useTestLlmConnection`; update zod/defaults/payload. → verify: `npm run build`/typecheck in `frontend-internal`; manual create+test against a known-good and a known-bad endpoint.
14. Cron config + backfill dialogs: swap checkbox → 3-way `<Select>`; update zod/KNOWN_FIELDS/API/hooks to send `merge_mode`. → verify: typecheck; manual create of each mode.

**Rollout:**
15. `alembic upgrade head` on the target DB.
16. **Restart `ckg-ai-celery_worker` AND `ckg-ai-celery_beat`** (project memory rule) — code under `backend/app/` won't take effect otherwise.
17. Smoke: trigger a `no_merge` run-now (no merge job created); trigger a normal run against a healthy LLM (merge succeeds); point a config at a dead URL and Test connection (clear error).
18. Once the gpt-oss endpoint is back, re-merge the ranges from step 4's report via a force-remerge backfill / the `merge-with-ai` date-range flow.

---

## 9. Foolproofness analysis (failure modes considered)

| Risk | Handling |
|---|---|
| **Counter double-count across retry rounds** | Failures bumped once, at the end, for the still-failing set only; successes bumped inline. `processed == succeeded+failed+skipped` is the invariant — unit-tested. |
| **Silent success on total outage** (the original bug) | Status derived from counters: `failed>0 ⇒ FAILED`. `mark_success` is no longer unconditional. |
| **Poison patient halts every backfill forever** | Strict semantics retained (any failure → stop) per decision, but `error_message` classifies transport-outage vs non-transport so the operator isn't misled. Escalation path documented (§3.4). |
| **Cron double-retrying a down provider** | `handle_failure` fails fast on the MERGE step (no 3x). The merge task already did its rounds. |
| **Re-merging already-succeeded patients on retry** | Retry set only ever contains patients that failed this run; `merged_at` guard also protects non-force re-runs. |
| **Cancel during retry** | Cancel flag checked every iteration and the loop breaks between rounds; cancel branch skips status finalization (route already wrote CANCELLED). |
| **Invalid mode combo (force+no-merge)** | Impossible — single enum, enforced at model + DB. |
| **`no_merge` losing data** | Patients are scraped; `merged_at` left NULL; a later normal/force run or date-range merge picks them up. Composes with the operator's workflow. |
| **Backfill silently skipping the failed date** | It doesn't — `_propagate_run_failed_to_backfill` halts the whole backfill at the failed date (desired). |
| **`reasoning_effort` not loaded at a call site** | Must be added to all 3 `load_only` lists; called out as the easy miss; covered by the payload test + a manual check. |
| **Test-connection false failure on reasoning models** | `max_tokens≈512` for the test so hidden reasoning doesn't starve the visible content. |
| **530 not retried at HTTP layer** | Intentional — 530 is a sustained origin-down signal. The round-level retry covers brief blips; fail-fast + alert covers real outages. (Option: add 530 to `_RETRYABLE_HTTP_STATUS` if you ever want one in-call retry — not recommended.) |
| **Worker held by inter-round `sleep`** | Backoff kept small (≈5s) and bounded by `_MERGE_ROUND_MAX`; it's a blip-dodge, not an outage-wait. |
| **Migration enum transaction trap** | We create a NEW enum type (`.create(checkfirst=True)`) — no `ALTER TYPE ADD VALUE`, so no COMMIT dance. Reuse-FAILED decision means **no** change to `merge_status` (no risky enum edit there). |
| **Frontend cache drift** | All new mutations keep the cache-update pattern; test-connection is a no-cache plain mutation. |

---

## 10. What this brief deliberately does NOT change
- Deterministic converters / merge field rules (CLAUDE.md §9).
- Chatbot knowledge packs (CLAUDE.md §10) — no pinned source changes here.
- `frontend-dashboard/` (read-only client app) — has no LLM/cron UI.
- The OpenAI-compatible `urllib` integration approach (no SDKs added).
- ASIK/EPUS scrape-step retry behavior (only the MERGE step's cron retry is suppressed).
- `merge_status` enum (reusing FAILED, decision 2).
