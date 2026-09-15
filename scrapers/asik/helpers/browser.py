"""
Browser lifecycle helpers: API interception + persistent session state.

- `APIInterceptor` listens to every Playwright `response` event and keeps a
  copy of JSON arrays under common keys (`data`, `results`, etc.) as a
  fallback for when DOM extraction is messy.
- The session functions let `--use-session` skip the CAPTCHA on repeat runs
  by reusing Chromium's user-data dir AND explicitly replaying cookies /
  localStorage / sessionStorage (the profile alone has proven unreliable on
  fresh browser starts).
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
    """Intercepts XHR/fetch responses to capture data from API calls."""

    def __init__(self, verbose: bool = False):
        self.captured_data: list[dict] = []
        self.all_responses: list[dict] = []
        self.verbose = verbose

    def on_response(self, response):
        url = response.url
        content_type = response.headers.get("content-type", "")

        if response.request.resource_type in ("xhr", "fetch") and "json" in content_type:
            try:
                body = response.json()
                req = response.request
                try:
                    post_data = req.post_data
                except Exception:
                    post_data = None
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
                        keys = list(body.keys())[:8]
                        shape = f"dict keys={keys}"
                    elif isinstance(body, list):
                        shape = f"list len={len(body)}"
                    else:
                        shape = type(body).__name__
                    console.print(
                        f"  [dim cyan][api][/dim cyan] "
                        f"{response.request.method} {response.status} "
                        f"{url} → {shape}"
                    )

                if isinstance(body, dict):
                    for key in ("data", "results", "items", "records", "rows", "content", "list"):
                        if key in body and isinstance(body[key], list) and len(body[key]) > 0:
                            self.captured_data.append({
                                "url": url,
                                "data_key": key,
                                "records": body[key],
                                "meta": {k: v for k, v in body.items()
                                         if k != key and not isinstance(v, (list, dict))},
                            })
                elif isinstance(body, list) and len(body) > 0:
                    self.captured_data.append({
                        "url": url,
                        "data_key": None,
                        "records": body,
                        "meta": {},
                    })
            except Exception:
                pass

    def get_latest_data(self) -> list[dict] | None:
        if self.captured_data:
            return self.captured_data[-1]["records"]
        return None

    def clear(self):
        self.captured_data.clear()

    def dump(self, path) -> int:
        """Write all captured XHR/fetch JSON responses to `path`. Returns count."""
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


def _wipe_session_dir():
    """Delete every entry under SESSION_DIR (keeping the directory itself)."""
    import shutil
    if not SESSION_DIR.exists():
        return
    for child in SESSION_DIR.iterdir():
        try:
            if child.is_dir() and not child.is_symlink():
                shutil.rmtree(child, ignore_errors=True)
            else:
                child.unlink()
        except Exception as e:
            console.print(f"  [yellow]Could not wipe {child.name}: {e}[/yellow]")


def launch_persistent_context(playwright, *, headless: bool = False, slow_mo: int = 50):
    """Launch the saved browser session from SESSION_DIR.

    Uses Playwright's normal persistent Chromium path so session reuse stays
    consistent across runs and across machines.

    If Chromium fails to come up (stale profile, Chrome major-version mismatch
    after a Playwright bump, etc.), wipe the profile and retry once with a
    fresh user_data_dir — auth will be redone via the configured CAPTCHA
    solver, which is preferable to hard-failing the job.

    Parameters
    ----------
    headless : bool
        Run Chromium without a visible window.  Default ``False``.
    slow_mo : int
        Milliseconds to wait between Playwright operations.  Default ``50``.
    """
    SESSION_DIR.mkdir(exist_ok=True)
    clear_session_locks()

    def _launch():
        return playwright.chromium.launch_persistent_context(
            user_data_dir=str(SESSION_DIR),
            headless=headless,
            slow_mo=slow_mo,
            viewport={"width": 1920, "height": 1080},
            locale="id-ID",
            timezone_id="Asia/Jakarta",
        )

    try:
        return _launch()
    except Exception as e:
        console.print(
            f"  [yellow]launch_persistent_context failed ({e!r}); "
            f"wiping session and retrying[/yellow]"
        )
        _wipe_session_dir()
        return _launch()


def restore_saved_auth_state(context, page: Page):
    """Restore cookies / localStorage / sessionStorage saved in SESSION_DIR.

    We still use the session folder profile, but we also restore explicit
    auth state because the site may not fully accept the reopened profile
    alone on a fresh browser start.
    """
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
            # Playwright's add_init_script signature is (script=None, *, path=None)
            # — it takes NO value to pass through to the script. The old call
            # passed `storage` positionally, so it raised TypeError on EVERY run
            # and web storage was never restored (the persistent profile happened
            # to carry localStorage on disk, which is why nothing looked broken).
            # A non-persistent context has no profile, so inline the data instead.
            script = (
                "(() => { const data = "
                + json.dumps(storage)
                + """;
                    const originData = data[window.location.origin];
                    if (!originData) return;
                    for (const [key, value] of Object.entries(originData.localStorage || {})) {
                        window.localStorage.setItem(key, value);
                    }
                    for (const [key, value] of Object.entries(originData.sessionStorage || {})) {
                        window.sessionStorage.setItem(key, value);
                    }
                })()"""
            )
            context.add_init_script(script)
            # Context init scripts only apply to pages created afterwards; the
            # caller already opened `page`, so arm it for its next navigation too.
            page.add_init_script(script)
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
        origins = [
            base_url,
            "https://form.kemkes.go.id",
        ]
        storage = {}
        for origin in origins:
            probe = context.new_page()
            try:
                probe.goto(origin, wait_until="domcontentloaded", timeout=30000)
                probe.wait_for_timeout(1000)
                storage[origin] = probe.evaluate(
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
