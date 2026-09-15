"""
=============================================================================
ASIK CKG Pelayanan Scraper — per-NIK variant
=============================================================================
Mirrors ../asik_sync/sync.py's NIK-search flow (3-tab walk, badge==1 OR
mulai==1 predicate to detect "filter narrowed") but, instead of opening
the patient detail page to fill SurveyJS forms, scrapes that single
record via ``scrape_patient_via_api`` (same code path the puskesmas-wide
ASIK scraper uses for each list-claim record).

Sync's helpers are imported, not duplicated. **Do not modify sync.py.**

Output mirrors the puskesmas-wide scraper exactly:

    {metadata, belum_pemeriksaan: [...], sedang_pemeriksaan: [...],
     selesai_pemeriksaan: [...]}

so the backend's ``_extract_patients`` works unchanged. The matched tab
contains exactly one entry; the other two arrays stay empty.

Usage (called by Celery task ``scrape.run`` when job.patient_id is set;
not designed to be invoked manually):

    python scraper.py --output out.json --nik 3275... --headless --use-session
"""

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

# Reuse asik helpers + asik_sync NIK-search helpers via sys.path injection
PATIENT_DIR = Path(__file__).resolve().parent
SCRAPERS_ROOT = PATIENT_DIR.parent
sys.path.insert(0, str(SCRAPERS_ROOT))  # for _lifecycle
sys.path.insert(0, str(SCRAPERS_ROOT / "asik"))
sys.path.insert(0, str(SCRAPERS_ROOT / "asik_sync"))

# Parent-death watchdog: kill ourselves if the launching terminal closes.
from _lifecycle import install as _install_lifecycle  # noqa: E402
_install_lifecycle()

from playwright.sync_api import sync_playwright, Page  # noqa: E402
from rich.console import Console  # noqa: E402

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
    navigate_to_pelayanan,
    close_popups,
)
from patient_scraper import scrape_patient_via_api, get_mitra_token  # noqa: E402
from sync import (  # noqa: E402
    _click_tab,
    _fill_search_input,
    _find_mulai_button_count,
    _read_active_tab_count,
    _select_nik_filter,
)

console = Console()

_TABS: tuple[tuple[str, str], ...] = (
    ("Belum Pemeriksaan", "belum_pemeriksaan"),
    ("Sedang Pemeriksaan", "sedang_pemeriksaan"),
    ("Selesai Pemeriksaan", "selesai_pemeriksaan"),
)


_SPECIFIC_SEARCH_PATH = "/api/pkg/specific-search/layanan-ckg"


def _specific_search_records(interceptor: APIInterceptor) -> list[dict]:
    """Concatenate non-empty specific-search/layanan-ckg responses since clear().

    The on-page NIK search box does NOT refilter ``/api/pkg/list-claim`` — it
    fires ``/api/pkg/specific-search/layanan-ckg`` and the result of THAT
    endpoint is what the rendered table reflects. So this is the source of
    truth for "what patient does this NIK refer to".
    """
    seen: set[str] = set()
    out: list[dict] = []
    for entry in interceptor.all_responses:
        if _SPECIFIC_SEARCH_PATH not in entry["url"]:
            continue
        if entry.get("status") != 200:
            continue
        body = entry.get("body") or {}
        data = body.get("data") or []
        if not isinstance(data, list):
            continue
        for r in data:
            rid = str(r.get("reg_id") or "")
            if rid and rid not in seen:
                seen.add(rid)
                out.append(r)
    return out


def _find_patient_tab_and_record(
    page: Page, interceptor: APIInterceptor, nik: str
) -> tuple[str | None, dict | None]:
    """Mirror asik_sync.sync's NIK-search flow: walk Belum / Sedang / Selesai
    Pemeriksaan, refire NIK input on each, check the predicate
    ``badge == 1 OR mulai == 1`` (sync's exact predicate). When the predicate
    trips, pick the patient record from the captured
    ``/api/pkg/specific-search/layanan-ckg`` response — that endpoint IS the
    NIK-filtered source the SPA renders from. Strict ``patient_nik == nik``
    match.

    Returns (tab_name, record) on success, (None, None) on miss.
    """
    for tab_name, _key in _TABS:
        console.print(f"  Trying tab: {tab_name}")
        interceptor.clear()
        _click_tab(page, tab_name)
        page.wait_for_timeout(1500)
        # Tab switch can reset the dropdown back to Nama; re-select NIK
        # and re-fire the search so specific-search refires for this tab.
        _select_nik_filter(page)
        _fill_search_input(page, nik)
        page.wait_for_timeout(3000)
        badge = _read_active_tab_count(page)
        mulai = _find_mulai_button_count(page)
        console.print(f"    badge={badge} mulai_buttons={mulai}")
        if not (badge == 1 or mulai == 1):
            continue

        records = _specific_search_records(interceptor)
        match = next(
            (r for r in records if str(r.get("patient_nik") or "").strip() == nik),
            None,
        )
        if match is not None:
            return tab_name, match
        # Predicate tripped but specific-search has no NIK match — bail on
        # this tab and keep walking. Don't blindly scrape the visible row;
        # without specific-search confirmation we can't trust it's the right
        # patient.
        console.print(
            f"    [yellow]predicate tripped but specific-search has no NIK "
            f"match (captured={len(records)})[/yellow]"
        )
    return None, None


def _result_key_for_tab(tab_name: str) -> str:
    for name, key in _TABS:
        if name == tab_name:
            return key
    return ""


def run(args) -> dict:
    cfg = load_config()
    base_url = cfg.get("base_url", "https://sehatindonesiaku.kemkes.go.id")
    headless = bool(cfg.get("headless", True)) if not args.no_headless else False
    nik = args.nik or cfg.get("nik")
    if not nik:
        raise ValueError("--nik (or config.nik) is required")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)

    output: dict = {
        "metadata": {
            "source": f"{base_url}/ckg-pelayanan",
            "scraped_at": datetime.now().isoformat(),
            "nik": nik,
            "mode": "per_nik",
        },
        "patient_tab": None,
        "patient_found": False,
        "belum_pemeriksaan": [],
        "sedang_pemeriksaan": [],
        "selesai_pemeriksaan": [],
    }

    t0 = time.time()
    captcha_duration = 0.0

    with sync_playwright() as p:
        slow_mo = 0 if headless else 50

        if args.use_session:
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

        page.set_default_timeout(cfg.get("timeout", 60000))
        interceptor = APIInterceptor(verbose=False)
        context.on("response", interceptor.on_response)

        try:
            captcha_duration = login(
                page, base_url, cfg.get("credentials", {}),
                headless=headless, config=cfg,
            )
            if args.use_session:
                save_auth_state(context, page, base_url)

            navigate_to_pelayanan(page, base_url)
            close_popups(page)

            # Mirror asik_sync.sync.run: type NIK once before walking tabs
            # so the very first list-claim refires with the search applied.
            console.print(f"\n[bold cyan]Searching NIK={nik}[/bold cyan]")
            _select_nik_filter(page)
            _fill_search_input(page, nik)
            page.wait_for_timeout(2500)

            tab_name, target = _find_patient_tab_and_record(page, interceptor, nik)
            if target is None:
                output["metadata"]["reason"] = "nik_not_found_in_asik"
                msg = (
                    f"NIK {nik} not found in ASIK across Belum/Sedang/Selesai "
                    f"Pemeriksaan tabs (today)"
                )
                console.print(f"[red]{msg}[/red]")
                raise RuntimeError(msg)

            output["patient_found"] = True
            output["patient_tab"] = tab_name
            result_key = _result_key_for_tab(tab_name or "")
            console.print(f"  [green]Patient found in: {tab_name}[/green]")

            mitra = get_mitra_token(page.context, base_url)
            console.print(f"  [dim]mitra token: {mitra[:24]}…[/dim]")

            reg_id = target.get("reg_id")
            faskes_code = target.get("faskes_code")
            screening_date = target.get("screening_date")
            label = (
                f"{(target.get('patient_full_name') or '').strip()} "
                f"({target.get('ticket_number','')})"
            )

            detail = scrape_patient_via_api(
                page.context,
                base_url=base_url,
                faskes_code=faskes_code,
                screening_date=screening_date,
                reg_id=reg_id,
                mitra=mitra,
                patient_label=label,
                pelayanan_nakes_only=bool(cfg.get("pelayanan_nakes_only", False)),
                include_blank_forms=bool(cfg.get("include_blank_forms", False)),
                scrape_tatalaksana=bool(cfg.get("scrape_tatalaksana", True)),
            )

            if result_key:
                output[result_key] = [detail]

            output["metadata"]["timing"] = {
                "total_elapsed_seconds": round(time.time() - t0, 2),
                "captcha_wait_seconds": round(captcha_duration, 2),
            }
            return output
        except Exception as exc:
            console.print(f"[bold red]Error: {exc}[/bold red]")
            try:
                page.screenshot(path=str(SCREENSHOT_DIR / "asik_patient_error.png"))
            except Exception:
                pass
            output.setdefault("error", str(exc))
            raise
        finally:
            try:
                if browser is not None:
                    browser.close()
                else:
                    context.close()
            except Exception:
                pass

            out_path = Path(args.output) if args.output else (
                OUTPUT_DIR / f"ckg_pelayanan_nik_{nik}.json"
            )
            try:
                out_path.parent.mkdir(parents=True, exist_ok=True)
                with open(out_path, "w", encoding="utf-8") as f:
                    json.dump(output, f, ensure_ascii=False, indent=2)
            except Exception as exc:
                console.print(f"[yellow]Could not write output: {exc}[/yellow]")


def main():
    parser = argparse.ArgumentParser(
        description="ASIK CKG Pelayanan scraper (per-NIK variant)",
    )
    parser.add_argument("--nik", type=str, default=None,
                        help="NIK to search. Falls back to config.nik.")
    parser.add_argument("--output", type=str, default=None,
                        help="Output JSON file path.")
    parser.add_argument("--headless", action="store_true", default=True)
    parser.add_argument("--no-headless", action="store_true",
                        help="Force visible browser even if config says headless.")
    parser.add_argument("--use-session", action="store_true",
                        help="Reuse saved browser session to skip CAPTCHA.")
    args = parser.parse_args()
    try:
        run(args)
    except Exception:
        sys.exit(1)


if __name__ == "__main__":
    main()
