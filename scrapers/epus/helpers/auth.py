"""
Login helpers for kotabekasi.epuskesmas.id.

Unlike the sibling `epus/` scraper (which logs in through the portal's
landing page + bottom-tab dropdown), epus-v2 goes straight to
`/login` with the standard email + password form. No CAPTCHA, no portal
hover — just a 302 back to `/home` on success. Verified 2026-04-18 during
recon (tools/recon.py, archived to .scratch/).
"""

import time

from playwright.sync_api import Page
from rich.console import Console

from .constants import SCREENSHOT_DIR

console = Console()


def login(page: Page, base_url: str, credentials: dict, *, headless: bool = True):
    """Go to /login, fill email + password, submit, wait until off /login.

    Returns ``True`` on success, raises on timeout.
    """
    console.print("\n[bold cyan]Step 1: Login[/bold cyan]")

    login_url = f"{base_url}/login"
    page.goto(login_url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(1500)

    # Already inside the app? (session reuse path)
    if "/login" not in page.url.lower():
        console.print("  [green]Already logged in (session reuse)[/green]")
        return True

    email = credentials.get("email", "")
    password = credentials.get("password", "")

    if not email or not password:
        raise RuntimeError(
            "epus-v2 requires credentials.email and credentials.password in config.json"
        )

    _fill_first_visible(page, email, [
        'input[type="email"]',
        'input[name*="email" i]',
        'input[name*="user" i]',
        'input[name*="login" i]',
        'input[placeholder*="email" i]',
        'input[placeholder*="user" i]',
        'input[type="text"]',
    ], field="email")

    _fill_first_visible(page, password, [
        'input[type="password"]',
        'input[name*="password" i]',
    ], field="password")

    SCREENSHOT_DIR.mkdir(exist_ok=True)
    page.screenshot(path=str(SCREENSHOT_DIR / "01_login_filled.png"))

    _click_submit(page)

    deadline = time.time() + 30
    while time.time() < deadline:
        if "/login" not in page.url.lower():
            page.wait_for_timeout(1000)
            console.print(f"  [green]Login successful (url = {page.url})[/green]")
            page.screenshot(path=str(SCREENSHOT_DIR / "02_after_login.png"))
            return True
        page.wait_for_timeout(500)

    page.screenshot(path=str(SCREENSHOT_DIR / "02_login_failed.png"))
    raise TimeoutError(
        "Login timed out — still on /login after 30s. Check credentials or screenshots/"
    )


def navigate_to_pelayanan(page: Page, base_url: str, *, tanggal: str,
                          status_periksa: str, ruangan_id: str, limit: str,
                          search_key: str | None = None):
    """Go to the filtered Pelayanan Medis list URL.

    The app handles ?tanggal, ?status_periksa, ?ruangan_id, ?limit, ?searchKey
    as form prefills — its JS fires the DataTables XHR immediately after the
    page loads. We don't need to touch the form; we only intercept the XHR.
    """
    console.print("\n[bold cyan]Step 2: Navigate to Pelayanan (filtered)[/bold cyan]")

    url = (
        f"{base_url}/pelayanan"
        f"?status_periksa={status_periksa}"
        f"&ruangan_id={ruangan_id}"
        f"&limit={limit}"
        f"&tanggal={tanggal}"
    )
    if search_key:
        url = f"{url}&searchKey={search_key}"
    console.print(f"  URL: {url}")

    try:
        page.goto(url, wait_until="networkidle", timeout=60000)
    except Exception:
        # networkidle can flake on long-poll; fall back to domcontentloaded.
        page.goto(url, wait_until="domcontentloaded", timeout=60000)

    # DataTables fires its XHR after DOMContentLoaded — give it a moment.
    page.wait_for_timeout(4000)
    SCREENSHOT_DIR.mkdir(exist_ok=True)
    page.screenshot(path=str(SCREENSHOT_DIR / "03_pelayanan.png"))


# ----------------------------------------------------------------------
# Internal helpers
# ----------------------------------------------------------------------

def _fill_first_visible(page: Page, value: str, selectors: list[str], *, field: str):
    for sel in selectors:
        try:
            el = page.query_selector(sel)
            if el and el.is_visible():
                el.fill(value)
                console.print(f"    Filled {field} into {sel}")
                return True
        except Exception:
            continue
    console.print(f"  [yellow]Could not fill {field}[/yellow]")
    return False


def _click_submit(page: Page):
    for sel in [
        'button[type="submit"]',
        'button:has-text("Login")',
        'button:has-text("Masuk")',
        'input[type="submit"]',
    ]:
        try:
            btn = page.locator(sel).first
            if btn.is_visible():
                btn.click()
                console.print(f"    Clicked submit ({sel})")
                return True
        except Exception:
            continue

    # JS fallback
    clicked = page.evaluate("""() => {
        const cands = document.querySelectorAll('button, input[type="submit"]');
        for (const b of cands) {
            const t = (b.textContent || b.value || '').trim().toLowerCase();
            if (['login', 'masuk', 'sign in', 'submit'].includes(t)) { b.click(); return true; }
        }
        const s = document.querySelector('button[type="submit"]');
        if (s) { s.click(); return true; }
        return false;
    }""")
    if clicked:
        console.print("    Clicked submit (JS fallback)")
    return clicked
