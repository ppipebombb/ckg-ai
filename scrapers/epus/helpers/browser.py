"""
Browser lifecycle helpers: API interception + persistent session state.

`APIInterceptor` listens to every Playwright `response` event and stores
JSON XHR / fetch bodies. The epus-v2 scraper extracts the Pelayanan Medis
list by matching responses whose URL path is `/pelayanan` with a DataTables
`columns[...]` query string (see `helpers/constants.py`).

The session functions let `--use-session` skip login on repeat runs by
reusing Chromium's persistent profile AND explicitly restoring cookies +
localStorage + sessionStorage. The profile alone has proven unreliable on
fresh browser starts in sibling scrapers.
"""

import json

from playwright.sync_api import Page
from rich.console import Console

from .constants import (
    SESSION_DIR,
    SESSION_STATE_PATH,
    SESSION_STORAGE_PATH,
)

console = Console()


class APIInterceptor:
    """Captures XHR / fetch JSON responses for later extraction."""

    def __init__(self, verbose: bool = False):
        self.all_responses: list[dict] = []
        self.verbose = verbose

    def on_response(self, response):
        url = response.url
        try:
            content_type = response.headers.get("content-type", "")
        except Exception:
            content_type = ""

        if response.request.resource_type not in ("xhr", "fetch"):
            return
        if "json" not in content_type:
            return

        try:
            body = response.json()
        except Exception:
            return

        try:
            req = response.request
            post_data = None
            try:
                post_data = req.post_data
            except Exception:
                pass
            try:
                req_headers = dict(req.headers) if req.headers else {}
            except Exception:
                req_headers = {}

            self.all_responses.append({
                "url": url,
                "method": req.method,
                "status": response.status,
                "request_post_data": post_data,
                "request_headers": req_headers,
                "body": body,
            })

            if self.verbose:
                if isinstance(body, dict):
                    shape = f"dict keys={list(body.keys())[:8]}"
                elif isinstance(body, list):
                    shape = f"list len={len(body)}"
                else:
                    shape = type(body).__name__
                console.print(
                    f"  [dim cyan][api][/dim cyan] "
                    f"{req.method} {response.status} {url[:140]} → {shape}"
                )
        except Exception:
            pass

    def latest_datatable(self) -> dict | None:
        """Return the most recent `/pelayanan?columns[...]` JSON response.

        Matches the DataTables-style XHR fired by the Pelayanan Medis
        list page. Returns the full body dict (with `meta` + `data`).
        """
        for entry in reversed(self.all_responses):
            url = entry["url"]
            if "/pelayanan?" not in url:
                continue
            if "columns" not in url:
                continue
            if entry.get("status") != 200:
                continue
            return entry["body"]
        return None

    def latest_datatable_url(self) -> str | None:
        """Return the captured DataTables URL (used to build page=N follow-ups)."""
        for entry in reversed(self.all_responses):
            url = entry["url"]
            if "/pelayanan?" in url and "columns" in url and entry.get("status") == 200:
                return url
        return None

    def clear(self):
        self.all_responses.clear()

    def dump(self, path) -> int:
        from pathlib import Path
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.all_responses, f, ensure_ascii=False, indent=2, default=str)
        return len(self.all_responses)


def clear_session_locks():
    """Remove stale Chrome profile lock files before reusing the session."""
    for name in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
        path = SESSION_DIR / name
        try:
            if path.exists() or path.is_symlink():
                path.unlink()
        except Exception as e:
            console.print(f"  [yellow]Could not remove stale session lock {name}: {e}[/yellow]")


# epuskesmas.id added a firewall rule (~2026-08-27) that blocks any request
# whose User-Agent carries the "HeadlessChrome" token — the string headless
# Chromium advertises by default — returning an "ePuskesmas.id - Blocked by
# Firewall" page with no login form. Overriding the UA to the same Chromium
# build's normal "Chrome" string (headless stays on; only the token differs)
# restores access. Keep the version aligned with the bundled Chromium when
# Playwright is upgraded; an older version here still works (only the token
# is what the firewall checks).
_CHROME_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/148.0.7778.96 Safari/537.36"
)


def launch_persistent_context(playwright, *, headless: bool = True, slow_mo: int = 50):
    """Launch Chromium with a persistent profile in SESSION_DIR."""
    SESSION_DIR.mkdir(exist_ok=True)
    clear_session_locks()

    return playwright.chromium.launch_persistent_context(
        user_data_dir=str(SESSION_DIR),
        headless=headless,
        slow_mo=slow_mo,
        viewport={"width": 1400, "height": 900},
        locale="id-ID",
        timezone_id="Asia/Jakarta",
        user_agent=_CHROME_UA,
    )


def restore_saved_auth_state(context, page: Page):
    """Restore cookies / localStorage / sessionStorage saved in SESSION_DIR."""
    if SESSION_STATE_PATH.exists():
        try:
            with open(SESSION_STATE_PATH, "r", encoding="utf-8") as f:
                state = json.load(f)
            cookies = state.get("cookies", [])
            if cookies:
                context.add_cookies(cookies)
        except Exception as e:
            console.print(f"  [yellow]Could not restore saved cookies: {e}[/yellow]")

    if SESSION_STORAGE_PATH.exists():
        try:
            with open(SESSION_STORAGE_PATH, "r", encoding="utf-8") as f:
                storage = json.load(f)
            script = """(data) => {
                const currentOrigin = window.location.origin;
                const originData = data[currentOrigin];
                if (!originData) return;
                for (const [key, value] of Object.entries(originData.localStorage || {})) {
                    window.localStorage.setItem(key, value);
                }
                for (const [key, value] of Object.entries(originData.sessionStorage || {})) {
                    window.sessionStorage.setItem(key, value);
                }
            }"""
            context.add_init_script(script, storage)
            page.add_init_script(script, storage)
        except Exception as e:
            console.print(f"  [yellow]Could not restore saved web storage: {e}[/yellow]")


def save_auth_state(context, page: Page, base_url: str):
    """Persist auth state into SESSION_DIR for --use-session reuse."""
    SESSION_DIR.mkdir(exist_ok=True)

    try:
        state = context.storage_state()
        with open(SESSION_STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception as e:
        console.print(f"  [yellow]Could not save storage state: {e}[/yellow]")

    try:
        storage = {}
        probe = context.new_page()
        try:
            probe.goto(base_url, wait_until="domcontentloaded", timeout=30000)
            probe.wait_for_timeout(1000)
            storage[base_url] = probe.evaluate(
                """() => ({
                    localStorage: Object.assign({}, window.localStorage),
                    sessionStorage: Object.assign({}, window.sessionStorage),
                })"""
            )
        finally:
            probe.close()

        with open(SESSION_STORAGE_PATH, "w", encoding="utf-8") as f:
            json.dump(storage, f, ensure_ascii=False, indent=2)
    except Exception as e:
        console.print(f"  [yellow]Could not save web storage: {e}[/yellow]")
