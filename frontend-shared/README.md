# frontend-shared

Single source of truth for UI/logic shared between **frontend-internal** (admin)
and **frontend-dashboard** (client). Edit a feature **here once** — both apps get
it. This exists so the two apps never drift out of sync.

## How it works (the copy, not a path alias)

Each app syncs this tree into a **gitignored `./_shared/`** before `dev` /
`build` / `typecheck`:

```
node ../frontend-shared/sync.mjs ./_shared   # run by the app's npm/pnpm scripts
```

`@shared/*` resolves to `./_shared/*` (see each app's `tsconfig.json`). Because
the synced files live **inside** the app dir, TypeScript, Tailwind's `@source`
scan, and Next's `output: "standalone"` tracing all resolve them with **zero**
monorepo/tsconfig/outputFileTracingRoot hacks — `react`, `@types/react`, etc.
resolve via the app's own `node_modules`.

`_shared/` is a build artifact: **never edit it, never commit it.** It is
regenerated (and stale files pruned) on every sync.

### Dev note
`next dev` syncs once at startup. If you edit a file here **while** a dev server
is running, re-run `pnpm sync-shared` (or `npm run sync-shared`) in that app, or
restart dev, to pick it up.

### Docker / deploy
Each app's Dockerfile does `COPY frontend-shared/ /frontend-shared/`; the build
script then syncs it into `/app/_shared`. The deploy preflight
(`.claude/skills/ckg-deploy/preflight.sh`) rebuilds **both** frontends when
anything under `frontend-shared/` changes.

## The host contract (what each app must provide)

Shared components import app-provided primitives via the `@/` alias. Both apps
**must** keep these at identical paths with compatible APIs:

- `@/components/ui/*` — button, input, label, select, table, switch, badge,
  card, popover, async-combobox
- `@/components/common/*` — page-header, pagination, empty-state, error-state
- `@/lib/api/client` — `http`, `asApiError`
- `@/lib/utils` — `cn`
- `@/lib/hooks/use-debounced-value`, `@/lib/hooks/use-puskesmas`,
  `@/lib/hooks/use-is-admin`
- `@/lib/api/hipertensi-charts` — the `ChartsMonthPoint` / `HipertensiCharts`
  **types** only (the hipertensi charts read them). Each app keeps its own
  module: internal additionally exports a clear-cache mutation, which per rule 2
  must not be reachable from here.
- **CSS custom properties** in each app's `app/globals.css`, under **both**
  `:root` and `.dark`. Beyond the shadcn set (`--card`, `--foreground`,
  `--muted`, `--border`, `--popover`, …), shared code reads:
  `--chart-treated-text`, `--chart-tercapai-text`,
  `--chart-tidak-tercapai-text`, `--chart-tidak-berkunjung-text` — the
  WCAG-AA-safe **text** variants of the chart series colours
  (`TEXT_COLORS` in `hipertensi/components/charts/theme.ts`). They must be
  theme-aware, so they cannot be literals in the shared TS module: no single hex
  passes AA on both a white and a near-black card. `globals.css` is per-app, so
  these four values are the one place both apps must be edited together — keep
  them identical.

App-specific behavior (the internal action bar / Show-browser / Sync buttons,
the internal hipertensi Diagnose tab, the dashboard hipertensi summary card) is
**not** here — it is injected by each app as a `ReactNode`/slot prop, so
internal-only features can never render in the client bundle.

## Rules

1. Put shared **feature** code here (api/types/hooks/stores/presentational
   components). Keep stable primitives per-app behind the host contract above.
2. Never import anything app-specific (no mutation API modules, no scrape/merge/
   sync hooks). If only one app needs it, it stays in that app and is passed in
   as a slot.
3. Bare deps used here (`react`, `next`, `@tanstack/react-query`, `zustand`,
   `zod`, `lucide-react`, `date-fns`, `sonner`, `react-hook-form`, `recharts`)
   must exist at the **same major version** in both apps' `package.json`.
4. The hipertensi charts (`hipertensi/components/charts/`) are heavy recharts
   widgets. Whatever renders them must load them through `next/dynamic` with
   `ssr: false` — recharts v3 renders nothing server-side, so SSR only costs
   bundle weight. (`hipertensi/components/hipertensi-charts-grid.tsx` does this
   for all six dashboard charts; the apps just render the grid.)
5. **Never copy-paste between the two apps.** If a change has to be made in both
   `frontend-dashboard/` and `frontend-internal/`, that code belongs here — move
   it and make the change once. A byte-identical block in both apps is a defect,
   not a coincidence: the copies agree only until the next edit.
6. **Share the whole rendered unit, not just the leaf.** What drifts is the call
   site — titles, colours, nouns, denominators, thresholds, copy. Lifting a small
   helper here while leaving the code that configures it duplicated in both apps
   is not single-sourcing. A user-visible string must exist in exactly one file.
7. **Leave no copy behind.** Once something lives here, the per-app version is
   stale code: delete it in the same change, plus any import it orphaned.
8. **Typecheck BOTH apps** after any change here — this tree has no build of its
   own, so a break only surfaces in a consumer, and passing one app proves
   nothing about the other:
   `cd frontend-dashboard && npm run typecheck` **and**
   `cd frontend-internal && pnpm typecheck`.
9. If a file here is pinned by the chatbot drift guard
   (`chatbot/knowledge.lock.json`), moving or renaming it must move the pin too —
   see root `CLAUDE.md` §10 and §12.3.
