"""
Pagination helpers for the patient list table.

- `click_next_page`: tries many selector strategies (text, arrows, aria,
  class patterns) and falls back to clicking the current-page-number + 1.
- `navigate_to_page_num`: clicks Next until the active page matches target.
- `get_current_page_num`: reads the active pagination element.
- `count_visible_patient_rows`: counts non-empty tbody rows on the current
  page (used to drive the per-row loop in the orchestrator).
"""

from playwright.sync_api import Page


def click_next_page(page: Page) -> bool:
    """Try to click the 'next page' button. Returns True on success."""

    next_selectors = [
        # Text-based
        'button:has-text("Next")', 'a:has-text("Next")',
        'button:has-text("Selanjutnya")', 'a:has-text("Selanjutnya")',
        # Arrow/chevron based
        'button:has-text(">")', 'a:has-text(">")',
        'button:has-text("»")', 'a:has-text("»")',
        'button:has-text("›")', 'a:has-text("›")',
        # Aria labels
        '[aria-label="Next"]', '[aria-label="next page"]',
        '[aria-label="Go to next page"]',
        # Class-based
        'li.next:not(.disabled) a',
        '.pagination .next:not(.disabled) a',
        '.pagination li:last-child:not(.disabled) a',
        'button[class*="next"]:not([disabled])',
        'a[class*="next"]:not([class*="disabled"])',
        '[class*="pagination"] button:last-child:not([disabled])',
        # SVG chevron buttons (common in modern UIs)
        'button[aria-label*="next" i]',
        'nav[aria-label*="pagination"] button:last-of-type:not([disabled])',
    ]

    for sel in next_selectors:
        try:
            el = page.locator(sel).first
            if el.is_visible() and el.is_enabled():
                el.click()
                page.wait_for_load_state("networkidle")
                return True
        except Exception:
            continue

    # Fallback: click the active-page-number + 1
    try:
        current_page_num = page.evaluate("""() => {
            const active = document.querySelector(
                '.pagination .active, [class*="pagination"] [aria-current="page"], ' +
                '[class*="pagination"] button[class*="active"], [class*="pagination"] a[class*="active"]'
            );
            if (active) {
                const num = parseInt(active.innerText.trim());
                if (!isNaN(num)) return num;
            }
            return null;
        }""")

        if current_page_num:
            next_num = current_page_num + 1
            for sel in [
                f'.pagination a:has-text("{next_num}")',
                f'.pagination button:has-text("{next_num}")',
                f'[class*="pagination"] a:has-text("{next_num}")',
                f'[class*="pagination"] button:has-text("{next_num}")',
            ]:
                try:
                    el = page.locator(sel).first
                    if el.is_visible():
                        el.click()
                        page.wait_for_load_state("networkidle")
                        return True
                except Exception:
                    continue
    except Exception:
        pass

    return False


def navigate_to_page_num(page: Page, target_page: int):
    """Click Next until the active page number reaches target_page."""
    current_page = get_current_page_num(page) or 1
    if current_page >= target_page:
        return

    for _ in range(target_page - current_page):
        if not click_next_page(page):
            break


def get_current_page_num(page: Page) -> int | None:
    """Return the active pagination page number if visible."""
    try:
        return page.evaluate("""() => {
            const active = document.querySelector(
                '.pagination .active, [class*="pagination"] [aria-current="page"], ' +
                '[class*="pagination"] button[class*="active"], [class*="pagination"] a[class*="active"]'
            );
            if (!active) return null;
            const num = parseInt(active.innerText.trim());
            return isNaN(num) ? null : num;
        }""")
    except Exception:
        return None


def count_visible_patient_rows(page: Page) -> int:
    """Count visible patient rows without extracting their table data."""
    try:
        return page.evaluate("""() => {
            const rows = document.querySelectorAll('table tbody tr');
            let count = 0;
            for (const row of rows) {
                if (row.offsetParent === null) continue;
                const text = row.innerText ? row.innerText.trim() : '';
                if (!text) continue;
                count++;
            }
            return count;
        }""") or 0
    except Exception:
        return 0
