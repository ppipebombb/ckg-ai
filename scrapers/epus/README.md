# epus-v2 — ePuskesmas Pelayanan Medis scraper

A parallel rebuild of the `epus/` scraper that targets the same portal
(`kotabekasi.epuskesmas.id`) but takes a purely **API-interceptor**
approach instead of DOM scraping + sidebar clicking.

## What it scrapes

`https://kotabekasi.epuskesmas.id/pelayanan` — the Pelayanan Medis list,
filtered to:

| Filter | Value |
|--------|-------|
| `status_periksa` | `3` (Sudah Diperiksa) |
| `ruangan_id` | `0001` (UMUM) |
| `limit` | `100` (site max) |
| `tanggal` | `17-04-2026` (override via `--date`) |

The page fires a DataTables-style `GET /pelayanan?columns[...]&page=N&...`
XHR on load. We intercept the first page's response, then replay the
captured URL with `page=2,3,…` (via `context.request.get()`) to paginate
until we've consumed `totalRecords`.

## Why a v2

`epus/` is actively being worked on by another developer, so this folder
is an independent rebuild. It doesn't share code with `epus/` and won't
be imported from there.

## Setup

```bash
cd epus-v2
pip install -r requirements.txt
playwright install chromium
cp config.example.json config.json   # fill in credentials.email + credentials.password
```

## Usage

```bash
python3 scraper.py                          # list + deep-scrape every record; today's date
python3 scraper.py --use-session            # skip login on repeat runs
python3 scraper.py --no-headless            # show the browser
python3 scraper.py --date 17-04-2026        # override date (DD-MM-YYYY)
python3 scraper.py --status belum           # Belum Diperiksa (status_periksa=2)
python3 scraper.py --ruangan-id 0002        # different poli
python3 scraper.py --max-pages 1            # debug / reconnaissance
python3 scraper.py --capture-network x.json # dump every captured XHR
python3 scraper.py --date 17-04-2026 --detail-limit 5
                                            # cap deep-scrape to first 5 patients
```

Output lands in `output/pelayanan_medis_<DD-MM-YYYY>.json`.

## Output schema

The output is `{metadata, patients: [...]}`. List-page records are
**not** persisted — the list page is only used internally to discover
pelayanan ids, which are then resolved against `/pelayanan/show/{id}`.
See `CLAUDE.md` for the full patient-entry schema (Data Pasien, Penyakit
Khusus, Risiko Kehamilan, Kunjungan riwayat with dynamic sub-tabs).

## Safety

This scraper is strictly read-only. It only:

- POSTs `/login` once per run (or skips via `--use-session`).
- GETs `/pelayanan?…` for the list JSON.
- In `--detail` mode: GETs `/pelayanan/show/{id}` (raw HTML, no JS run)
  and `/pelayanan/showriwayatpelayanan?…` (JSON).

It never clicks any row action buttons (`Periksa`, `Kirim`, `Hapus`,
`Simpan`, `Selesaikan`, etc.) and does not write or modify any record.
The detail scraper uses `context.request.get()` instead of navigating
the browser, so the page-load JS that would otherwise auto-fire
`POST /klaster_siklushidup/{id}` never runs. See `CLAUDE.md` for the
full safety rationale.
