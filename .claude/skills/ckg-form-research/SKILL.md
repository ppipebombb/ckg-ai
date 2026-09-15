---
name: ckg-form-research
description: >-
  Research a patient-data SOURCE (a portal like ePuskesmas, or any future
  health-record URL) and map it to the ASIK CKG form so the app can fill ASIK
  from that source. Use when: adding a new data source, auditing or extending a
  `<source>_to_asik` converter, checking whether the live ASIK form drifted, or
  verifying merge data quality. Produces a verified converter + a coverage audit
  and keeps the shared research docs current. Works with any model (Claude,
  Kimi, …): all checking is in deterministic scripts; the model only does the
  source→ASIK mapping judgment.
---

# CKG Form Research

## Purpose

The app fills the **ASIK CKG form** (`sehatindonesiaku.kemkes.go.id/ckg-pelayanan`)
from one or more **data sources**. Source #1 is **ePuskesmas (EPUS)**. More
sources will come. For each source we need a deterministic converter,
`app/services/<source>_to_asik.py`, that reshapes the source's raw scrape into
ASIK-form shape. The merge then combines `source-converted ∪ raw ASIK`
deterministically (source/EPUS wins; LLM only annotates conflicts — see
`references/asik-target.md`).

**Your job in this skill:** given a source (URL + creds), produce or update a
**verified `<source>_to_asik.py` + coverage audit**, and update the shared
state docs so the next researcher starts from truth.

## Mental model

- **Target = ASIK** — fixed. The set of questions to fill. Captured in
  `backend/app/data/asik_form_mapping.json` (the living target schema, with
  per-source coverage).
- **Source = the portal you're researching** — EPUS today, X tomorrow. Varies.
  ⚠ EPUS is itself **multi-instance**: a family of per-region portals
  (`<region>.epuskesmas.id`), each its own login and *possibly its own data shape*
  (e.g. jaksel renames a `data_pasien` key). One converter must handle every region —
  verify per region, not via a region-blind random sample (which the busiest region
  dominates). See `RESEARCH_STATUS.md` → Regions.
- **Converter = `<source>_to_asik.py`** — pure dict-in/dict-out, no LLM, no
  network. The quality of the merged data depends almost entirely on this file.

## Golden rules (do not violate)

1. **Zero hallucination.** Every value the converter emits must come from the
   source's raw scrape. `verify_converter.py` enforces this — a value that
   doesn't trace to source is a bug.
2. **Source (EPUS) wins** on any conflict; ASIK fills gaps. The converter only
   produces the source side. Never invent ASIK values.
3. **Deterministic.** No randomness, no LLM calls inside the converter. Same
   input → same output.
4. **Push checking into the scripts.** The scripts below are the source of
   truth for coverage / drift / hallucination. Trust them over eyeballing.
5. **Measure scope, never assume it.** Before calling any slice "out of scope"
   (an age band, a form family, a service), prove it with data —
   `profile_source.py` for who's in the population, `inspect_source.py` + a
   field-level union for whether the data is actually there. A tab can *exist*
   and still be a **hollow shell** (staff names + dates, zero clinical content),
   and a field that exists for adults can be **0% populated for the target band**
   (e.g. EPUS eye/ear data is empty for under-18) — check population *per klaster*,
   not just "adults have it." See the war story in Operational notes.
6. **Finish the goal; don't ship "done + an optional extra" when the extra is
   in-scope.** "Done" = the converter output becomes the **real ASIK form**
   end-to-end — correct values **and** correct klaster paket grouping (run the
   full merge via `verify_converter`, not just the converter dict). Keep going
   until that holds. Stop to ask only when the user must genuinely *decide* a fork;
   never hand back in-scope work reframed as an optional next step, and never say
   "done" while a known in-scope gap is open. (2026-06-02: pediatric was reported
   "done" while a card-grouping fix and a "deferred" form were still open — both
   turned out to be in scope; the deferred one only closed after the right check.)
7. **A tab's data lives in BOTH `fields` AND `tables` — read both, every time.**
   The scraper stores a tab's form questions in `tabs.<T>.fields`, but its
   editable GRIDS — lab exam/result rows (Laboratorium), drug rows (Resep),
   diagnosis rows — in `tabs.<T>.tables`. A `fields`-only read sees a tab's
   visit boilerplate and misses its richest clinical content. Not hypothetical:
   a `fields`-only blind spot hid the ENTIRE Laboratorium results table
   (Microalbuminuria → Albumin Urin, Trombosit, Hb — all "Tidak ada di EPUS" on
   the report) from the converter AND from both source-side audits until
   2026-06-03. Converter mappers, `audit_uncovered.py`, and `profile_source.py`
   must each walk both halves — a tab that's a "shell" in `fields` can be a
   gold mine in `tables`. (War story in Operational notes.)
8. **Completeness is enforced by `run_full_pass.py`, not by your diligence.** The recurring
   full pass runs through `scripts/run_full_pass.py`, which executes every step in order
   (incl. the captcha-gated live ASIK drift) and emits a GATE: a step that did not run shows
   `NOT_RUN` and forces `GATE: INCOMPLETE` (exit 2). Never substitute this doc's prior verdict
   for actually running a step; never decide a step is "probably unchanged, skip it"; never
   report "no drift" for a `NOT_RUN` step. A weak model exploited exactly that seam on
   2026-06-05 — it ran the cheap offline scripts, silently skipped the live scrape, and
   reported a clean "no issues" (the offline scripts can't contradict a step that never ran).
   The runner closes it. **Echo the `GATE:` line verbatim in every report.**

9. **Audit the SCRAPER against the LIVE site, not just the converter against the DB.** Every
   DB-side audit (`audit_regions` / `verify_converter` / `audit_coverage` / `audit_uncovered`)
   reads what we ALREADY scraped — so none of them can see that the SCRAPER itself is dropping
   live data. That is a real blind spot: 2026-06-05, EPUS jaksel's new-build Anamnesa tab bar
   listed only ~15 of ~33 modules, so bar-only discovery silently dropped ~17 data-bearing tabs
   per patient (incl. the converter-consumed Konseling HIV / TB Paru / PKPR) for the LARGEST
   region — invisible to every DB-side check because the DB never had those tabs to begin with.
   `scripts/audit_source_completeness.py` (now step 5 of `run_full_pass.py`) closes it: it logs
   into each region live (read-only, no captcha), runs the REAL production discovery, and
   force-probes for any module / show-section / AJAX read the scraper misses. A `data ≠ DB`
   gap (the scraper isn't capturing something the site serves) is as much a bug as a converter
   miss — and only a live scraper-vs-site check finds it. When you fix the scraper, also keep
   `patient_scraper._KNOWN_MODULES` and this script's allowlists current (the audit tells you
   what to add).

## Prerequisites

- Backend venv: run every script with `<repo>/backend/.venv/bin/python`.
- Local Postgres + Redis up (the scripts read decrypted patient records).
- Source + ASIK credentials (per-puskesmas, in the DB `puskesmas.<source>_cred`
  / `asik_cred`, Fernet-encrypted). For a brand-new source, you supply creds.

## Solving the ASIK login captcha

ASIK login has a 4-digit image captcha. **Which mode you use depends on whether
the model running this skill can read images** — not every orchestrator can
(Kimi and other text-only models can't). So the captcha config is no longer
fixed at "the agent solves it": **self-test first, then branch.**

### Step 0 — can YOU (the running model) read images?  ·  [decide once per session]

```bash
backend/.venv/bin/python .claude/skills/ckg-form-research/scripts/captcha_config.py selftest
# → prints a probe PNG path. Read it with your OWN vision, then verify:
backend/.venv/bin/python .claude/skills/ckg-form-research/scripts/captcha_config.py selftest --check <the-4-digits>
```

`VISION_OK` → **Branch A** (you solve captchas).  `VISION_FAIL`, or you simply
can't perceive the image → **Branch B** (a DB vision key solves them). The
expected answer is a salted hash, so a blind model can't accidentally pass by
reading the meta file — you only pass by actually reading the pixels.

### Branch A — you have vision: `agent` mode  (default, strongest, no API key)

Run the scraper **in the background**, watch its output for a
`CAPTCHA_HANDOFF: <png>` line. **Read** that PNG with your own vision (upscaled
4× — read the 4 digits) and **write** them to `captcha_answer.txt` in the same
folder. Repeat per attempt until "Login successful":
```
run scraper (run_in_background) → on "CAPTCHA_HANDOFF: <png>": Read <png>,
Write the 4 digits to <png's dir>/captcha_answer.txt → repeat until login
```
Ambiguous digit? The shot is already 4×; trust the retry loop (it refreshes +
re-hands a new captcha on a wrong guess, up to 20×).

### Branch B — no vision: `llm` mode  (a DB vision key solves it — no handoff)

Point the scraper at a vision-capable endpoint whose key lives (Fernet-encrypted)
in the DB, then run the scrape normally — the scraper auto-solves:
```bash
backend/.venv/bin/python .claude/skills/ckg-form-research/scripts/captcha_config.py apply
#   resolve  → preview the pick (health-checks each endpoint, no write)
#   apply    → patch scrapers/asik/config.json → type="llm" (backs up prior block)
#   restore  → put the old block back     ·    --config <path>  targets another scraper
#   --no-health-check / --health-timeout <s>   tune the liveness probe
```
The key is resolved from the DB in this **vision-safe** order, and **each endpoint
is health-checked** — a DOWN one is skipped so the chain fails over (first LIVE wins):
1. the config flagged **captcha only** (`is_active_captcha` — the UI "captcha" badge),
2. **ocr.juxtalabs.io** — your **local, free, self-hosted** vision LLM,
3. a **gpt-4o** OpenAI key (paid but reliable; gpt-4o → gpt-4o-mini → any gpt-4*) —
   the preferred failover when local OCR is down,
4. a **free CLOUD** vision model (24/7) — **last resort**, when even the gpt-4o key
   is unavailable. Auto-detected providers: Google Gemini, OpenRouter, Groq, GitHub Models.

The general `is_active` config is **never** used — it may be a text-only model
(today `gpt-oss-20b`, blind) that would fail every captcha. If nothing usable
exists the script errors and tells you what to add.

> **Free 24/7 cloud vision (tier 4, last resort) — add one so the chain still
> solves captchas if both local OCR and the gpt-4o key are down.** Best pick:
> **Google Gemini 2.5 Flash-Lite** free tier (1,500 req/day, 30 RPM, no card; a
> 4-digit captcha carries no PII, so the free-tier-trains-on-data caveat is moot
> here). Add it in the **LLM Configs** UI:
> - provider `openai` · model `gemini-2.5-flash-lite`
> - base_url `https://generativelanguage.googleapis.com/v1beta/openai`
> - api_key = your free key from `aistudio.google.com/apikey`
>
> Alternative: **OpenRouter** — base_url `https://openrouter.ai/api/v1`, a `:free`
> vision model (e.g. `qwen/qwen2.5-vl-72b-instruct:free`), key from `openrouter.ai`.
> The chain auto-detects either by its base_url and slots it in at tier 4.

### Other modes
- **`manual`**: terminal half-block render + a human types it (dev/standalone only).
- **agent-browser** (Branch A only): skip the scraper and drive login directly via
  the **agent-browser** skill (navigate → screenshot the captcha → read → type →
  submit). Same agent-solve idea, no handoff file. No vision → use Branch B.

## Procedure

> **Recurring EPUS full pass → run the orchestrator, do not hand-run these steps.**
> `backend/.venv/bin/python .claude/skills/ckg-form-research/scripts/run_full_pass.py --source epus`
> executes every step below (forcing the live-drift step) and gates on completeness — see
> `RESEARCH_STATUS.md` → "Full research pass". The per-script breakdown below is for bringing
> up a NEW source, drilling into a flagged region, or understanding what the runner runs.

### 0. Start from truth

Read `RESEARCH_STATUS.md` (in this skill dir). It lists the target schema date,
every source's coverage %, known gaps, and last-audit date. Don't re-discover
what's already mapped.

### 1. Refresh the TARGET (ASIK) — detect ASIK drift  ·  [manual scrape, then script]

First dump TODAY's live ASIK forms (visible browser, **you solve the captcha**;
session persists for repeat runs):

```bash
cd scrapers/asik   # config.json: include_blank_forms=true, pelayanan_nakes_only=false
python3 scraper.py --no-headless --tab selesai --date <YYYY-MM-DD> \
    --max-patients 4 --output output/live_today.json
```

> **Pick a date you KNOW has completed (`Selesai`) screenings** — `--date` defaults to
> today and does **not** fall back to earlier dates. An empty/low-volume date produces an
> empty dump that would falsely read as "no drift"; `capture_target.py` refuses such a dump
> (exit 2) rather than judging drift on it.

Then diff that dump against the committed target schema:

```bash
backend/.venv/bin/python .claude/skills/ckg-form-research/scripts/capture_target.py \
    --dump scrapers/asik/output/live_today.json
```

Reports **NEW LIVE** forms/questions (ASIK added them → new mapping targets) and
ones in the mapping not seen live. A non-empty NEW LIVE list = drift to address.
(Full target-schema rebuild from the Padanan Excel is a heavier manual step:
see `references/asik-target.md`.)

### 2. Inspect the SOURCE  ·  [agent-browser, then script]

**First, profile the population — never scope from assumption (Golden rule 5).**
This prints the age-band breakdown and, per band, which tabs actually carry
clinical content vs. which are hollow shells (`<-- SHELL`):

```bash
backend/.venv/bin/python .claude/skills/ckg-form-research/scripts/profile_source.py --source epus
# --sample 3000 for a fast read; --band 12-17 for one band's tab detail
```

Use this output to decide what's genuinely in/out of scope *before* mapping. A
tab at `present 71% | has-clinical 0%` is a shell — its forms can't be filled
even though kids exist. (This is exactly the trap the 2026-06-02 pediatric audit
fell into — see Operational notes.)

**EPUS is multi-region — prove the converter generalises to ALL instances.** Run the
cross-region audit: it diffs each region's shape (tab names + `data_pasien` keys) and
compares **age-controlled** extraction, flagging any region the converter under-fills.
The usual culprit is a renamed key (the audit surfaces it under "data_pasien keys that
VARY by region") — fix with a `.get("X") or .get("<alias>")` fallback in the converter.

```bash
backend/.venv/bin/python .claude/skills/ckg-form-research/scripts/audit_regions.py --source epus
```

**Does the SCRAPER capture everything the LIVE site serves? (Golden rule 9 — the seam
DB-side audits can't see.)** This logs into each region live (read-only, no captcha), runs the
REAL production discovery, and force-probes for any module / show-section / AJAX read the
scraper misses (it caught the jaksel 17-tab drop). Exit 1 = MUST-FIX scraper gap, 3 = TRIAGE:

```bash
backend/.venv/bin/python .claude/skills/ckg-form-research/scripts/audit_source_completeness.py --source epus
#   --per-region N   patients sampled per region (default 3)    --regions jaksel   scope to one
```

Every source-side script (`profile_source` / `inspect_source` / `audit_coverage` /
`audit_uncovered` / `audit_source_completeness`) takes `--region(s) <url-or-name>` to scope to one region.

For a **new** source with no scraper yet — use the **agent-browser** skill to
log into the source URL (human solves captcha), walk its forms, and capture
field names + a few sample records. See `references/methodology.md` §"Discovering
a new source". Graduate it into a real Playwright scraper under
`scrapers/<source>/` (mirror `scrapers/epus/`) once the shape is understood —
production needs the scraper, research can start on agent-browser.

For a source that already has a scraper (EPUS), dump a decrypted sample record:

```bash
backend/.venv/bin/python .claude/skills/ckg-form-research/scripts/inspect_source.py --source epus --nik <NIK>
```

### 3. Map source → ASIK  ·  [your judgment — the irreducible core]

For each ASIK question (from `asik_form_mapping.json`), find the source field(s)
that answer it and the transform. This is the one step a model must do, not a
script. Record each mapping as `(source_path, asik_form, asik_field, transform)`.
Honor: klaster/age/gender gating, conditional reveals, value coercion, and
chronic-disease flags. See `references/converter-pattern.md` for every pattern,
worked from `epus_to_asik.py`.

### 4. Write / extend `app/services/<source>_to_asik.py`  ·  [your judgment]

Follow `references/converter-pattern.md` exactly: per-form mapper functions, a
public `<source>_to_asik(raw) -> dict`, and a `<SOURCE>_BREADCRUMBS` table
(asik_form → field → source path). Defensive `.get()` everywhere — a source
shape change must degrade to `null`, never crash.

### 5. Audit coverage (both directions) + drift  ·  [script]

Coverage is a TWO-WAY check — run BOTH. `audit_coverage.py` works the **target
(ASIK) side**: are the questions ASIK asks getting filled? `audit_uncovered.py`
works the **source side**: is there scraped data we're NOT mapping? You need
both — a target-side-only audit will never tell you a whole source tab is going
to waste (that's how the Laboratorium lab results hid for months: the mapping
said "no EPUS source", so the target side was "complete" and nobody looked at
the source side). 

```bash
backend/.venv/bin/python .claude/skills/ckg-form-research/scripts/audit_coverage.py  --source epus
backend/.venv/bin/python .claude/skills/ckg-form-research/scripts/audit_uncovered.py --source epus   # add --region <r> to find a region's misses
```

`audit_coverage` reports: converter form-names with no canonical ASIK match
(name drift), breadcrumb field labels not matching the live ASIK label (label
drift), live ASIK adult forms the converter never emits (missing), and a
per-form covered/total tally. Fix every name/label drift (they break paket
grouping + ASIK sync-back). Decide shell-vs-skip for missing forms.

`audit_uncovered` lists populated SOURCE leaf-paths (walking BOTH `fields` AND
`tables`) that no breadcrumb consumes, ranked by fill%. **Triage the top of
that list** — a high-fill, clinical-looking path that maps to an ASIK question
is a gap to close (e.g. `Laboratorium > … > Microalbuminuria`). It's a heuristic
that surfaces candidates, not a pass/fail gate; region spelling variants
("Trombosit (PLT)") may show even when an alias already maps them.

### 6. Verify quality + persist  ·  [script]

```bash
backend/.venv/bin/python .claude/skills/ckg-form-research/scripts/verify_converter.py --source epus --n 10
# "all EPUS tested": run the same gate once PER region (fails if ANY region fails):
backend/.venv/bin/python .claude/skills/ckg-form-research/scripts/verify_converter.py --source epus --all-regions --n 8 --models oss
```

Runs the converter + the real merge pipeline on N records and asserts:
**0 hallucinated values**, complete field set (= source ∪ ASIK), valid output
shape, and — if `--models` given — 0 cross-model merge divergence. Then:

- Update `asik_form_mapping.json` coverage (audit_coverage does this).
- Write/refresh `backend/app/prompts/<SOURCE>_TO_ASIK_VERIFICATION.md`.
- Update this skill's `RESEARCH_STATUS.md` (coverage %, date, gaps).

## Adding a brand-new source — checklist

1. DB: add a `scraped_<source>_data` column on `patients` (mirror
   `scraped_epus_data`); store the Fernet-encrypted raw scrape there.
2. `scrapers/<source>/` — a Playwright scraper (mirror `scrapers/epus/`).
3. `app/services/<source>_to_asik.py` — the converter (this skill, steps 3–4).
4. `puskesmas.<source>_cred` — encrypted creds column if per-puskesmas.
5. Wire the source into the merge (`merge.py` already merges
   `converted ∪ asik` source-agnostically — point it at the new converter).
6. Run steps 5–6; commit the converter + verification doc + updated status.
7. Run `profile_source.py --source <source>` and record the population + per-band
   tab reality (incl. shell tabs) in `RESEARCH_STATUS.md` before declaring any
   slice in/out of scope (Golden rule 5).

## Operational notes (gotchas, learned the hard way)

- **`fields` are only HALF a tab — the `tables` grids carry lab/Resep/Diagnosa data (war
  story, 2026-06-03).** A puskesmas asked why "Konsentrasi Albumin Urin" was marked *Tidak ada
  di EPUS* when EPUS Cipondoh's Laboratorium tab clearly shows lab results. It WAS being
  scraped — into `tabs.Laboratorium.tables["Ubah Data Laboratorium"]` ({Pemeriksaan, Hasil,
  Satuan, …} rows) — but THREE places only ever read `tabs.<T>.fields`: the converter, plus
  `audit_uncovered.py` (walked only `fields`, so the inverse-coverage audit never listed the
  lab results) and `profile_source.py` (counted clinical content only in `fields`, so it
  stamped Laboratorium `<-- SHELL` and steered everyone away — the very trap rule 5 warns about,
  one layer deeper). Net: the data was on disk for months, invisible to every check, and
  3 ASIK questions stayed "manual" (Microalbuminuria→Albumin Urin, Trombosit, Hb), each in
  forms the converter already emitted as empty. Fixes: converter reads the Laboratorium result
  table (`_lab_results`); both audits now walk `fields` + `tables`. Lessons: (1) **a tab's data
  can live in `tables`, not `fields`** — read both (Golden rule 7); (2) **a "no source" / SHELL
  verdict is only as good as what the script looked at** — a target-side audit that trusts the
  mapping's "no EPUS source" annotation can never discover a source that actually HAS the data;
  run `audit_uncovered.py` (the source-side inverse) too; (3) when adding a lab/exam field, match
  the test-name leaf EXACTLY (region spellings vary — "Hb (Hemoglobin)" / "Hemoglobin (HGB)" /
  "Hemoglobin", "Trombosit" / "↳ Trombosit (PLT)") — substring matching would grab HbsAg/HbA1c.
- **Never declare scope from assumption — profile first (war story, 2026-06-02).** A run
  asserted *"EPUS has no pediatric data, so kids are out of scope."* Wrong on both counts.
  `profile_source.py` showed **~23% of EPUS patients are under 18** (≈14.6k people). Then the
  *second* layer: those kids' pediatric tabs (`Imunisasi`, `Tumbuh Kembang Anak`, `Periksa
  Gizi`) are **hollow shells** — present but holding only staff names + dates, no antigen-level
  or developmental content — so most pediatric ASIK forms still can't be filled, while a few
  CAN (growth/anthropometry, telinga-mata, TB-risk, child glucose) from the general clinical
  tabs shared with adults. Two lessons: (1) "out of scope" must be *measured*, not guessed;
  (2) **"present" ≠ "populated"** — a tab can exist and be empty. `profile_source.py` measures
  both. Full per-family verdict is in `RESEARCH_STATUS.md` → Pediatric section.
- **EPUS is multi-region — one region's quirk is invisible in a blended sample (war story,
  2026-06-03).** EPUS = per-region portals (`<region>.epuskesmas.id`); a region-blind random
  sample is ~70% the busiest region, so a smaller region's renamed key hides. `audit_regions.py`
  measured 3 regions and caught it: jaksel keys birthplace/DOB as `Tempat & Tgl Lahir` (comma)
  vs the others' `Tempat/Tgl Lahir` (slash) — the converter read only the slash key and silently
  dropped 2 identity fields for ~65% of jaksel patients (fill 4.1 vs 5.8). Two lessons: (1) verify
  **per region** (`verify_converter --all-regions`; the source-scripts' `--region`), never just a
  blended sample; (2) **control for age band when comparing regions** — a raw fill gap is mostly
  age mix (jaksel skews young, fewer lansia), not a converter bug. Full state: `RESEARCH_STATUS.md`
  → Regions.
- **Run scripts from anywhere** with `backend/.venv/bin/python <script>` — they load
  `backend/.env` themselves (don't depend on CWD). The shared `scripts/_regions.py` helper
  (region inventory + stratified `sample_by_region` + `resolve_regions`) is imported by the
  region-aware scripts; keep it next to them.
- **Cross-date twins:** the same NIK has multiple `patients` rows (one per scrape date);
  some have `scraped_asik_data = NULL`. The scripts filter `…isnot(None)`, but if you
  query patients yourself, always filter the source + ASIK columns not-null.
- **Live ASIK form names carry ordering prefixes** (`1. `, `6a. `). `capture_target.py`
  strips them; when you name a converter form, use the **de-prefixed** live name.
- **ASIK login captcha** — solve it per the self-test gate above (Branch A you read
  it; Branch B a DB vision key reads it via `captcha_config.py apply`). Sessions
  live a few days, then re-login. EPUS portal is per-region (`<region>.epuskesmas.id`).
- **Settle names against a FRESH live dump, not an old spec sheet** — the Padanan Excel
  drifts from live (that's how `Skrining Malnutrisi - Lansia` vs live `SKILAS Malnutrisi`
  slipped through until the 2026-05-29 audit).
- **After editing a converter:** Celery worker restart + re-merge existing patients with
  `force_remerge` (backend change → see project memory).

## What "done" looks like

- `audit_coverage.py` shows no name/label drift, coverage tally explained.
- `audit_uncovered.py` triaged: every high-fill source path (across `fields` AND `tables`)
  that maps to an ASIK question is either mapped or has a one-line reason it can't be.
- `verify_converter.py` exits 0 (0 hallucination, complete, consistent) — run it for
  **every klaster you emit** (e.g. `--min-age 0 --max-age 17` for kids, `--min-age 18`
  for adults), not just a random sample that may be one klaster.
- `verify_converter.py --all-regions` exits 0 (**every EPUS region** passes, not just the
  busiest) and `audit_regions.py` exits 0 (regions within extraction parity, all
  converter-critical tabs present, no unhandled `data_pasien` key rename).
- The **full merge pipeline** output (not just the converter dict) is the real ASIK
  form: values correct AND grouped into the right klaster paket cards (`paket_for` is
  klaster-aware — adult keywords must not capture kid fields).
- `RESEARCH_STATUS.md` + the verification doc reflect the run; no in-scope gap left open.
- Worker restart noted (backend changes need it — see the project memory).
