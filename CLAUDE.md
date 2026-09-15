# CLAUDE.md

Behavioral guidelines to reduce common LLM coding mistakes. Merge with project-specific instructions as needed.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

**This file is the contract for every machine and every agent working on this
repo.** More than one person works here, each with their own assistant, their own
settings, and their own habits — none of which travel. Only what is committed
here does. So a convention that lives in someone's head, in a chat, or in a
machine-local config **does not exist** as far as the next contributor's agent is
concerned: it will reason from the code in front of it, reach a different and
locally-reasonable conclusion, and ship it. If you learn something that should
constrain the next change — a workflow, a trap, an invariant, an incident —
**write it here, in the same PR**. Rules §11–§14 exist because each of them was
learned the expensive way.

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

## 5. SQLAlchemy Query Discipline

**Never SELECT *. Load only columns the endpoint actually returns.**

- Always use `load_only(Model.col1, Model.col2, ...)` on every ORM query.
- For joined relationships, chain `.load_only(...)` on the `joinedload(...)` option too.
- Some model columns are heavy blobs (e.g. `Puskesmas.epus_cred`, `Puskesmas.asik_cred`). Loading them when not needed wastes memory and bandwidth.
- Each endpoint/handler owns its query. Don't rely on a dependency that loaded a "full" ORM object and then access extra fields — the dep can't know what you need.
- For auth-gating only (no data needed), use deps that return just the UUID (`get_current_user_id`, `get_current_admin_id`) and write your own targeted query in the handler.

Pattern for a handler that joins a relationship:
```python
obj = db.scalar(
    select(Model)
    .options(
        load_only(Model.id, Model.field_a, Model.field_b),
        joinedload(Model.relation).load_only(Related.name),
    )
    .where(Model.id == some_id)
)
```

### 5.1 `contains_eager` when you need INNER JOIN + eager-load

When the query needs an explicit `.join(Model.relation)` (e.g. to gate on the parent — soft-delete guard via the auto-filter on the related table — or to filter against related columns) AND wants to eager-load that same relation, use `contains_eager`, NOT `joinedload`.

`joinedload(Model.rel)` emits a SECOND, separately-aliased LEFT OUTER JOIN. Combined with an explicit `.join(Model.rel)` you end up with two joins to the same table — wasteful and confusing.

`contains_eager(Model.rel)` attaches the eager-load to the explicit `.join(...)` — one join, used for both filtering and population.

Pattern (job-list with soft-delete-of-puskesmas guard):
```python
stmt = (
    select(Job)
    .join(Job.puskesmas)  # INNER JOIN — auto soft-delete filter on Puskesmas excludes orphans
    .options(
        load_only(*_JOB_OUT_COLS),
        contains_eager(Job.puskesmas).load_only(Puskesmas.name),
    )
    .order_by(Job.created_at.desc())
)
```

Use plain `joinedload(...)` only when you do NOT need an explicit join (e.g. LEFT OUTER eager-load where the relation may legitimately be missing and you want NULLs preserved).

For pure log/stream/exists-style endpoints that only need a column from the parent for a soft-delete check (no eager-load required), the bare `.join(Model.rel)` with no `contains_eager` / `joinedload` is correct and intentional. Match this pattern across sibling endpoints of the same resource — don't mix.

## 6. Soft-Delete Query Filtering

A global SQLAlchemy event listener in `backend/app/core/soft_delete.py` auto-injects `deleted_at IS NULL` into every SELECT that touches a `SoftDeleteMixin` model (`User`, `Admin`, `Patient`, `Puskesmas`, `LlmConfig`, `ScrapeJob`).

- **SELECTs**: filter is automatic — do not repeat it.
- **UPDATEs / DELETEs / raw SQL**: auto-filter does NOT apply — add `Model.deleted_at.is_(None)` to `.where(...)` explicitly.
- **Bypass**: use `.execution_options(include_deleted=True)` only when soft-deleted rows are intentionally wanted.

## 7. Frontend Conventions (Next.js + TanStack Query)

Stack: Next.js (App Router) + TypeScript + Tailwind v4 + TanStack Query v5 + zod + react-hook-form. Lives in `/frontend-internal`.

### 7.1 Cache-update over refetch
Mutations MUST update the TanStack Query cache directly in `onSuccess`. Do NOT call `invalidateQueries` or `refetch` to "just refresh the list" after a CRUD mutation. Allowed exceptions:
- The mutation has side-effects on unrelated queries the server computes (justify in a comment).
- A terminal SSE event arrives (e.g. scrape `done`) and the server holds derived totals — invalidate exactly the affected detail key, once.
- The user explicitly asks to refresh.

Pattern:
```ts
onSuccess: (created) => {
  qc.setQueryData(keys.detail(created.id), created);
  qc.setQueriesData<Page<T>>({ queryKey: keys.all }, (old) =>
    old ? { ...old, items: [created, ...old.items], total: old.total + 1 } : old);
}
```

### 7.2 Lazy data fetching
- Queries live inside the page component that needs them — never in `(dashboard)/layout.tsx` or above.
- The dashboard layout fires only `GET /admin/auth/me` (cached `staleTime: Infinity`).
- Sidebar `<Link>` uses `prefetch={false}` — navigation is the only fetch trigger.
- For lists rendered on demand (form selects, etc.), pass `enabled` to gate the query on the open state.
- No polling. Status comes from SSE; one final invalidate on terminal event.

### 7.3 Query-key factory per resource
Every `lib/hooks/use-<resource>.ts` exports a `<resource>Keys` object. Never inline string-array keys at call sites.

### 7.4 Pagination
List queries take `{ page, size }` in their key and use `placeholderData: keepPreviousData`. Reset `page = 1` whenever a filter input changes.

### 7.5 Forms
react-hook-form + zod resolver. Schemas live in `lib/api/types.ts` next to the API type so one definition drives both runtime validation and TypeScript inference (`z.infer<typeof X>`). Reset form on dialog open via `useEffect`, not on render.

### 7.6 Auth & API client
- JWT stored in `localStorage["ckg.auth"]` as `{ token, exp }`. Read via `useAuth()` from the zustand store hydrated by `useAuthHydration()` in the providers.
- Single axios instance in `lib/api/client.ts` attaches `Authorization: Bearer <token>`. On 401 it clears auth and redirects to `/login`.
- Per-resource API modules in `lib/api/*.ts` parse responses through zod. Never call `axios` directly from a component.

### 7.7 Error responses (one shape, many messages)

Backend contract: every non-2xx response body is `{"detail": "<string>"}`. Multiple errors are joined with `"; "` (the backend's 422 handler in `backend/app/main.py` enforces this for Pydantic errors). Field-validation messages are prefixed with the field path, e.g. `"email: value is not a valid email; password: too short"`.

Frontend rules:
- Always parse errors via `asApiError(err)` from `lib/api/client.ts`. Returns `{ status, message, messages, fieldErrors }`. Never read `error.response.data` directly.
- For toast display, pass `asApiError(err).message` — it is newline-joined and renders multi-line in sonner.
- For forms, do **not** call `toast.error` in the `catch` block. Use `applyApiErrorToForm(err, form.setError, KNOWN_FIELDS)` from `lib/api/form-errors.ts`. It maps prefixed messages → `setError` per field and toasts any leftover non-field messages. `KNOWN_FIELDS` is a `readonly` tuple of the schema's paths.
- For inline rendering (page-level error states), use `<ErrorState error={...} />` — it renders a bulleted list for multiple messages and a single line for one.
- Never iterate `toast.error(...)` per message. One error event = one toast.
- Backend rule: never raise `HTTPException(detail=[...])` or `HTTPException(detail={...})`. If multiple business errors must surface, join with `"; "`.

### 7.8 SSE
Use the native `EventSource` with `?token=<JWT>` query param (the backend reads token from query for SSE compatibility). Always `close()` on unmount. On `done`/`failed`/`cancelled` events: close the stream and `qc.invalidateQueries({ queryKey: scrapeKeys.detail(jobId) })` exactly once to refresh server-computed totals.

### 7.9 Performance rules (Vercel React best-practices)
- No barrel imports (`bundle-barrel-imports`) — import directly from the file.
- `next/dynamic` for heavy charts and rarely-rendered widgets (`bundle-dynamic-imports`); see `app/(dashboard)/llm-logs/page.tsx` for `UsageChart`.
- Stable query keys via the factory; memoize the query object with `useMemo` when it depends on multiple inputs.
- Functional `setState` (`rerender-functional-setstate`).
- No components defined inside other components (`rerender-no-inline-components`).
- Don't subscribe to state only used in callbacks (`rerender-defer-reads`) — read from the zustand store with a selector.

### 7.10 File layout
- `app/` — routing only. Pages stay thin and compose components.
- `components/ui/` — primitive UI (buttons, inputs, dialogs).
- `components/<domain>/` — domain-specific composites (e.g. `puskesmas/`, `scrape/`).
- `components/common/` — cross-cutting: `PageHeader`, `Pagination`, `ConfirmDialog`, `EmptyState`, `ErrorState`.
- `lib/api/` — transport (one module per resource).
- `lib/hooks/` — TanStack Query hooks (one module per resource).
- `lib/` — pure utilities (env, cn, auth storage).

### 7.11 What NOT to do
- Don't add a global `<Toaster />` per page; it's already mounted once in `app/providers.tsx`.
- Don't put TanStack Query hooks behind another wrapper hook unless reuse is real.
- Don't add server actions or RSC fetching — every API call goes through the client (CORS-allowlisted FastAPI on :8000).
- Don't read tokens from cookies — backend expects `Authorization` header (or `?token=` for SSE).

### 7.12 List filter state in zustand (no URL params)
List pages that link to a detail page MUST keep their filter/search/pagination state in a per-resource zustand store under `lib/stores/<resource>-list-store.ts`, NOT in `useState`.

Why: `useState` dies when the list component unmounts on detail navigation, so the in-page Back button (and browser back) land on a fresh list with all filters reset. A zustand store outlives the unmount, and TanStack Query cache-hits on the same factory key — instant restore, no extra fetch.

Why not URL params: this app intentionally keeps the SPA feel — no `?page=` / `?name=` in the address bar.

Rules:
- One store per resource: `usePuskesmasListStore`, `useScrapeJobsListStore`, etc. File: `lib/stores/<resource>-list-store.ts`.
- Store shape: one field per filter + `setX()` per field + `reset()`. Any setter that changes a filter MUST reset `page` to 1.
- In-memory only — no `persist` middleware. Hard reload resets to defaults.
- Read via individual selectors (`s.page`, `s.name`, …) — don't subscribe to the whole store object.
- Truly local UI state (open/close dialog, "editing" row) stays in `useState`. Only navigation-relevant state belongs in the store.
- Detail-page Back link stays a plain `<Link href="/<resource>">` — no `router.back()`, no `from` query param.
- Lists without a detail route (`users`, `llm-configs`, `llm-logs`) may keep `useState` until they add one.

### 7.13 Debounce text-search filters

Free-text inputs that feed a TanStack Query key MUST be debounced before entering the key. Use `useDebouncedValue` from `lib/hooks/use-debounced-value.ts` with the default 300 ms delay. The raw value still drives the `<Input>` (and the zustand list store, per 7.12) so typing feels instant; only the query input is debounced.

Pattern:
```ts
const name = usePuskesmasListStore((s) => s.name);
const debouncedName = useDebouncedValue(name);
const query = useMemo(
  () => ({ page, size: 20, name: debouncedName.trim() || undefined }),
  [page, debouncedName],
);
```

Does NOT apply to:
- `<Select>`, checkbox, date picker — single deliberate commit, no per-keystroke firing.
- Inputs that filter client-side only (no API round-trip).

If a screen needs a different delay, pass it explicitly (`useDebouncedValue(value, 500)`) and add a one-line comment explaining why.

### 7.14 API-backed dropdowns

Any picker whose options come from a paginated API MUST use `components/ui/async-combobox.tsx`. Required behaviors: (1) fixed max-height with a scrollable list region so long results never overflow the viewport; (2) infinite scroll via `useInfiniteQuery` + IntersectionObserver sentinel that calls `fetchNextPage` when the bottom comes into view; (3) debounced search input (`useDebouncedValue`) that drives the server-side `name`-style filter.

Static-option dropdowns (fixed enums, day/month) keep using `<Select>`.

Define a resource adapter hook following this signature:
```ts
function useFooOptions(search: string): {
  options: { id: string; label: string }[];
  isLoading: boolean;
  isFetchingNextPage: boolean;
  hasNextPage: boolean;
  fetchNextPage: () => void;
  error: unknown;
}
```

Use a separate `infiniteList` key namespace in the query-key factory (e.g. `fooKeys.infiniteList(q)`) so that existing `setQueriesData` mutation patches against `fooKeys.lists()` do not collide with `InfiniteData<Page<T>>` shape. Update each mutation's `onSuccess` to also patch `infiniteLists()`.

When a selected id may not be in the loaded pages (edit forms, persisted filters), pass `selectedLabel` from the resource's detail-cache so the trigger renders the correct name immediately:

```tsx
<AsyncCombobox
  value={value}
  onChange={onChange}
  useOptions={useFooOptions}
  selectedLabel={detailQuery.data?.name}
  placeholder="Select…"
/>
```

## 8. Never write N+1 queries

An **N+1** is any code path where one logical operation issues `1 + N` round-trips that scale with input size: a parent fetch (1) plus a per-child fetch (N). The same shape shows up in background tasks that poll a database row each iteration of a long loop. Treat these as bugs, not optimizations — fix them at write time.

### 8.1 Eager-load every relation you will read

Any relation accessed during response serialization or downstream logic MUST be eager-loaded in the same query that fetched the parent — via `joinedload(...)` or `contains_eager(...)` per §5.1 — paired with `load_only(...)` so the eager-load doesn't drag heavy blobs.

Never rely on lazy-load triggering during `_to_out(...)` / Pydantic serialization / template rendering. By the time SQLAlchemy emits the per-row SELECT, you've already lost.

### 8.2 Don't poll Postgres in long-running task loops

Background tasks (Celery jobs, batch processors) often need to react to external state — typically a cancel signal. Do NOT do this with `db.refresh(job, ["status"])` or any per-iteration `select(...)`. For a job processing N patients, that's N extra SELECTs each round-trip and per-tick TCP latency. It also keeps the row hot in the DB cache for no reason.

**Use Redis as the cancel/control signal.** The mutating route writes a flag; the worker polls Redis (already an open in-process connection in our pattern) each iteration.

Pattern (already in use for `merge:job:*` and `scrape:job:*`):

```python
# Helper, alongside _log_key / _stream_chan in the task module:
def _cancel_key(job_id: str) -> str:
    return f"<resource>:job:{job_id}:cancel"

# In the cancel route — write the flag with a generous TTL:
crud.mark_cancelled(db, obj)
redis_client().set(f"<resource>:job:{job_id}:cancel", "1", ex=86400)

# In the task loop — read the flag, never refresh the ORM:
cancel_key = _cancel_key(job_id)
for item in target_ids:
    try:
        if rc.get(cancel_key) == "1":
            cancelled = True
            break
    except Exception:
        pass
    ...
```

The one-shot status check at task start (before the loop, to honor a cancel that arrived while PENDING) and the recovery check inside the outer exception handler may stay as DB lookups — they fire at most twice per task lifetime, so they don't scale with input.

### 8.3 Batch when you need data for N ids

If you have a list of N IDs and need a column for each, write ONE query: `WHERE id IN (...)` or `WHERE id = ANY(:ids)`, build a `{id: row}` dict, then iterate in Python. Never `for id in ids: db.scalar(select(...).where(... == id))`.

### 8.4 Pipeline fan-out IO

Multiple Redis or HTTP calls inside a loop? Use `redis_client.pipeline()` for Redis (one round-trip), and `asyncio.gather` / a single multi-get for HTTP. Same principle: replace `1 + N` round-trips with `1`.

### 8.5 Rule of thumb

If a code path's query count grows with input size, and each query has the same shape, you have an N+1. Either:
1. Fold them into one batched query, OR
2. Move the per-iteration signal out of the database (Redis, in-memory state, etc.).

Code review should flag this on first read. Don't merge it.

## 9. Patient merge + form research

The merge (`backend/app/tasks/merge.py`) is **backend-deterministic**, not LLM-driven:

- The LLM is given `(converted-source, raw ASIK)` and emits items **only for both-filled
  fields it must judge for conflict**. Patient identity is **withheld from the LLM**:
  `_strip_identitas_for_llm` trims `identitas_pasien` to `Jenis Kelamin` / `Tanggal Lahir`
  / `Tempat Lahir` (age/sex context for the plausibility check) and the raw ASIK
  `detail_data` block is dropped from the prompt — the backend still consumes the full
  `converted` / `asik`. The backend owns field **presence + raw values + status** via
  `_complete_source_fields` / `_rebuild_identitas` / `_normalize_status_flags`
  (it adds every one-sided/empty source field, overwrites values from source, **prunes
  anything not in a source** → zero hallucination).
- **Clinical fields: source (ePuskesmas) wins** every conflict; ASIK fills gaps.
  **Identitas is the INVERSE — ASIK-wins**: `_rebuild_identitas` builds identity from
  source + ASIK `detail_data`, taking the ASIK value when present and using ePuskesmas
  only to fill gaps (ASIK is the system of record for identity). Rendered first on the
  detail page.
- Consequence: field presence/values/status are **model-independent** (all models produce
  byte-identical merges). So **merge data quality ≈ converter quality**, not prompt/model.
  The quality bottleneck is `app/services/<source>_to_asik.py`.

**Do NOT hand-roll converter audits / coverage / drift / hallucination checks.** Use the
**`ckg-form-research` skill** (`.claude/skills/ckg-form-research/`) — it's the canonical,
generalized (`--source X`) tooling for: adding a data source, auditing/extending a
`<source>_to_asik` converter, detecting ASIK drift, and verifying merge quality. Start at
its `RESEARCH_STATUS.md` (`.claude/skills/ckg-form-research/RESEARCH_STATUS.md`).

When you change a converter or anything under `backend/app/`: **restart the Celery worker**
and **re-merge** affected patients with `force_remerge` (see project memory).

## 10. Chatbot knowledge packs (`chatbot/`)

frontend-dashboard ships an explainer chatbot whose ONLY knowledge is
`chatbot/knowledge/*.md` (Indonesian, fact-only; composed with
`chatbot/system.md` per `chatbot/manifest.json`). The packs are a distillation
of the code — never write a rule there from general knowledge; **the code
always wins** (client-feedback changes often ship without a docs update).

**Whenever you change any logic, label, threshold, feature, page, or on-screen
copy that the chatbot describes, update the affected `chatbot/knowledge/*.md`
pack IN THE SAME change.** The chatbot is live for clients: if the code and the
packs disagree, users get wrong answers about what they see on screen, and that
confusion is the whole failure mode this rule exists to prevent. This is
**behavior-driven, not hash-driven** — the `knowledge.lock.json` hash-lock below
only catches edits to *pinned* sources, but a pack can also describe a
NON-pinned file (e.g. a patient-detail component) and go stale silently. Do not
rely on the lock alone: if you touched anything a pack talks about (backend
logic, a route, a threshold/band, a filter, a UI label/layout/flow), open that
pack and reconcile every claim — and keep the three surfaces that share this
content in sync (the pack, the "Cara Membaca" formula card, the Excel "Formula &
Logika" sheet). `manifest.json` maps page → packs when you're unsure which pack.

**It triggers more often than you think.** Assume you owe the packs an update if
your change touches any of these — this is the list people skip:

- a **user-visible string** in either app: a chart/card/page title, an axis or
  legend label, a button, a tooltip, an empty/error message;
- a **number the bot quotes**: a threshold, a band, a denominator, a percentage
  base, a date floor, a cache TTL;
- **what a chart plots** — swapping a Y axis from absolute counts to a share
  changes what the bot must say about it, even though no backend code moved;
- a **page**: added, removed, renamed, re-routed (then also do the 4-step
  route wiring in `frontend-dashboard/AGENTS.md` — the page key is a strict enum
  in THREE places);
- **filters, ordering, or gating** that change which rows a user sees;
- **moving a described file** — including into `frontend-shared/`. The claim did
  not change, but its pin did (§11.6, §12.3).

A pure refactor usually changes no claim — still re-read the pack, because
"usually" is doing real work in that sentence.

If you change ANY pinned source file (`chatbot/knowledge.lock.json` lists
them — the hipertensi registry scan, report routes, dashboard scan/cards, the
formula card, the dashboard/registry pages, the shared charts + charts grid):

1. Re-read the affected pack(s) and update any claim that changed (a pure
   refactor changes the hash but usually no claims — still re-check).
2. Re-bless: `cd backend && python scripts/bless_chatbot_knowledge.py`
3. `pytest tests/test_chatbot_knowledge.py` must pass (hash lock +
   byte-identical label/threshold greps). Commit pack + lock in the same PR.

**⛔ Steps 2–3 are NOT optional, and editing the pack prose is NOT a substitute
for them.** The lock stores each pinned file's *content hash*; touching the source
file — even a pure refactor, even while correctly reconciling the pack — changes
that hash. Skip the re-bless and `test_pinned_sources_match_lock` lands **RED on
master and stays red until someone else re-blesses**, blocking everyone's CI.
**This has happened:** the 2026-07-21 Hipertensi chart-2 Y-axis revert edited two
pinned chart files and reconciled `dashboard.md`, but never re-blessed — master
shipped red. So: after ANY edit to a pinned source, **run step 3 and watch it pass
before you commit.** `knowledge.lock.json` (the refreshed lock) MUST be in the same
commit as the source change. If a pinned file moved/renamed, its pin path moves too
(§11.6, §12.3).

Keep the packs in sync with the user-facing "Cara Membaca Kertas Kerja Ini"
card and the Excel "Formula & Logika" sheet — the bot must never contradict
what is on screen. Full contract: `chatbot/README.md`.

---

## 11. `frontend-shared/` — two apps, ONE source (read before touching any UI)

There are two Next.js apps: **frontend-internal** (admin) and **frontend-dashboard**
(client). Most of what they show is the same. `frontend-shared/` exists so that
sameness is written **once**. Full mechanism + host contract:
**`frontend-shared/README.md` — read it before your first edit here.**

### 11.1 The rule

> **If both apps show it, it lives in `frontend-shared/`. No exceptions.**

Before you write or edit a component, hook, store, api module, type, or a
user-visible string in either app, answer one question:

> *Does the other app show this too?*

- **Yes** → write it in `frontend-shared/`, import it from both apps. Even if
  only one app needs it *today* and the other is "a follow-up".
- **No** → it stays in that app.
- **Unsure** → it goes in `frontend-shared/`. Pulling something back out to one
  app later is cheap; hunting two drifted copies later is not.

### 11.2 The tell: you are about to make the same edit twice

**If you catch yourself applying the same change to both
`frontend-dashboard/…` and `frontend-internal/…`, STOP.** That is not "keeping
them in sync" — that is the bug this directory exists to prevent. Go move the
code to `frontend-shared/` and make the edit once.

A block that is byte-identical in both apps is a **defect**, not a coincidence.
It does not matter that the copies agree right now. They agree until the next
edit, and then one ships a change the other silently doesn't — the client app
and the admin app show different numbers for the same metric, and nobody finds
out until a client asks.

### 11.3 Extracting the leaf is NOT single-sourcing

The thing that drifts is the **call site**, not the leaf component. If you lift a
small presentational helper into `frontend-shared/` but leave the code that
*configures* it — the titles, colours, nouns, denominators, thresholds, copy —
copy-pasted in both apps, you have moved 12 lines and left the 110 lines that
actually drift. **Share the whole rendered unit** (the card, the grid, the
section), so that a title or a denominator exists in exactly one file.

Corollary: **do not leave a copy behind.** Once something is in
`frontend-shared/`, the per-app copy is stale code — delete it in the same
change, along with any import/helper your deletion orphaned.

### 11.4 What legitimately stays per-app

Only these. Anything else is duplication looking for an excuse:

- **Host-contract primitives** — `@/components/ui/*`, `@/components/common/*`,
  `@/lib/api/client`, `@/lib/utils`, the hooks listed in the README. Both apps
  keep their own at identical paths; shared code imports them via `@/`.
- **App-specific chrome and behavior** — the internal action bar / Show-browser /
  Sync buttons / clear-cache control, the internal Diagnose tab, each app's page
  header and picker wiring. Per README rule 2 these must **never** be reachable
  from `frontend-shared/`; inject them as a `ReactNode` slot prop instead, so an
  internal-only mutation can never render in the client bundle.
- **Mutation API modules and their hooks** where only one app is allowed the
  mutation (e.g. internal's `clearHipertensiChartsCache`).

### 11.5 `_shared/` is a build artifact — never edit it, never commit it

`frontend-dashboard/_shared/` and `frontend-internal/_shared/` are **generated
copies** of `frontend-shared/`, gitignored, wiped and regenerated on every sync.
Editing a file under `_shared/` is editing a build artifact: your change is
destroyed on the next `sync-shared` and cannot be committed. If a file you want
to change is under `_shared/`, the real file is the same path under
`frontend-shared/`.

`next dev` syncs once at startup. If you edit `frontend-shared/` while a dev
server is running, re-run `npm run sync-shared` (dashboard) / `pnpm sync-shared`
(internal) or restart dev, or you will debug a stale copy.

### 11.6 Checklist for any change under `frontend-shared/`

1. **Both apps typecheck.** `frontend-shared/` has no build of its own — a break
   only shows up in a consumer. Run **both**, every time:
   `cd frontend-dashboard && npm run typecheck` **and**
   `cd frontend-internal && pnpm typecheck`. Passing one proves nothing about
   the other.
2. **Imports obey the host contract.** Only `@/` paths the README lists, plus
   the bare deps in README rule 3 (same major in both `package.json`).
3. **Charts stay lazy.** Heavy recharts widgets load via `next/dynamic` with
   `ssr: false` (README rule 4) — recharts v3 renders nothing server-side, so
   SSR only costs bundle weight.
4. **Chatbot pins follow the code.** If you move a file the chatbot packs
   describe, the pin must move with it — see §10 and §12.3.
5. **Deploy rebuilds both frontends** when anything under `frontend-shared/`
   changes (`.claude/skills/ckg-deploy/preflight.sh` detects this). Never ship
   one app against a changed shared tree.

## 12. Don't let a bug survive the push

`master` deploys to a live clinical app. These are the cheap checks that catch
the failures we have actually shipped — run them before you say a change is
done, not after review.

### 12.1 Verify what you changed, in the layer you changed it

| You touched | You must run |
|---|---|
| `frontend-shared/**` | **both** apps' typecheck (§11.6) + lint |
| either `frontend-*/**` | that app's `typecheck` + `lint` |
| `backend/app/**` | `pytest` for the affected area + **restart the Celery worker** |
| a chatbot-pinned source | re-bless + `pytest tests/test_chatbot_knowledge.py` (§10) |
| a `<source>_to_asik` converter | the `ckg-form-research` tooling + re-merge with `force_remerge` (§9) |

"It typechecks" is not "it works". Typecheck and lint prove the code compiles —
they say nothing about what renders. For a visible change, say plainly in your
report **whether you looked at it in a browser or not**; an unverified claim that
something renders correctly is worse than an honest "not verified visually".

### 12.2 Report honestly

State what you ran and what it said. If a check failed, say so with the output.
If you skipped one, say which and why. Never describe a change as verified on
the strength of a check you did not run.

### 12.3 A guard you add must be a guard that can't be dropped

When you extend a drift guard, wire it **all the way**. Adding a file to
`PINNED_SOURCES` in `backend/scripts/bless_chatbot_knowledge.py` without also
adding it to `REQUIRED_PINNED` in `backend/tests/test_chatbot_knowledge.py`
gives a pin that any later edit can silently remove with no test failing — a
guard that looks present and isn't. Same principle everywhere: a check nothing
enforces is documentation, not a check.

## 13. Production is not a scratchpad

The prod server (`simpus-app-prd`) runs the live app on **finite disk**. It has
already been taken down by a maintenance command that was "just a read": a
**dump of the prod database written onto the prod VPS filled the disk and caused
an outage**. Postgres cannot write to a full disk, so the app dies — and the
dump that caused it is the thing you have to delete to recover.

**Never write bulk data onto the prod VPS.** No `pg_dump`, no `docker cp` of a
volume, no CSV/JSON export of a table, no log tarball, no `tar` of anything —
not to `~`, not to `/tmp`, not "just for a minute". Size on disk is not
proportional to how quick the command felt.

If you genuinely need prod data:

1. **Ask Akbar first.** Say what you need, why, and how large it will be.
2. Prefer **not copying it at all** — answer the question with a `psql` query
   that returns counts/aggregates (`docker exec ckg-ai-postgres-1 psql -U ckg_ai
   -d ckg_ai -c "SELECT count(*) …"`). Almost every "I need a dump" is really a
   question a `SELECT count(*)` answers.
3. If a dump is truly required: `df -h /` **first**, confirm free space is
   several times the expected size, stream it **off-box** rather than landing it
   on prod, and delete it in the same session — named explicitly, per the global
   delete rules.

Also on prod, per `.claude/skills/ckg-deploy/SKILL.md`:

- **Never touch `postgres` or `redis`** — no `build`, `stop`, `rm`, `restart`,
  `down`, or recreate. After any deploy, confirm `postgres` uptime is
  **unchanged** as proof.
- **Never `docker ... prune`** or any bulk/`--all` cleanup, including when disk
  is full. A full disk is a **stop-and-ask**, not a self-authorized cleanup.
- **Never delete or modify existing `.env` values**; only add missing keys.
- **Never silently kill in-flight work** (scrape / merge / warm / cron) — the
  preflight inventories it; confirm kill-vs-resume with Akbar.

Report a disk problem. Do not fix it by deleting things.

## 14. Destructive commands, and who owns the history

These are not style preferences. Each one has already cost real work — locally
and on the server. They apply on **any** machine, to **any** agent working here.

### 14.1 Never delete what you did not create

Only ever delete, remove, or stop a resource **you created in this session**,
named **explicitly**. Never a broad, machine-wide, or "unused" sweep.

- **No `prune`, ever** — `docker system/container/image/volume/network/builder
  prune`. A machine-wide `docker container prune` once wiped every stopped
  container on a dev machine. **Stopped ≠ garbage**: containers are kept
  deliberately, to be started on demand.
- No `docker rm` / `rmi` / `volume rm` / `network rm` on anything you did not
  create this session. No `docker compose down -v` or `--remove-orphans`.
- No `rm -rf`, bulk delete, `git clean`, or `git reset --hard` over files you
  did not create this session.

**Before any delete: list what it will affect** (`docker ps -a`, `ls`) and
confirm every item is yours. If you cannot *prove* an item is yours, leave it.
If a problem seems to call for cleanup (disk full, port taken), **stop and ask** —
describe the situation and propose the minimal, named fix. Do not self-authorize.

### 14.2 Clean up what you *did* start

- Long-running processes you started (`next dev`, watchers, tunnels, Playwright
  or agent-browser sessions) — kill them before you finish. If one must stay up,
  say so explicitly with its PID and port. Never orphan a dev server. Only kill
  processes **you** started.
- Debug/one-off scripts — do not leave them in the repo or on the server. If one
  is genuinely worth keeping, say so explicitly and get a decision.

### 14.3 Akbar owns the branches and the history

- **Never create a branch** — not "to be safe", not a backup branch. Work on the
  checked-out branch. If you think a new branch is needed, ask, and say which
  parent you would use.
- **Never commit or push unless explicitly told to.** Finish the work, leave the
  tree dirty, and report what changed. Do not `git add`. Do not offer a
  "checkpoint commit" and then make it — offer, and wait.
- **Never rewrite history on your own** — no `reset --hard`, `rebase`,
  `commit --amend`, or force-push. When a reset *is* asked for, check the
  topology first (`git log --oneline <parent>..HEAD`, check for an upstream) and
  prove afterwards that nothing was lost.

### 14.4 "Check" / "review" / "investigate" means report, then stop

If the request is to look into something, **the findings are the deliverable** —
not a diff. Do not fix, refactor, commit, or deploy off the back of it, however
small or certain the fix. Report, propose, wait for an explicit go. Certainty is
not authorization; if you cannot tell whether a report or an implementation is
wanted, ask. One question is cheap; a wrong large diff burns review time, which
is the scarce resource here.

---

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.
