"""
=============================================================================
ASIK CKG Sekolah Scraper — main entry point
=============================================================================
Scrapes school health-checkup (CKG Sekolah) patient data from
sehatindonesiaku.kemkes.go.id/ckg-pelayanan-sekolah.

Unlike CKG Umum (/ckg-pelayanan), this page has NO date filter — it is
filtered by **Pilih Sekolah** + **Pilih Kelas**. We dynamically enumerate every
school the puskesmas is assigned, every class within each school's jenjang
(SD 1-6 / SMP 7-9 / SMA 10-12), and all three status tabs
(Belum / Sedang / Selesai Pemeriksaan) so no student is missed.

Key constraint (see CLAUDE.md): the list/school request bodies are AES-encrypted
client-side (`{"data": "<cipher>"}`) and CANNOT be forged. Responses are
plaintext JSON. So we DRIVE THE REAL UI (select school → class → search → tab →
paginate) and INTERCEPT the plaintext responses via APIInterceptor — exactly the
pattern the CKG-Umum scraper uses for list-claim. Per student, clicking "Mulai"
navigates to the detail page and fires `get-screening` (intercepted); its Nakes
form URLs are opened in tabs and read from the SurveyJS DOM (reused from
asik/patient_scraper). We scrape **Pelayanan oleh Nakes + Tatalaksana** and skip
Pemeriksaan Mandiri.

Reuses asik/ helpers + patient_scraper via sys.path injection (same pattern as
asik_patient/). Login, CAPTCHA, session persistence, form reading are shared.

Usage:
  python scraper.py --no-headless              # visible browser, manual CAPTCHA
  python scraper.py --headless --use-session   # headless + session reuse (worker)
  python scraper.py --max-schools 1 --max-students 2   # quick recon
=============================================================================
"""

import sys as _sys
from pathlib import Path as _Path

SCRAPERS_ROOT = _Path(__file__).resolve().parent.parent
_sys.path.insert(0, str(SCRAPERS_ROOT))            # for _lifecycle
_sys.path.insert(0, str(SCRAPERS_ROOT / "asik"))   # reuse asik helpers + patient_scraper

from _lifecycle import install as _install_lifecycle  # noqa: E402
_install_lifecycle()

import argparse  # noqa: E402
import json  # noqa: E402
import time  # noqa: E402
from datetime import datetime  # noqa: E402

from pathlib import Path  # noqa: E402
from playwright.sync_api import sync_playwright, Page  # noqa: E402
from rich.console import Console  # noqa: E402
from rich.panel import Panel  # noqa: E402

from helpers import (  # noqa: E402
    OUTPUT_DIR,
    SCREENSHOT_DIR,
    SESSION_DIR,
    APIInterceptor,
    load_config,
    launch_persistent_context,
    restore_saved_auth_state,
    save_auth_state,
    login,
    close_popups,
)
from helpers.auth import SessionExpiredError, verify_session  # noqa: E402
from patient_scraper import (  # noqa: E402
    _batch_read_forms_via_tabs,
    scrape_patient_tatalaksana,
    _fmt_id_date,
    _fmt_gender,
    _compute_age_id,
)

console = Console()

SCHOOL_TABS = [
    ("Belum Pemeriksaan", "belum_pemeriksaan", "belum"),
    ("Sedang Pemeriksaan", "sedang_pemeriksaan", "sedang"),
    ("Selesai Pemeriksaan", "selesai_pemeriksaan", "selesai"),
]

SARANA_URL = "/api/pkg/sarana/get-sarana-sekolah"
JENJANG_URL = "/api/pkg/anak-sekolah/list-jenjang-sekolah"
LIST_PATIENT_URL = "/api/pkg/anak-sekolah/list-patient"
GET_SCREENING_URL = "/api/pkg/anak-sekolah/get-screening"


class CKGSekolahScraper:
    def __init__(self, args):
        self.args = args
        self.config = load_config()
        self.base_url = self.config.get(
            "base_url", "https://sehatindonesiaku.kemkes.go.id"
        )
        self.target_path = self.config.get("target_path", "/ckg-pelayanan-sekolah")
        self.interceptor = APIInterceptor(verbose=bool(getattr(args, "capture_network", None)))
        self.schools_out: list[dict] = []
        self.start_time = 0.0
        self.captcha_duration = 0.0
        # Combobox triggers show the placeholder first, then the last selection;
        # tracked so _open_combobox can target whichever text is shown.
        self._prev_school_text = "Pilih sekolah"

    # ─────────────────────────────────────────────────────────────────────
    def run(self):
        self.start_time = time.time()
        headless = self.args.headless
        browser_mode = "[bold red]HEADLESS[/bold red]" if headless else "[bold green]VISIBLE[/bold green]"
        console.print(Panel(
            f"[bold green]ASIK CKG Sekolah Scraper[/bold green]\n"
            f"Browser: {browser_mode}\n"
            f"Scope: every school × every class × all tabs (Nakes + Tatalaksana)",
            title="Starting",
        ))

        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)

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
                    viewport={"width": 1920, "height": 1080},
                    locale="id-ID",
                    timezone_id="Asia/Jakarta",
                )
                page = context.new_page()

            page.set_default_timeout(self.config.get("timeout", 60000))
            context.on("response", self.interceptor.on_response)

            try:
                self.captcha_duration = login(
                    page, self.base_url, self.config.get("credentials", {}),
                    headless=headless, config=self.config,
                )
                if self.args.use_session:
                    save_auth_state(context, page, self.base_url)

                self._goto_sekolah(page)
                self._accept_privacy_modal(page)
                close_popups(page, silent=True)

                schools = self._enumerate_schools(page)
                if self.args.only_school:
                    needle = self.args.only_school.lower()
                    schools = [s for s in schools if needle in (s.get("school_name") or "").lower()]
                if self.args.max_schools:
                    schools = schools[: self.args.max_schools]
                skip_set = {c for c in (self.args.skip_schools or "").split(",") if c}
                console.print(
                    f"[bold]Schools to scrape: {len(schools)}"
                    + (f" (skipping {len(skip_set)} already done)" if skip_set else "")
                    + "[/bold]"
                )

                for idx, school in enumerate(schools, 1):
                    if skip_set and school.get("school_code") in skip_set:
                        console.print(
                            f"\n[dim]== School {idx}/{len(schools)}: "
                            f"{school.get('school_name')} — SKIP (already scraped) ==[/dim]"
                        )
                        continue
                    console.print(
                        f"\n[bold magenta]== School {idx}/{len(schools)}: "
                        f"{school.get('school_name')} ({school.get('category_code')}) ==[/bold magenta]"
                    )
                    # Proactively refresh an expired session BEFORE the school so a
                    # mid-run expiry can't dead-zone the rest of the run.
                    self._ensure_session(page)
                    try:
                        result, blocked = self._scrape_school(page, school)
                        # blocked = a combobox would not open. If the session is
                        # actually dead, re-establish it and redo the school once.
                        if blocked:
                            dead = False
                            try:
                                dead = not verify_session(page.context, self.base_url)
                            except Exception:
                                dead = False
                            if dead and self._ensure_session(page):
                                result, blocked = self._scrape_school(page, school)
                    except SessionExpiredError as e:
                        console.print(
                            f"  [yellow]Session expired on {school.get('school_name')} — recovering[/yellow]"
                        )
                        result = {"school": school, "classes": [], "error": f"session: {e}"}
                        if self._ensure_session(page):
                            try:
                                result, _ = self._scrape_school(page, school)
                            except Exception as e2:
                                result = {"school": school, "classes": [], "error": str(e2)}
                    except Exception as e:
                        console.print(f"  [red]School failed: {e}[/red]")
                        result = {"school": school, "classes": [], "error": str(e)}
                    self.schools_out.append(result)
                    self._save_results()
                    self._write_school_file(idx, result)

                self._save_results()
            except Exception as e:
                console.print(f"\n[bold red]Error: {e}[/bold red]")
                try:
                    page.screenshot(path=str(SCREENSHOT_DIR / "error_sekolah.png"))
                except Exception:
                    pass
                raise
            finally:
                if getattr(self.args, "capture_network", None):
                    try:
                        n = self.interceptor.dump(self.args.capture_network)
                        console.print(f"[cyan]Network capture: {n} responses → {self.args.capture_network}[/cyan]")
                    except Exception:
                        pass
                if browser is not None:
                    browser.close()
                else:
                    context.close()

    # ─────────────────────────────────────────────────────────────────────
    def _goto_sekolah(self, page: Page, force: bool = False):
        if force or self.target_path not in page.url:
            page.goto(f"{self.base_url}{self.target_path}", wait_until="networkidle")
            page.wait_for_timeout(2500)

    def _ensure_session(self, page: Page) -> bool:
        """Re-establish the session if it expired mid-run (the 'Sesi Telah
        Berakhir / login dari perangkat lain' case that dead-zones every school
        after expiry — Cipondoh school 24, 2026-06-29). Probe verify_session;
        if dead, clear cookies, re-run login (gpt-4o CAPTCHA), re-navigate to the
        sekolah page and re-accept the privacy modal. Returns True if usable.
        Modeled on the asik (CKG Umum) scraper's mid-run recovery."""
        try:
            if verify_session(page.context, self.base_url):
                return True
        except Exception:
            return True  # probe error → assume ok, don't thrash on a transient blip
        console.print("  [yellow]Session expired — re-running login flow[/yellow]")
        try:
            page.context.clear_cookies()
        except Exception:
            pass
        try:
            login(page, self.base_url, self.config.get("credentials", {}),
                  headless=self.args.headless, config=self.config)
            if self.args.use_session:
                save_auth_state(page.context, page, self.base_url)
            self._goto_sekolah(page, force=True)
            self._accept_privacy_modal(page)
            # Page was reloaded → the school trigger shows the placeholder again.
            self._prev_school_text = "Pilih sekolah"
            return True
        except Exception as e:
            console.print(f"  [red]Re-login failed: {e}[/red]")
            return False

    def _write_school_file(self, idx: int, result: dict):
        """Write one completed school to its own file so the Celery task can
        upsert it progressively (the scraper has no DB access). Shape mirrors the
        full output so the task's _extract_school_students reads it directly. A
        cancel/crash after this leaves the school already saved."""
        try:
            p = OUTPUT_DIR / f"school_{idx:04d}.json"
            p.write_text(json.dumps({"schools": [result]}, ensure_ascii=False))
        except Exception as e:
            console.print(f"  [yellow]could not write per-school file: {e}[/yellow]")

    def _accept_privacy_modal(self, page: Page, wait_first: bool = True):
        """Dismiss the 'Pemberitahuan Privasi' modal whose overlay otherwise
        INTERCEPTS EVERY CLICK (the cause of whole-run 'could not open combobox'
        failures — Playwright won't click an element covered by the overlay).

        Robust by design: WAIT for the async-mounted modal before deciding it's
        absent, dismiss it (real Playwright events work where synthetic don't),
        then VERIFY the privacy overlay is actually gone and retry/nuke until it
        is. No-op when the modal isn't present. Verifies on the privacy TEXT, not
        any checkbox, so post-dismiss page checkboxes can't false-positive."""
        present = (
            "() => /Pemberitahuan Privasi|SAYA TELAH MEMBACA/i"
            ".test(document.body.innerText)"
        )
        if wait_first:
            # The modal mounts a beat AFTER navigation settles; the old code
            # checked immediately, raced it, and left the overlay up for the whole
            # run. Wait so "absent" is a real verdict, not a timing miss.
            try:
                page.wait_for_function(present, timeout=6000)
            except Exception:
                pass  # genuinely no modal within 6s — fine
        for _ in range(3):
            try:
                if not page.evaluate(present):
                    return  # overlay confirmed gone
            except Exception:
                return
            console.print("  [cyan]Accepting privacy notice modal...[/cyan]")
            try:
                cb = page.locator("input[type=checkbox]").first
                if cb.is_visible():
                    cb.check(timeout=4000)
                    page.wait_for_timeout(250)
            except Exception:
                pass
            try:
                page.get_by_text("Setuju", exact=True).first.click(timeout=4000)
                page.wait_for_timeout(900)
            except Exception:
                pass
            # Still up? Nuke the fixed full-width overlay, then re-verify next loop.
            try:
                if page.evaluate(present):
                    page.evaluate("""() => {
                        const cb=[...document.querySelectorAll('input[type=checkbox]')].find(c=>c.offsetParent!==null);
                        let n=cb; while(n&&n.parentElement){const cs=getComputedStyle(n); if(cs.position==='fixed'&&n.clientWidth>800)break; n=n.parentElement;}
                        if(n&&n!==document.body)n.remove();
                        document.body.style.overflow='auto';
                    }""")
                    page.wait_for_timeout(400)
            except Exception:
                pass

    # ─────────────────────────────────────────────────────────────────────
    def _enumerate_schools(self, page: Page) -> list[dict]:
        """Read the page-load get-sarana-sekolah response (encrypted request,
        plaintext response) for the full puskesmas school list. Open the school
        dropdown once to ensure the call has fired, then read the interceptor."""
        deadline = time.time() + 12
        schools = self._sarana_from_interceptor()
        if not schools:
            # Nudge the dropdown so the SPA fetches the list if it hasn't.
            try:
                self._open_combobox(page, ["Pilih sekolah"])
                page.keyboard.press("Escape")
            except Exception:
                pass
        while not schools and time.time() < deadline:
            page.wait_for_timeout(400)
            schools = self._sarana_from_interceptor()
        out = []
        seen = set()
        for s in schools:
            code = s.get("ihs_no") or s.get("school_code")
            name = s.get("school_name")
            key = (code, name)
            if not name or key in seen:
                continue
            seen.add(key)
            # list-jenjang-sekolah expects the readable jenjang (SD/SMP/SMA),
            # which is category_short_name / category_name — NOT the numeric
            # category_code (e.g. "13305"). Store the readable one.
            out.append({
                "school_code": code,
                "school_name": name,
                "category_code": (
                    s.get("category_short_name")
                    or s.get("category_name")
                    or s.get("category_code")
                ),
                "category_code_num": s.get("category_code"),
                "_raw": s,
            })
        return out

    def _sarana_from_interceptor(self) -> list[dict]:
        for entry in reversed(self.interceptor.all_responses):
            if entry["url"].endswith(SARANA_URL) and entry["status"] == 200:
                data = (entry.get("body") or {}).get("data")
                if isinstance(data, list):
                    return data
        return []

    def _classes_for_category(self, context, category_code: str) -> list[dict]:
        """list-jenjang-sekolah takes a PLAINTEXT {category_code} body, so call
        it directly. Returns [{code, name}] (empty for PAUD / unknown)."""
        if not category_code:
            return []
        try:
            resp = context.request.post(
                f"{self.base_url}{JENJANG_URL}",
                data=json.dumps({"category_code": category_code}),
                headers={"Content-Type": "application/json"},
            )
            if not resp.ok:
                return []
            return (resp.json() or {}).get("data") or []
        except Exception:
            return []

    # ─────────────────────────────────────────────────────────────────────
    def _scrape_school(self, page: Page, school: dict) -> tuple[dict, bool]:
        """Scrape one school. Returns (result, blocked); blocked=True when a
        school/class combobox could not be opened — the symptom of a blocking
        overlay or an EXPIRED SESSION, so the caller can re-establish the session
        and redo the school instead of silently recording 0 students."""
        classes = self._classes_for_category(page.context, school.get("category_code"))
        if self.args.only_class:
            classes = [c for c in classes if (c.get("name") or "") == self.args.only_class]
        if self.args.max_classes:
            classes = classes[: self.args.max_classes]
        if not classes:
            console.print("  [yellow]No classes for this jenjang (PAUD/empty) — skipped[/yellow]")
            return {"school": school, "classes": []}, False

        blocked = False
        # Select the school once; classes are re-selected per loop. The combobox
        # trigger shows the placeholder first, then the previous selection — so
        # we pass both as open-candidates.
        ok = self._select_combobox_option(
            page, ["Pilih sekolah", self._prev_school_text], school["school_name"],
            search=True,
        )
        if not ok:
            # A privacy overlay that slipped past the initial dismissal blocks
            # every click. Re-dismiss (no wait — page is loaded) and retry once.
            self._accept_privacy_modal(page, wait_first=False)
            ok = self._select_combobox_option(
                page, ["Pilih sekolah", self._prev_school_text], school["school_name"],
                search=True,
            )
        if not ok:
            blocked = True
        self._prev_school_text = school["school_name"]
        prev_class_text = "Pilih kelas"
        class_results = []
        for cls in classes:
            class_name = cls.get("name")
            console.print(f"  [cyan]Class: {class_name}[/cyan]")
            if not self._select_combobox_option(
                page, ["Pilih kelas", prev_class_text], class_name, search=False,
            ):
                blocked = True
            prev_class_text = class_name
            self._click_search(page)
            tabs_out = {}
            for tab_label, result_key, _short in SCHOOL_TABS:
                students = self._scrape_tab(page, school, cls, tab_label)
                tabs_out[result_key] = students
            class_results.append({
                "class_name": class_name,
                "class_code": cls.get("code"),
                "tabs": tabs_out,
            })
        return {"school": school, "classes": class_results}, blocked

    def _reset_capture(self):
        """Drop captured responses so the interceptor readers (which scan
        all_responses) can't return a stale list-patient/get-screening from a
        previous tab/page/student. Called right before each UI action that
        triggers a fresh encrypted request."""
        self.interceptor.all_responses.clear()
        self.interceptor.captured_data.clear()

    def _scrape_tab(self, page: Page, school: dict, cls: dict, tab_label: str) -> list[dict]:
        self._reset_capture()
        self._click_tab(page, tab_label)
        page.wait_for_timeout(2000)
        close_popups(page, silent=True)

        students: list[dict] = []
        page_num = 1
        max_pages = self.args.max_pages or 500
        while page_num <= max_pages:
            rows, pagination = self._list_patient_from_interceptor(page)
            if not rows:
                break
            console.print(
                f"      [{tab_label}] page {page_num}/{pagination.get('total_page','?')} "
                f"— {len(rows)} students"
            )
            # Capture every student's dataDetail (the localStorage payload the
            # detail page decodes) in one pass WITHOUT navigating — a Vue-router
            # guard cancels navigation while we click each Mulai, so the list
            # page stays intact. Each detail is then read in a throwaway tab.
            if not self.args.list_only:
                data_details = self._capture_data_details(page, len(rows))
            else:
                data_details = [None] * len(rows)
            for ridx, row in enumerate(rows):
                if self.args.max_students and len(students) >= self.args.max_students:
                    console.print("      [yellow]--max-students reached[/yellow]")
                    return students
                dd = data_details[ridx] if ridx < len(data_details) else None
                try:
                    student = self._scrape_student(page, school, cls, tab_label, row, dd)
                    students.append(student)
                except Exception as e:
                    console.print(f"        [red]student error: {e}[/red]")
                    students.append({
                        **self._student_base(school, cls, tab_label, row),
                        "error": str(e),
                    })
            # Next page within this tab — the main list page was never navigated.
            total_page = pagination.get("total_page") or 1
            if page_num >= total_page:
                break
            self._reset_capture()
            if not self._click_next_page(page, page_num + 1):
                break
            page.wait_for_timeout(1800)
            page_num += 1
        return students

    def _capture_data_details(self, page: Page, n: int) -> list[str | None]:
        """Click all N Mulai buttons with a Vue-router navigation guard active,
        capturing each student's localStorage['dataDetail'] without leaving the
        list. Returns dataDetails in row order (Mulai buttons render in row
        order, so index i ↔ row i)."""
        installed = page.evaluate("""() => {
            window.__dd = [];
            if (!window.__ddPatched) {
                const orig = localStorage.setItem.bind(localStorage);
                localStorage.setItem = function(k, v){ if (k === 'dataDetail') window.__dd.push(v); return orig(k, v); };
                window.__ddPatched = true;
            }
            const root = document.querySelector('#__nuxt') || document.body.firstElementChild;
            let app = root && root.__vue_app__;
            let router = null;
            try { router = app && app.config.globalProperties.$router; } catch (e) {}
            if (router && router.beforeEach) { window.__rmGuard = router.beforeEach(() => false); return true; }
            return false;
        }""")
        if not installed:
            console.print("        [yellow]router guard unavailable — dataDetail capture may fail[/yellow]")
        try:
            count = page.get_by_role("button", name="Mulai").count()
            for i in range(min(n, count)):
                try:
                    page.get_by_role("button", name="Mulai").nth(i).click(timeout=4000)
                    page.wait_for_timeout(120)
                except Exception:
                    pass
        finally:
            page.evaluate("() => { if (window.__rmGuard) { try { window.__rmGuard(); } catch(e){} } window.__rmGuard = null; }")
        dds = page.evaluate("() => window.__dd || []")
        if len(dds) != n:
            console.print(f"        [yellow]captured {len(dds)}/{n} dataDetails[/yellow]")
        return dds

    # ─────────────────────────────────────────────────────────────────────
    def _scrape_student(self, page: Page, school: dict, cls: dict,
                        tab_label: str, row: dict, data_detail: str | None) -> dict:
        base = self._student_base(school, cls, tab_label, row)
        label = f"{base['nama']} ({base.get('ticket_number','')})"
        if self.args.list_only:
            return base
        if not data_detail:
            base["error"] = "no dataDetail captured"
            return base

        # Open the detail in a throwaway tab seeded with this student's
        # dataDetail; its get-screening fires for THIS reg_id. The main list
        # page is never navigated.
        screening = self._read_detail_via_tab(page.context, data_detail, base.get("reg_id"))
        if screening is None:
            base["error"] = "get-screening not captured"
            return base

        base["klaster_code"] = screening.get("patient_klaster_code")
        base["klaster_name"] = screening.get("patient_klaster_name")
        base["detail_data"] = self._detail_from_screening(screening)
        # faskes_code from get-screening is authoritative for tatalaksana.
        if screening.get("faskes_code"):
            base["faskes_code"] = screening["faskes_code"]

        nakes_items = []
        nakes_meta = []  # parallel to nakes_items: (pemeriksaan_code, layanan_code)
        for layanan in screening.get("screening_layanan") or []:
            for pem in layanan.get("list_pemeriksaan") or []:
                is_submitted = bool(pem.get("IsSubmitForm"))
                is_skip = bool(pem.get("is_skip"))
                has_answers = is_submitted and not is_skip
                link = pem.get("pemeriksaan_link")
                name = pem.get("pemeriksaan") or layanan.get("layanan") or pem.get("pemeriksaan_code") or ""
                if not link:
                    continue
                # include_blank_forms is always on for school (capture schema).
                nakes_items.append({"layanan": name, "url": link, "has_answers": has_answers})
                nakes_meta.append((pem.get("pemeriksaan_code"), layanan.get("layanan_code")))

        console.print(f"        [bold]{label}[/bold] — {len(nakes_items)} Nakes form(s)")
        pelayanan_nakes = []
        if nakes_items:
            pelayanan_nakes = _batch_read_forms_via_tabs(page.context, nakes_items)
            # _batch_read_forms_via_tabs returns results in input order; attach
            # the form's FRM code so the form-map tooling can key by it.
            for entry, (frm_code, layanan_code) in zip(pelayanan_nakes, nakes_meta):
                if isinstance(entry, dict):
                    entry["pemeriksaan_code"] = frm_code
                    entry["layanan_code"] = layanan_code
        base["pelayanan_nakes"] = pelayanan_nakes

        # Pemeriksaan Mandiri (self-exam forms). get-screening is structurally
        # identical to CKG-Umum detail-screening, so `screening_forms[]` mirrors
        # the umum scraper; read the SurveyJS forms exactly like Nakes.
        mandiri_items = []
        mandiri_meta = []  # parallel to mandiri_items: pemeriksaan_code (FRM)
        for form in screening.get("screening_forms") or []:
            is_submitted = bool(form.get("IsSubmitForm"))
            link = form.get("FormLink")
            name = form.get("FormName") or form.get("FormCode") or ""
            if not link:
                continue
            # include_blank_forms is always on for school (capture schema).
            mandiri_items.append({"layanan": name, "url": link, "has_answers": is_submitted})
            mandiri_meta.append(form.get("FormCode"))

        console.print(f"        [bold]{label}[/bold] — {len(mandiri_items)} Mandiri form(s)")
        pemeriksaan_mandiri = []
        if mandiri_items:
            pemeriksaan_mandiri = _batch_read_forms_via_tabs(page.context, mandiri_items)
            for entry, frm_code in zip(pemeriksaan_mandiri, mandiri_meta):
                if isinstance(entry, dict):
                    entry["pemeriksaan_code"] = frm_code
        base["pemeriksaan_mandiri"] = pemeriksaan_mandiri

        # Tatalaksana (follow-up) — best effort; the plaintext reg_id-scoped
        # list-detail endpoint (shared with CKG Umum) catches its own errors.
        if screening.get("is_have_tatalaksana"):
            try:
                tata = scrape_patient_tatalaksana(
                    page.context,
                    base_url=self.base_url,
                    faskes_code=base.get("faskes_code") or "",
                    reg_id=base.get("reg_id") or "",
                    program_code=screening.get("program_code") or "pkg",
                )
                if tata:
                    base["tatalaksana"] = tata
            except Exception as e:
                base["tatalaksana"] = {"error": str(e)}

        base["_raw_detail"] = screening
        return base

    def _read_detail_via_tab(self, context, data_detail: str, expect_reg: str | None):
        """Open /detail-pemeriksaan in a fresh tab seeded with `data_detail` in
        localStorage; the detail page decodes it and fires get-screening, which
        we intercept. Returns the get-screening `data` (verified against
        expect_reg when given) or None."""
        self.interceptor.all_responses.clear()
        tab = context.new_page()
        try:
            # Set dataDetail as a DIRECT statement (not an arrow-function
            # expression, which add_init_script would define-but-never-call,
            # leaving the detail page to read the stale SHARED localStorage).
            # Runs before the detail page's own scripts on every navigation.
            tab.add_init_script(
                "try{window.localStorage.setItem('dataDetail',"
                + json.dumps(data_detail) + ");}catch(e){}"
            )
            tab.goto(f"{self.base_url}{self.target_path}/detail-pemeriksaan",
                     wait_until="networkidle", timeout=40000)
            deadline = time.time() + 8
            while time.time() < deadline:
                for e in reversed(self.interceptor.all_responses):
                    if e["url"].endswith(GET_SCREENING_URL) and e["status"] == 200:
                        data = (e.get("body") or {}).get("data") or {}
                        got = (data.get("patient_detail") or {}).get("reg_id")
                        if expect_reg and got and got != expect_reg:
                            continue  # stale/other student — keep waiting
                        return data
                tab.wait_for_timeout(200)
            return None
        finally:
            try:
                tab.close()
            except Exception:
                pass

    def _student_base(self, school: dict, cls: dict, tab_label: str, row: dict) -> dict:
        patient = row.get("patient") or {}
        wali = row.get("wali") or {}
        short = {"Belum Pemeriksaan": "belum", "Sedang Pemeriksaan": "sedang",
                 "Selesai Pemeriksaan": "selesai"}[tab_label]
        school_obj = row.get("school") or {}
        return {
            "nik": (patient.get("nik") or "").strip(),
            "nama": (patient.get("full_name") or "").strip(),
            "born_date": patient.get("born_date") or "",
            "gender": patient.get("gender") or "",
            "reg_id": row.get("reg_id"),
            "ticket_number": row.get("ticket_number"),
            "register_date": row.get("register_date"),
            "faskes_code": row.get("faskes_code") or row.get("partner_code"),
            "school_code": school.get("school_code"),
            "school_name": school.get("school_name") or school_obj.get("school_name"),
            "category_code": school.get("category_code"),
            "class_name": cls.get("name") or school_obj.get("class_name"),
            "screening_status": short,
            "wali": wali,
            "_raw_list_row": row,
        }

    def _detail_from_screening(self, screening: dict) -> dict:
        """Build a readable identity block from get-screening.patient_detail
        (mirrors asik detail_data shape)."""
        pd = screening.get("patient_detail") or {}
        dom = screening.get("domicile") or {}
        individu = {}
        if pd.get("patient_nik"):
            individu["NIK"] = pd["patient_nik"]
        if pd.get("patient_full_name"):
            individu["Nama"] = pd["patient_full_name"].strip()
        if pd.get("patient_born_date"):
            individu["Tanggal Lahir"] = _fmt_id_date(pd["patient_born_date"])
            age = _compute_age_id(pd["patient_born_date"])
            if age:
                individu["Umur"] = age
        if pd.get("patient_gender"):
            individu["Jenis Kelamin"] = _fmt_gender(pd["patient_gender"])
        if pd.get("ticket_number"):
            individu["Nomor Tiket"] = pd["ticket_number"]
        wali_name = (pd.get("wali_full_name") or "").strip()
        if wali_name:
            individu["Nama Wali"] = wali_name
        detail = {"data_individu": individu}
        sch = screening.get("school") or {}
        if sch:
            detail["data_sekolah"] = {
                k: v for k, v in {
                    "Sekolah": sch.get("name"),
                    "Kelas": sch.get("class_name"),
                    "NISN": sch.get("nisn"),
                }.items() if v
            }
        domisili = {}
        for k_src, k_dst in (
            ("address", "Alamat Domisili"), ("province_name", "Provinsi"),
            ("city_name", "Kota"), ("district_name", "Kecamatan"),
            ("sub_district_name", "Kelurahan"),
        ):
            if dom.get(k_src):
                domisili[k_dst] = dom[k_src]
        if domisili:
            detail["data_domisili"] = domisili
        return detail

    # ─────────────────────────────────────────────────────────────────────
    # Interceptor readers
    # ─────────────────────────────────────────────────────────────────────
    def _list_patient_from_interceptor(self, page: Page, wait_ms: int = 5000):
        deadline = time.time() + wait_ms / 1000.0
        while time.time() < deadline:
            for entry in reversed(self.interceptor.all_responses):
                if entry["url"].endswith(LIST_PATIENT_URL) and entry["status"] == 200:
                    body = entry.get("body") or {}
                    data = body.get("data")
                    if isinstance(data, list):
                        return data, (body.get("pagination") or {})
            page.wait_for_timeout(200)
        return [], {}

    # ─────────────────────────────────────────────────────────────────────
    # UI driving — Playwright REAL-EVENT locators only. The custom Vue
    # comboboxes/tabs/buttons ignore synthetic DOM .click() (verified live), so
    # everything here goes through page.get_by_role / get_by_text / locator.click.
    # ─────────────────────────────────────────────────────────────────────
    def _open_combobox(self, page: Page, candidate_texts: list[str]):
        """Open a custom select by clicking its visible trigger. The trigger
        text is the placeholder ('Pilih sekolah'/'Pilih kelas') OR the current
        selection, so we try each candidate until one clicks."""
        for txt in candidate_texts:
            try:
                el = page.get_by_text(txt, exact=True).first
                if el.is_visible():
                    el.click(timeout=4000)
                    page.wait_for_timeout(700)
                    return True
            except Exception:
                continue
        return False

    def _select_combobox_option(self, page: Page, candidate_texts: list[str],
                                option_text: str, search: bool):
        """Open the combobox (by trigger candidates) and click the option whose
        exact text == option_text. School picker (search=True) types into the
        dropdown filter input first to narrow a long list."""
        if not self._open_combobox(page, candidate_texts):
            console.print(f"        [yellow]could not open combobox for '{option_text}'[/yellow]")
            return False
        if search:
            try:
                box = page.locator("input:visible").last
                box.fill(option_text[:24])
                page.wait_for_timeout(900)
            except Exception:
                pass
        try:
            page.get_by_text(option_text, exact=True).first.click(timeout=5000)
            page.wait_for_timeout(800)
            return True
        except Exception:
            console.print(f"        [yellow]option '{option_text}' not found[/yellow]")
            return False

    def _click_search(self, page: Page):
        try:
            page.get_by_text("Tampilkan Pencarian", exact=False).first.click(timeout=5000)
        except Exception:
            console.print("        [yellow]Tampilkan Pencarian not clickable[/yellow]")
        page.wait_for_timeout(2500)

    def _click_tab(self, page: Page, tab_name: str):
        # Tabs carry a count badge ("Sedang Pemeriksaan 25"), so match by
        # substring. Wait for the tab to render (after go_back the list re-mounts),
        # prefer role=tab, fall back to text match.
        try:
            page.get_by_text(tab_name, exact=False).first.wait_for(state="visible", timeout=8000)
        except Exception:
            pass
        for attempt in range(2):
            try:
                page.get_by_role("tab", name=tab_name).first.click(timeout=3000)
                page.wait_for_timeout(800)
                return
            except Exception:
                pass
            try:
                page.get_by_text(tab_name, exact=False).first.click(timeout=3000)
                page.wait_for_timeout(800)
                return
            except Exception:
                if attempt == 0:
                    page.wait_for_timeout(1200)
        console.print(f"        [yellow]tab '{tab_name}' not clickable[/yellow]")

    def _click_next_page(self, page: Page, target_page: int) -> bool:
        # Real-event clicks (Vue ignores synthetic). Prefer the explicit page
        # number, fall back to a "next" arrow. Scoped to a pagination/nav region
        # so a stray "2" elsewhere isn't clicked.
        scopes = ['[class*="pagination"]', 'nav', 'ul']
        for sc in scopes:
            try:
                region = page.locator(sc).filter(has_text=str(target_page)).last
                btn = region.get_by_text(str(target_page), exact=True).first
                if btn.is_visible():
                    btn.click(timeout=2500)
                    return True
            except Exception:
                continue
        for nm in ("Next", "next", "Berikutnya", "›", ">"):
            try:
                el = page.get_by_role("button", name=nm).first
                if el.is_visible():
                    el.click(timeout=2000)
                    return True
            except Exception:
                continue
        return False

    # ─────────────────────────────────────────────────────────────────────
    def _save_results(self):
        total = sum(
            len(v)
            for sch in self.schools_out
            for cls in sch.get("classes", [])
            for v in cls.get("tabs", {}).values()
        )
        output_file = self.args.output or str(
            OUTPUT_DIR / f"ckg_sekolah_{datetime.now().strftime('%Y-%m-%d')}.json"
        )
        total_elapsed = round(time.time() - self.start_time, 2)
        output = {
            "metadata": {
                "source": f"{self.base_url}{self.target_path}",
                "scraped_at": datetime.now().isoformat(),
                "total_students": total,
                "total_schools": len(self.schools_out),
                "timing": {
                    "total_elapsed_seconds": total_elapsed,
                    "captcha_wait_seconds": round(self.captcha_duration, 2),
                },
            },
            "schools": self.schools_out,
        }
        Path(output_file).parent.mkdir(parents=True, exist_ok=True)
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
        console.print(f"  [green]Saved {total} students across {len(self.schools_out)} school(s) → {output_file}[/green]")


def main():
    parser = argparse.ArgumentParser(description="ASIK CKG Sekolah Scraper")
    parser.add_argument("--use-session", action="store_true",
                        help="Reuse saved browser session (skip CAPTCHA on repeat runs)")
    parser.add_argument("--headless", action=argparse.BooleanOptionalAction, default=True,
                        help="Headless mode. Default True. Use --no-headless for visible browser.")
    parser.add_argument("--output", type=str, default=None, help="Output JSON path")
    parser.add_argument("--max-schools", type=int, default=None, help="Limit schools (debug)")
    parser.add_argument("--max-classes", type=int, default=None, help="Limit classes per school (debug)")
    parser.add_argument("--max-students", type=int, default=None, help="Limit students per tab (debug)")
    parser.add_argument("--max-pages", type=int, default=None, help="Limit pages per tab")
    parser.add_argument("--skip-schools", type=str, default=None,
                        help="Comma-separated school_codes to skip (resume — already scraped)")
    parser.add_argument("--only-school", type=str, default=None,
                        help="Only scrape schools whose name contains this (debug/targeted)")
    parser.add_argument("--only-class", type=str, default=None,
                        help="Only scrape this exact class name, e.g. 'Kelas 11' (debug/targeted)")
    parser.add_argument("--list-only", action="store_true",
                        help="Skip per-student detail (Mulai/forms); list rows only")
    parser.add_argument("--capture-network", type=str, default=None, metavar="PATH",
                        help="Dump all captured XHR/fetch JSON to PATH for analysis")
    args = parser.parse_args()
    CKGSekolahScraper(args).run()


if __name__ == "__main__":
    main()
