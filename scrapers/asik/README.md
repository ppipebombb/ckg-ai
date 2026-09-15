# ASIK CKG Pelayanan Scraper

Scrapes patient records from the Indonesian Ministry of Health ASIK portal
(`sehatindonesiaku.kemkes.go.id/ckg-pelayanan`) — the CKG Umum → Pelayanan
page. Collects data from both **Sedang Pemeriksaan** and **Selesai
Pemeriksaan** tabs, with full pagination. Always runs in **deep mode**:
every patient's detail page is opened and every eligible form is read.

> All commands below assume `cd asik` first.

## What it scrapes

For each patient row, the script enters the detail page and collects:

1. **Detail Data dialog** — full patient demographics (NIK, DOB, alamat,
   kelurahan / kecamatan, etc.).
2. **Pemeriksaan Mandiri** — for each row with a **green check** icon
   (`icon-success.svg`, not `icon-success-gray.svg`), opens `Input Data`
   and reads the answers.
3. **Pelayanan oleh Nakes** — for each row where `Diperiksa = "Ya"` AND
   status badge reads `Selesai diperiksa`, opens `Input Data` and reads
   the measurements / screening results.

The scraper **never** clicks `Kirim`, `Simpan`, `Submit`, `Selesaikan`,
`Selesaikan Layanan`, or `Kirim Rapor`. It is strictly read-only.

## CAPTCHA handling

The script opens a **visible** Chromium window, pre-fills credentials from
`config.json`, then **pauses up to 5 minutes for you to solve the CAPTCHA
and click login**. Once the URL leaves `/login`, automation takes over.

Use `--use-session` to persist the browser profile + cookies /
localStorage under `session/` so subsequent runs skip the CAPTCHA.

## Setup

```bash
pip install -r requirements.txt
playwright install chromium
cp config.example.json config.json
# edit config.json with your ASIK credentials
```

`config.json` is gitignored — do not commit it.

## Configure

`config.json` fields:

```json
{
  "base_url": "https://sehatindonesiaku.kemkes.go.id",
  "headless": false,
  "slow_mo": 100,
  "timeout": 60000,
  "max_pages": 500,
  "credentials": {
    "puskesmas_code": "",
    "username": "your_email@example.com",
    "password": "your_password"
  },
  "date": ""
}
```

Set `date` in `YYYY-MM-DD` format to filter by a single date, or pass it
on the CLI.

## Usage

```bash
# Scrape both tabs (default)
python3 scraper.py --use-session

# Only one tab
python3 scraper.py --use-session --tab sedang
python3 scraper.py --use-session --tab selesai

# Limit pages (useful for smoke testing)
python3 scraper.py --use-session --max-pages 1

# Custom output
python3 scraper.py --use-session --output full_data.json

# Date filter
python3 scraper.py --use-session --date 2026-04-16

# Testing
python3 scraper.py --use-session --tab selesai --max-pages 1

# No Headless
python3 scraper.py --use-session --no-headless
```

### CLI flags

| Flag | Default | Purpose |
|------|---------|---------|
| `--use-session` | off | Reuse saved browser session (skip CAPTCHA). |
| `--tab {both,sedang,selesai}` | `both` | Which patient-list tab to scrape. |
| `--max-pages N` | unlimited (capped by detected total or `config.max_pages`, default 500) | Stop after N paginated pages per tab. |
| `--output PATH` | `output/ckg_pelayanan_<YYYY-MM-DD>.json` | Output JSON path. |
| `--date YYYY-MM-DD` | from `config.json` | Date filter (single day). |

## Output

```json
{
  "metadata": {
    "source": "https://sehatindonesiaku.kemkes.go.id/ckg-pelayanan",
    "scraped_at": "2026-04-15T10:30:00",
    "total_records": 42,
    "tabs": {
      "sedang_pemeriksaan": 12,
      "selesai_pemeriksaan": 30
    }
  },
  "sedang_pemeriksaan": [
    {
      "detail_data": {
        "data_individu": {
          "NIK": "317401XXXXXXXXXX",
          "Nama": "ANAK CONTOH",
          "Tanggal Lahir": "13 Jan 2023",
          "Jenis Kelamin": "Perempuan"
        },
        "data_wali": {
          "NIK": "367405XXXXXXXXXX",
          "Nama": "IBU CONTOH",
          "Tanggal Lahir": "06 Okt 1999",
          "Jenis Kelamin": "Perempuan"
        },
        "data_domisili": {
          "Alamat Domisili": "Tebet",
          "Provinsi": "DKI Jakarta",
          "Kota": "Kota Adm. Jakarta Selatan",
          "Kecamatan": "Tebet",
          "Kelurahan": "Tebet Timur"
        }
      },
      "pemeriksaan_mandiri": [
        {
          "layanan": "Demografi Dewasa Perempuan",
          "form_data": {
            "Status Perkawinan": "Menikah",
            "Apakah Anda sedang hamil?": "Tidak"
          }
        }
      ],
      "pelayanan_nakes": [
        {
          "layanan": "Gizi (BB - TB - Lingkar Perut) Perempuan",
          "form_data": {
            "Berat Badan (Kg)": "56",
            "Pengukuran Tinggi Badan (cm)": "171"
          }
        }
      ],
      "tatalaksana": {
        "ta_lak_id": "01KV04TRD5W9BWA72ZD14K62RS",
        "klaster": "Remaja 17 Tahun Perempuan",
        "screening_date": "2026-06-13",
        "rows": [
          {
            "kelompok_skrinning": "Pemeriksaan Gula Darah Remaja",
            "tatalaksana_name": "Prediabetes",
            "hasil_pemeriksaan": "3 Prediabetes (Prediabetes)",
            "status": "belum_dilakukan",
            "status_label": "Belum tatalaksana",
            "is_submit_form": false,
            "form_data": null
          }
        ]
      }
    }
  ],
  "selesai_pemeriksaan": [ ]
}
```

The `tatalaksana` key appears only for patients whose pemeriksaan is finished
and who have follow-up rows (`detail-screening.is_have_tatalaksana`). Each row
mirrors the Tatalaksana table. `form_data` is `null` when the row's status is
`belum_dilakukan` (the per-row form is blank); for a recorded row it holds the
`{question: answer}` map read from the same SurveyJS form path as the others.
The curated fields are lossless-backed: each row keeps the full API row under
`_raw`, and `tatalaksana._raw_meta` keeps every top-level field, so nothing the
API returns is dropped even if it's a field we never mapped. See `CLAUDE.md` →
"Tatalaksana (follow-up treatment)" for the full contract.

Partial progress is written to `output/progress_<tab>.json` after every
patient, so a crash mid-run loses at most one row.

Failed rows are recorded inline as
`{"error": "...", "source_row": "Page X Row Y"}` so the sequence stays
aligned.

## How it works

```
launch browser ──► manual login (CAPTCHA) ──► /ckg-pelayanan
       │                                            │
       │                                            ▼
       │                              close popups (Pengaturan Pelayanan)
       │                                            │
       │                                            ▼
       │                                  set date range filter
       │                                            │
       │                                            ▼
       │                       for each selected tab (Sedang / Selesai):
       │                         ├── click tab
       │                         ├── for each page of the table:
       │                         │     └── for each row:
       │                         │           ├── open patient detail
       │                         │           ├── scrape via patient_scraper
       │                         │           ├── save progress JSON
       │                         │           └── return to list + restore page
       │                         └── click "next page"
       ▼
write final JSON to output/
```

`scraper.py` owns the orchestration. The helpers in `helpers/` own the
browser-level concerns:

| Module | Responsibility |
|--------|---------------|
| `helpers/constants.py` | paths, table columns, tab / month maps, `load_config()` |
| `helpers/browser.py` | `APIInterceptor` + persistent Chromium session |
| `helpers/auth.py` | `login`, `navigate_to_pelayanan`, `close_popups` |
| `helpers/calendar.py` | `set_date_filter` (single-date picker) |
| `helpers/pagination.py` | `click_next_page`, `navigate_to_page_num`, row counters |
| `patient_scraper.py` | `scrape_patient_detail` — per-patient deep scraper |

## What gets clicked

### Tab selection

`Sedang Pemeriksaan` and `Selesai Pemeriksaan`. The picker walks the DOM
with a `TreeWalker` and chooses the **deepest visible element** whose own
direct text (text nodes only, excluding children) equals the tab name —
OR whose `innerText` starts with the tab name with no more than 15 extra
characters (room for a badge count like `Selesai Pemeriksaan 7`).

A tab is treated as already active if its element has any of:
`aria-selected="true"`, `aria-current="page"`, or className matching
`/active|selected|current/`.

### Date range picker

| Step | Element clicked | Condition |
|------|-----------------|-----------|
| Open picker | First element whose text matches regex `\d{2}\s+\w{3}\s+\d{4}\s*-\s*\d{2}\s+\w{3}\s+\d{4}` (e.g. `05 Apr 2026 - 11 Apr 2026`). | Any `div / span / input / button / p`. |
| Read header | First element whose trimmed text matches `^[A-Za-z]{3,9}\s+\d{4}$` — that's the **left panel** header. | — |
| Navigate months | Element whose trimmed text equals `>` (next) or `<` (prev), `offsetParent !== null`. | Loops up to 48 times (4 years). |
| Click day | Walks `td / button / div / span / a`; first visible match where trimmed text = day number, className does **not** match `/disabled\|outside\|muted\|other\|grey\|gray\|prev\|next/`, `aria-disabled != "true"`, and `offsetWidth ≤ 80` and `offsetHeight ≤ 80`. | First match wins (= left panel). |

### Popup / modal removal

Six strategies, run every call:

1. **"Pengaturan Pelayanan" modal** — find an `H1/H2/H3/DIV/SPAN/P` whose
   trimmed text equals `Pengaturan Pelayanan`, walk up to 10 ancestors
   looking for a container that is `position: fixed/absolute` and wider
   than 30 % of the viewport, OR has `role="dialog"`, OR has a className
   matching `/modal|overlay|backdrop|dialog/i`. Removed via `.remove()`.
2. **Overlays / backdrops** — any element whose className contains
   `overlay`, `backdrop`, `modal-bg`, `modal-mask`, `dialog-overlay`, if
   positioned `fixed` or `absolute`.
3. **`role="dialog" / alertdialog"`** — removed unconditionally.
4. **Close-button fallback** (only if nothing was removed) — click the
   first visible `Tutup / Close / OK / Oke / ×` button.
5. **Generic full-screen overlay** — any `<div>` with `position: fixed`,
   `z-index > 999`, area ≥ 50 % × 50 % of viewport, containing `h1/h2/h3/form/select`.
6. **Body unlock** — clears `document.body.style.overflow` and
   `document.documentElement.style.overflow`.

### Per-row patient flow (`patient_scraper.py`)

For each row:

1. **Mulai button** — inside `tbody tr[rowIndex]`, click the first
   `button | a` whose trimmed text is `Mulai`.
2. **Detail Data dialog** — click the global `Detail Data` button, locate
   the `[role="dialog"] / [class*="modal"] / ...` whose `innerText`
   contains `Detail Data`, pair known labels with adjacent values. Close
   with the first `Tutup / Close / ×` button.
3. **Pemeriksaan Mandiri** — find the `Pemeriksaan Mandiri` heading,
   walk up to 8 ancestors to the container that holds at least one
   `<table>`, iterate every `<tr>`. Click `Input Data` only if all of:
   - row contains `<img>` whose `src` has `icon-success` but **not**
     `icon-success-gray` (green check)
   - row has an `Input Data` button
   - first `<td>` text is non-empty (= layanan name)
4. **Pelayanan oleh Nakes** — the section uses a CSS grid layout, not a
   `<table>`. Walk up to 8 ancestors to a container with more than 2
   `[class*="grid-cols"]` children, iterate each grid row. Click `Input
   Data` only if all of: has `Input Data` button, row text contains
   `Ya` (the *Diperiksa* toggle), row text contains `Selesai diperiksa`
   (green status badge), first child text is non-empty.
5. **Input Data click disambiguation** — for each `Input Data` button,
   walk up to 6 ancestors to the containing row (`<TR>` or `<div>` whose
   className contains `grid-cols`) and click only if that container's
   `innerText` contains the target layanan name.
6. **Return to detail page** — `page.go_back(...)` preferred,
   `window.history.back()` as a fallback, `page.goto(...)` as a last
   resort.

## Safety

`patient_scraper.py` keeps a blocklist of button labels that **must never
be clicked** (`DANGEROUS_BUTTONS`):

```python
["kirim", "submit", "selesaikan", "simpan", "save",
 "selesaikan layanan", "kirim rapor"]
```

`is_dangerous_button(text)` lower-cases and trims before comparing. The
form-reading flow only reads field values and then navigates back via
browser history — it never submits.

## Folder layout

```
asik/
├── scraper.py                 # CLI + orchestrator (CKGPelayananScraper)
├── patient_scraper.py         # Per-patient deep scraper (detail + forms)
├── helpers/
│   ├── __init__.py
│   ├── constants.py           # paths, tab / month maps, load_config
│   ├── browser.py             # APIInterceptor + persistent session
│   ├── auth.py                # login + navigate + close_popups
│   ├── calendar.py            # date range picker
│   └── pagination.py          # next / page-number navigation
├── config.example.json        # Config template (commit this)
├── config.json                # Your real config — gitignored
├── requirements.txt           # Python deps (playwright, rich)
├── README.md                  # This file
├── output/                    # Scraped JSON + per-run progress — gitignored
├── screenshots/               # Debug screenshots — gitignored
├── session/                   # Persistent browser profile — gitignored
└── tools/                     # (debugging helpers archived to .scratch/ — see below)
```

`config.json`, `output/`, `screenshots/`, and `session/` are gitignored at
the repo root via `*/config.json`, `*/output/`, etc.

## Debugging tools

These standalone scripts (used while building the scraper, not needed for
normal operation) have been **archived to `.scratch/scrapers/asik/tools/`**
(gitignored, kept for history) — they are no longer in the active tree.

```bash
# from .scratch/scrapers/asik/tools/
python3 debug_dom.py --use-session          # Dump DOM after manual nav
python3 inspect_input_data.py               # Probe Input Data form
python3 inspect_live_forms.py               # Inspect forms on form.kemkes.go.id
```

## Tips

- **Smoke test first** — `--max-pages 1` scrapes one page (~10 patients).
- **Progress is saved** — `output/progress_*.json` is written after each
  patient, so a crash loses at most one row.
- **Screenshots are your friend** — on failure check `screenshots/` for
  `error.png`, `01_login_prefilled.png`, `04_calendar_debug.png`,
  `tab_<key>.png`, etc.
- **Session drift** — if `--use-session` stops working, delete the
  `session/` folder and log in fresh.
