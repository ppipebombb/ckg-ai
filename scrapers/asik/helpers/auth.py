"""
Login + navigation + popup removal.

- `login` opens the target page, lets the ASIK site bounce to /login if
  needed, prefills credentials from config, then polls for up to 5 minutes
  while the operator solves the CAPTCHA and submits the login form.
- `navigate_to_pelayanan` reaches /ckg-pelayanan either by direct `goto`
  or by clicking through the sidebar (CKG Umum -> Pelayanan).
- `close_popups` deletes the "Pengaturan Pelayanan" modal (which has no
  close button) and any overlay / dialog elements from the DOM.
"""

import time

from playwright.sync_api import Page
from rich.console import Console

from .constants import SCREENSHOT_DIR

console = Console()


class SessionExpiredError(RuntimeError):
    """Raised mid-scrape when an authoritative API call returns 401/403.

    Caught by the main scrape loop, which re-runs the login flow (CAPTCHA)
    and retries the current patient. Distinct from generic RuntimeError so
    we don't accidentally retry on unrelated server errors.
    """


def verify_session(context, base_url: str) -> bool:
    """Probe /api/user-management/me to confirm the restored session is still
    valid server-side.

    Cookies can be present client-side yet rejected by the server (e.g. the
    "Sesi Telah Berakhir — login dari perangkat lain" case where another
    device logged in and invalidated this session). Returns False on 401/403
    or transport error, True only when the API returns 200.
    """
    try:
        r = context.request.get(
            f"{base_url}/api/user-management/me",
            headers={"Accept": "application/json"},
            timeout=10000,
        )
    except Exception as e:
        console.print(f"  [yellow]Session probe failed: {e}[/yellow]")
        return False
    if r.status == 200:
        return True
    console.print(f"  [yellow]Session probe returned HTTP {r.status} — session invalid[/yellow]")
    return False


def login(page: Page, base_url: str, credentials: dict, *,
          headless: bool = False, config: dict = None):
    """Open login page, prefill credentials, and solve CAPTCHA.

    When *headless* is ``False`` (default) the user solves the CAPTCHA in the
    visible browser window.  When ``True`` the CAPTCHA image is screenshotted
    and solved via :func:`captcha_solver.solve_captcha` (terminal input or,
    later, an LLM API call).

    Even when the URL stays on /ckg-pelayanan after restore (cookies were
    accepted client-side), we probe /api/user-management/me to confirm the
    server still trusts the session. If not (401/403), we force the login
    flow — covers the case where another device logged in and the server
    invalidated our session token.
    """
    console.print("\n[bold cyan]Step 1: Login[/bold cyan]")

    page.goto(f"{base_url}/ckg-pelayanan", wait_until="domcontentloaded")
    page.wait_for_timeout(2000)

    if "/login" not in page.url.lower() and "ckg" in page.url.lower():
        if verify_session(page.context, base_url):
            console.print("  [green]Already logged in! (session reuse worked)[/green]")
            return 0.0
        console.print("  [yellow]Restored session rejected by server — forcing fresh login[/yellow]")
        # Drop the dead session before re-login so /login flow starts clean.
        try:
            page.context.clear_cookies()
        except Exception:
            pass
        page.goto(f"{base_url}/login", wait_until="domcontentloaded")
        page.wait_for_timeout(2000)

    console.print("  [yellow]Login page detected. Filling in credentials...[/yellow]")

    if credentials.get("username"):
        try:
            for sel in [
                'input[type="email"]', 'input[name*="email"]',
                'input[name*="user"]', 'input[name*="nip"]',
                'input[placeholder*="email" i]', 'input[placeholder*="user" i]',
                'input[type="text"]',
            ]:
                el = page.query_selector(sel)
                if el and el.is_visible():
                    el.fill(credentials["username"])
                    console.print(f"    Filled username into: {sel}")
                    break
        except Exception as e:
            console.print(f"    [yellow]Could not fill username: {e}[/yellow]")

    if credentials.get("password"):
        try:
            el = page.query_selector('input[type="password"]')
            if el and el.is_visible():
                el.fill(credentials["password"])
                console.print("    Filled password")
        except Exception as e:
            console.print(f"    [yellow]Could not fill password: {e}[/yellow]")

    page.screenshot(path=str(SCREENSHOT_DIR / "01_login_prefilled.png"))

    solver_type = ((config or {}).get("captcha_solver") or {}).get("type")
    auto_captcha = solver_type == "llm"

    if not headless and not auto_captcha:
        # ── Visible browser, no LLM solver: user solves CAPTCHA manually ──
        console.print("\n  [bold yellow]>>> SOLVE THE CAPTCHA IN THE BROWSER AND CLICK LOGIN <<<[/bold yellow]")
        console.print("  [yellow]Waiting for you to complete login...[/yellow]")

        max_wait = 300  # seconds
        captcha_start = time.time()
        while time.time() - captcha_start < max_wait:
            if "/login" not in page.url.lower():
                captcha_duration = time.time() - captcha_start
                console.print("  [green]Login successful![/green]")
                page.wait_for_timeout(2000)
                page.screenshot(path=str(SCREENSHOT_DIR / "02_after_login.png"))
                return captcha_duration
            page.wait_for_timeout(1000)

        raise TimeoutError("Login timed out after 5 minutes. Please try again.")

    # ── Auto-solve: screenshot CAPTCHA, solve via terminal/LLM, submit ──
    # (Runs in both headless and visible modes when an LLM solver is configured —
    # visible mode lets a demo viewer watch the LLM-driven login.)
    from captcha_solver import solve_captcha

    captcha_duration = 0.0
    max_attempts = 20
    prev_src = ""
    for attempt in range(1, max_attempts + 1):
        console.print(f"\n  [cyan]CAPTCHA attempt {attempt}/{max_attempts}[/cyan]")

        # Wait until the captcha <img> has actually loaded its data URL.
        # Without this, on first paint or after a refresh click, the screenshot
        # may capture an empty/placeholder image (the LLM then receives a
        # solid-color rectangle and either guesses or refuses).
        if not _wait_for_captcha_loaded(page, prev_src):
            console.print(
                "  [yellow]Captcha image did not finish loading in time; "
                "refreshing and retrying without spending an LLM call[/yellow]"
            )
            if attempt < max_attempts:
                _refresh_captcha(page)
            continue

        captcha_img = _find_captcha_image(page)
        if captcha_img is None:
            raise RuntimeError("Could not locate CAPTCHA image element on the login page.")

        prev_src = page.evaluate("(el) => el.src || ''", captcha_img)

        captcha_path = SCREENSHOT_DIR / f"captcha_attempt_{attempt}.png"
        captcha_img.screenshot(path=str(captcha_path))

        # Reject near-uniform shots before spending an LLM call. Real CAPTCHA
        # screenshots have stddev ~30+ (digits on noisy bg); modal-covered or
        # placeholder shots peg under 10. Without this, a covered shot would
        # always come back as "0000" (system-prompt floor of 4 digits).
        if _screenshot_looks_blank(captcha_path):
            console.print(
                "  [yellow]Captcha screenshot looks blank/covered; "
                "refreshing without spending an LLM call[/yellow]"
            )
            try:
                captcha_path.unlink()
            except Exception:
                pass
            if attempt < max_attempts:
                _dismiss_post_submit_modal(page)
                _refresh_captcha(page)
            continue

        captcha_start = time.time()
        answer = solve_captcha(captcha_path, config=config)
        captcha_duration += time.time() - captcha_start

        if not answer:
            console.print("  [yellow]Empty answer, skipping attempt[/yellow]")
            if attempt < max_attempts:
                _refresh_captcha(page)
            continue

        captcha_input = _find_captcha_input(page)
        if captcha_input is None:
            raise RuntimeError("Could not locate CAPTCHA input field.")
        captcha_input.fill("")
        captcha_input.fill(answer)
        console.print(f"  Filled CAPTCHA answer: {answer}")

        # Masuk is a `<div class="bg-disabled cursor-not-allowed">` until the
        # captcha input has text; framework swaps it to `<button type=submit>`
        # on input. There's a brief Vue-render tick where the button renders
        # with `disabled=true` before validation resolves. Without this wait,
        # `_find_submit_button` can catch the disabled tick and the next
        # `.click()` burns its full 60s Locator timeout. Failed submits also
        # clear the captcha and revert Masuk back to the div — refresh+retry
        # restores the button.
        if not _wait_for_submit_enabled(page, timeout_ms=5000):
            console.print(
                "  [yellow]Submit button still disabled after captcha fill; "
                "refreshing and retrying[/yellow]"
            )
            if attempt < max_attempts:
                _dismiss_post_submit_modal(page)
                _refresh_captcha(page)
            continue

        submit_btn = _find_submit_button(page)
        if submit_btn is None:
            raise RuntimeError("Could not locate 'Masuk' submit button.")
        # Cap click timeout at 10s. Default 60s would block the retry loop
        # past the user's patience if the button flips back to disabled mid-click.
        try:
            submit_btn.click(timeout=10000)
        except Exception as e:
            console.print(f"  [yellow]Submit click failed: {e}; refreshing and retrying[/yellow]")
            if attempt < max_attempts:
                _dismiss_post_submit_modal(page)
                _refresh_captcha(page)
            continue
        page.wait_for_timeout(3000)

        if "/login" not in page.url.lower():
            console.print("  [green]Login successful![/green]")
            page.wait_for_timeout(2000)
            page.screenshot(path=str(SCREENSHOT_DIR / "02_after_login.png"))
            return captcha_duration

        console.print("  [yellow]Still on login page — CAPTCHA may have been wrong.[/yellow]")
        if attempt < max_attempts:
            # Failed submit pops a "Belum berhasil masuk" modal with a backdrop
            # overlay. Without dismissing, the next attempt's submit_btn.click()
            # is blocked by pointer-events for the full 60s Locator timeout and
            # the retry loop dies before reaching attempt 3.
            _dismiss_post_submit_modal(page)
            _refresh_captcha(page)

    raise RuntimeError(f"Login failed after {max_attempts} CAPTCHA attempts.")


def navigate_to_pelayanan(page: Page, base_url: str):
    """Reach /ckg-pelayanan via direct navigation or sidebar click."""
    console.print("\n[bold cyan]Step 2: Navigate to CKG Umum → Pelayanan[/bold cyan]")

    if "/ckg-pelayanan" in page.url:
        console.print("  [green]Already on the Pelayanan page![/green]")
        page.wait_for_timeout(2000)
        return

    try:
        page.goto(f"{base_url}/ckg-pelayanan", wait_until="networkidle")
        page.wait_for_timeout(3000)
        if "/ckg-pelayanan" in page.url:
            console.print("  [green]Navigated directly to /ckg-pelayanan[/green]")
            return
    except Exception:
        pass

    console.print("  Trying sidebar navigation...")

    try:
        for sel in [
            'text="CKG Umum"', ':text("CKG Umum")',
            'a:has-text("CKG Umum")', 'span:has-text("CKG Umum")',
            'div:has-text("CKG Umum")', 'li:has-text("CKG Umum")',
        ]:
            try:
                el = page.locator(sel).first
                if el.is_visible():
                    el.click()
                    page.wait_for_timeout(1000)
                    console.print("    Clicked 'CKG Umum'")
                    break
            except Exception:
                continue
    except Exception as e:
        console.print(f"    [yellow]Could not click CKG Umum: {e}[/yellow]")

    try:
        for sel in [
            'a:has-text("Pelayanan")', 'text="Pelayanan"',
            ':text("Pelayanan")', 'span:has-text("Pelayanan")',
        ]:
            try:
                el = page.locator(sel).first
                if el.is_visible():
                    el.click()
                    page.wait_for_load_state("networkidle")
                    page.wait_for_timeout(2000)
                    console.print("    Clicked 'Pelayanan'")
                    break
            except Exception:
                continue
    except Exception as e:
        console.print(f"    [yellow]Could not click Pelayanan: {e}[/yellow]")

    page.screenshot(path=str(SCREENSHOT_DIR / "03_pelayanan_page.png"))
    console.print(f"  Current URL: {page.url}")


def close_popups(page: Page, silent: bool = False):
    """Remove modal overlays (including the "Pengaturan Pelayanan" one that
    has no close button) from the DOM, then unlock body scroll."""
    if not silent:
        console.print("\n[bold cyan]Step 3: Closing popups/modals...[/bold cyan]")

    removed = page.evaluate("""() => {
        let removed = 0;

        // === Strategy 1: Remove the "Pengaturan Pelayanan" modal ===
        // This modal has no close button, so we nuke it from the DOM.
        // It appears on first visit after login.
        const allElements = document.querySelectorAll('*');
        for (const el of allElements) {
            if (el.tagName === 'H1' || el.tagName === 'H2' || el.tagName === 'H3' ||
                el.tagName === 'DIV' || el.tagName === 'SPAN' || el.tagName === 'P') {
                if (el.innerText && el.innerText.trim() === 'Pengaturan Pelayanan') {
                    let modal = el;
                    for (let i = 0; i < 10; i++) {
                        if (!modal.parentElement) break;
                        modal = modal.parentElement;
                        const style = window.getComputedStyle(modal);
                        if ((style.position === 'fixed' || style.position === 'absolute') &&
                            (modal.offsetWidth > window.innerWidth * 0.3)) {
                            modal.remove();
                            removed++;
                            break;
                        }
                        if (modal.getAttribute('role') === 'dialog' ||
                            modal.classList.toString().match(/modal|overlay|backdrop|dialog/i)) {
                            modal.remove();
                            removed++;
                            break;
                        }
                    }
                    break;
                }
            }
        }

        // === Strategy 2: Remove any backdrop/overlay that blocks clicks ===
        const overlays = document.querySelectorAll(
            '[class*="overlay"], [class*="backdrop"], [class*="modal-bg"], ' +
            '[class*="modal-mask"], [class*="dialog-overlay"]'
        );
        for (const overlay of overlays) {
            const style = window.getComputedStyle(overlay);
            if (style.position === 'fixed' || style.position === 'absolute') {
                overlay.remove();
                removed++;
            }
        }

        // === Strategy 3: Remove modals by role="dialog" ===
        const dialogs = document.querySelectorAll('[role="dialog"], [role="alertdialog"]');
        for (const dialog of dialogs) {
            dialog.remove();
            removed++;
        }

        // === Strategy 5: Remove any remaining fixed full-screen overlays ===
        const allFixed = document.querySelectorAll('div');
        for (const div of allFixed) {
            const style = window.getComputedStyle(div);
            if (style.position === 'fixed' && style.zIndex > 999 &&
                div.offsetWidth >= window.innerWidth * 0.5 &&
                div.offsetHeight >= window.innerHeight * 0.5 &&
                div.querySelector('h1, h2, h3, form, select')) {
                div.remove();
                removed++;
            }
        }

        // === Strategy 6: Remove body scroll lock (modals often set overflow:hidden) ===
        document.body.style.overflow = '';
        document.documentElement.style.overflow = '';

        return removed;
    }""")

    if removed > 0:
        console.print(f"  Removed {removed} modal/overlay element(s) from DOM")
        page.wait_for_timeout(500)
        return

    # Fast path for the recurring post-submit confirm modal. The DOM sweep above
    # doesn't match it, so we used to reach it through the Playwright fallback —
    # up to 8 sequential `is_visible()` round-trips, and in practice it is the
    # THIRD one ("OK") that hits, on nearly every form. Doing the same match in a
    # single evaluate turns ~3 IPC round-trips per call into 0 extra; with
    # close_popups running ~45x per patient that is the difference between
    # seconds and tens of seconds. Same selectors, same order, same click.
    clicked = page.evaluate("""() => {
        const byText = ['Tutup', 'Close', 'OK', '\\u00d7'];
        const vis = (e) => e && e.offsetParent !== null;
        const btns = Array.from(document.querySelectorAll('button')).filter(vis);
        for (const want of byText) {
            const hit = btns.find(b => (b.innerText || '').trim() === want);
            if (hit) { hit.click(); return 'button:' + want; }
        }
        for (const sel of ['[aria-label="Close"]', '.btn-close', '.swal2-confirm', '.swal2-close']) {
            const el = document.querySelector(sel);
            if (vis(el)) { el.click(); return sel; }
        }
        return null;
    }""")
    if clicked:
        page.wait_for_timeout(500)
        console.print(f"  Closed popup via button: {clicked}")
        return

    # Safety net: the JS click can miss a control that only responds to a real
    # trusted event. Rarely reached now, so its cost no longer dominates.
    close_selectors = [
        'button:has-text("Tutup")', 'button:has-text("Close")',
        'button:has-text("OK")', 'button:has-text("×")',
        '[aria-label="Close"]', '.btn-close',
        '.swal2-confirm', '.swal2-close',
    ]
    for sel in close_selectors:
        try:
            btn = page.locator(sel).first
            if btn.is_visible():
                btn.click()
                page.wait_for_timeout(500)
                console.print(f"  Closed popup via button: {sel}")
                return
        except Exception:
            continue

    if not silent:
        console.print("  No popups found")


# ─────────────────────────────────────────────────────────────────────────
# CAPTCHA element helpers (used by headless login flow)
# ─────────────────────────────────────────────────────────────────────────

def _find_captcha_image(page: Page):
    """Locate the CAPTCHA image element using multiple selector strategies."""
    # Exact alt match seen in the live ASIK login DOM. Try first because the
    # real captcha is served as a base64 data: URL with no "captcha" substring
    # in src — the legacy src*= selectors below only match on alt fallback.
    for sel in [
        'img[alt="image-captcha"]',
        'img[alt*="captcha" i]',
        'img[src*="captcha" i]',
        'img[src*="Captcha"]',
    ]:
        el = page.query_selector(sel)
        if el and el.is_visible():
            return el

    # Heuristic: walk up from the CAPTCHA input to find the nearest <img>
    captcha_input = _find_captcha_input(page)
    if captcha_input:
        handle = page.evaluate_handle("""(inputEl) => {
            let container = inputEl.parentElement;
            for (let i = 0; i < 5; i++) {
                if (!container) break;
                const img = container.querySelector('img');
                if (img && img.offsetParent !== null) return img;
                container = container.parentElement;
            }
            return null;
        }""", captcha_input)
        el = handle.as_element()
        if el:
            return el

    # Last resort: canvas element
    canvas = page.query_selector('canvas')
    if canvas and canvas.is_visible():
        return canvas

    return None


def _find_captcha_input(page: Page):
    """Locate the CAPTCHA text input field."""
    for sel in [
        'input[placeholder*="captcha" i]',
        'input[placeholder*="Masukkan" i]',
        'input[name*="captcha" i]',
        'input[id*="captcha" i]',
    ]:
        el = page.query_selector(sel)
        if el and el.is_visible():
            return el
    return None


def _find_submit_button(page: Page):
    """Locate the 'Masuk' login submit button."""
    for sel in [
        'button:has-text("Masuk")',
        'button[type="submit"]',
        'input[type="submit"]',
        'button:has-text("Login")',
        'button:has-text("Sign in")',
    ]:
        try:
            el = page.locator(sel).first
            if el.is_visible():
                return el
        except Exception:
            continue
    return None


def _wait_for_captcha_loaded(page: Page, prev_src: str = "", timeout_ms: int = 8000) -> bool:
    """Block until a supported CAPTCHA element is loaded with a fresh src.

    Returns True if a supported image/canvas selector is ready and (when
    prev_src is given for an image) different from the previous attempt's src.
    Returns False on timeout instead of raising so the caller can decide whether
    to proceed or fail the attempt.
    """
    try:
        page.wait_for_function(
            """(prev) => {
                const visible = (el) => {
                    if (!el) return false;
                    const rect = el.getBoundingClientRect();
                    const style = window.getComputedStyle(el);
                    return rect.width > 0 && rect.height > 0
                        && style.visibility !== 'hidden'
                        && style.display !== 'none';
                };
                const imageReady = (im) => {
                    if (!visible(im)) return false;
                    if (!im.complete) return false;
                    if (im.naturalWidth <= 0 || im.naturalHeight <= 0) return false;
                    const src = im.src || '';
                    return !prev || !src || src !== prev;
                };

                const imageSelectors = [
                    'img[alt="image-captcha"]',
                    'img[alt*="captcha" i]',
                    'img[src*="captcha" i]',
                    'img[src*="Captcha"]',
                ];
                for (const sel of imageSelectors) {
                    const im = document.querySelector(sel);
                    if (imageReady(im)) return true;
                }

                const input = document.querySelector(
                    'input[placeholder*="captcha" i], ' +
                    'input[placeholder*="Masukkan" i], ' +
                    'input[name*="captcha" i], ' +
                    'input[id*="captcha" i]'
                );
                if (input) {
                    let container = input.parentElement;
                    for (let i = 0; i < 5; i++) {
                        if (!container) break;
                        const im = container.querySelector('img');
                        if (imageReady(im)) return true;
                        container = container.parentElement;
                    }
                }

                const canvas = document.querySelector('canvas');
                if (visible(canvas) && canvas.width > 0 && canvas.height > 0) {
                    return true;
                }

                return false;
            }""",
            arg=prev_src,
            timeout=timeout_ms,
        )
        return True
    except Exception:
        return False


def _wait_for_submit_enabled(page: Page, timeout_ms: int = 5000) -> bool:
    """Block until the login submit button is a real `<button type=submit>`
    with text Masuk/Login AND not `disabled`.

    On the ASIK login page Masuk renders as a `<div class="bg-disabled
    cursor-not-allowed">` while the captcha input is empty; it swaps to a
    `<button type=submit>` once the captcha has text. The swap can briefly
    render the button with `disabled=true` for one Vue tick. Returns False
    on timeout so caller can refresh+retry rather than burning Playwright's
    60s click-timeout against a stuck-disabled button.
    """
    try:
        page.wait_for_function(
            """() => {
                const candidates = Array.from(document.querySelectorAll(
                    'button[type="submit"], input[type="submit"], button'
                ));
                for (const el of candidates) {
                    const txt = (el.innerText || el.value || el.textContent || '').trim().toLowerCase();
                    if (!txt.includes('masuk') && !txt.includes('login') && !txt.includes('sign in')) continue;
                    const rect = el.getBoundingClientRect();
                    if (rect.width <= 0 || rect.height <= 0) continue;
                    const style = window.getComputedStyle(el);
                    if (style.visibility === 'hidden' || style.display === 'none') continue;
                    if (el.disabled) continue;
                    if (el.getAttribute('aria-disabled') === 'true') continue;
                    return true;
                }
                return false;
            }""",
            timeout=timeout_ms,
        )
        return True
    except Exception:
        return False


def _screenshot_looks_blank(path) -> bool:
    """True when the saved CAPTCHA screenshot is near-uniform (modal-covered
    or unloaded placeholder). Threshold of 10 was picked from live runs:
    real CAPTCHAs measure stddev ~30-45, modal/blank shots <8.
    """
    try:
        from PIL import Image, ImageStat
        img = Image.open(path).convert("L")
        stddev = ImageStat.Stat(img).stddev[0]
        return stddev < 10.0
    except Exception:
        return False


def _dismiss_post_submit_modal(page: Page) -> bool:
    """Close the error modal shown after a failed login submit.

    Modal structure on the live page (captured 2026-04-28):
      wrapper  div.!z-99999.fixed...backdrop-blur-5
         └ overlay  div.fixed.inset-0.opacity-50.z-20  (intercepts clicks)
         └ box     contains text "Belum berhasil masuk" + button "Ok" (.btn-fill-warning)

    Click the Ok button first (lets the framework run its own teardown);
    fall back to nuking the wrapper + overlay from the DOM if no button is
    visible. Returns True when something was dismissed.
    """
    try:
        btn = page.locator(
            'button.btn-fill-warning:has-text("Ok"), '
            'button:has-text("Ok"), '
            'button:has-text("OK"), '
            'button:has-text("Tutup")'
        ).first
        if btn.is_visible():
            btn.click()
            page.wait_for_timeout(400)
            return True
    except Exception:
        pass

    removed = page.evaluate("""() => {
        let n = 0;
        document.querySelectorAll('div').forEach(el => {
            const cls = (typeof el.className === 'string') ? el.className : '';
            if (cls.includes('backdrop-blur')) { el.remove(); n++; return; }
            if (cls.includes('opacity-50') && cls.includes('z-20')
                && cls.includes('fixed') && cls.includes('inset-0')) {
                el.remove(); n++;
            }
        });
        return n;
    }""")
    if removed:
        page.wait_for_timeout(200)
    return removed > 0


def _refresh_captcha(page: Page):
    """Click the CAPTCHA refresh button to get a new image.

    Caller is expected to invoke ``_wait_for_captcha_loaded`` afterward to
    block until the new image has actually rendered — without that gate, the
    next screenshot can race the network and capture an empty placeholder.
    """
    # Precise path for the ASIK login page: refresh button is a sibling of the
    # captcha img wrapper. This is the only reliable handle — the button has
    # no aria-label or title, so attribute selectors won't find it.
    clicked = page.evaluate("""() => {
        const im = document.querySelector('img[alt="image-captcha"]')
                || document.querySelector('img[alt*="captcha" i]');
        if (!im) return false;
        const wrapper = im.parentElement;
        const row = wrapper && wrapper.parentElement;
        if (!row) return false;
        const btn = row.querySelector('button');
        if (!btn) return false;
        btn.click();
        return true;
    }""")
    if clicked:
        console.print("  Refreshed CAPTCHA image")
        return

    # Fallback: aria/title hints (kept for resilience if the DOM changes)
    for sel in [
        'button[aria-label*="refresh" i]',
        'button[title*="refresh" i]',
        '[aria-label*="refresh" i]',
    ]:
        try:
            el = page.locator(sel).first
            if el.is_visible():
                el.click()
                console.print(f"  Refreshed CAPTCHA image (via {sel})")
                return
        except Exception:
            continue

    console.print("  [yellow]Could not find CAPTCHA refresh button[/yellow]")
