# Research methodology

How to research a data source and map it to the ASIK form, reliably, with any model.

## The architecture you're feeding

Merge is hybrid + **backend-deterministic** (see `asik-target.md`):

1. `<source>_to_asik(raw)` — deterministic reshape of the source scrape into ASIK
   form shape. **You build/maintain this.** It is the quality bottleneck.
2. Backend (`merge.py`) combines `converted ∪ raw ASIK`: it owns field *presence*
   and *raw values* and *status*; the LLM only writes the conflict note. Source
   (EPUS) wins; ASIK fills gaps.

Consequence: **a converter gap never breaks the merge** — a missed field just shows
as ASIK-only (or empty) instead of source-enriched. Your job is to maximize correct
enrichment and catch drift, not to chase a crash.

## Discovering a NEW source (agent-browser)

1. Use the **agent-browser** skill to open the source login URL. Fill creds from the
   DB (`puskesmas.<source>_cred`, Fernet — decrypt with `app.core.security.decrypt_json`)
   or supplied creds. **The operator solves the captcha** in the visible window.
2. Navigate to a patient record. Capture: the form/section structure, every field
   label, value types (radio/enum/number/text), and conditional reveals (click a
   gating answer, see what appears).
3. Pull 3–5 sample patients covering variety (M/F, adult/lansia, with/without chronic
   disease) so you see every klaster's fields.
4. Save the raw shape. Then **graduate to a Playwright scraper** under
   `scrapers/<source>/` (mirror `scrapers/epus/`: `helpers/auth.py` login+captcha,
   `helpers/browser.py` session persistence, a `scraper.py` that writes the raw blob).
   Production needs the scraper; research can start on agent-browser.
5. Store the encrypted raw scrape in `patients.scraped_<source>_data`.

> Close any agent-browser/Playwright session you spawn before ending. Only kill your
> own session, not unrelated Chrome.

## Mapping source → ASIK (the judgment core)

For each ASIK question in `asik_form_mapping.json` (adult slice), answer: *does the
source contain this, and how do I transform it?* Categories:

- **Direct 1:1** — number or enum that maps straight (BB, TB, sistole, Ya/Tidak).
  Coerce types (string→int, normalize Ya/Iya/ya).
- **Value-map** — source vocab → ASIK enum (e.g. `Tidak Merokok`→`Tidak`,
  marital `Kawin`→`Menikah`).
- **Derived/union** — combine fields (chronic flag = self-report ∪ diagnosis-mark ∪
  ICDX-prefix scan; pack-years = rokok×lama).
- **Gated** — only emit for the right klaster (age/gender) and honor conditional
  reveals (child field only when parent = trigger).
- **No source** — leave the field absent/null; it becomes an ASIK-only shell. Record
  it as a known gap in `RESEARCH_STATUS.md`, don't invent a value.

Use `inspect_source.py` to see raw-source-vs-converter side by side while mapping.

## Verify loop (deterministic — trust the scripts)

1. `audit_coverage.py --source X` → fix every NAME/LABEL drift (they break paket
   grouping + ASIK sync-back). Reason about each MISSING form (shell vs skip).
2. `verify_converter.py --source X --models deepseek,gpt,oss` → must show 0
   hallucination, complete field set, 0 cross-model divergence.
3. Update `RESEARCH_STATUS.md` + write `<SOURCE>_TO_ASIK_VERIFICATION.md`.

## Keeping it healthy over time (drift)

The converter is the bottleneck, so make gaps **visible** and **self-healing**:

- **Drift detection (do):** schedule `capture_target.py` against a fresh ASIK dump
  (weekly). New live forms/questions = new mapping targets. Also watch a runtime
  metric: a spike in "ASIK-only" fields or a brand-new ASIK-only label = drift.
- **Self-healing fallback (option, discussed):** the LLM is idle now. You can re-task
  it as a *verified* fallback extractor — for an unmapped one-sided ASIK field, hand
  it the raw source blob + the question, have it propose `(value, source_path)`, then
  the backend **verifies the value exists in the raw source** before using it (discard
  if not → keeps the zero-hallucination guarantee). Deterministic core + LLM tail.
  Mark such values "auto-extracted, review", and promote frequent ones into the
  deterministic converter.
- **Regression guard (option):** pin coverage in CI; fail the build if a converter or
  schema change drops coverage or introduces an unmapped live question.

## Cross-model note (Kimi etc.)

The checking lives in the scripts (coverage, hallucination, divergence) — they catch a
weaker/different model's mistakes. The model only does the mapping judgment + writes the
converter. Run the same `audit_coverage` + `verify_converter` regardless of model; a
green run means correct, whoever produced it.
