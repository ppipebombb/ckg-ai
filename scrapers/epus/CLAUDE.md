# epus-v2/CLAUDE.md — ePuskesmas Pelayanan Medis scraper (v2)

> Per-scraper LLM context. Root conventions (tech stack, safety rules,
> sub-scraper layout, code style) live in `../CLAUDE.md`. Keep this file
> up to date when epus-v2's data flow, modules, CLI, or output schema
> change.
>
> **This is an independent rebuild of the sibling `epus/` folder.**
> Another developer is actively working on `epus/` — do not modify
> `epus/` when the task is about epus-v2 (and vice versa).

## What this scrapes

`https://kotabekasi.epuskesmas.id/pelayanan` — the Pelayanan Medis list
page for Kota Bekasi. This scraper extracts records filtered by:

| Filter | Default | Meaning |
|--------|---------|---------|
| `status_periksa` | `3` (Sudah Diperiksa) | `2` = Belum Diperiksa |
| `ruangan_id` | `0001` (UMUM) | other poli ids also work |
| `limit` | `100` | site's max page size |
| `tanggal` | `17-04-2026` | DD-MM-YYYY (today's data was empty during recon) |

All filters are overridable via CLI. Default `tanggal` is `17-04-2026`
rather than "today" because today (2026-04-18) returned zero records
during initial recon — the recon date has real data.

## Why this is v2

`epus/` already targets this portal, but is being iterated on by another
developer. `epus-v2/` is an independent folder built from scratch that:

- Logs in directly at `/login` (vs. epus's portal-hover-into-dropdown path).
- Uses the DataTables XHR interceptor to pull structured records (vs.
  epus's DOM table scrape).
- Has no per-patient deep scrape (list-only).

The two folders share no code.

## Data flow

```
CLI args → launch browser →
  POST /login (email + password, no CAPTCHA) → 302 /home →
  GET /pelayanan?status_periksa=3&ruangan_id=0001&limit=100&tanggal=…
    (the SPA's on-load JS fires a DataTables XHR)
  →  APIInterceptor captures the response:
       { meta:{…}, data:{records:[…], totalRecords:N, page:"1", limit:"100"} }
  →  if totalRecords > limit:
       replay captured URL with page=2,3,… via context.request.get()
       (Laravel requires the X-Requested-With: XMLHttpRequest header)
  →  concatenate records, save JSON
```

Measured on 2026-04-18 (headless, 152 records for 17-04-2026,
status_periksa=3, ruangan_id=0001): ~11s end-to-end.

## The DataTables XHR (how the interceptor matches it)

The list page fires a single `GET` whose path is `/pelayanan` but whose
query string starts with `columns[0][data]=number&columns[0][searchable]=0&…`
and returns `application/json` with:

```json
{ "meta": { "result": "success", "code": 200, ... },
  "data": { "records": [...], "totalRecords": 152, "page": "1", "limit": "100" } }
```

`APIInterceptor.latest_datatable()` finds the most recent captured
response whose URL contains both `/pelayanan?` and `columns` with
`status == 200`, then returns the body. `latest_datatable_url()` returns
the URL itself so we can swap `page=1` → `page=N` for pagination.

### Why pagination needs custom headers

Calling `page.context.request.get(next_url)` against the captured URL
returns HTML, not JSON, because Laravel's `Request::ajax()` check keys
off `X-Requested-With: XMLHttpRequest`. Without it, Laravel routes the
request back to the HTML controller and returns a full page. Fix: pass
`X-Requested-With: XMLHttpRequest`, `Accept: application/json…`, and a
plausible `Referer` in the follow-up GETs (see
`scraper.py::_harvest_all_pages`).

## Record shape (top-level keys)

Preserved verbatim from the API response — nested objects are not
flattened. Representative keys:

```
id, pendaftaran_id, ruangan_id, laboratorium_id,
tanggal, tanggal_mulai, tanggal_mulai_dokter, tanggal_selesai,
antrean, prefix, status_bpjs, statuspulang_id,
mapping_klaster, siklus_hidup, jadwal_antrian_id,
ruangan: { nama, id },
kamar (string or object),
pendaftaran: {
  id, pasien_id, no_asuransi, asuransi_id, reg_type,
  status_pstprb, status_pstprol, keadaan_pasien,
  umur_tahun, umur_bulan, umur_hari,
  kunjungan, skrining_visual, warna_skrining_visual,
  pasien: { id, nama, nik, kelurahan_id, jenis_kelamin,
            tempat_lahir, tanggal_lahir, no_rm_lama,
            umur_tahun, umur_bulan, umur_hari,
            kelurahan: { id, nama }, peserta_bpjs: { ... } },
  asuransi: { id, nama, is_bridgingbpjs },
  dataAsuransi,
},
jadwal_antrian: { id, dokter_id, dokter: { id, nama } },
skrining_visual_medic: { pelayanan_id, value, color },
icon_bpjs, faskesAsal, customStatusSatuData, statusAskep
```

> `pendaftaran.pasien.nama` arrives with HTML wrapping (icon + skrining
> label). The scraper does **not** strip this — downstream consumers can
> strip tags if needed. This preserves full fidelity with the API.

## Module responsibilities

| Module | Does what |
|--------|-----------|
| `scraper.py` | CLI, orchestration, pagination loop, output. `_harvest_all_pages` owns the intercept → replay logic. `_deep_scrape_details` drives the per-patient flow. |
| `patient_scraper.py` | Per-patient detail scrape. `scrape_patient_detail` fetches `/pelayanan/show/{id}` + `/anamnesa/create/{id}?…` in parallel, discovers the tab list from Anamnesa's tab bar, parallel-fetches every other tab via stdlib `urllib` in a `ThreadPoolExecutor` (cookies snapshotted from the Playwright context), then batch-parses every tab HTML in a single `page.evaluate` call. Defines `DANGEROUS_URL_SUBSTRINGS` + `install_write_guard` as defense-in-depth. |
| `helpers/auth.py` | `login` (email + password + submit) and `navigate_to_pelayanan` (build the filtered URL and goto). |
| `helpers/browser.py` | `APIInterceptor` (captures all XHR/fetch JSON bodies), `launch_persistent_context`, `restore_saved_auth_state`, `save_auth_state`. |
| `helpers/constants.py` | Paths, `STATUS_PERIKSA`, defaults (`DEFAULT_RUANGAN_ID`, `DEFAULT_LIMIT`), `today_ddmmyyyy()`, `load_config`. |
| `tools/recon.py` | Standalone recon (not part of main flow): login + goto + dump every XHR to `output/recon_*.json`. Used during initial reverse-engineering. |
| `tools/recon_dates.py` | Sweep recent dates to find one with populated records. |
| `tools/recon_show.py` | Load `/pelayanan/show/{id}`, probe the DOM, click the latest Kunjungan card, dump modal + tabs. Used historically when we scraped via `/showriwayatpelayanan`. |
| `tools/recon_riwayat.py` | Direct probe of `/pelayanan/showriwayatpelayanan` via the onclick handler — confirmed the response is JSON `{title, form}` with one big HTML blob. (Historical; that flow is no longer used.) |
| `tools/recon_tabs.py` | Probe the tab-button structure on the show page: raw-HTTP fetch vs. JS-rendered, anchor enumeration, anamnesa-tab body fetch. |
| `tools/recon_tab_pages.py` | Fetch a handful of module pages (Diagnosa, Resep, PAL, Haji, COVID-19, …) raw and summarize their form-field prefixes. |
| `tools/recon_compare.py` | Compare the show page across different patient IDs to confirm the tab-visibility problem (only some tabs render as buttons per patient). |
| `tools/recon_force_tabs.py` | Confirm that `GET /{module}/create/{pelayanan_id}` returns 200 even when the show page didn't render that tab — this is why the scraper doesn't rely on show-page anchors. |
| `tools/recon_module_source.py` | Probe for a canonical module manifest (inline `<script>` blobs, `/konfigurasiform`, `/pelayanan/getmodule`…). None exists — but it confirmed the Anamnesa page always embeds every sibling-module anchor, which is what the runtime discovery relies on. |
| `tools/recon_discover_modules.py` | Verify that Anamnesa's tab bar lists every patient tab across multiple patients (including ones whose show page only renders 2–3 buttons). This is the empirical basis for using Anamnesa as the tab-discovery bootstrap. |

> **Archived:** the `tools/recon_*.py` reconnaissance scripts above (plus `epus_config.py`, `gen_asik_report.py`) were one-off reverse-engineering aids and now live under `.scratch/scrapers/epus/tools/` (gitignored, kept for history) — they are no longer in the active tree. The live skrining tooling (`recon_skrining.py`, `skrining_inventory.py`, `enrich_db_skrining.py`) remains here and stays tracked.

There is no `captcha_solver.py`, no `calendar.py` — the flow uses URL
params, not date-picker clicks, and the portal has no CAPTCHA.

## CLI flags

```
--use-session          Reuse saved browser session (skip login on repeat runs)
--headless / --no-headless   Default: True. Use --no-headless for a visible browser.
--date DD-MM-YYYY      tanggal filter (default: today; falls back to config.filters.date if set)
--status {sudah,belum} status_periksa filter (default: sudah = 3)
--ruangan-id ID        ruangan_id filter (default: 0001 = UMUM)
--limit N              page size (default and site max: 100)
--max-pages N          Stop after N pages (debugging)
--output PATH          Custom output JSON path
--capture-network PATH Dump every captured XHR/fetch JSON response to PATH
--detail-limit N       Cap how many patients to deep-scrape (for testing).
                       Default: no cap (every list record is deep-scraped).
--tab-workers N        Concurrent tab fetches per patient. Default: 10.
                       5 is safer on slow servers; 20 adds ~5% speed
                       with more load.
```

## Per-patient detail scrape (always on)

Drives off the list's `records[].id` (the pelayanan id). For each one:

1. `GET /pelayanan/show/{id}` — fetched via `context.request.get()` (raw
   HTTP, **no browser navigation, no JS**). This is important because
   opening the URL in a tab auto-fires `POST /klaster_siklushidup/{id}`,
   which is a write. Fetching the raw HTML bypasses that entirely.
   - `table#table_pasien` → `data_pasien` dict of label : value
   - Panel "Penyakit Khusus" (`tabel_detail_warna_penyakit`) → array of
     `{Warna, ICDX, Penyakit}` (empty when the sentinel "Data tidak
     ditemukan." row is present — `parseArrayTable` filters it)
   - Panel "Risiko Kehamilan" (`tabel_detail_risiko_kehamilan`) → array
     of `{Warna, Skor Ibu (KSPR), Status}`
   - "Riwayat Pasien" → `riwayat_pasien`: array of `{jenis, nama, tanggal}`
     (illness history — Sekarang / Dulu / Keluarga). "Alergi Pasien" →
     `alergi`: array of `{jenis, nama, tanggal}`. **Region-robust**: the new
     build (jaksel/Tebet) uses `table_riwayat` / `table_alergi` (3 cols, has
     Tanggal); the old build (kotabekasi/kotatangerang) renders a
     `<label>`-titled, id-less 2-column table (no Tanggal). Located by id-hint
     OR exact heading text, so both builds parse to the same shape (`tanggal`
     is `null` on the old build). Empty/absent → `[]`.
   - "Data Skrining" (`table#table_skrining`) → `data_skrining`: array of
     `{skrining, tanggal, keterangan, detail_href}` — the legacy screening
     index, server-rendered in all 3 regions. The first tbody row (an
     "add-new" template with a `<select name="skrining">`) is skipped. Rows
     are ILP (no hidden inputs, `keterangan="Skrining ILP"` — overlaps
     `skrining_klaster`) or legacy (hidden `Skrining[n][skrining]/[tanggal]`
     + a `detail_href` "show link"). We capture the index only — `detail_href`
     pages are **not** auto-fetched (a patient can have 4–19 historical
     screenings; fetching each would multiply per-patient fetches, and the
     current-visit details already arrive via the module tabs).

2. `GET /anamnesa/create/{pelayanan_id}?from='pelayanan'&action='edit'` —
   this is the **tab-discovery bootstrap**. Its tab bar consistently
   contains links to every sibling module regardless of patient state,
   so we parse its anchors (`<a href>` whose path ends with the
   `pelayanan_id`, with visible text 1..60 chars) to discover the
   current list of tabs. That list drives step 3.

   The Anamnesa HTML is also parsed for its own form fields, so no extra
   fetch is needed — Anamnesa's discovery pass doubles as its content
   pass.

   **Bar discovery is necessary but NOT sufficient — it is unioned with a
   known-module safety net (`_merge_known_modules`).** The per-region builds
   list DIFFERENT module subsets in their Anamnesa tab bar: verified live
   2026-06-05, jaksel's new build lists only ~15 of the ~33 modules that
   `GET /{module}/create/{pid}` actually serves WITH DATA, so pure bar
   discovery silently dropped ~17 tabs/patient for the LARGEST region
   (covid19, tbparu, mata, konselinghiv, periksaiva/ims, pkpr, psikologi,
   kohort, mtbsv2, imunisasi, kb, caten, odontogram, periksagizi,
   anestesibedah, kartubayi) — including the converter-consumed
   **Konseling HIV / TB Paru / PKPR** tabs, so jaksel's HIV/TB/PKPR
   conversions were empty. The union force-fetches every `_KNOWN_MODULES`
   entry too; a module that doesn't apply to a patient/region returns 404
   and is dropped (probed-only modules leave no error stub). Discovery stays
   dynamic — a NEW module in the bar is still picked up, so future modules
   need no code change. After this fix all 3 regions scrape ~33–34 tabs.

3. For each other discovered tab, GET the URL from its anchor, parse
   the response as a Laravel form page, and emit a clean shape that
   mirrors data_pasien: `fields = { "<Section>": { "<Question>": answer, … } }`.
   Question labels come from `.form-group > .control-label` (what the
   user actually reads on screen). Answers are type-specific — e.g. a
   radio's answer is the checked option's label ("Ya" / "Tidak"), a
   select's answer is the selected option's text ("Berobat Jalan"), a
   grouped checkbox is `{optionLabel: bool, …}`.
   **Unanswered questions are emitted as `null`** so downstream can
   diff the full question set (e.g. against `asik/`).

### Why the output reads like data_pasien (not raw form dumps)

Earlier versions emitted raw `<input name>` values grouped by bracket
prefix — `Anamnesa[keluhan_utama]` → `fields.Anamnesa.keluhan_utama`.
That worked but leaked:
  - database IDs (`PeriksaFisik[id]`, `Anamnesa[dokter_id]`) which are
    rendered as `<input type="text" class="hidden">` (not
    `type="hidden"`),
  - JSON config blobs (`data_imt`) stuffed into hidden inputs,
  - framework scaffolding from the tindakan consent modal / antrol
    countdown / print dialog that every tab ships.

The current extractor only walks controls that have both (a) no
`hidden` / `d-none` CSS class, (b) a `.form-group` ancestor with a
`.control-label`, (c) a `.box` / `.panel` / `fieldset` ancestor with a
heading, and (d) aren't inside a blocked modal / nav container
(`_BOILERPLATE_CONTAINER_IDS`) or a blocked section heading
(`_BOILERPLATE_SECTION_PREFIXES`). That drops all the scaffolding in
one pass without per-field allow-listing.

### Speed: parallel tab fetches + batched DOM parsing

With ~32 tabs per patient × 150+ patients, sequential scraping was
~21s/patient (~53 min total). Two optimizations cut that to ~5s/patient
(~13 min total):

- **Parallel fetches.** Playwright's sync API blocks on IPC to the
  browser, so `context.request.get()` can't run concurrently. Instead,
  we snapshot cookies via `context.cookies()` once per patient, build a
  `Cookie: …` header, and fetch all the tab URLs through
  `urllib.request` inside a `ThreadPoolExecutor`. Stdlib only — no new
  dependency. Configurable via `--tab-workers` (default 10; 5 for slow
  servers, 20 for marginal extra speed).
- **Batched DOM parsing.** `page.evaluate` has a ~5ms round-trip
  overhead. For 32 tabs × 150 patients that's ~25 seconds of pure IPC.
  `_parse_tabs_batch` sends every tab HTML in one `evaluate` call and
  returns an array of parsed field dicts. One IPC per patient instead
  of 32.

Benchmarked on 3 patients (post-login, post-list): 5 workers → 6.5s,
10 workers → 5.2s, 20 workers → 4.9s. Diminishing returns past 10.
Read-only semantics are preserved — urllib never executes JS, and write
endpoints (`/klaster_siklushidup/*`, `/pelayanan/save`, etc.) are not
among the discovered tab URLs.

### Why tab discovery is dynamic (not a hardcoded list)

Three candidate "source of truth" pages were evaluated (see
`tools/recon_module_source.py` + `tools/recon_discover_modules.py`):

| Candidate                          | Result |
|------------------------------------|--------|
| `/pelayanan/show/{pid}`            | Unreliable. Only 2–8 tabs render as buttons for most patients — the UI "unlocks" the rest after the user clicks into one. Parsing its anchors gives inconsistent per-patient coverage. |
| `/konfigurasiform`, `/pelayanan/getmodule`, `/pelayanan/listmodule`, … | No JSON manifest exists. The admin pages return HTML with no structured module list. |
| `/anamnesa/create/{pid}?…`          | **Reliable.** Its tab bar links to every sibling module across every patient tested (197732, 197125, 197129, 197135). Patient-state-independent. |

So the scraper fetches Anamnesa once per patient as a bootstrap and
discovers tabs from its tab-bar anchors. If Kemkes adds a new module
(say "Rontgen") the next run picks it up automatically; if they rename
one the label updates automatically. The only thing that would break is
Kemkes removing the Anamnesa module itself or re-skinning the tab bar
without anchor links — both are unlikely.

(For reference, the backend endpoints for every discovered module
accept a `GET` regardless of whether the show page rendered them as
buttons — confirmed by `tools/recon_force_tabs.py`. The "sometimes the
tab isn't there" behavior is purely UI gating, not data gating.)

### Boilerplate filtered from tab field output

Every tab page ships the same tindakan-consent modal, antrol countdown
widgets, print/sign toggles, etc. These share prefixes that aren't part
of the tab's own data. `_BOILERPLATE_PREFIXES` drops them
(`tindakanPayload`, `aggrement`, `skip_validasi_antrol`,
`antrol_countdown_send`, `CetakSuratElektronik`, etc.), and also drops
the standalone duplicates of `Pelayanan[...]` fields (`tanggal_mulai`,
`tanggal_selesai`, `dokter_id` as bare names).

### HTML parsing strategy

All HTML is parsed via `new DOMParser().parseFromString(html, 'text/html')`
inside `page.evaluate`. DOMParser **does not execute scripts**, so even
if the server HTML contains an inline `<script>` that would POST to a
write endpoint, it never runs. This keeps us safe *and* avoids adding
a `beautifulsoup4` dependency.

Editable-grid tables with `<thead>` (Resep drug list, Pemakaian Obat,
Diagnosa rows, Riwayat Lab/Odontogram) ARE extracted into a separate
`tables` key on each tab. Cell values come from visible inputs/selects
only — never from `innerText`, which would concatenate every `<option>`
and leak the option list as data. Empty template rows (unsaved form
seeds) are dropped by the "all cells empty" check. Radio/checkbox-only
tables (Skrining) are skipped here because Pass 1 already captures
them as `fields`.

Output shape:
```jsonc
"Resep": {
  "url": "…/resep/create/…",
  "module": "resep",
  "fields": { … },                  // metadata + form-field questions
  "tables": {
    "Resep": [                       // table heading from .box-header
      { "Racikan": "", "Nama Obat": "ACETYLCYSTEINE …",
        "Jumlah": "10", "Signa": "3 x 1",
        "Aturan Pakai": "Sesudah Makan", "Keterangan": "" },
      …
    ]
  }
}
```

### Output schema

The final JSON is `{metadata, patients: [...]}`. The list is the source of
pelayanan ids (`records[].id`) **and** each record is persisted per-patient as
`list_record` (BPJS Prolanis/PRB flags, asuransi, dokter, kelurahan, structured
umur, visual-triage — structured data not on the show page). `_records_from`
stashes every record by id; `_deep_scrape_details` attaches it to each result.

```jsonc
{
  "metadata": {
    "source": "https://kotabekasi.epuskesmas.id/pelayanan/show/{id}",
    "scraped_at": "...",
    "total_patients": 152,
    "filters": { "tanggal": "...", "status_periksa": "3", ... },
    "timing": { "total_elapsed_seconds": 123.4 }
  },
  "patients": [ ... ]
}
```

Each entry in `patients`:

```jsonc
{
    "pelayanan_id": "197732",
    "data_pasien": { "ID.": "197732", "NIK": "…", "Nama Pasien": "SANTI", … },
    "list_record": { "id": "197732", "pendaftaran": { "pasien": { "peserta_bpjs": { "pstPrb": "", "pstProl": "" }, … }, "asuransi": {…} }, "jadwal_antrian": { "dokter": { "nama": "dr. …" } }, … },
    "penyakit_khusus": [],
    "risiko_kehamilan": [],
    "riwayat_pasien": [
      { "jenis": "Riwayat Penyakit Sekarang", "nama": "batuk 1 minggu …", "tanggal": "04-06-2026" },
      { "jenis": "Riwayat Penyakit Dulu", "nama": "Riwayat Hipertensi tidak ada …", "tanggal": "04-06-2026" }
    ],
    "alergi": [
      { "jenis": "Obat", "nama": "Tidak Ada", "tanggal": "04-06-2026" }
    ],
    "data_skrining": [
      { "skrining": "Skrining Kesehatan Jiwa Dewasa dan Lansia (PHQ-4)",
        "tanggal": "2026-06-04", "keterangan": "Skrining ILP", "detail_href": null },
      { "skrining": "TBC", "tanggal": "2025-11-11", "keterangan": null,
        "detail_href": "https://…/skrining/create/243435?from='pelayanan'" }
    ],
    "tabs": {
      "Anamnesa": {
        "url": "https://…/anamnesa/create/197732?…",
        "module": "anamnesa",
        "fields": {
          "Pasien Pulang": {
            "Status Pulang": "Berobat Jalan",
            "Tgl. Mulai": "21-04-2026 08:59:58",
            "Lama Pelayanan": { "hari": "0", "jam": "0", "menit": "0" },
            "Tgl. Rencana Kontrol": null
          },
          "Anamnesa": {
            "Dokter / Tenaga Medis": "IKA KURNIA",
            "Keluhan Utama": "ambil hasil tes dahak sekalian konsul",
            "Lama Sakit": { "tahun": "0", "bulan": "0", "hari": "1" }
          },
          "Periksa Fisik": {
            "Sistole": "102",
            "Diastole": "75",
            "Triage": "Tidak Gawat Darurat",
            "Merokok": "Tidak"
          },
          "Keadaan Fisik": {
            "Pemeriksaan Kulit": {
              "Inspeksi": "Normal : kulit tidak ada ikterik/pucat/sianosis",
              "Palpasi": "Normal : lembab, turgor baik/elastic, tidak ada edema"
            }
          }
        }
      },
      "Diagnosa": {
        "fields": {
          "Buat Baru Diagnosa": {
            "Prognosa": "Sanam (Sembuh)",
            "Tandai Penyakit Kronis": {
              "Diabetes Mellitus": false,
              "Hipertensi": false,
              "Kanker": false
            }
          }
        }
      },
      "COVID-19": {
        "fields": {
          "Informasi Klinis": {
            "Demam": "Tidak",
            "Batuk": "Tidak",
            "Tgl timbul gejala (onset)": null
          }
        }
      }
    }
  }
```

Answer types:
  - text/number/date inputs → string (or null when empty)
  - textarea → trimmed text (or null)
  - select → selected option's text ("Berobat Jalan"); placeholder
    options ("- PILIH -", "Pilih …") become null
  - radio group → the checked option's label ("Ya" / "Tidak") or null
  - single checkbox → true/false
  - grouped checkboxes (e.g. Tandai Penyakit Kronis) → dict of each
    option's check state
  - multiple inputs sharing one question label → sub-dict keyed by the
    form name's last bracket segment (e.g. Lama Sakit → tahun/bulan/hari)

If a tab fetch errors, the entry becomes `{"url": …, "module": …,
"error": "…"}` so the rest of the patient's output is still intact.

## How to run

```bash
cd epus-v2
pip install -r requirements.txt
playwright install chromium
cp config.example.json config.json             # fill credentials
python3 scraper.py                              # list + deep scrape every record; today's date
python3 scraper.py --date 17-04-2026            # override date
python3 scraper.py --use-session                # fastest — reuses cookies
python3 scraper.py --no-headless                # visible browser for debugging
python3 scraper.py --max-pages 1                # quick smoke test (page 1 only)
python3 scraper.py --date 17-04-2026 --detail-limit 5   # cap to first 5 patients
```

## Safety rules (scraper-specific)

This scraper is strictly read-only. Concretely:

- Only HTTP write per run: `POST /login` (auth). Same goes for
  `save_auth_state` when `--use-session` is passed (a probe page-load).
- All list data: `GET /pelayanan?…` (DataTables JSON).
- All show-page data: `GET /pelayanan/show/{id}` (raw HTML).
- Tab-discovery bootstrap: `GET /anamnesa/create/{id}?…` (raw HTML).
- Per-tab data: `GET /{module}/…/{id}?…` for each anchor discovered in
  the Anamnesa page's tab bar (raw HTML). The exact URL is the one the
  site ships — we never rewrite it.

### Why we never navigate the browser to `/pelayanan/show/{id}`

Loading that URL in a Playwright page (as opposed to fetching the raw
HTML) runs the page's on-load JavaScript, which auto-fires
`POST /klaster_siklushidup/{id}` — a **write** that re-saves the
patient's klaster + siklus hidup fields. Even though the values being
re-saved match the existing values (so it's idempotent in practice), the
policy is zero writes. The detail-scrape flow uses
`context.request.get()` to pull the raw HTML, so JS never runs.

`patient_scraper.install_write_guard(context)` adds a belt-and-braces
route handler that aborts `POST` requests to any URL matching
`DANGEROUS_URL_SUBSTRINGS` (`/klaster_siklushidup/`, `/pelayanan/save`,
`/pelayanan/kirim`, `/pelayanan/update`, `/pelayanan/delete`). The main
flow doesn't need it because no navigation is performed, but it's there
for any future caller that does.

### Why DOMParser (and not BeautifulSoup)

All HTML parsing in `patient_scraper.py` happens inside
`page.evaluate(js, html)` where the JS uses
`new DOMParser().parseFromString(html, 'text/html')`. DOMParser is a
specified-to-not-execute-scripts browser API, so even if the HTML blob
from `showriwayatpelayanan` embeds a `<script>`, it will never run.
This avoids adding `beautifulsoup4` as a dependency (per root
CLAUDE.md's "No unnecessary dependencies" rule) while keeping parsing
safe.
