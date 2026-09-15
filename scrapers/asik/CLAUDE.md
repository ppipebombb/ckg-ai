# asik/CLAUDE.md — ASIK CKG Pelayanan scraper

> Per-scraper LLM context. Root conventions (tech stack, safety rules,
> sub-scraper layout, code style) live in `../CLAUDE.md`. Keep this file
> up to date when ASIK's data flow, modules, CLI, or output schema change.

## What this scrapes

`https://sehatindonesiaku.kemkes.go.id/ckg-pelayanan` — the CKG Umum
"Pelayanan" page. For each authorised puskesmas user, it reads the
patient list filtered by date, then deep-scrapes every eligible patient's
demographic data + self-assessment forms + nakes-service forms.

## Data flow

```
CLI args → launch browser → login (CAPTCHA) → navigate to /ckg-pelayanan
→ close popups → set date range → for each tab (Belum/Sedang/Selesai Pemeriksaan):
    → click tab (browser fires POST /api/pkg/list-claim)
    → for each page:
        → read patient list from interceptor's last list-claim response
        → for each record:
            → POST /api/pkg/detail-screening with reg_id
              (one call returns demographics + domicile + every form URL
               + is_have_tatalaksana flag + program_code)
            → batch-open Mandiri form URLs in new tabs, read SurveyJS DOM
            → batch-open Nakes form URLs in new tabs, read SurveyJS DOM
            → if is_have_tatalaksana: POST /api/pkg/tatalaksana/list-detail
              (one call returns the whole follow-up table); batch-open the
              per-row form URLs whose status != "belum_dilakukan"
            → save progress
        → click_next_page → list-claim refires for next page
→ write final JSON
```

The list page is never navigated away from, so date filter + tab + page
number stay set throughout — no re-application needed. The detail page
is never opened either: `/api/pkg/detail-screening` returns everything
the dialog used to render. Forms still must be opened as tabs because
their answers come back AES-encrypted via `cha-formbuilder`, so we read
the SurveyJS DOM instead.

Measured on 2026-04-17 (11 patients, headless, session reuse): ~6 s/patient
(legacy DOM-driven flow was ~53 s/patient before this was rewritten).

### Form reading (new-tab approach)

The scraper opens form URLs from the API response in **new browser tabs**
via `context.new_page()`. The list page stays put.

- `FormLink` (in `screening_forms[]`) → Pemeriksaan Mandiri tab URL
- `pemeriksaan_link` (in `screening_layanan[].list_pemeriksaan[]`) → Pelayanan Nakes tab URL
- Both are batched (size 4) by `_batch_read_forms_via_tabs`.
- Each tab shares the browser context (cookies/auth for `form.kemkes.go.id`).
- `_read_all_form_fields` reads the rendered SurveyJS DOM in each tab.

#### Gating the read on the answer XHR (critical)

Each form page fires
`POST .../cha/cha-formbuilder/.../get/skrining-layanan` to fetch the
patient's answers as AES ciphertext; SurveyJS then decrypts and applies
them to the DOM. The question labels are already in the static HTML at
`DOMContentLoaded`, so a naive "tab loaded → read" flow sometimes catches
the DOM *before* answers are applied. Symptom we hit: two radio fields
on `Skrining Penyakit Periodontal` flipping between `"Tidak"`/`"Ya"` and
`None` across otherwise-identical runs.

The fix (`_batch_read_forms_via_tabs`):
1. **Subscribe** `tab.on("response", ...)` and flip a per-tab flag when
   `skrining-layanan` returns `200`. This must happen *before* `tab.goto`
   — subscribing after goto risks missing a fast response.
2. After goto, `_poll_flag` blocks up to 6s waiting for the flag.
3. Fixed `wait_for_timeout(120)` after the flag — enough time for
   SurveyJS to apply the decrypted answers within a couple of animation
   frames, cheap enough not to dominate wall time.
4. Read once with `_read_all_form_fields`.

No retries, no heuristic settle loop, no `networkidle` (too broad — icon
CDN fetches + long-poll keep the tab from ever going idle cheaply). The
gate is the *specific* XHR that delivers answers. Confirmed consistent
across 3 repeated runs on date 2026-04-17 with zero cross-run diffs and
the same ~44 s scraping time as the ungated read.

### Why we don't read form answers from the API

`screening_forms[i].FormResult` does ship in the detail-screening
response, but it's keyed by opaque codes (`LPM…|FRM…|PPM…|text` → `PPV…`)
and the human-label schema lives behind `POST .../cha-formbuilder/.../get/skrining-layanan`
as AES-encrypted ciphertext. Without reverse-engineering the bundled JS
to find the decryption key, the codes are unusable — so we still open
form pages and let the SurveyJS bundle decrypt + render them for us.

### Tatalaksana (follow-up treatment)

The detail page's top-right **"Mulai Tatalaksana"** button is clickable only
once the patient is **Selesai Pemeriksaan**. `/detail-screening` exposes this
as `is_have_tatalaksana` — when `true`, we fetch the follow-up table directly
from the API (no detail-page navigation, same as everything else):

```
POST /api/pkg/tatalaksana/list-detail
body: {"find_one":{"faskes_code":"","ta_lak_id":""},
       "find_two":{"faskes_code":<same as detail-screening>,
                   "reg_id":<same>, "program_code":<detail-screening.program_code or "pkg">}}
```

The response's `tatalaksana[]` array is one row per
(Kelompok Skrinning × klasifikasi) needing follow-up. Each row maps to the UI
table 1:1:

| Output field | Source | UI column |
|--------------|--------|-----------|
| `kelompok_skrinning` | `hasil_pemeriksaan` | Kelompok Skrinning (group header) |
| `tatalaksana_name` | `tatalaksana_name` | row label under the group |
| `hasil_pemeriksaan` | `parameter.hasil.{nilai,klasifikasi}` + `tatalaksana_name` | Hasil Pemeriksaan (e.g. `3 Prediabetes (Prediabetes)`) |
| `status` / `status_label` | `status` (`belum_dilakukan` → "Belum tatalaksana") | Status |
| `form_data` | the per-row `form_layanan.form_link` (read when status ≠ belum **or** `is_submit_form`) | Tatalaksana |

It is **dynamic** — however many groups/rows exist are all emitted. One
`list-detail` call is reg_id-scoped and returns **every** finding across **all**
kelompok in a single response (verified live 2026-06-16: DEVINA returned 4 rows
spanning 3 distinct kelompok — Gizi, Gula Darah, Tekanan Darah — at once), so
multi-condition patients are not split across calls and nothing is missed.

**Per-row form gate (verified live 2026-06-16):** a `belum_dilakukan` row's
"Mulai Tatalaksana" opens a **blank** form (only today's date pre-filled), so
we emit the table row but `form_data` stays `null`. Any other status (observed:
**`selesai`**) — **or** `form_layanan.is_submit_form == true` — means the
treatment was recorded; `_tata_row_needs_form` ORs the submitted flag so a
recorded row that ever reports an empty/unknown status is still read rather than
dropped. The flag tracks the status exactly on real data (True↔selesai,
False↔belum), and is False for blank rows, so this costs nothing. Its `form_link`
is the **same kind of `form.kemkes.go.id/v2/skrining-form` SurveyJS URL** the
Mandiri/Nakes path already reads (it fires the identical `cha-formbuilder/.../get/skrining-layanan`
answer-XHR), so it's opened with `has_answers=True` and read via
`_read_all_form_fields`. The treatment form's question set varies by klaster
(remaja vs dewasa; Diagnosis/Tindakan/Peresepan/Edukasi/Konseling/Tindak-lanjut
sections appear conditionally), which the generic SurveyJS reader handles.

> **Gate on `is_have_tatalaksana`, not the tab.** A patient can sit in
> *Sedang Pemeriksaan* and still have completed (`selesai`) tatalaksana rows
> (verified live: NIK 3275055503020011 / DEVINA AURELIA, 2 recorded rows). The
> detail-screening flag catches these; a "Selesai-tab-only" gate would miss them.

> **Reader note (the tatalaksana forms exposed a real bug, now fixed):** the
> recorded form's Diagnosis/Tindakan/Dosis fields are SurveyJS tag-comboboxes
> whose `.value` is an internal code (an Array `["R73"]` or a string `"DSP7"`),
> not the readable label. `_read_all_form_fields` now reads custom widgets via
> innerText (the visible label) and only trusts `.value` on real INPUT/SELECT/
> TEXTAREA controls — see `elText`. Validated end-to-end against DEVINA's two
> `selesai` rows (e.g. `"Dosis pemakaian": "Dewasa 0.5 Tablet; 3 kali tiap 1
> hari; selama 7.0 - 7.0 hari"`); Mandiri/Nakes field counts were unchanged.

> **Dynamic-panel repeats (multiple obat) — handled.** A Peresepan with several
> "Tambah obat" entries renders one `"Pilih obat"`/`"Dosis pemakaian"` question
> per obat with the *same* title. `setAnswer` now keeps every occurrence under
> an indexed key — `"Pilih obat"`, `"Pilih obat (2)"`, `"Pilih obat (3)"`, … —
> instead of dropping repeats; because questions render in panel order,
> `"Pilih obat (n)"` pairs with `"Dosis pemakaian (n)"`. The final prefix-dedup
> skips ` (n)` keys so identical repeats aren't collapsed. Validated live against
> DEVINA's 3-obat prescription (Acarbose + Metformin 500 + Metformin 750, 17
> fields). This is general — *any* repeated-label question across forms is now
> preserved, not just Peresepan.

> **Empty answers stay `null` — no phantom defaults (fixed 2026-06-16).** A
> selectbase question (radio / checkbox) is answered **only** by its `:checked`
> option(s). If nothing is checked the question is genuinely unanswered → `null`.
> The reader used to fall through to the label/dropdown/combobox readers, which
> would grab the **first option label** (`"Ya"`, the first checkbox, …) and emit
> it as a fabricated answer. `_read_all_form_fields` now computes `isSelectBase`
> (the `.sd-question__content` holds a radio/checkbox input) and skips those
> text-scraping fallbacks for selectbase questions — so an empty Ya/Tidak never
> reads as `"Ya"`. Proven with an offline DOM fixture (answered radios/checkboxes/
> text/dropdowns unchanged; unanswered ones → `null`) and a live DEVINA re-scrape
> (field counts byte-identical, every real answer intact). Filled text/date/
> dropdown controls are unaffected — they are not selectbase.

> **More reader-correctness fixes (deep review 2026-06-16).** An adversarial
> offline-DOM-fixture sweep found three more silent-corruption paths, all fixed
> and regression-checked live:
> 1. **Prefix-dedup deleted distinct questions.** The "remove polluted duplicate
>    key" pass deleted any `key` that merely *starts with* a shorter key and
>    shares its value — so `"Apakah pasien dirujuk ke FKTL"` was wiped by
>    `"Apakah pasien dirujuk"` (both `"Ya"`). Now it deletes only when the text
>    after the shorter label is blank or *is the answer itself* (true pollution),
>    never a genuinely longer question.
> 2. **`"Lainnya"` free text was dropped.** A selected radio/checkbox "other"
>    option kept only the `"Lainnya"` label; the typed detail is now appended
>    (`"Lainnya: <text>"`) from the revealed `.sd-comment` input.
> 3. **Boolean toggles** (`.sd-boolean`) read `true→"on"`, `false→null`. Now read
>    via `checked`/`indeterminate`: `true`/`false` → their on/off label, unset →
>    `null`. Defensive — current CKG forms use Ya/Tidak radiogroups, not booleans.
>
> A `data-name` fallback for title-less questions was **tried and reverted**: the
> only title-less elements in the real forms are non-data display/expression
> panels (`education_display`, `PROTA…-REK-…`), so keying them by `data-name`
> just added null-valued noise (DEVINA 7/17 → 9/20). Dropping them is correct.

## Module responsibilities

| Module | Does what |
|--------|-----------|
| `scraper.py` | CLI parsing, tab iteration, list-claim pagination loop, progress saving. `_deep_scrape_patients` reads patient records from the captured list-claim response and dispatches to `scrape_patient_via_api`. |
| `patient_scraper.py` | `scrape_patient_via_api` calls `/api/pkg/detail-screening` then batch-opens form URLs in tabs and reads them via `_read_all_form_fields`. When `is_have_tatalaksana`, `scrape_patient_tatalaksana` fetches `/api/pkg/tatalaksana/list-detail` and reads recorded per-row forms. Also `get_mitra_token` / `fetch_detail_screening` / `fetch_tatalaksana_detail` / Indonesian formatter helpers. |
| `captcha_solver.py` | Decoupled CAPTCHA solver — manual input now, LLM API later |
| `helpers/auth.py` | Login flow (visible + headless), navigation, popup removal |
| `helpers/browser.py` | Browser launch, session persistence, API response interception |
| `helpers/calendar.py` | Date range picker automation |
| `helpers/pagination.py` | Page-by-page navigation |
| `helpers/constants.py` | Paths, config loading, shared constants |

## Config keys

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `pelayanan_nakes_only` | bool | `false` | When `true`, skip all Pemeriksaan Mandiri forms and only collect Pelayanan Nakes data. Useful when only nakes service records are needed, cutting per-patient time roughly in half. |
| `include_blank_forms` | bool | `false` | When `true`, open and read every form in `list_pemeriksaan` regardless of `IsSubmitForm` or `is_skip` status. Unsubmitted forms will have `form_data` with all question labels present but values `null`. Useful for extracting the full question schema across all services for comparison. The answer-XHR gate is automatically skipped for blank entries to avoid the 6 s/form penalty. |
| `scrape_tatalaksana` | bool | `true` | When `true` (default), patients flagged `is_have_tatalaksana` also get their follow-up table scraped into a `tatalaksana` key (see Output schema). Set `false` to skip the extra `/tatalaksana/list-detail` call + per-row form reads. Always skipped under `--list-only`. |
| `mandiri_only` | bool | `false` | When `true` (or via `--mandiri-only`), open ONLY the Pemeriksaan Mandiri forms and skip Pelayanan Nakes + Tatalaksana (`pelayanan_nakes` is empty, `tatalaksana` absent). For the backend Mandiri-only backfill that patches existing patients without re-scraping Nakes. |

## CLI flags

```
--use-session          Reuse saved browser session (skip CAPTCHA on repeat runs)
--headless / --no-headless   Headless mode. Default: True (CAPTCHA solved in terminal). Use --no-headless for visible browser.
--tab {all,both,sedang,selesai,belum}   Which tab(s) to scrape (default: all)
--max-pages N          Limit pages per tab
--max-patients N       Stop after N patients (debug / reconnaissance)
--output PATH          Custom output JSON path
--date YYYY-MM-DD      Date filter (single day). Defaults to today's date.
--capture-network PATH Dump every captured XHR/fetch JSON response (request
                       body + response body + headers) to PATH for offline
                       analysis. Used for endpoint discovery.
--mandiri-only         Open ONLY Pemeriksaan Mandiri forms (skip Nakes +
                       Tatalaksana). See config key `mandiri_only`.
--niks NIK,NIK         Comma-separated NIK allowlist; only matching list-claim
                       rows (by `patient_nik`) are deep-scraped.
```

## CAPTCHA solver (`captcha_solver.py`)

This is deliberately a **separate file** so it can be swapped independently.

- `solve_captcha(image_path, config)` — main entry point
- Currently: renders CAPTCHA in terminal using Pillow half-block chars, prompts for text input
- Future: set `config.captcha_solver.type` to `"llm"` and provide `api_key` to auto-solve
- The solver has **zero Playwright dependency** — it only takes an image path and returns text

## Output schema

```json
{
  "metadata": { "source": "...", "scraped_at": "...",
                "date_filter": { "value": "YYYY-MM-DD",
                                 "source": "cli|config|default_today" },
                "total_records": N,
                "tabs": { "belum_pemeriksaan": K, "sedang_pemeriksaan": M, "selesai_pemeriksaan": N },
                "timing": { "total_elapsed_seconds": 123.4,
                             "captcha_wait_seconds": 15.2,
                             "scraping_seconds": 108.2 } },
  "belum_pemeriksaan": [...],
  "sedang_pemeriksaan": [
    {
      "detail_data": {
        "data_individu": { "NIK": "...", "Nama": "...", ... },
        "data_wali": { "NIK": "...", "Nama": "...", ... },
        "data_domisili": { "Alamat Domisili": "...", "Provinsi": "...", ... }
      },
      "pemeriksaan_mandiri": [...],
      "pelayanan_nakes": [...],
      "tatalaksana": {
        "ta_lak_id": "...", "klaster": "Remaja 17 Tahun Perempuan",
        "klaster_code": "...", "screening_date": "YYYY-MM-DD",
        "rows": [
          {
            "kelompok_skrinning": "Pemeriksaan Gula Darah Remaja",
            "tatalaksana_name": "Prediabetes",
            "hasil_pemeriksaan": "3 Prediabetes (Prediabetes)",
            "hasil_detail": { "klasifikasi": "Prediabetes", "nilai": 3, "warna_code": 3 },
            "parameter": { "code": "...", "label": "...", "rekomendasi": "...", ... },
            "status": "belum_dilakukan", "status_label": "Belum tatalaksana",
            "tatalaksana_code": "...", "hasil_pemeriksaan_code": "...",
            "form_code": "...", "form_name": "...", "is_submit_form": false,
            "form_data": null,
            "_raw": { ...the full untouched API row... }
          }
        ],
        "_raw_meta": { ...every top-level list-detail field except the rows... }
      }
    }
  ],
  "selesai_pemeriksaan": [...]
}
```

> **Lossless by design.** The curated keys above are a convenience view of the
> UI table; `rows[]._raw` (the full API row) and `tatalaksana._raw_meta` (all
> non-row top-level fields) guarantee that nothing the API returns is dropped,
> even fields we never anticipated (`log_activity`, `detail_faskes`, future
> columns…). The inner form reader is likewise dynamic — it captures *every*
> `.sd-question` (unknown questions included; value `null` if extraction fails
> but the label is still emitted). So new statuses, columns, klaster-specific
> form fields, etc. survive without a code change.
>
> `tatalaksana` is optional — present only when `is_have_tatalaksana` and at
> least one follow-up row exists. `rows[].form_data` is `null` for
> `belum_dilakukan` rows (blank form) and a `{question: answer}` dict for
> recorded rows. On a hard fetch error the whole key becomes `{"error": "..."}`.
> A recorded row whose individual form failed to load gets `form_read_error`
> set (with `form_data` `{}`), so a transient read failure is distinguishable
> from a genuinely empty form — re-scrape just those rows, not every patient.
> (`_batch_read_forms_via_tabs` returns results in input order and tags failed
> forms with an `error` key, which also surfaces on Mandiri/Nakes entries.)
> `data_wali` is optional — omitted when the patient has no guardian section.
> `metadata.date_filter` records which single-day filter was applied and
> whether it came from `--date`, `config.json`, or the implicit "today"
> default.

## How to run

```bash
cd asik
pip install -r requirements.txt
playwright install chromium
cp config.example.json config.json   # fill in credentials
python3 scraper.py                   # default: headless + terminal CAPTCHA
python3 scraper.py --use-session     # headless + session reuse (fastest)
python3 scraper.py --no-headless     # visible browser (CAPTCHA in UI)
```
