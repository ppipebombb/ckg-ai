"""
=============================================================================
epus-v2 — Pelayanan Medis scraper (kotabekasi.epuskesmas.id)
=============================================================================
Logs in with email + password, navigates to /pelayanan with the
pre-applied filters (status_periksa, ruangan_id, limit, tanggal),
intercepts the DataTables-style JSON XHR that the page fires, and
writes the records to JSON. No form clicking — strictly URL + intercept.

Filters default to the ones the task called for:
  - status_periksa = 3   (Sudah Diperiksa)
  - ruangan_id     = 0001 (UMUM)
  - limit          = 100  (max the UI accepts)
  - tanggal        = 17-04-2026 (overridable via --date)

Paginates by re-issuing the captured DataTables request with `page=N`
substituted, using context.request.get() — the app's cookies are
automatically attached.

Usage:
  python scraper.py                         # headless, default filters
  python scraper.py --use-session           # skip login on repeat runs
  python scraper.py --no-headless           # show the browser
  python scraper.py --date 17-04-2026       # override date
  python scraper.py --status belum          # Belum Diperiksa (2) instead
  python scraper.py --ruangan-id 0002       # different poli
  python scraper.py --max-pages 1           # debugging
  python scraper.py --capture-network all_xhr.json  # dump every captured XHR
=============================================================================
"""

# --- parent-death watchdog: kill ourselves if the launching terminal closes ---
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))
from _lifecycle import install as _install_lifecycle  # noqa: E402
_install_lifecycle()
# --- end watchdog ---

import argparse
import json
import re
import time
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright, Page
from rich.console import Console
from rich.panel import Panel
from rich.table import Table as RichTable

from helpers import (
    OUTPUT_DIR,
    SCREENSHOT_DIR,
    SESSION_DIR,
    STATUS_PERIKSA,
    DEFAULT_RUANGAN_ID,
    DEFAULT_LIMIT,
    today_ddmmyyyy,
    APIInterceptor,
    load_config,
    launch_persistent_context,
    _CHROME_UA,
    restore_saved_auth_state,
    save_auth_state,
    login,
    navigate_to_pelayanan,
)
from patient_scraper import scrape_patient_detail, scrape_patients_concurrent

console = Console()


class PelayananMedisScraper:

    def __init__(self, args):
        self.args = args
        self.config = load_config()
        self.base_url = self.config.get("base_url", "https://kotabekasi.epuskesmas.id")
        self.interceptor = APIInterceptor(verbose=bool(getattr(args, "capture_network", None)))
        self._list_ids: list[str] = []  # internal — pelayanan ids discovered from the list
        self._list_records: dict[str, dict] = {}  # id -> full DataTables list record
        self.patients: list[dict] = []
        # Multi-date mode: results_by_date[ISO date] = list of patient dicts
        # for that day. Populated only when --dates is used; final output
        # shape switches to {"by_date": {...}} so the worker can attribute
        # each record to the correct Patient.filter_date.
        self.results_by_date: dict[str, list[dict]] = {}
        self.dates_list: list[str] = []  # list of DD-MM-YYYY when --dates is set
        if getattr(args, "dates", None):
            self.dates_list = [d.strip() for d in args.dates.split(",") if d.strip()]
        # When set, scraper loops niks × dates with searchKey filter applied
        # per (date, nik). Used by GDP orchestrator to restrict EPUS scrape
        # to the NIKs that came back from ASIK phase.
        self.niks_list: list[str] = []
        if getattr(args, "niks", None):
            self.niks_list = [n.strip() for n in args.niks.split(",") if n.strip()]
        # DataTables URL captured on first navigation. Direct (date, nik)
        # cycles replay this URL with params swapped — skips page.goto and
        # the SPA boot, keeping each lookup to one HTTP round-trip.
        self._dt_url_template: str | None = None

    # --------------------------------------------------------------
    # Entry point
    # --------------------------------------------------------------
    def run(self):
        self.start_time = time.time()

        headless = self.args.headless
        date = self.args.date or self.config.get("filters", {}).get("date") or today_ddmmyyyy()
        status_key = self.args.status
        status_periksa = STATUS_PERIKSA[status_key]
        ruangan_id = self.args.ruangan_id or \
            self.config.get("filters", {}).get("ruangan_id") or DEFAULT_RUANGAN_ID
        limit = self.args.limit or \
            self.config.get("filters", {}).get("limit") or DEFAULT_LIMIT
        search_key = self.args.nik or self.config.get("filters", {}).get("search_key")

        self.date = date
        self.status_key = status_key
        self.status_periksa = status_periksa
        self.ruangan_id = ruangan_id
        self.limit = limit
        self.search_key = search_key

        browser_mode = "[bold red]HEADLESS[/bold red]" if headless else "[bold green]VISIBLE[/bold green]"
        console.print(Panel(
            f"[bold green]epus-v2 Pelayanan Medis Scraper[/bold green]\n"
            f"Browser: {browser_mode}\n"
            f"Date: {date}  |  status_periksa={status_periksa} ({status_key})\n"
            f"ruangan_id={ruangan_id}  |  limit={limit}",
            title="Starting",
        ))

        OUTPUT_DIR.mkdir(exist_ok=True)
        SCREENSHOT_DIR.mkdir(exist_ok=True)

        with sync_playwright() as p:
            slow_mo = 0 if headless else 50

            if self.args.use_session:
                if SESSION_DIR.exists():
                    console.print("[cyan]Reusing saved session...[/cyan]")
                context = launch_persistent_context(p, headless=headless, slow_mo=slow_mo)
                page = context.pages[0] if context.pages else context.new_page()
                restore_saved_auth_state(context, page)
                browser = None
            else:
                browser = p.chromium.launch(headless=headless, slow_mo=slow_mo)
                context = browser.new_context(
                    viewport={"width": 1400, "height": 900},
                    locale="id-ID",
                    timezone_id="Asia/Jakarta",
                    # Same firewall-bypass UA as launch_persistent_context (see
                    # browser.py) — the no-session path (single-date scrapes) must
                    # override the HeadlessChrome UA too, or epuskesmas.id's WAF
                    # returns a formless "Blocked by Firewall" page and login fails.
                    user_agent=_CHROME_UA,
                )
                page = context.new_page()

            page.set_default_timeout(self.config.get("timeout", 60000))
            context.on("response", self.interceptor.on_response)

            try:
                login(page, self.base_url, self.config.get("credentials", {}), headless=headless)
                if self.args.use_session:
                    save_auth_state(context, page, self.base_url)

                if self.dates_list and self.niks_list:
                    # Multi-date bulk-intersect path. Per date: paginate full
                    # EPUS list (no searchKey), then intersect with target NIK
                    # set in memory. Drops list req count from N_niks to
                    # ceil(daily_total / page_size) per date — typically
                    # 1-3 reqs vs 1000+. Detail fetches unchanged (only
                    # matches get deep-scraped).
                    target_set = {n for n in self.niks_list if n}
                    for d_ddmmyyyy in self.dates_list:
                        self._scrape_one_date_bulk_intersect(
                            page,
                            tanggal=d_ddmmyyyy,
                            target_niks=target_set,
                        )
                        self._save_results()
                elif self.dates_list:
                    # Multi-date: walk every date in one browser session.
                    for d_ddmmyyyy in self.dates_list:
                        self._scrape_one_date(
                            page,
                            tanggal=d_ddmmyyyy,
                            status_periksa=status_periksa,
                            ruangan_id=ruangan_id,
                            limit=limit,
                            search_key=search_key,
                        )
                        self._save_results()
                else:
                    navigate_to_pelayanan(
                        page,
                        self.base_url,
                        tanggal=date,
                        status_periksa=status_periksa,
                        ruangan_id=ruangan_id,
                        limit=limit,
                        search_key=search_key,
                    )

                    self._harvest_all_pages(page)
                    self._deep_scrape_details(page)
                self._save_results()

            except Exception as e:
                console.print(f"\n[bold red]Error: {e}[/bold red]")
                try:
                    page.screenshot(path=str(SCREENSHOT_DIR / "error.png"))
                except Exception:
                    pass
                raise
            finally:
                if getattr(self.args, "capture_network", None):
                    try:
                        n = self.interceptor.dump(self.args.capture_network)
                        console.print(f"\n[bold cyan]Network capture:[/bold cyan] "
                                      f"wrote {n} response(s) to {self.args.capture_network}")
                    except Exception as e:
                        console.print(f"[yellow]Could not dump network capture: {e}[/yellow]")

                if browser is not None:
                    browser.close()
                else:
                    context.close()

    # --------------------------------------------------------------
    # Bulk + intersect path: pull full EPUS list for one date (no
    # searchKey), build {nik: pelayanan_id} from records, intersect with
    # the target NIK set in memory, deep-scrape only matches.
    # Used by the GDP orchestrator after the ASIK phase produces the NIK
    # universe — replaces N_niks per-NIK list reqs with a single
    # paginated bulk fetch per date.
    # --------------------------------------------------------------
    def _scrape_one_date_bulk_intersect(
        self,
        page: Page,
        *,
        tanggal: str,
        target_niks: set[str],
    ):
        console.print(
            f"\n[bold magenta]== Date {tanggal} (bulk + intersect, "
            f"{len(target_niks)} target NIKs) ==[/bold magenta]"
        )
        self.date = tanggal
        self.search_key = None
        self._list_ids = []
        before = len(self.patients)
        self.interceptor.clear()

        body: dict | None = None
        if self._dt_url_template is None:
            navigate_to_pelayanan(
                page,
                self.base_url,
                tanggal=tanggal,
                status_periksa=self.status_periksa,
                ruangan_id=self.ruangan_id,
                limit=self.limit,
                search_key=None,
            )
            body = self._wait_for_list_body(page)
            captured = self.interceptor.latest_datatable_url()
            if captured:
                self._dt_url_template = captured
        else:
            url = _remove_query_param(self._dt_url_template, "searchKey")
            url = _replace_query_param(url, "tanggal", tanggal)
            url = _replace_query_param(url, "page", "1")
            body = self._fetch_list_body(page, url, tanggal)

        if body is None:
            console.print("  [yellow]No list body — skipping date.[/yellow]")
            return

        all_records = self._records_from(body)
        total = self._total_from(body)
        limit_n = int(self.limit) if str(self.limit).isdigit() else 100
        total_pages = (total + limit_n - 1) // limit_n if total else 1
        console.print(
            f"  Page 1: {len(all_records)} records (total={total}, pages={total_pages})"
        )

        if total_pages > 1 and self._dt_url_template:
            base = _remove_query_param(self._dt_url_template, "searchKey")
            base = _replace_query_param(base, "tanggal", tanggal)
            for page_num in range(2, total_pages + 1):
                url = _replace_query_param(base, "page", str(page_num))
                page_body = self._fetch_list_body(page, url, tanggal)
                if page_body is None:
                    break
                recs = self._records_from(page_body)
                if not recs:
                    break
                all_records.extend(recs)

        matches: list[dict] = []
        for rec in all_records:
            pasien = ((rec.get("pendaftaran") or {}).get("pasien") or {})
            rec_nik = _clean_nik(pasien.get("nik"))
            if rec_nik and rec_nik in target_niks:
                matches.append(rec)
        console.print(f"  Matches: {len(matches)} / {len(all_records)}")
        self._list_ids.extend(r["id"] for r in matches if r.get("id"))

        if self._list_ids:
            self._deep_scrape_details(page)

        iso = _ddmmyyyy_to_iso(tanggal)
        new_patients = self.patients[before:]
        bucket = self.results_by_date.setdefault(iso, [])
        bucket.extend(new_patients)
        if new_patients:
            # Progressive checkpoint for the worker. Worker polls
            # OUTPUT_DIR/by_date/<ISO>.json during subprocess lifetime,
            # upserts each new file, commits per-date — so a mid-run
            # cancel preserves dates already finished.
            self._save_progress_for_date(iso, new_patients)

    def _save_progress_for_date(self, iso: str, patients: list[dict]) -> None:
        by_date_dir = OUTPUT_DIR / "by_date"
        try:
            by_date_dir.mkdir(parents=True, exist_ok=True)
            final_path = by_date_dir / f"{iso}.json"
            tmp_path = by_date_dir / f"{iso}.json.tmp"
            payload = {"patients": patients}
            tmp_path.write_text(json.dumps(payload, ensure_ascii=False))
            tmp_path.replace(final_path)  # atomic rename on POSIX
        except Exception as e:
            console.print(f"  [yellow]progress checkpoint failed for {iso}: {e}[/yellow]")

    def _fetch_list_body(self, page: Page, url: str, tanggal: str) -> dict | None:
        referer = (
            f"{self.base_url}/pelayanan?status_periksa={self.status_periksa}"
            f"&ruangan_id={self.ruangan_id}&limit={self.limit}&tanggal={tanggal}"
        )
        headers = {
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Referer": referer,
        }
        try:
            resp = page.context.request.get(url, headers=headers, timeout=60000)
            if resp.status != 200:
                console.print(f"  [yellow]list fetch HTTP {resp.status}[/yellow]")
                return None
            return resp.json()
        except Exception as e:
            console.print(f"  [red]list fetch error: {e}[/red]")
            return None

    # --------------------------------------------------------------
    # Per-NIK direct DataTables fetch (no page.goto per cycle).
    #
    # First call captures the DataTables URL by doing one real navigation;
    # the captured URL is reused for every subsequent (date, nik) — params
    # tanggal / searchKey / page get swapped via _replace_query_param and
    # the body fetched directly.
    # Kept for legacy callers; GDP orchestrator now uses the bulk-intersect
    # path above.
    # --------------------------------------------------------------
    def _scrape_one_date_direct(self, page: Page, *, tanggal: str, search_key: str):
        console.print(f"\n[bold magenta]== Date {tanggal} / NIK {search_key} (direct) ==[/bold magenta]")
        self.date = tanggal
        self.search_key = search_key
        self._list_ids = []
        # `accumulate=True` semantics in this loop: don't reset self.patients
        # because we drop into _deep_scrape_details which appends. We track
        # the slice we just scraped via `before` and tail it into by_date.
        before = len(self.patients)
        self.interceptor.clear()

        records: list[dict] = []
        if self._dt_url_template is None:
            # Bootstrap: real navigate captures the URL pattern.
            navigate_to_pelayanan(
                page,
                self.base_url,
                tanggal=tanggal,
                status_periksa=self.status_periksa,
                ruangan_id=self.ruangan_id,
                limit=self.limit,
                search_key=search_key,
            )
            body = self._wait_for_list_body(page)
            if body is not None:
                records = self._records_from(body)
                total = self._total_from(body)
                if total > len(records):
                    # Bootstrap path with > 1 page: defer to legacy harvester.
                    self._list_ids.extend(r["id"] for r in records if r.get("id"))
                    self._harvest_all_pages_extra(page, records, total)
                    captured = self.interceptor.latest_datatable_url()
                    if captured:
                        self._dt_url_template = captured
                else:
                    self._list_ids.extend(r["id"] for r in records if r.get("id"))
                    captured = self.interceptor.latest_datatable_url()
                    if captured:
                        self._dt_url_template = captured
        else:
            url = self._dt_url_template
            url = _replace_query_param(url, "tanggal", tanggal)
            url = _replace_query_param(url, "searchKey", search_key)
            url = _replace_query_param(url, "page", "1")
            referer = (
                f"{self.base_url}/pelayanan?status_periksa={self.status_periksa}"
                f"&ruangan_id={self.ruangan_id}&limit={self.limit}"
                f"&tanggal={tanggal}&searchKey={search_key}"
            )
            headers = {
                "X-Requested-With": "XMLHttpRequest",
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "Referer": referer,
            }
            try:
                resp = page.context.request.get(url, headers=headers, timeout=60000)
                if resp.status == 200:
                    body = resp.json()
                    records = self._records_from(body)
                    self._list_ids.extend(r["id"] for r in records if r.get("id"))
                else:
                    console.print(f"  [yellow]direct fetch HTTP {resp.status}[/yellow]")
            except Exception as e:
                console.print(f"  [red]direct fetch error: {e}[/red]")

        if not self._list_ids:
            console.print(f"  No EPUS records for NIK {search_key} on {tanggal}")
        else:
            self._deep_scrape_details(page)

        iso = _ddmmyyyy_to_iso(tanggal)
        bucket = self.results_by_date.setdefault(iso, [])
        bucket.extend(self.patients[before:])

    def _harvest_all_pages_extra(self, page: Page, page1_records: list[dict], total: int):
        """Fetch remaining pages after page 1 has already been captured."""
        captured_url = self.interceptor.latest_datatable_url()
        if not captured_url:
            return
        limit_n = int(self.limit) if str(self.limit).isdigit() else 100
        total_pages = (total + limit_n - 1) // limit_n
        referer = (
            f"{self.base_url}/pelayanan?status_periksa={self.status_periksa}"
            f"&ruangan_id={self.ruangan_id}&limit={self.limit}&tanggal={self.date}"
        )
        if self.search_key:
            referer = f"{referer}&searchKey={self.search_key}"
        headers = {
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Referer": referer,
        }
        for page_num in range(2, total_pages + 1):
            next_url = _replace_query_param(captured_url, "page", str(page_num))
            try:
                resp = page.context.request.get(next_url, headers=headers, timeout=60000)
                if resp.status != 200:
                    break
                body = resp.json()
            except Exception:
                break
            recs = self._records_from(body)
            if not recs:
                break
            self._list_ids.extend(r["id"] for r in recs if r.get("id"))

    # --------------------------------------------------------------
    # Multi-date helper: re-navigate, harvest, deep-scrape, snapshot.
    # --------------------------------------------------------------
    def _scrape_one_date(self, page: Page, *, tanggal: str, status_periksa: str,
                         ruangan_id: str, limit: str, search_key: str | None,
                         accumulate: bool = False):
        label = f"Date {tanggal}"
        if search_key:
            label += f" / NIK {search_key}"
        console.print(f"\n[bold magenta]== {label} ==[/bold magenta]")
        # Reset per-date state. self.date drives screenshot/output naming and
        # the Referer header in the pagination loop. accumulate=True keeps
        # results across multiple calls within the same date (per-NIK loop).
        self.date = tanggal
        self.status_periksa = status_periksa
        self.ruangan_id = ruangan_id
        self.limit = limit
        self.search_key = search_key
        self._list_ids = []
        if not accumulate:
            self.patients = []
        self.interceptor.clear()
        navigate_to_pelayanan(
            page,
            self.base_url,
            tanggal=tanggal,
            status_periksa=status_periksa,
            ruangan_id=ruangan_id,
            limit=limit,
            search_key=search_key,
        )
        self._harvest_all_pages(page)
        before = len(self.patients)
        self._deep_scrape_details(page)
        if accumulate:
            # Append patients harvested in this nik pass to the per-date bucket.
            iso = _ddmmyyyy_to_iso(tanggal)
            bucket = self.results_by_date.setdefault(iso, [])
            bucket.extend(self.patients[before:])
        else:
            # Snapshot under ISO key for downstream consumers (worker upserts
            # into Patient.filter_date which is ISO).
            self.results_by_date[_ddmmyyyy_to_iso(tanggal)] = list(self.patients)

    # --------------------------------------------------------------
    # Pagination — replay the captured DataTables URL with page=N.
    # The list drives pelayanan ids AND is persisted per-patient as
    # `list_record` (stashed in _records_from → attached in _deep_scrape_details).
    # --------------------------------------------------------------
    def _harvest_all_pages(self, page: Page):
        # Page 1 came in from the initial navigation.
        body = self._wait_for_list_body(page)
        if body is None:
            console.print("  [yellow]No DataTables XHR captured — list may be empty or timed out.[/yellow]")
            return

        page1_records = self._records_from(body)
        total = self._total_from(body)
        captured_url = self.interceptor.latest_datatable_url()

        console.print(f"  Page 1: {len(page1_records)} ids "
                      f"(totalRecords = {total})")
        self._list_ids.extend(r["id"] for r in page1_records if r.get("id"))

        if total <= len(page1_records):
            return

        if not captured_url:
            console.print("  [yellow]No DataTables URL captured — can't paginate.[/yellow]")
            return

        limit = int(self.limit) if str(self.limit).isdigit() else 100
        total_pages = (total + limit - 1) // limit
        max_pages = self.args.max_pages or total_pages
        max_pages = min(max_pages, total_pages)
        console.print(f"  Total pages: {total_pages} (scraping up to {max_pages})")

        referer = (
            f"{self.base_url}/pelayanan?status_periksa={self.status_periksa}"
            f"&ruangan_id={self.ruangan_id}&limit={self.limit}&tanggal={self.date}"
        )
        if self.search_key:
            referer = f"{referer}&searchKey={self.search_key}"
        headers = {
            # Laravel's ajax() check keys off this — without it we get HTML back.
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Referer": referer,
        }

        for page_num in range(2, max_pages + 1):
            next_url = _replace_query_param(captured_url, "page", str(page_num))
            console.print(f"  Page {page_num}/{max_pages}: fetching via context.request.get()")
            try:
                resp = page.context.request.get(next_url, headers=headers, timeout=60000)
                if resp.status != 200:
                    console.print(f"    [red]HTTP {resp.status} — stopping pagination[/red]")
                    break
                body = resp.json()
            except Exception as e:
                console.print(f"    [red]Error fetching page {page_num}: {e}[/red]")
                break

            got = self._records_from(body)
            console.print(f"    got {len(got)} ids")
            if not got:
                break
            self._list_ids.extend(r["id"] for r in got if r.get("id"))

    def _wait_for_list_body(self, page: Page, wait_ms: int = 8000) -> dict | None:
        deadline = time.time() + (wait_ms / 1000.0)
        while time.time() < deadline:
            body = self.interceptor.latest_datatable()
            if body is not None:
                return body
            page.wait_for_timeout(250)
        return None

    def _records_from(self, body) -> list[dict]:
        if not isinstance(body, dict):
            return []
        data = body.get("data") or {}
        records = data.get("records")
        if not isinstance(records, list):
            return []
        # Side-effect: stash the full DataTables record per id so the deep scrape
        # can persist it (BPJS Prolanis/PRB flags, asuransi, dokter, kelurahan,
        # structured umur, visual-triage — structured data not on the show page).
        # This is the single chokepoint every harvest path funnels through.
        for r in records:
            rid = r.get("id")
            if rid is not None:
                self._list_records[str(rid)] = r
        return records

    @staticmethod
    def _total_from(body) -> int:
        if not isinstance(body, dict):
            return 0
        data = body.get("data") or {}
        total = data.get("totalRecords")
        try:
            return int(total)
        except (TypeError, ValueError):
            return 0

    # --------------------------------------------------------------
    # Per-patient detail scrape (--detail)
    # --------------------------------------------------------------
    def _deep_scrape_details(self, page: Page):
        limit = self.args.detail_limit
        total = len(self._list_ids)
        if limit is not None:
            total = min(total, limit)

        if total <= 0:
            console.print("\n[yellow]No patients to scrape.[/yellow]")
            return

        console.print(f"\n[bold cyan]Scraping {total} patient(s) from /pelayanan/show/{{id}}[/bold cyan]")

        target_ids = list(self._list_ids[:total])
        patient_workers = max(1, int(getattr(self.args, "patient_workers", 1) or 1))

        if patient_workers > 1:
            console.print(
                f"  [cyan]Concurrent patient mode: workers={patient_workers}, "
                f"tab-workers={self.args.tab_workers}[/cyan]"
            )

            def _on_progress(pid, completed, n_total):
                console.print(f"  [{completed}/{n_total}] pelayanan_id={pid}")
                self._save_progress()

            results = scrape_patients_concurrent(
                page.context,
                page,
                base_url=self.base_url,
                pelayanan_ids=target_ids,
                max_parallel_fetches=self.args.tab_workers,
                max_patient_workers=patient_workers,
                on_progress=_on_progress,
            )
            for entry in results:
                entry["list_record"] = self._list_records.get(str(entry.get("pelayanan_id")))
            self.patients.extend(results)
            return

        for idx, pel_id in enumerate(target_ids, start=1):
            console.print(f"  [{idx}/{total}] pelayanan_id={pel_id}")
            try:
                detail = scrape_patient_detail(
                    page.context,
                    page,
                    base_url=self.base_url,
                    pelayanan_id=str(pel_id),
                    max_parallel_fetches=self.args.tab_workers,
                )
                detail["list_record"] = self._list_records.get(str(pel_id))
                self.patients.append(detail)
                self._save_progress()
            except Exception as e:
                console.print(f"    [red]Error: {e}[/red]")
                self.patients.append({
                    "pelayanan_id": str(pel_id),
                    "error": str(e),
                })

    # --------------------------------------------------------------
    # Persistence
    # --------------------------------------------------------------
    def _save_progress(self):
        """Checkpoint after every patient so a mid-run crash loses at most one."""
        try:
            with open(OUTPUT_DIR / "progress.json", "w", encoding="utf-8") as f:
                json.dump(self.patients, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _save_results(self):
        total_elapsed = round(time.time() - self.start_time, 2)

        date_suffix = self.date or today_ddmmyyyy()
        output_file = self.args.output or str(
            OUTPUT_DIR / f"pelayanan_medis_{date_suffix}.json"
        )

        if self.dates_list:
            total_patients = sum(len(v) for v in self.results_by_date.values())
            output = {
                "metadata": {
                    "source": f"{self.base_url}/pelayanan/show/{{id}}",
                    "scraped_at": datetime.now().isoformat(),
                    "total_patients": total_patients,
                    "filters": {
                        "tanggal": self.dates_list,
                        "status_periksa": self.status_periksa,
                        "status_label": "Sudah Diperiksa" if self.status_key == "sudah" else "Belum Diperiksa",
                        "ruangan_id": self.ruangan_id,
                        "limit": self.limit,
                    },
                    "timing": {
                        "total_elapsed_seconds": total_elapsed,
                    },
                },
                "by_date": {
                    iso: {"patients": rows} for iso, rows in self.results_by_date.items()
                },
            }
        else:
            total_patients = len(self.patients)
            output = {
                "metadata": {
                    "source": f"{self.base_url}/pelayanan/show/{{id}}",
                    "scraped_at": datetime.now().isoformat(),
                    "total_patients": total_patients,
                    "filters": {
                        "tanggal": self.date,
                        "status_periksa": self.status_periksa,
                        "status_label": "Sudah Diperiksa" if self.status_key == "sudah" else "Belum Diperiksa",
                        "ruangan_id": self.ruangan_id,
                        "limit": self.limit,
                    },
                    "timing": {
                        "total_elapsed_seconds": total_elapsed,
                    },
                },
                "patients": self.patients,
            }

        Path(output_file).parent.mkdir(parents=True, exist_ok=True)
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)

        summary = RichTable(title="Scrape Results")
        summary.add_column("Field", style="cyan")
        summary.add_column("Value", style="green")
        summary.add_row("Patients", str(total_patients))
        summary.add_row("Date", self.date)
        summary.add_row("status_periksa", f"{self.status_periksa} ({self.status_key})")
        summary.add_row("ruangan_id", self.ruangan_id)
        summary.add_row("Elapsed", f"{total_elapsed}s")
        console.print(summary)

        console.print(Panel(
            f"[bold green]Saved to: {output_file}[/bold green]",
            title="Done!",
        ))

        if self.patients:
            p0 = self.patients[0]
            dp0 = p0.get("data_pasien") or {}
            nama = dp0.get("Nama Pasien") or dp0.get("Nama") or ""
            console.print(f"\n  [cyan]Sample patient 1:[/cyan] "
                          f"pelayanan_id={p0.get('pelayanan_id')} nama={nama}")


# ----------------------------------------------------------------------
# Utilities
# ----------------------------------------------------------------------
def _ddmmyyyy_to_iso(s: str) -> str:
    parts = s.split("-")
    if len(parts) != 3:
        return s
    d, m, y = parts
    return f"{y}-{m}-{d}"


def _replace_query_param(url: str, key: str, value: str) -> str:
    """Replace ?key=... or &key=... in a URL. Simple regex — the DataTables
    URL is already valid, we just swap page=1 → page=N."""
    pattern = re.compile(rf"([?&]){re.escape(key)}=[^&]*")
    if pattern.search(url):
        return pattern.sub(rf"\g<1>{key}={value}", url)
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}{key}={value}"


def _clean_nik(raw) -> str:
    """Strip HTML tags + whitespace from a NIK field. EPUS DataTables returns
    NIK with a trailing </br> tag (e.g. '3275040706880011</br>'). DB stores
    clean 16-digit NIKs, so the bulk-intersect comparison must normalize."""
    if raw is None:
        return ""
    return re.sub(r"<[^>]+>", "", str(raw)).strip()


def _remove_query_param(url: str, key: str) -> str:
    """Strip ?key=... or &key=... from URL entirely. Used to clear searchKey
    from a captured DataTables URL when switching to bulk-list mode."""
    url = re.sub(rf"&{re.escape(key)}=[^&]*", "", url)
    url = re.sub(rf"\?{re.escape(key)}=[^&]*&", "?", url)
    url = re.sub(rf"\?{re.escape(key)}=[^&]*$", "", url)
    return url


# ============================================================
# CLI
# ============================================================
def main():
    parser = argparse.ArgumentParser(
        description="epus-v2 Pelayanan Medis scraper (kotabekasi.epuskesmas.id)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scraper.py                         # Default: headless, Sudah Diperiksa, UMUM, 2026-04-17
  python scraper.py --use-session           # Skip login on repeat runs
  python scraper.py --no-headless           # Show the browser
  python scraper.py --date 15-04-2026       # Override the date (DD-MM-YYYY)
  python scraper.py --status belum          # Belum Diperiksa
  python scraper.py --ruangan-id 0002       # Different poli
  python scraper.py --limit 50              # Smaller page size
  python scraper.py --max-pages 1           # Only page 1
  python scraper.py --output data.json      # Custom output path
  python scraper.py --capture-network x.json  # Dump every XHR for debugging
        """,
    )
    parser.add_argument("--use-session", action="store_true",
                        help="Save/reuse the browser session to skip login")
    parser.add_argument("--headless", action=argparse.BooleanOptionalAction, default=True,
                        help="Run browser headless. Default: True. Use --no-headless for visible.")
    parser.add_argument("--date", type=str, default=None,
                        help="tanggal filter in DD-MM-YYYY. Default: today (or config.filters.date if set)")
    parser.add_argument("--dates", type=str, default=None,
                        help="Comma-separated DD-MM-YYYY list. Multi-date mode: walks every "
                             'date in one browser session and emits {"by_date": {ISO: {"patients": [...]}}}. '
                             "Overrides --date.")
    parser.add_argument("--niks", type=str, default=None,
                        help="Comma-separated NIK list. With --dates, scraper iterates "
                             "dates × niks applying searchKey={nik} per (date, nik). "
                             "Used by GDP orchestrator after ASIK phase to restrict "
                             "EPUS scrape to NIKs found in ASIK.")
    parser.add_argument("--status", type=str, default="sudah",
                        choices=["sudah", "belum"],
                        help="Status filter. sudah=Sudah Diperiksa (3), belum=Belum Diperiksa (2)")
    parser.add_argument("--ruangan-id", type=str, default=None,
                        help="Poli/Ruangan id. Default: 0001 (UMUM)")
    parser.add_argument("--limit", type=str, default=None,
                        help="Page size. Default (and site max): 100")
    parser.add_argument("--max-pages", type=int, default=None,
                        help="Stop after scraping N pages")
    parser.add_argument("--output", type=str, default=None,
                        help="Output JSON file path")
    parser.add_argument("--capture-network", type=str, default=None, metavar="PATH",
                        help="Dump every captured XHR/fetch JSON response to this path")
    parser.add_argument("--detail-limit", type=int, default=None,
                        help="Cap how many patients to deep-scrape (useful for testing). "
                             "Default: no cap (scrape every list record).")
    parser.add_argument("--tab-workers", type=int, default=10,
                        help="Concurrent tab fetches per patient. Each patient has ~32 "
                             "tabs; scrape happens in parallel. Default: 10. 5 is safer "
                             "on slow servers, 20 gives ~5%% extra speed with more load.")
    parser.add_argument("--patient-workers", type=int, default=1,
                        help="Concurrent patients per chunk. 1 = sequential (legacy). "
                             "3 = ~3x speedup with conservative server load. Higher "
                             "values risk per-server rate limits.")
    parser.add_argument("--nik", type=str, default=None,
                        help="Per-NIK scrape. Adds &searchKey=<NIK> to /pelayanan URL "
                             "so the list filters to a single patient.")

    args = parser.parse_args()
    PelayananMedisScraper(args).run()


if __name__ == "__main__":
    main()
