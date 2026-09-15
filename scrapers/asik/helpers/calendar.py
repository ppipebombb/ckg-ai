"""
Single-date picker for the dual-panel calendar on /ckg-pelayanan.

The popup has two side-by-side month panels (e.g. "Apr 2026" | "Mei 2026"),
navigation arrows (<<, <, >, >>), and clickable day cells. To select a
single date, click the target day twice — this sets both start and end to
the same date (e.g. "16 Apr 2026 - 16 Apr 2026").

Public entry: `set_date_filter(page, date)`. The other functions are
walk-the-calendar helpers and stay module-private.

Failure policy: `set_date_filter` RAISES `DateFilterError` on any failure
(bad format, picker not found, can't navigate, day not selectable, or the
selection didn't take). It never returns silently — a silently-unapplied
filter makes the page keep its DEFAULT date range, and the scraper would
then harvest those rows and mislabel them with the requested date. A loud
failure fails the job instead of emitting wrong-dated data.
"""

from datetime import datetime as dt

from playwright.sync_api import Page
from rich.console import Console

from .constants import MONTH_NUM_TO_ABBR, SCREENSHOT_DIR

console = Console()


class DateFilterError(RuntimeError):
    """Raised when the calendar date filter could not be applied as requested."""


def set_date_filter(page: Page, date: str):
    """Set the date filter via the calendar UI by double-clicking a single date (YYYY-MM-DD).

    Raises DateFilterError on any failure so the caller never proceeds to
    scrape the page's default (unfiltered) date range by mistake.
    """
    console.print(f"\n[bold cyan]Step 4: Setting date filter: {date}[/bold cyan]")

    try:
        d = dt.strptime(date, "%Y-%m-%d")
    except ValueError:
        raise DateFilterError(f"Invalid date format {date!r}; expected YYYY-MM-DD")

    console.print(f"  Date: {d.day} {MONTH_NUM_TO_ABBR[d.month]} {d.year}")

    # ── Step A: Open the calendar popup ──
    #   The date picker is an mx-datepicker Vue component. Wait for it to be
    #   present, click it, and confirm the popup actually rendered (retry once)
    #   so a slow mount can't slip through as a silent no-op.
    console.print("  Opening date picker...")
    try:
        page.wait_for_selector('.mx-datepicker', timeout=15000)
    except Exception:
        raise DateFilterError("Date picker (.mx-datepicker) never appeared")

    dp = page.locator('.mx-datepicker')
    opened = False
    for _ in range(2):
        dp.first.click()
        try:
            page.wait_for_selector('.mx-calendar', timeout=5000)
            opened = True
            break
        except Exception:
            page.wait_for_timeout(500)
    if not opened:
        page.screenshot(path=str(SCREENSHOT_DIR / "04_calendar_debug.png"))
        raise DateFilterError("Clicked the date picker but the calendar popup did not open")

    page.wait_for_timeout(800)
    page.screenshot(path=str(SCREENSHOT_DIR / "04_calendar_opened.png"))

    # ── Step B: Read which month the left panel is currently showing ──
    left_month = _read_left_panel(page)
    if not left_month:
        page.screenshot(path=str(SCREENSHOT_DIR / "04_calendar_debug.png"))
        raise DateFilterError("Could not read the calendar's displayed month")

    console.print(f"  Calendar left panel shows: {left_month}")

    # ── Step C: Navigate the LEFT panel to the target month ──
    target_val = d.year * 12 + d.month
    if not _navigate_to_month(page, target_val):
        page.screenshot(path=str(SCREENSHOT_DIR / "04_calendar_debug.png"))
        raise DateFilterError(
            f"Could not navigate the calendar to {d.year}-{d.month:02d}"
        )

    page.wait_for_timeout(500)

    # ── Step D: Click the day twice to select a single-day range ──
    console.print(f"  Clicking day {d.day} (first click — start date)")
    if not _click_day(page, d):
        raise DateFilterError(
            f"Date {date} is not selectable in ASIK (day cell missing or disabled) — "
            f"it is likely before the earliest allowed date (CKG starts 2025-01-01) "
            f"or in the future"
        )
    page.wait_for_timeout(1000)

    console.print(f"  Clicking day {d.day} (second click — end date)")
    if not _click_day(page, d):
        raise DateFilterError(f"Day cell for {date} is not selectable on second click")
    page.wait_for_timeout(2000)

    page.screenshot(path=str(SCREENSHOT_DIR / "04_date_selected.png"))
    console.print("  [green]Date filter set![/green]")

    # Note: completing the range closes the popup, so we can't re-read the
    # selected cell here. The authoritative correctness check is the
    # `screening_date` guard in scraper._deep_scrape_patients — every returned
    # row must carry the requested date, else the run aborts.

    # ── Step E: Wait for table data to reload ──
    page.wait_for_timeout(2000)


def _read_left_panel(page: Page) -> dict | None:
    """Return {month, year, value} for the calendar's LEFT panel.

    Reads the month from an in-month day cell's ISO `title` (e.g.
    "2025-08-15") rather than the localized header text. The header renders
    abbreviations like "Agt"/"Mei"/"Des" whose exact spelling varies by the
    datepicker's locale data — parsing it once silently failed on August
    ("Agt"), aborting navigation and leaving the default range applied. The
    `title` attribute is always ISO, so this is locale-proof.
    """
    iso = page.evaluate("""() => {
        // Range mode renders two `.mx-calendar` panels; the first is the left.
        const cal = document.querySelector('.mx-calendar');
        if (!cal) return null;
        // Any day cell belonging to the displayed month (not the prev/next
        // month bleed-in) carries an ISO date for that month.
        const cell = cal.querySelector('td.cell:not(.not-current-month)');
        return cell && cell.title ? cell.title : null;
    }""")

    if not iso:
        return None

    try:
        d = dt.strptime(iso, "%Y-%m-%d")
    except ValueError:
        return None

    return {"month": d.month, "year": d.year, "value": d.year * 12 + d.month}


def _navigate_to_month(page: Page, target_val: int) -> bool:
    """Move the LEFT panel to the month encoded by target_val (year*12 + month).

    Distance-aware and locale-independent (reads the panel via `_read_left_panel`,
    i.e. day-cell ISO titles). When the gap is a year or more it jumps whole
    years with the double arrows (mx-btn-icon-double-left/right), then steps
    months with the single arrows (mx-btn-icon-left/right) — so far-back dates
    (2024, 2023, …) converge in a handful of clicks instead of dozens.

    Stops with False (→ caller raises DateFilterError) when the panel stalls:
    a click that didn't register, or a min/max boundary where the arrow is
    disabled. Never loops silently and never settles on the wrong month.
    """
    last_val = None
    stalls = 0
    # Generous safety cap; real navigation needs far fewer (≤ ~12 with year jumps).
    for _ in range(120):
        current = _read_left_panel(page)
        if not current:
            return False

        cur_val = current["value"]
        if cur_val == target_val:
            return True

        # Stall detection: the previous click left the panel where it was.
        if cur_val == last_val:
            stalls += 1
            if stalls >= 2:
                console.print("    [yellow]Calendar navigation stalled (arrow not advancing)[/yellow]")
                return False
        else:
            stalls = 0
        last_val = cur_val

        diff = target_val - cur_val
        if abs(diff) >= 12:
            btn_class = '.mx-btn-icon-double-right' if diff > 0 else '.mx-btn-icon-double-left'
        else:
            btn_class = '.mx-btn-icon-right' if diff > 0 else '.mx-btn-icon-left'
        btn = page.locator(btn_class).first
        if btn.count() == 0:
            # Year-jump arrow absent on some builds — fall back to a month step.
            btn_class = '.mx-btn-icon-right' if diff > 0 else '.mx-btn-icon-left'
            btn = page.locator(btn_class).first
            if btn.count() == 0:
                console.print("    [yellow]Could not find calendar nav arrow[/yellow]")
                return False

        btn.click()
        page.wait_for_timeout(350)

    return False


def _click_day(page: Page, d: dt) -> bool:
    """Click the exact date cell in the LEFT panel by its `title="YYYY-MM-DD"`.

    mx-datepicker tags every day `<td class="cell">` with `title` set to its
    ISO date. The grid bleeds in trailing days from the prior/next month with
    class `not-current-month` — those share the same day-text as the target
    month's days, so a text-only match would pick the wrong cell. Selecting by
    `title` and excluding `not-current-month`/`disabled` is unambiguous.
    """
    iso = d.strftime("%Y-%m-%d")
    found = page.evaluate("""(iso) => {
        const panels = document.querySelectorAll('.mx-calendar');
        const scope = panels.length > 0 ? panels[0] : document;
        const cell = scope.querySelector(
            `td.cell[title="${iso}"]:not(.disabled):not(.not-current-month)`
        );
        if (!cell) return false;
        cell.setAttribute('data-scraper-day', '1');
        return true;
    }""", iso)

    if not found:
        console.print(f"  [yellow]Could not find day cell for {iso}[/yellow]")
        return False

    page.click('[data-scraper-day="1"]')
    page.evaluate("() => document.querySelector('[data-scraper-day]')?.removeAttribute('data-scraper-day')")
    return True
