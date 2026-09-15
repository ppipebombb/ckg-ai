# asik_sekolah/CLAUDE.md — ASIK CKG Sekolah scraper

> Per-scraper LLM context. Root conventions live in `../CLAUDE.md`. Reuses the
> `asik/` helpers + `asik/patient_scraper` form-reader via `sys.path` injection
> (same pattern as `asik_patient/`). Keep this file current when the school data
> flow, CLI, or output schema changes.

## What this scrapes

`https://sehatindonesiaku.kemkes.go.id/ckg-pelayanan-sekolah` — the **CKG
Sekolah** (school health checkup) Pelayanan page. Unlike CKG Umum, it has **no
date filter**: it is filtered by **Pilih Sekolah × Pilih Kelas**. We walk every
school the puskesmas is assigned, every class in each school's jenjang
(SD 1-6 / SMP 7-9 / SMA 10-12), and all three status tabs (Belum / Sedang /
Selesai Pemeriksaan). We scrape **Pelayanan oleh Nakes + Pemeriksaan Mandiri +
Tatalaksana**. Writes to the `school_patients` table (NOT `patients`).

## The decisive constraint (verified live 2026-06-29)

The list/school request bodies are **AES-encrypted client-side** —
`{"data": "<cipher>"}` — and CANNOT be forged (no `/encrypt` round-trip; the app
encrypts in its JS bundle with a key we don't have). **Responses are plaintext
JSON.** So we DRIVE THE REAL UI and INTERCEPT the plaintext responses via
`APIInterceptor`, exactly like CKG-Umum does for `list-claim`.

| Endpoint | Request | How we get it |
|---|---|---|
| `/api/pkg/sarana/get-sarana-sekolah` | **encrypted** | fires on page load → intercept response (all schools: `ihs_no`, `school_name`, `category_short_name` = SD/SMP/SMA) |
| `/api/pkg/anak-sekolah/list-jenjang-sekolah` | **plaintext** `{"category_code":"SMA"}` | call directly via `context.request.post`; returns `[{code,name}]` classes |
| `/api/pkg/anak-sekolah/list-patient` | **encrypted** | select school+class+tab+page in the UI → intercept response (`data[]` + `pagination`) |
| `/api/pkg/anak-sekolah/get-screening` | **encrypted** | the detail page reads `localStorage["dataDetail"]` and fires it → intercept response (Nakes form URLs + `patient_klaster_*`, `is_have_tatalaksana`, `program_code:"pkg"`) |

> `get-screening` is structurally identical to CKG-Umum `detail-screening`
> (`screening_layanan[].list_pemeriksaan[].pemeriksaan_link` are the same
> `form.kemkes.go.id/v2/skrining-form` SurveyJS URLs), so the form reader is
> reused verbatim. **`category_short_name` (SD/SMP/SMA), not the numeric
> `category_code` (e.g. "13305"), is what `list-jenjang` expects.**

> A fully-API path (forge `get-screening` via `/encrypt`) was investigated and
> rejected: `/encrypt` produces a server-decryptable token, but the exact inner
> payload could not be determined (consistent 500s suggest the handler needs
> session state the normal UI flow sets up), and `/decrypt` mirrors `/encrypt`.
> Driving the UI + intercepting is the robust path.

## Vue real-event clicks (critical)

The custom Vue comboboxes/tabs/buttons **ignore synthetic `page.evaluate(el.click())`**
— they only respond to real input events. Everything in the UI-driving section
uses Playwright locators (`get_by_role`, `get_by_text`, `.click()`), which
dispatch real events. Do NOT regress to JS `.click()` for these controls.

## Data flow (throwaway-tab architecture — the list page is NEVER navigated)

```
login (reuse asik login + LLM/terminal CAPTCHA) → /ckg-pelayanan-sekolah
→ accept "Pemberitahuan Privasi" modal (checkbox + Setuju)
→ intercept get-sarana-sekolah → all schools
→ for each school:
    → list-jenjang-sekolah (plaintext) → classes
    → select school in dropdown (search), for each class:
        → select class, click "Tampilkan Pencarian"
        → for each tab (Belum/Sedang/Selesai):
            → click tab → intercept list-patient (rows + pagination)
            → for each page:
                → CAPTURE every student's localStorage["dataDetail"] in ONE pass:
                  install a Vue-router beforeEach(()=>false) guard + a
                  localStorage.setItem hook, then click all Mulai buttons — the
                  guard cancels navigation so the list stays intact and we
                  collect N dataDetails in row order
                → remove the guard
                → for each (row, dataDetail): open a THROWAWAY TAB seeded with
                  that dataDetail → detail page fires get-screening (intercept)
                  → open Nakes pemeriksaan_link forms in tabs, read SurveyJS DOM
                  → if is_have_tatalaksana: read tatalaksana (best-effort)
                → click the next page number (real-event) on the main list
→ write JSON
```

### Why this design (go_back does NOT work)

`page.go_back()` after a detail does **not** restore the filtered list — the
list component remounts empty (filter lost, 0 Mulai buttons, no list-patient
refire). So we never navigate the main list page. Instead:

- The detail page reads the selected student from **`localStorage["dataDetail"]`**
  (a `c3`+reg_id+per-record-AES blob; not constructable, but the app computes it
  when Mulai is clicked).
- A **Vue-router `beforeEach(()=>false)` guard** (found via
  `#__nuxt.__vue_app__.config.globalProperties.$router`) lets us click every
  Mulai to harvest all `dataDetail`s **without** the view ever swapping.
- Each detail is then loaded in a **throwaway `context.new_page()`** seeded with
  that student's `dataDetail`; its get-screening fires for that exact reg_id and
  is intercepted. Verified to match per-student (we check `expect_reg`).

> **`add_init_script` gotcha:** seed `dataDetail` with a **direct statement**
> (`window.localStorage.setItem('dataDetail', "...")`), NOT an arrow-function
> expression (`() => {...}`) — Playwright would define-but-never-call the latter,
> and the throwaway tab would read the stale SHARED localStorage (every student
> then resolves to the last-clicked one). This was a real bug, now fixed.

## Output schema

```json
{ "metadata": {...},
  "schools": [
    { "school": {"school_code","school_name","category_code"(=SD/SMP/SMA)},
      "classes": [
        { "class_name": "Kelas 11", "class_code": "...",
          "tabs": { "belum_pemeriksaan": [student...],
                    "sedang_pemeriksaan": [...], "selesai_pemeriksaan": [...] } } ] } ] }
```

Each `student` is a flat dict (the backend `_extract_school_students` +
`school_patient.upsert_from_school_scrape` read these top-level keys): `nik`,
`nama`, `born_date`, `gender`, `reg_id`, `ticket_number`, `register_date`,
`faskes_code`, `school_code/name`, `category_code`, `class_name`,
`klaster_code/name`, `screening_status` (belum/sedang/selesai), `detail_data`,
`pelayanan_nakes` + `pemeriksaan_mandiri` (each `[{layanan,
form_data:{question:answer}, pemeriksaan_code}]`), `tatalaksana`, and
`_raw_list_row` / `_raw_detail` (lossless).

## CLI flags

```
--use-session            Reuse saved browser session (skip CAPTCHA on repeat runs)
--headless/--no-headless Default headless (CAPTCHA via LLM solver or terminal)
--output PATH            Output JSON path
--only-school SUBSTR     Only schools whose name contains SUBSTR (targeted/debug)
--only-class "Kelas 11"  Only this exact class (targeted/debug)
--max-schools/--max-classes/--max-students/--max-pages N   Limits (debug)
--list-only              Skip per-student detail (Mulai/forms); list rows only
--capture-network PATH   Dump every captured XHR/fetch JSON for analysis
```

## Verified state (2026-06-29)

End-to-end **proven at scale** on `MAS JABAL NUR UNIVERSAL / Kelas 11`: LLM-CAPTCHA
login + session reuse, school enumeration, plaintext class enumeration,
school+class dropdown selection (real-event), search, tab switch, `list-patient`
interception, **pagination across all 3 Sedang pages (10+10+5)**, dataDetail
capture via the router guard, throwaway-tab get-screening per student, **12 Nakes
forms each read with mapped questions + answers** (Selesai students fully filled,
Sedang students partial — semantically correct), tatalaksana, and the backend
`_extract_school_students` + `upsert_from_school_scrape` → `school_patients`
ingestion. **Full class = 32 students (25 Sedang + 7 Selesai), 32 distinct NIKs,
0 errors.**

## Form-question catalog

`backend/app/data/asik_sekolah_form_mapping.json` is the committed catalog of
every Pelayanan-Nakes question per form per klaster — keyed by the form's FRM
code (`pemeriksaan_code`), with `layanan`, the `klaster` it appears in, and the
union of `questions`. Generate/extend it with:

```bash
python tools/build_form_map.py \
  ../../backend/app/data/asik_sekolah_form_mapping.json  <scrape-output.json> [...]
```

The scraper runs with `include_blank_forms=True`, so even unsubmitted forms
contribute their rendered schema; the build tool **unions** across runs, so the
map grows as you scrape more klaster (it currently covers the klaster that have
registered students in the scraped puskesmas — most Cipondoh schools have none,
so coverage is data-limited, not a tooling limit). Re-run the scraper on more
populated schools and re-run the tool to broaden it.

### Spec catalog (reference) + coverage audit (2026-06-29)

`backend/app/data/asik_sekolah_form_catalog.json` is the **2026 spec** catalog
generated from the Kemenkes metadata xlsx — `tools/build_catalog_from_xlsx.py`
reads `documents/Metadata Program Rutin(1).xlsx` (sheet "Update USEKREM Padanan
Paket Od", module "Usia Sekolah dan Remaja") and emits **all 43 forms · 205
questions · 363 answer options · 28 klaster**, each form tagged `tipe`
(`Layanan`=Pelayanan Nakes / `Skrining Mandiri`=self-report) and `live_verified`
(computed against the live map). Regenerate:

```bash
python tools/build_catalog_from_xlsx.py \
  "../../documents/Metadata Program Rutin(1).xlsx" \
  ../../backend/app/data/asik_sekolah_form_catalog.json \
  ../../backend/app/data/asik_sekolah_form_mapping.json   # live map → reconciliation
```

**The xlsx is REFERENCE ONLY — live ASIK is ground truth** (nothing is hardcoded;
the scraper never reads the catalog). Audit findings:

- **Nakes coverage is complete.** For the one live-validated klaster
  (Kelas 11&12-L), `reconciliation.spec_not_in_live == []` — every spec Nakes form
  is present live; live even has 5 MORE than the spec's ✅-matrix marks
  (`live_not_in_spec`: Kebugaran 128, Kadar CO 186, Frambusia 199, Skabies 201,
  Hepatitis 257). The scraper iterates every `screening_layanan` + nested
  `pemeriksaan`, so it cannot miss a present Nakes form (the 3 NTDs nest under one
  layanan and were all captured).
- **Within a form, every INPUT question is captured.** The fields the spec lists
  but a live form omits are server-COMPUTED interpretations (IMT/U, BP category,
  the "Hasil Pemeriksaan …" hearing/vision summaries — `options:[]` in the catalog)
  and CONDITIONAL follow-ups (e.g. diabetes-duration, only if "pernah didiagnosis
  = Ya"). ASIK derives/gates these; conditionals get captured for students who
  trigger them and the live map unions them in.
- **Spec drift** (xlsx ≠ live): NTDs consolidated to one paket in spec but split
  live; Hepatitis renumbered (spec 122 = Mandiri vs live 257 = Nakes). Trust live.
- **Scope: Nakes + Mandiri (2026-06-30).** The `Skrining Mandiri` self-report
  forms (Kesehatan Jiwa, Aktivitas Fisik, Perilaku Merokok, Kesehatan Reproduksi,
  Talasemia, …) come from `get-screening`'s `screening_forms[]` and are now read
  into each student's `pemeriksaan_mandiri[]` alongside `pelayanan_nakes`.
- **Klaster coverage:** only Kelas 11&12-L is live-validated; the other 13 school
  klaster are spec-only until a puskesmas with populated SD/SMP/SMA is scraped.

## Resilience: session recovery + progressive save + resume (2026-06-30)

A whole-puskesmas run is hours long, and the ASIK session **expires mid-run** —
verified live: Cipondoh died at school 24/43 ("Sesi Telah Berakhir / login dari
perangkat lain"), after which every combobox was blocked and schools 24-43 saved
0. Three mechanisms (modeled on the `asik`/CKG-Umum scraper) make it robust:

1. **Expired-session detection + recovery** (`_ensure_session`). Probes
   `verify_session` → `GET /api/user-management/me` (200 = alive). Called
   **before each school** (catches between-school expiry) and again when a school
   comes back **`blocked`** (a combobox wouldn't open) AND the session is dead.
   Recovery = clear cookies → `login()` (gpt-4o CAPTCHA) → re-`goto` sekolah →
   re-accept the privacy modal → reset `_prev_school_text` → **redo the whole
   school**. `_scrape_school` now returns `(result, blocked)` so the run loop owns
   this retry. So a mid-run expiry self-heals instead of dead-zoning the rest.
2. **Progressive per-school save** (`_write_school_file` → `OUTPUT_DIR/school_NNNN.json`).
   The scraper has **no DB access** (security), so it writes one file per completed
   school; the Celery task's in-run poll loop upserts + commits **per school**
   (mirrors EPUS per-date in `tasks/scrape.py`). A cancel/crash now keeps every
   completed school instead of losing the whole run (school data used to save only
   on clean exit). On cancel/fail the task records the salvaged counts.
3. **Resume** (`--skip-schools CODE,CODE`). The task passes the `school_code`s
   already saved for this puskesmas in the last 24h, so a re-run **continues from
   where it stopped** rather than redoing hours of completed schools. (Empty
   schools have no rows → cheaply re-scraped; that's fine.)

## Known TODO / caveats

1. **Mid-school expiry re-scrapes the school** (not the class). If the session
   dies partway through a school, the whole school is redone after recovery (its
   already-read classes are re-read). Correct but slightly wasteful; acceptable.
2. **Tatalaksana endpoint for school** is assumed to be the same plaintext
   `/api/pkg/tatalaksana/list-detail` as CKG Umum (reg_id-scoped). It's
   best-effort (errors caught); confirm the values on a student with recorded
   tatalaksana.
3. **`restore_saved_auth_state` warning** (`add_init_script ... 3 args`) is a
   pre-existing asik-helper Playwright-version mismatch; cookies still restore so
   login works, only web-storage restore is skipped.
4. **`go_back` is intentionally unused** — see "Why this design" above. Do not
   reintroduce a Mulai→detail→go_back loop; it loses the list.
