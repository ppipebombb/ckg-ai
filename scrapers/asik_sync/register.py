"""
=============================================================================
ASIK CKG Register — create a NEW patient in ASIK via Playwright
=============================================================================
Registers an `epus_only + tandai_ckg` patient into ASIK's
"Cari/Daftarkan Individu" flow (page `/ckg-pendaftaran-individu` →
"Daftar Baru"), then hands off to the existing form-fill (`sync.py`).

This module implements STEP 1 of that flow plus a **dry-run probe** mode:

  dry_run_probe = true
    Fill the step-1 form, click "Selanjutnya", read the guard, and — if we
    reach step 2 ("Isi data pendukung") — CAPTURE the step-2 structure into
    `step2_dom` and STOP. It NEVER clicks anything that commits (no
    "Daftarkan dengan NIK", no "Selesai"). Run over the epus_only set this
    doubles as the yield check + the step-2 selector capture.

  dry_run_probe = false  (live)
    Fill step 2 ("Isi data pendukung") from reg.step2, then gated by reg.commit:
      commit falsy → STOP at outcome `step2_filled` (nothing committed).
      commit true  → step 3 (Pilih our NIK's row → "Daftarkan dengan NIK" = THE
        COMMIT) → read the "Berhasil Daftar / No. Tiket" ticket → best-effort
        "Konfirmasi Hadir" → outcome `created` (+ ticket, hadir). Mulai
        Pemeriksaan + the exam fill are owned by the existing sync.py scraper.

Guarantees / gotchas honoured (all live-verified — see
`documents/create-patient-asik/FINDINGS.md`):
  - GENUINE Playwright events for every form interaction (Vue/SurveyJS
    reject synthetic JS clicks). `page.evaluate` is used ONLY to read/locate
    the DOM, never to set a value or click a submit/date/checkbox.
  - The exam-date button needs a real (CDP) click or Vue's model never
    updates and Selanjutnya stays disabled.
  - Tanggal Lahir is a vue2-datepicker (`.mx-*`) — click-only, no input.
  - DOB comes from `register.dob` (backend already derived it from the NIK).

Output JSON:
  { nik, dry_run_probe, outcome, served_detail, step2_dom, ticket, hadir,
    screenshot, elapsed_seconds, captcha_seconds, error }
=============================================================================
"""

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

# Reuse asik helpers
SYNC_DIR = Path(__file__).resolve().parent
SCRAPERS_ROOT = SYNC_DIR.parent
ASIK_DIR = SCRAPERS_ROOT / "asik"
sys.path.insert(0, str(SCRAPERS_ROOT))  # for _lifecycle
sys.path.insert(0, str(ASIK_DIR))

# Parent-death watchdog: kill ourselves if the launching terminal closes.
from _lifecycle import install as _install_lifecycle  # noqa: E402
_install_lifecycle()

from playwright.sync_api import sync_playwright, Page  # noqa: E402
from rich.console import Console  # noqa: E402

from helpers import (  # noqa: E402
    SCREENSHOT_DIR,
    SESSION_DIR,
    launch_persistent_context,
    restore_saved_auth_state,
    save_auth_state,
    login,
    close_popups,
)

console = Console()

REGISTER_PATH = "/ckg-pendaftaran-individu"

# vue2-datepicker month-panel cell abbreviations (id-ID). Candidates per month
# so a locale variant for August (Agt/Agu/Ags) still resolves.
_MX_MONTH_CANDS = {
    1: ["Jan"], 2: ["Feb"], 3: ["Mar"], 4: ["Apr"], 5: ["Mei", "May"],
    6: ["Jun"], 7: ["Jul"], 8: ["Agt", "Agu", "Ags", "Aug"], 9: ["Sep"],
    10: ["Okt", "Oct"], 11: ["Nov"], 12: ["Des", "Dec"],
}

# Full Indonesian month names as rendered in the exam-date calendar header.
_ID_MONTHS = [
    "januari", "februari", "maret", "april", "mei", "juni",
    "juli", "agustus", "september", "oktober", "november", "desember",
]

# The exam calendar header is ABBREVIATED ("Agt 2026"), not the full month name.
# Map every recognised header token (the mx abbreviations + the full names) → month
# number, so _exam_ym / _click_exam_nav agree on what counts as a month token.
_EXAM_MONTH_LOOKUP: dict[str, int] = {
    **{c.lower(): n for n, cands in _MX_MONTH_CANDS.items() for c in cands},
    **{full: i for i, full in enumerate(_ID_MONTHS, start=1)},
}


def _exam_month_num(token: str) -> int | None:
    """Header month token ('Agt', 'Agustus', 'Agu', …) → 1-based month number."""
    t = (token or "").strip().lower()
    if t in _EXAM_MONTH_LOOKUP:
        return _EXAM_MONTH_LOOKUP[t]
    return next(
        (i for i, full in enumerate(_ID_MONTHS, start=1) if len(t) >= 3 and full.startswith(t)),
        None,
    )

# Step-2 heading / field markers — reaching any means we passed both guards.
_STEP2_MARKERS = (
    "isi data pendukung",
    "status pernikahan",
    "penyandang disabilitas",
    "pekerjaan",
    "alamat domisili",
)


def _load_config(config_path: Path) -> dict:
    if not config_path.exists():
        raise FileNotFoundError(f"config not found: {config_path}")
    with open(config_path) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Consent modal + launch retry (copied from sync.py so this module is
# self-contained; behaviour is identical).
# ---------------------------------------------------------------------------
def _dismiss_consent_modal(page: Page) -> bool:
    """Remove ASIK's privacy-consent modal ('Pemberitahuan Privasi / Persetujuan').

    Appears on a cold session; `close_popups` doesn't target it by name. Removing it
    from the DOM (the same nuke strategy `close_popups` uses for 'Pengaturan
    Pelayanan') unblocks navigation — verified against live ASIK 2026-07-20.
    """
    try:
        return bool(page.evaluate(
            """() => {
                let removed=false;
                for (const el of document.querySelectorAll('div,span,p,h1,h2,h3')) {
                    if (el.children.length===0 && /Pemberitahuan Privasi|Persetujuan/.test((el.innerText||'').trim())) {
                        let m=el;
                        for (let i=0;i<12&&m.parentElement;i++){ m=m.parentElement;
                            const s=getComputedStyle(m);
                            if ((s.position==='fixed'||s.position==='absolute') && m.offsetWidth>window.innerWidth*0.3){ m.remove(); removed=true; break; }
                        }
                        break;
                    }
                }
                document.body.style.overflow=''; document.documentElement.style.overflow='';
                return removed;
            }"""
        ))
    except Exception:
        return False


def _launch_persistent_with_retry(p, *, headless: bool, slow_mo: int, attempts: int = 6, delay: float = 10.0):
    """Launch the persistent context, retrying if the profile is locked.

    Registration shares the per-puskesmas Chromium profile with the ASIK scrape and
    the sync; two processes cannot open one user-data-dir at once. If another holds
    it, wait and retry rather than fail.
    """
    last_exc: Exception | None = None
    for i in range(attempts):
        try:
            return launch_persistent_context(p, headless=headless, slow_mo=slow_mo)
        except Exception as exc:
            last_exc = exc
            console.print(
                f"[yellow]persistent profile busy (attempt {i + 1}/{attempts}); "
                f"a scrape/sync may be using this puskesmas session — waiting {delay:.0f}s[/yellow]"
            )
            time.sleep(delay)
    raise last_exc  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Small genuine-interaction primitives
#
# All of these click with real Playwright events. `page.evaluate` shows up
# only to READ text or LOCATE elements — never to set a value or fire a
# submit/date/checkbox click (Vue/SurveyJS reject synthetic clicks).
# ---------------------------------------------------------------------------
def _page_text(page: Page) -> str:
    try:
        return page.evaluate("() => document.body.innerText || ''")
    except Exception:
        return ""


def _wait_for_text(page: Page, needles, timeout_ms: int = 15000) -> bool:
    deadline = time.monotonic() + timeout_ms / 1000
    lowered = [n.lower() for n in needles]
    while time.monotonic() < deadline:
        txt = _page_text(page).lower()
        if any(n in txt for n in lowered):
            return True
        page.wait_for_timeout(300)
    return False


def _click_text(page: Page, text: str, *, exact: bool = True, prefer_last: bool = False, timeout: int = 5000) -> bool:
    """Genuine-click the first (or last) VISIBLE element whose text matches."""
    loc = page.get_by_text(text, exact=exact)
    n = loc.count()
    order = range(n - 1, -1, -1) if prefer_last else range(n)
    for i in order:
        el = loc.nth(i)
        try:
            if el.is_visible():
                el.scroll_into_view_if_needed(timeout=2000)
                el.click(timeout=timeout)
                return True
        except Exception:
            continue
    return False


def _click_button_by_text(page: Page, text: str, *, timeout: int = 8000) -> bool:
    """Genuine-click a <button> (or any element) whose exact text is `text`."""
    try:
        b = page.get_by_role("button", name=text, exact=True)
        if b.count() and b.first.is_visible():
            b.first.scroll_into_view_if_needed(timeout=2000)
            b.first.click(timeout=timeout)
            return True
    except Exception:
        pass
    return _click_text(page, text, exact=True, timeout=timeout) or _click_text(page, text, exact=False, timeout=timeout)


def _fill_field(page: Page, locator, value) -> None:
    """Click a text input then type with real keystrokes (Vue per-key validators)."""
    loc = locator.first
    loc.scroll_into_view_if_needed(timeout=3000)
    loc.click(timeout=8000)
    page.keyboard.press("Control+A")
    page.keyboard.press("Delete")
    page.keyboard.type(str(value), delay=20)
    page.wait_for_timeout(150)


# ---------------------------------------------------------------------------
# Step-1 field fills
# ---------------------------------------------------------------------------
def _select_gender(page: Page, gender: str) -> None:
    if not (_click_text(page, "Pilih jenis kelamin", exact=True)
            or _click_text(page, "Pilih jenis kelamin", exact=False)):
        raise RuntimeError("Jenis Kelamin trigger ('Pilih jenis kelamin') not found")
    page.wait_for_timeout(400)
    # The just-rendered option is the LAST exact-text match; the trigger still
    # reads "Pilih jenis kelamin" at this point so there is no self-collision.
    if not _click_text(page, gender, exact=True, prefer_last=True):
        raise RuntimeError(f"Jenis Kelamin option '{gender}' not clickable")
    page.wait_for_timeout(250)


def _parse_ymd(value: str):
    dt = datetime.strptime(value, "%Y-%m-%d")
    return dt.year, dt.month, dt.day


def _mx_cell_texts(page: Page) -> list[str]:
    return page.evaluate(
        """() => Array.from(document.querySelectorAll('.mx-calendar .cell'))
            .filter(c => c.offsetParent !== null)
            .map(c => (c.innerText || '').trim())"""
    ) or []


def _click_mx_cell(page: Page, text: str, *, exclude_other_month: bool = False, timeout: int = 4000) -> None:
    sel = ".mx-calendar .cell:not(.not-current-month)" if exclude_other_month else ".mx-calendar .cell"
    loc = page.locator(sel).filter(has_text=re.compile(rf"^\s*{re.escape(text)}\s*$"))
    loc.first.scroll_into_view_if_needed(timeout=2000)
    loc.first.click(timeout=timeout)


def _open_dob_picker(page: Page) -> bool:
    for locf in (
        lambda: page.get_by_placeholder("Pilih tanggal lahir"),
        lambda: page.locator(".mx-input"),
    ):
        try:
            loc = locf().first
            if loc.count() > 0 and loc.is_visible():
                loc.click(timeout=5000)
                page.wait_for_timeout(400)
                return True
        except Exception:
            continue
    return _click_text(page, "Pilih tanggal lahir", exact=True)


def _pick_mx_date(page: Page, year: int, month: int, day: int) -> None:
    """Drive an ALREADY-OPEN vue2-datepicker (.mx-*) to (year, month, day):
    year(decade) → year → month → day, all genuine clicks. Shared by the DOB picker
    and the 'Data Individu Terdaftar' date filter (same component), so the proven
    navigation lives in one place."""
    # Header year button opens the decade grid.
    page.locator(".mx-btn-current-year").first.click(timeout=4000)
    page.wait_for_timeout(300)

    # Each double-left = -10 years; loop until the target year cell is visible.
    reached = False
    for _ in range(40):
        if str(year) in _mx_cell_texts(page):
            reached = True
            break
        page.locator(".mx-btn-icon-double-left").first.click(timeout=4000)
        page.wait_for_timeout(200)
    if not reached:
        raise RuntimeError(f"year {year} not reachable in the datepicker")
    _click_mx_cell(page, str(year))
    page.wait_for_timeout(300)

    # Month panel.
    month_clicked = False
    for cand in _MX_MONTH_CANDS[month]:
        try:
            _click_mx_cell(page, cand)
            month_clicked = True
            break
        except Exception:
            continue
    if not month_clicked:
        raise RuntimeError(f"month {month} not clickable in the datepicker")
    page.wait_for_timeout(300)

    # Day grid — exclude the greyed prev/next-month cells.
    _click_mx_cell(page, str(day), exclude_other_month=True)
    page.wait_for_timeout(300)


def _pick_dob(page: Page, year: int, month: int, day: int) -> None:
    """Drive the vue2-datepicker: open → year → month → day. All genuine."""
    if not _open_dob_picker(page):
        raise RuntimeError("could not open Tanggal Lahir picker")
    _pick_mx_date(page, year, month, day)

    try:
        shown = page.locator(".mx-input").first.input_value()
        console.print(f"    [dim]DOB field now shows: {shown!r}[/dim]")
        if not (shown or "").strip():
            console.print("    [yellow]DOB field appears empty after picking — continuing[/yellow]")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Tanggal Pemeriksaan (exam-date) — the right calendar of day+quota buttons.
# ---------------------------------------------------------------------------
def _exam_ym(page: Page) -> tuple[int, int] | None:
    """The exam calendar's current (year, month). Its header is a MONTH button ('Agt')
    immediately followed by a YEAR button ('2026') — two separate buttons, not one
    'Agt 2026' string (captured live 2026-08-06). Returns None if not found."""
    res = page.evaluate(
        """(months) => {
            const set = new Set(months);
            const btns = [...document.querySelectorAll('button')].filter(b => b.offsetParent !== null);
            for (const mb of btns) {
                const mt = (mb.innerText || '').trim();
                if (!set.has(mt.toLowerCase())) continue;
                const mr = mb.getBoundingClientRect();
                for (const yb of btns) {
                    if (yb === mb) continue;
                    const yt = (yb.innerText || '').trim();
                    if (!/^\\d{4}$/.test(yt)) continue;
                    const yr = yb.getBoundingClientRect();
                    // year button sits just right of the month button on the same row
                    if (Math.abs(yr.top - mr.top) < 12 && yr.left >= mr.right - 4 && yr.left - mr.right < 40)
                        return { month: mt, year: parseInt(yt, 10) };
                }
            }
            return null;
        }""",
        list(_EXAM_MONTH_LOOKUP.keys()),
    )
    if not res:
        return None
    m = _exam_month_num(res["month"])
    return (res["year"], m) if m else None


def _click_exam_nav(page: Page, forward: bool) -> bool:
    """Click the exam calendar's prev/next month arrow. The two arrows are text-less icon
    buttons GROUPED at the right end of the header row (each wrapping an <svg>), not
    flanking the month text — leftmost = prev month, rightmost = next. Anchor off the
    month button's row, tag the wanted arrow, click it genuinely via Playwright."""
    side = "next" if forward else "prev"
    tagged = page.evaluate(
        """([months, side]) => {
            const set = new Set(months);
            const btns = [...document.querySelectorAll('button')].filter(b => b.offsetParent !== null);
            const anchor = btns.find(b => set.has((b.innerText || '').trim().toLowerCase()));
            if (!anchor) return false;
            const ar = anchor.getBoundingClientRect(), cy = ar.top + ar.height / 2;
            const arrows = btns.filter(b => {
                if ((b.innerText || '').trim() || !b.querySelector('svg')) return false;
                const r = b.getBoundingClientRect();
                if (!r.width || r.width > 34 || r.height > 34) return false;
                return Math.abs((r.top + r.height / 2) - cy) < 22 && (r.left + r.width / 2) > ar.right;
            }).sort((a, b) => a.getBoundingClientRect().left - b.getBoundingClientRect().left);
            if (arrows.length < 2) return false;
            const want = side === 'prev' ? arrows[0] : arrows[arrows.length - 1];
            document.querySelectorAll('[data-ckg-examnav]').forEach(e => e.removeAttribute('data-ckg-examnav'));
            want.setAttribute('data-ckg-examnav', side);
            return true;
        }""",
        [list(_EXAM_MONTH_LOOKUP.keys()), side],
    )
    if not tagged:
        return False
    try:
        page.locator(f"[data-ckg-examnav='{side}']").first.click(timeout=2500)
        return True
    except Exception:
        return False
    finally:
        try:
            page.evaluate(
                "() => document.querySelectorAll('[data-ckg-examnav]').forEach(e => e.removeAttribute('data-ckg-examnav'))"
            )
        except Exception:
            pass


def _navigate_exam_month(page: Page, year: int, month: int) -> bool:
    """Page the exam calendar to (year, month) via the < / > header arrows. Best-effort:
    returns False (caller then books the nearest selectable day) if the header can't be
    read or a click doesn't move the calendar."""
    prev_state = None
    for _ in range(24):
        state = _exam_ym(page)
        if state is None:
            return False
        if state == (year, month):
            return True
        if state == prev_state:  # last click didn't move the calendar → give up
            return False
        prev_state = state
        forward = state < (year, month)
        if not _click_exam_nav(page, forward):
            return False
        page.wait_for_timeout(400)
    return False


def _scan_exam_buttons(page: Page) -> list[dict]:
    """Read exam-day <button>s: first inner span = day, second = quota.

    Returns [{gi, day, quota, disabled}] where `gi` is the button's global
    index among ALL <button>s — identical to `page.locator('button').nth(gi)`
    DOM order, so the caller clicks the exact same element genuinely.
    """
    return page.evaluate(
        """() => {
            const btns = Array.from(document.querySelectorAll('button'));
            const out = [];
            btns.forEach((b, gi) => {
                if (b.offsetParent === null) return;
                const spans = b.querySelectorAll('span');
                if (!spans.length) return;
                const dayTxt = (spans[0].innerText || '').trim();
                if (!/^\\d{1,2}$/.test(dayTxt)) return;
                const day = parseInt(dayTxt, 10);
                if (day < 1 || day > 31) return;
                let quota = null;
                if (spans.length >= 2) {
                    const q = (spans[1].innerText || '').trim();
                    if (/^\\d+$/.test(q)) quota = parseInt(q, 10);
                }
                out.push({ gi, day, quota, disabled: b.disabled === true || b.getAttribute('disabled') !== null });
            });
            return out;
        }"""
    ) or []


def _click_exam_day(page: Page, target_day: int) -> dict:
    """Genuine-click the exam-date button for `target_day`.

    The EXACT requested day wins even when its quota is 0 — a full day is still
    registrable by confirming the "Kuota Pemeriksaan Habis" popup (handled in
    _read_outcome). Only quota, NOT clickability, is 0 on such a day; picking a
    different date instead silently books the patient under the wrong Tanggal
    Pemeriksaan (the exact bug that broke the past-date create: day 18 quota 0 got
    booked as day 20 quota 40, so Konfirmasi Hadir — filtered by 18 — found no row).

    Fall back to the nearest day ONLY when the requested day isn't clickable at all
    (a greyed date), preferring a fallback that still has quota."""
    cands = _scan_exam_buttons(page)
    if not cands:
        raise RuntimeError("no exam-date day buttons found")

    def clickable(c: dict) -> bool:  # greyed/disabled days can't be clicked; quota 0 CAN
        return not c["disabled"]

    def has_quota(c: dict) -> bool:
        return c["quota"] is None or c["quota"] > 0

    # 1. The requested day if it's clickable — even at quota 0 (Kuota-Habis confirm).
    pick = next((c for c in cands if c["day"] == target_day and clickable(c)), None)
    if pick is None:
        # 2. Requested day not clickable → nearest clickable day, quota-bearing first.
        clickables = [c for c in cands if clickable(c)]
        pool = [c for c in clickables if has_quota(c)] or clickables
        if pool:
            pick = min(pool, key=lambda c: abs(c["day"] - target_day))
            console.print(
                f"    [yellow]exam day {target_day} not clickable; using nearest "
                f"day {pick['day']} (quota={pick['quota']})[/yellow]"
            )
    if pick is None:
        # 3. Last resort: the exact day regardless, else the very first candidate.
        pick = next((c for c in cands if c["day"] == target_day), None) or cands[0]

    page.locator("button").nth(pick["gi"]).scroll_into_view_if_needed(timeout=2000)
    page.locator("button").nth(pick["gi"]).click(timeout=5000)
    return pick


def _handle_kuota_habis(page: Page) -> bool:
    if "kuota pemeriksaan habis" in _page_text(page).lower():
        console.print("    [yellow]'Kuota Pemeriksaan Habis' modal — clicking 'Lanjut'[/yellow]")
        try:
            _click_button_by_text(page, "Lanjut")
            page.wait_for_timeout(600)
            return True
        except Exception:
            return False
    return False


def _exam_nav_debug(page: Page) -> str:
    """Logged only when month-navigation fails: the exam calendar's header band (the
    month/year buttons + the < / > arrow buttons above the day grid). This is the
    fragile step most likely to break if ASIK changes the calendar markup — the dump
    shows exactly what the header row looks like so the arrow-locating can be re-fitted."""
    try:
        info = page.evaluate(
            """() => {
                const vis = e => e.offsetParent !== null;
                // Anchor on the day grid: buttons with span0 = 1-2 digit day, span1 = quota.
                const days = [...document.querySelectorAll('button')].filter(b => {
                    if (!vis(b)) return false;
                    const s = b.querySelectorAll('span');
                    return s.length >= 2 && /^\\d{1,2}$/.test((s[0].innerText||'').trim()) && /^\\d+$/.test((s[1].innerText||'').trim());
                });
                if (!days.length) return { note: 'no day+quota buttons found' };
                const rects = days.map(b => b.getBoundingClientRect());
                const top = Math.min(...rects.map(r => r.top));
                const left = Math.min(...rects.map(r => r.left)), right = Math.max(...rects.map(r => r.right));
                const header = [...document.querySelectorAll('button,svg,i')].filter(e => {
                    if (!vis(e)) return false;
                    const r = e.getBoundingClientRect();
                    if (!r.width || r.width > 360) return false;
                    const cy = r.top + r.height/2, cx = r.left + r.width/2;
                    return cy < top && cy > top - 120 && cx > left - 40 && cx < right + 40;
                }).map(e => ({tag: e.tagName.toLowerCase(), cls: (e.className||'').toString().slice(0,32),
                              txt: (e.innerText||'').trim().slice(0,12), x: Math.round(e.getBoundingClientRect().left)}))
                  .slice(0, 20);
                return { days: days.length, header };
            }"""
        )
        return json.dumps(info, ensure_ascii=False)[:900]
    except Exception as exc:
        return f"debug-failed: {exc}"


def _pick_exam_date(page: Page, exam_date: str) -> dict:
    try:
        y, m, d = _parse_ymd(exam_date)
    except Exception:
        now = datetime.now()
        y, m, d = now.year, now.month, now.day
    ym_before = _exam_ym(page)
    navigated = _navigate_exam_month(page, y, m)  # best-effort
    pick = _click_exam_day(page, d)
    console.print(
        f"    exam-date: requested {y}-{m:02d}-{d:02d} | calendar {ym_before} -> "
        f"{_exam_ym(page)} | navigated={navigated} picked day={pick.get('day')}"
    )
    if not navigated:
        console.print(f"    [yellow]exam-nav did not reach the target month; calendar={_exam_nav_debug(page)}[/yellow]")
    # NOTE: for a past/full date the "Kuota Pemeriksaan Habis" confirm does NOT appear
    # here — it appears after 'Selanjutnya' and is handled in _read_outcome.
    page.wait_for_timeout(400)
    return pick


# ---------------------------------------------------------------------------
# Wali section + Selanjutnya
# ---------------------------------------------------------------------------
def _maybe_skip_wali(page: Page) -> bool:
    """Adults have no wali section. When present (lansia/balita), tick the
    'Daftarkan tanpa data wali' CHECKBOX to skip it.

    It is a CUSTOM checkbox: clicking the label *text* does NOT toggle the
    underlying input (verified live). The input must be clicked genuinely.
    Checkbox order when the wali section is present:
      [0] Tidak punya NIK, [1] Daftarkan tanpa data wali, [2] Nomor sama dengan peserta
    """
    txt = _page_text(page).lower()
    if "isi data wali" not in txt and "daftarkan tanpa data wali" not in txt:
        return False
    console.print("    Wali section present — ticking 'Daftarkan tanpa data wali'")
    cb = page.locator("input[type=checkbox]").nth(1)
    try:
        cb.scroll_into_view_if_needed(timeout=2000)
    except Exception:
        pass
    for attempt in range(2):
        try:
            if cb.is_checked():
                break
            cb.click(force=True, timeout=4000)
        except Exception:
            try:
                cb.check(force=True, timeout=3000)
            except Exception:
                pass
        page.wait_for_timeout(400)
    ok = False
    try:
        ok = cb.is_checked()
    except Exception:
        pass
    if not ok:
        console.print("    [yellow]wali checkbox did not register as checked[/yellow]")
    page.wait_for_timeout(300)
    return ok


def _click_selanjutnya(page: Page) -> bool:
    """Genuine-click the styled DIV whose exact text is 'Selanjutnya' and that
    is enabled (computed cursor != 'not-allowed'). `get_by_text(exact)` already
    resolves to the leaf, so there is no need to reject parents with a same-text
    child."""
    loc = page.get_by_text("Selanjutnya", exact=True)
    n = loc.count()
    for i in range(n):
        el = loc.nth(i)
        try:
            if not el.is_visible():
                continue
            cursor = el.evaluate("e => getComputedStyle(e).cursor")
            if cursor == "not-allowed":
                continue
            el.scroll_into_view_if_needed(timeout=3000)
            el.click(timeout=5000)
            return True
        except Exception:
            continue
    return False


# ---------------------------------------------------------------------------
# Outcome reading after Selanjutnya
# ---------------------------------------------------------------------------
def _extract_served_detail(page: Page) -> str | None:
    return page.evaluate(
        """() => {
            for (const el of document.querySelectorAll('div,section,p')) {
                const t = (el.innerText || '').trim();
                if (/sudah menerima layanan/i.test(t) && t.length < 600) return t;
            }
            return null;
        }"""
    )


def _read_outcome(page: Page, timeout_ms: int = 8000):
    """Return (outcome, served_detail) after Selanjutnya. Polls because the
    guard modal / step-2 render arrives a beat after the click."""
    deadline = time.monotonic() + timeout_ms / 1000
    lanjut_clicked = False
    kuota_handled = False
    while time.monotonic() < deadline:
        low = _page_text(page).lower()
        if "sudah menerima layanan" in low:
            return "already_served", _extract_served_detail(page)
        if "tidak valid" in low:
            return "dukcapil_invalid", None
        # Past / full exam date → "Kuota Pemeriksaan Habis" confirm gates the flow;
        # click its "Lanjut" (NOT "Pilih Tanggal Lain") to proceed, then keep polling.
        # It appears BEFORE the Dukcapil "Data peserta valid" gate, so handle it first.
        if not kuota_handled and _handle_kuota_habis(page):
            kuota_handled = True
            deadline = time.monotonic() + timeout_ms / 1000  # fresh window
            page.wait_for_timeout(1200)
            continue
        # Dukcapil OK → a "Data peserta valid" modal gates step 2 behind a
        # "Lanjutkan" button; click it once, then keep polling for step-2 markers.
        if not lanjut_clicked and "data peserta valid" in low:
            if _click_button_by_text(page, "Lanjutkan"):
                lanjut_clicked = True
                deadline = time.monotonic() + timeout_ms / 1000  # fresh window for step-2 render
                page.wait_for_timeout(1200)
                continue
        if any(m in low for m in _STEP2_MARKERS):
            return "would_create", None
        page.wait_for_timeout(300)
    # Could not classify — dump the actual page so we can see what it landed on.
    try:
        body = _page_text(page)
        console.print(f"[red]NO-OUTCOME page text (first 1500):[/red]\n{body[:1500]}")
        heads = page.evaluate(
            """() => Array.from(document.querySelectorAll('h1,h2,h3,button,[role=dialog]'))
                .map(e => (e.innerText||'').trim()).filter(t => t && t.length < 80).slice(0, 25)"""
        )
        console.print(f"[red]NO-OUTCOME headings/buttons:[/red] {json.dumps(heads)[:600]}")
        SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
        shot = SCREENSHOT_DIR / "register_no_outcome.png"
        page.screenshot(path=str(shot), full_page=True)
        console.print(f"    no-outcome screenshot: {shot}")
    except Exception:
        pass
    raise RuntimeError("could not determine outcome after Selanjutnya (no guard, no step-2 markers)")


# ---------------------------------------------------------------------------
# Step-2 structure capture (dry-run probe only)
# ---------------------------------------------------------------------------
def _read_open_options(page: Page) -> list[str]:
    return page.evaluate(
        """() => {
            const sels = ['[role=option]','.sv-list__item','.sd-list__item','li','.option',
                          '.dropdown-item','.select-option','.ant-select-item','.el-select-dropdown__item'];
            const out = []; const seen = new Set();
            for (const s of sels) {
                for (const el of document.querySelectorAll(s)) {
                    if (el.offsetParent === null) continue;
                    const t = (el.innerText || '').trim();
                    if (t && t.length < 120 && !seen.has(t)) { seen.add(t); out.push(t); }
                }
            }
            return out.slice(0, 400);
        }"""
    ) or []


def _probe_dropdown(page: Page, candidates: list[str]) -> dict:
    """Open a step-2 dropdown by its (default/placeholder) trigger text, read
    the option strings, then close it. Non-committing."""
    info = {"trigger_text": None, "opened": False, "options": [], "has_search_input": False}
    trigger = None
    for c in candidates:
        loc = page.get_by_text(c, exact=True)
        for i in range(loc.count()):
            el = loc.nth(i)
            try:
                if el.is_visible():
                    trigger = el
                    info["trigger_text"] = c
                    break
            except Exception:
                continue
        if trigger:
            break
    if not trigger:
        return info
    try:
        trigger.scroll_into_view_if_needed(timeout=3000)
        trigger.click(timeout=3000)
        info["opened"] = True
        page.wait_for_timeout(400)
        info["options"] = _read_open_options(page)
        info["has_search_input"] = bool(page.evaluate(
            """() => Array.from(document.querySelectorAll('input'))
                .some(i => i.offsetParent !== null && /cari|search/i.test((i.getAttribute('placeholder')||'')))"""
        ))
    except Exception as e:
        info["error"] = str(e)
    finally:
        try:
            page.keyboard.press("Escape")
        except Exception:
            pass
        page.wait_for_timeout(200)
    return info


def _probe_alamat(page: Page) -> dict:
    """Click the Alamat Domisili control and capture what it reveals — a plain
    options list, a searchable input, or a province/kab/kec/kel cascade."""
    info = {
        "trigger_found": False, "trigger_text": None, "opened": False,
        "revealed_texts": [], "has_search_input": False,
        "region_hints": None, "revealed_html": None,
    }
    trigger = None
    for c in ["Pilih alamat domisili", "Pilih Alamat Domisili", "Alamat Domisili"]:
        loc = page.get_by_text(c, exact=True)
        for i in range(loc.count()):
            el = loc.nth(i)
            try:
                if el.is_visible():
                    trigger = el
                    info["trigger_found"] = True
                    info["trigger_text"] = c
                    break
            except Exception:
                continue
        if trigger:
            break
    if not trigger:
        return info
    try:
        trigger.scroll_into_view_if_needed(timeout=3000)
        trigger.click(timeout=3000)
        info["opened"] = True
        page.wait_for_timeout(500)
        info["revealed_texts"] = _read_open_options(page)
        info["has_search_input"] = bool(page.evaluate(
            """() => Array.from(document.querySelectorAll('input'))
                .filter(i => i.offsetParent !== null)
                .some(i => /cari|search|alamat|provinsi|kab|kec|kel/i.test((i.getAttribute('placeholder')||'')))"""
        ))
        info["region_hints"] = page.evaluate(
            """() => {
                const t = (document.body.innerText || '').toLowerCase();
                return {
                    provinsi: t.includes('provinsi'),
                    kabupaten: t.includes('kabupaten') || t.includes('kota'),
                    kecamatan: t.includes('kecamatan'),
                    kelurahan: t.includes('kelurahan') || t.includes('desa'),
                };
            }"""
        )
        info["revealed_html"] = page.evaluate(
            """() => {
                const nodes = Array.from(document.querySelectorAll(
                    '[role=listbox],[role=dialog],.dropdown,.menu,.popup,[class*=dropdown],[class*=popover]'
                )).filter(e => e.offsetParent !== null);
                nodes.sort((a, b) => (b.innerText || '').length - (a.innerText || '').length);
                return nodes.length ? nodes[0].outerHTML.slice(0, 12000) : null;
            }"""
        )
    except Exception as e:
        info["error"] = str(e)
    finally:
        try:
            page.keyboard.press("Escape")
        except Exception:
            pass
        page.wait_for_timeout(200)
    return info


def _capture_step2(page: Page) -> dict:
    """Dump the step-2 form structure for offline selector design. Reads labels
    + a trimmed container HTML, and probes each dropdown + the alamat control."""
    out: dict = {}
    out["labels"] = page.evaluate(
        """() => {
            const set = []; const seen = new Set();
            for (const el of document.querySelectorAll('label, .label, p, span, div')) {
                if (el.children.length !== 0) continue;
                const t = (el.innerText || '').trim();
                if (t && t.length < 80 && el.offsetParent !== null && !seen.has(t)) { seen.add(t); set.push(t); }
            }
            return set.slice(0, 300);
        }"""
    )
    out["container_html"] = page.evaluate(
        """() => {
            let node = null;
            for (const el of document.querySelectorAll('*')) {
                if ((el.innerText || '').includes('Status Pernikahan')) node = el;
            }
            if (!node) return null;
            let p = node;
            for (let i = 0; i < 8 && p && p.parentElement; i++) {
                if ((p.innerText || '').length > 400) break;
                p = p.parentElement;
            }
            return p ? p.outerHTML.slice(0, 20000) : null;
        }"""
    )
    out["dropdowns"] = {
        "Status Pernikahan": _probe_dropdown(
            page, ["Belum Menikah", "Pilih status pernikahan", "Pilih status"]),
        "Penyandang disabilitas": _probe_dropdown(
            page, ["Tidak memiliki disabilitas", "Pilih disabilitas", "Pilih penyandang disabilitas"]),
        "Pekerjaan": _probe_dropdown(page, ["Pilih pekerjaan"]),
    }
    out["alamat"] = _probe_alamat(page)
    out["detail_alamat"] = page.evaluate(
        """() => {
            const ta = Array.from(document.querySelectorAll('textarea')).find(t => t.offsetParent !== null);
            return ta ? { present: true, placeholder: ta.getAttribute('placeholder') || null } : { present: false };
        }"""
    )
    return out


def _screenshot(page: Page, nik: str) -> str | None:
    try:
        SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
        path = SCREENSHOT_DIR / f"register_{nik}_{int(time.time())}.png"
        page.screenshot(path=str(path), full_page=True)
        return str(path)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Step-2 fill (live path) — "Isi data pendukung"
#
# Structure captured live 2026-08-06 (documents/create-patient-asik/FINDINGS.md
# §Step2): Status Pernikahan + Penyandang disabilitas are gender-style custom
# dropdowns; Pekerjaan is a searchable modal; Alamat Domisili is a 4-level
# Provinsi→Kota→Kecamatan→Kelurahan cascade (each a searchable list, async-
# loaded); Detail Alamat Domisili is a free-text textarea. NOTHING here commits —
# the commit ("Daftarkan") lives on step 3, which is a separate (later) step.
# ---------------------------------------------------------------------------
_DEFAULT_DISABILITAS = "Tidak memiliki disabilitas"


def _select_step2_dropdown(page: Page, trigger_text: str, value: str) -> None:
    """Open a gender-style custom dropdown by its current/placeholder text and
    click the wanted option (prefer_last dodges the trigger self-collision)."""
    if not (_click_text(page, trigger_text, exact=True)
            or _click_text(page, trigger_text, exact=False)):
        raise RuntimeError(f"step-2 dropdown trigger '{trigger_text}' not found")
    page.wait_for_timeout(400)
    if not _click_text(page, value, exact=True, prefer_last=True):
        raise RuntimeError(f"step-2 option '{value}' not clickable")
    page.wait_for_timeout(250)


def _select_pekerjaan(page: Page, value: str) -> None:
    """Pekerjaan is a modal picker with a search box; search then click."""
    if not (_click_text(page, "Pilih pekerjaan", exact=True)
            or _click_text(page, "Pilih pekerjaan", exact=False)):
        raise RuntimeError("Pekerjaan trigger ('Pilih pekerjaan') not found")
    page.wait_for_timeout(500)
    search = page.get_by_placeholder("Cari pekerjaan")
    if search.count():
        _fill_field(page, search, value)
        page.wait_for_timeout(500)
    if not _click_text(page, value, exact=True, prefer_last=True):
        raise RuntimeError(f"Pekerjaan option '{value}' not found")
    page.wait_for_timeout(300)


def _pick_location_level(page: Page, search_placeholder: str, name: str) -> None:
    """One level of the Alamat cascade: type the name into this level's search
    box, wait for the async list, then click the exact-name option. prefer_last
    picks the list row over the same-named breadcrumb of the parent selection."""
    search = page.get_by_placeholder(search_placeholder)
    if not search.count():
        raise RuntimeError(f"location search box '{search_placeholder}' not found")
    _fill_field(page, search, name)
    page.wait_for_timeout(1200)  # per-level list is fetched async ("Memuat data..")
    if not _click_text(page, name, exact=True, prefer_last=True):
        raise RuntimeError(f"location '{name}' not found under '{search_placeholder}'")
    page.wait_for_timeout(1000)


def _fill_alamat_cascade(page: Page, provinsi: str, kota: str, kecamatan: str, kelurahan: str) -> None:
    if not (_click_text(page, "Pilih alamat domisili", exact=True)
            or _click_text(page, "Pilih alamat domisili", exact=False)):
        raise RuntimeError("Alamat Domisili trigger ('Pilih alamat domisili') not found")
    page.wait_for_timeout(600)
    _pick_location_level(page, "Cari Provinsi", provinsi)
    _pick_location_level(page, "Cari Kabupaten/Kota", kota)
    _pick_location_level(page, "Cari Kecamatan", kecamatan)
    _pick_location_level(page, "Cari Kelurahan", kelurahan)  # closes the modal + fills the field


def _fill_detail_alamat(page: Page, text: str) -> None:
    ta = page.locator("textarea")
    if ta.count() and text:
        _fill_field(page, ta, text)


def _fill_step2(page: Page, step2: dict) -> None:
    """Fill the 5 step-2 fields from the assembled values. Raises on a missing
    required value or an un-clickable control — the caller treats that as error."""
    for key in ("status_pernikahan", "pekerjaan", "alamat", "detail_alamat"):
        if key not in step2:
            raise RuntimeError(f"step2 config missing '{key}'")
    alamat = step2["alamat"]
    for lvl in ("provinsi", "kota", "kecamatan", "kelurahan"):
        if not alamat.get(lvl):
            raise RuntimeError(f"step2 alamat missing '{lvl}'")

    console.print("    · Status Pernikahan")
    _select_step2_dropdown(page, "Pilih status pernikahan", step2["status_pernikahan"])

    disabilitas = step2.get("disabilitas") or _DEFAULT_DISABILITAS
    if disabilitas != _DEFAULT_DISABILITAS:
        console.print("    · Penyandang disabilitas")
        _select_step2_dropdown(page, _DEFAULT_DISABILITAS, disabilitas)

    console.print("    · Pekerjaan")
    _select_pekerjaan(page, step2["pekerjaan"])

    console.print("    · Alamat Domisili (cascade)")
    _fill_alamat_cascade(page, alamat["provinsi"], alamat["kota"], alamat["kecamatan"], alamat["kelurahan"])

    console.print("    · Detail Alamat Domisili")
    _fill_detail_alamat(page, step2["detail_alamat"])


# ---------------------------------------------------------------------------
# Step 3 (commit) + Konfirmasi Hadir — the LIVE create path (gated by reg.commit)
# ---------------------------------------------------------------------------
# Step 3 "List Data Individu" was captured live 2026-08-06 (NIK 3275044303030016):
# a table (NIK | Nama Individu | Tgl Lahir | Jenis Kelamin | Aksi) → click "Pilih"
# on our NIK's row (button flips to "Dipilih") → "Daftarkan dengan NIK" enables →
# clicking it COMMITS → success modal "Berhasil Daftar / No. Tiket: <XXX>" (e.g.
# "JTN-QAD") → "Tutup". Mulai Pemeriksaan + the exam fill are NOT done here — the
# existing sync.py scraper owns them; this flow only needs the patient registered
# + marked hadir so they surface in /ckg-pelayanan "Belum Pemeriksaan".
def _read_ticket(page: Page) -> str | None:
    """Read 'No. Tiket: <XXX>' from the Berhasil Daftar success modal."""
    m = re.search(r"No\.?\s*Tiket\s*[:：]?\s*([A-Z0-9][A-Z0-9\-]{2,})", _page_text(page))
    return m.group(1) if m else None


def _step3_select_and_commit(page: Page, nik: str) -> str | None:
    """From step 2, advance to step 3, select our NIK's row, and click 'Daftarkan
    dengan NIK' (THE commit). Returns the success ticket. Raises before the final
    Daftarkan click if any stage is missing, so a failure never half-commits."""
    console.print("[bold cyan]Step 10: Selanjutnya → List Data Individu[/bold cyan]")
    if not _click_selanjutnya(page):
        raise RuntimeError("step-2 'Selanjutnya' (to step 3) not clickable")
    if not _wait_for_text(page, ["List Data Individu"], timeout_ms=15000):
        raise RuntimeError("step-3 'List Data Individu' not shown after Selanjutnya")
    page.wait_for_timeout(800)

    console.print("[bold cyan]Step 11: Pilih matching individu[/bold cyan]")
    picked = False
    try:
        row = page.locator("tr").filter(has_text=nik)
        if row.count():
            btn = row.get_by_role("button", name=re.compile("Pilih", re.I))
            if btn.count():
                btn.first.click()
                picked = True
    except Exception:
        picked = False
    if not picked and not _click_text(page, "Pilih", exact=True):
        # Fallback only safe when a single Pilih is on screen (filter → one row).
        raise RuntimeError(f"step-3 'Pilih' for NIK {nik} not found")
    page.wait_for_timeout(1000)

    console.print("[bold cyan]Step 12: Daftarkan dengan NIK (COMMIT)[/bold cyan]")
    if not _click_button_by_text(page, "Daftarkan dengan NIK"):
        raise RuntimeError("'Daftarkan dengan NIK' not clickable (row not selected?)")
    if not _wait_for_text(page, ["Berhasil Daftar", "No. Tiket"], timeout_ms=20000):
        raise RuntimeError("no 'Berhasil Daftar' confirmation after Daftarkan")
    ticket = _read_ticket(page)
    console.print(f"    committed — ticket = [bold]{ticket}[/bold]")
    # Close the success modal. Do NOT click 'Bantu Isi Skrining Mandiri'.
    _click_button_by_text(page, "Tutup", timeout=5000)
    page.wait_for_timeout(1200)
    return ticket


def _set_terdaftar_date_filter(page: Page, exam_date: str) -> bool:
    """Set the 'Data Individu Terdaftar' date filter (an .mx-datepicker that DEFAULTS TO
    TODAY) to `exam_date` (ISO). VERIFIED LIVE 2026-08-06: both the Terdaftar list AND the
    'Masukkan nomor tiket' search are scoped to this filter — a patient registered for a
    PAST exam date is otherwise invisible (the ticket search returns 'Terdaftar pada
    tanggal lain'). Reuses the same .mx-* navigation as the DOB picker. Best-effort:
    returns False (with a diagnostic) if the picker can't be opened/driven."""
    try:
        y, m, d = _parse_ymd(exam_date)
    except Exception:
        return False
    opened = False
    for sel in (
        ".mx-datepicker .mx-input-wrapper",
        ".mx-datepicker .mx-icon-calendar",
        ".mx-datepicker",
    ):
        try:
            loc = page.locator(sel).first
            if loc.count():
                loc.scroll_into_view_if_needed(timeout=2000)
                loc.click(timeout=4000)
                page.wait_for_timeout(600)
                cal = page.locator(".mx-calendar")
                if cal.count() and cal.first.is_visible():
                    opened = True
                    break
        except Exception:
            continue
    if not opened:
        console.print("    [yellow]Terdaftar date-filter picker did not open[/yellow]")
        return False
    try:
        _pick_mx_date(page, y, m, d)
        page.wait_for_timeout(1400)  # the list re-fetches for the selected date
        console.print(f"    Terdaftar date filter set to {exam_date}")
        return True
    except Exception as exc:
        console.print(f"    [yellow]Terdaftar date-filter set failed: {exc}[/yellow]")
        return False


def _dump_terdaftar(page: Page) -> None:
    """Diagnostic: log the visible Terdaftar rows + a screenshot when a row isn't found."""
    try:
        rows = page.evaluate(
            """() => Array.from(document.querySelectorAll('tr'))
                .filter(r => r.offsetParent !== null)
                .map(r => (r.innerText || '').replace(/\\s+/g, ' ').trim())
                .filter(t => t.length > 3).slice(0, 15)"""
        )
        console.print(f"    [dim]Terdaftar rows: {json.dumps(rows, ensure_ascii=False)[:800]}[/dim]")
        SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
        shot = SCREENSHOT_DIR / f"konfirmasi_hadir_no_row_{int(time.time())}.png"
        page.screenshot(path=str(shot), full_page=True)
        console.print(f"    no-row screenshot: {shot}")
    except Exception:
        pass


def _search_terdaftar_by_nik(page: Page, nik: str) -> None:
    """Narrow the (already date-scoped) 'Data Individu Terdaftar' list to one NIK —
    needed only when a day's registrations paginate past the first view. The
    search-type control is a CUSTOM Vue dropdown (not a <select>): its trigger shows
    the current type ('Nomor Tiket' by default). Click it, pick 'NIK', then type the
    NIK into `#searchNik` (STABLE id — the placeholder changes with the type, the id
    does not; verified live 2026-08-19). Best-effort: a failure just leaves the list
    as-is for the caller's row scan."""
    try:
        for cur in ("Nomor Tiket", "Nama", "No. Tiket"):
            trig = page.get_by_text(cur, exact=True)
            if trig.count() and trig.first.is_visible():
                trig.first.click(timeout=3000)
                page.wait_for_timeout(400)
                opt = page.get_by_text("NIK", exact=True)  # last match = the dropdown item
                for j in range(opt.count() - 1, -1, -1):
                    o = opt.nth(j)
                    try:
                        if o.is_visible():
                            o.click(timeout=3000)
                            break
                    except Exception:
                        continue
                break
        page.wait_for_timeout(400)
        box = page.locator("#searchNik")
        box.fill(nik, timeout=5000)
        page.keyboard.press("Enter")
        page.wait_for_timeout(1600)
    except Exception as exc:
        console.print(f"    [yellow]Terdaftar NIK-search (fallback) failed: {exc}[/yellow]")


def _konfirmasi_hadir(
    page: Page, base_url: str, nama: str, nik: str, ticket: str | None,
    exam_date: str | None = None,
) -> bool:
    """Mark the just-registered patient 'hadir' so they surface in /ckg-pelayanan
    'Belum Pemeriksaan', where the existing sync.py fill picks them up.

    Navigates FRESH to 'Data Individu Terdaftar' first. The post-commit page carries a
    residual 'Berhasil Daftar' success-modal backdrop that intercepts the date-filter
    click — verified live 2026-08-19: a fresh load opens the .mx-datepicker cleanly
    (overlays=0) while the post-commit page did not, so the filter stayed on TODAY and a
    past-date registration was invisible ('picker did not open' → no row).

    The list is DATE-SCOPED (defaults to today), so the filter is set to `exam_date`
    first; the day's registrations then render directly and we locate the row by name
    (the list shows Nama/Tgl Lahir but no NIK). A NIK search narrows a paginated day.
    On the row: 'Konfirmasi Hadir' → the 'Tandai Hadir?' popup → tick consent #verify →
    'Hadir' (the popup's confirm; NOT 'Konfirmasi Hadir'). Returns True on apparent success."""
    try:
        # Fresh load ⇒ clean state (no post-commit modal backdrop over the datepicker).
        page.goto(base_url + REGISTER_PATH, wait_until="domcontentloaded")
        page.wait_for_timeout(2000)
        try:
            close_popups(page)
        except Exception:
            pass
        page.wait_for_timeout(500)

        if exam_date:
            _set_terdaftar_date_filter(page, exam_date)
        # Date-scoped list now shows the day's registrations directly — locate our row.
        row = page.locator("tr").filter(has_text=nama)
        if not row.count():
            _search_terdaftar_by_nik(page, nik)  # paginated day → narrow to one NIK
            row = page.locator("tr").filter(has_text=nama)
        if not row.count():
            console.print(
                f"    [yellow]Konfirmasi Hadir: no row for '{nama}' "
                f"(date filter={exam_date}, nik={nik})[/yellow]"
            )
            _dump_terdaftar(page)
            return False
        # Already attended? Then we're done.
        if row.filter(has_text=re.compile("Sudah Hadir", re.I)).count():
            console.print(f"    [green]row for '{nama}' already 'Sudah Hadir'[/green]")
            return True
        btn = row.get_by_role("button", name=re.compile("Konfirmasi Hadir", re.I))
        if not btn.count():
            console.print("    [yellow]Konfirmasi Hadir: row found but no 'Konfirmasi Hadir' button[/yellow]")
            _dump_terdaftar(page)
            return False
        btn.first.click()
        page.wait_for_timeout(1500)
        # 'Tandai Hadir?' popup: tick consent (#verify), then click the enabled 'Hadir'.
        cb = page.locator("#verify")
        (cb.first if cb.count() else page.locator("input[type=checkbox]").last).check(force=True)
        page.wait_for_timeout(400)
        hadir = page.get_by_role("button", name="Hadir", exact=True)
        if not hadir.count():
            console.print("    [yellow]'Hadir' confirm button not found in 'Tandai Hadir?' popup[/yellow]")
            return False
        hadir.first.click()
        page.wait_for_timeout(1500)
        return True
    except Exception as exc:
        console.print(f"[yellow]Konfirmasi Hadir failed: {exc}[/yellow]")
        return False


# ---------------------------------------------------------------------------
# The registration flow (step 1 + dry-run probe of step 2)
# ---------------------------------------------------------------------------
def _register_flow(page: Page, base_url: str, reg: dict, dry_run_probe: bool):
    """Returns (outcome, served_detail, step2_dom, screenshot_path)."""
    nik = reg["nik"]

    console.print("\n[bold cyan]Step 2: Open Cari/Daftarkan Individu[/bold cyan]")
    page.goto(base_url + REGISTER_PATH, wait_until="domcontentloaded")
    page.wait_for_timeout(2500)
    close_popups(page, silent=True)
    _dismiss_consent_modal(page)
    page.wait_for_timeout(500)

    console.print("[bold cyan]Step 3: Daftar Baru → Formulir Pendaftaran[/bold cyan]")
    if not _click_button_by_text(page, "Daftar Baru"):
        raise RuntimeError("could not click 'Daftar Baru'")
    page.wait_for_timeout(1500)
    if not _wait_for_text(page, ["Formulir Pendaftaran", "Isi identitas", "Isi Identitas"], timeout_ms=15000):
        console.print("[yellow]'Formulir Pendaftaran' modal not confirmed by text — proceeding[/yellow]")

    console.print("[bold cyan]Step 4: Fill identitas[/bold cyan]")
    _fill_field(page, page.locator("#nik"), nik)                                   # NIK
    _fill_field(page, page.get_by_placeholder("Masukkan nama lengkap"), reg["nama"])   # Nama Lengkap
    _fill_field(page, page.get_by_placeholder("Masukkan nomor whatsapp"), reg["whatsapp"])  # No. Whatsapp
    _select_gender(page, reg["gender"])                                            # Jenis Kelamin

    console.print("[bold cyan]Step 5: Tanggal Lahir (vue2-datepicker)[/bold cyan]")
    y, m, d = _parse_ymd(reg["dob"])
    _pick_dob(page, y, m, d)

    console.print("[bold cyan]Step 6: Tanggal Pemeriksaan[/bold cyan]")
    pick = _pick_exam_date(page, reg["exam_date"])
    console.print(f"    picked exam day={pick.get('day')} quota={pick.get('quota')}")

    _maybe_skip_wali(page)

    console.print("[bold cyan]Step 7: Selanjutnya[/bold cyan]")
    if not _click_selanjutnya(page):
        diag = page.evaluate(
            """() => {
                const inputs = Array.from(document.querySelectorAll('input,textarea'))
                    .filter(i => i.offsetParent !== null && i.type !== 'checkbox')
                    .map(i => ({ph: i.placeholder || i.id, val: (i.value||'').slice(0,20)}));
                const cbs = Array.from(document.querySelectorAll('input[type=checkbox]'))
                    .map(c => c.checked);
                const disp = Array.from(document.querySelectorAll('div'))
                    .map(d => (d.textContent||'').trim())
                    .filter(t => /^(Laki-laki|Perempuan|\\d{1,2}\\s\\w{3}\\s\\d{4})$/.test(t));
                const errs = Array.from(document.querySelectorAll('*'))
                    .filter(e => e.children.length===0 && /wajib diisi|tidak valid/i.test(e.textContent||''))
                    .map(e => e.textContent.trim().slice(0,40));
                const waliShown = /Isi Data Wali/i.test(document.body.innerText);
                return {inputs, checkboxes: cbs, displays: [...new Set(disp)].slice(0,4),
                        errors: [...new Set(errs)], waliShown};
            }"""
        )
        console.print(f"[red]Selanjutnya-disabled DIAG:[/red] {json.dumps(diag)[:600]}")
        try:
            page.screenshot(path=str(SCREENSHOT_DIR / "register_selanjutnya_disabled.png"), full_page=True)
            console.print(f"    diag screenshot: {SCREENSHOT_DIR / 'register_selanjutnya_disabled.png'}")
        except Exception:
            pass
        raise RuntimeError("'Selanjutnya' not clickable (still disabled — a field likely did not register)")
    page.wait_for_timeout(2500)

    console.print("[bold cyan]Step 8: Read outcome[/bold cyan]")
    outcome, served_detail = _read_outcome(page)
    console.print(f"    outcome = [bold]{outcome}[/bold]")
    if served_detail:
        console.print(f"    served: {served_detail[:200]}")

    step2_dom = None
    shot = _screenshot(page, nik)
    extra: dict = {}

    if outcome == "would_create":
        if dry_run_probe:
            console.print("[bold cyan]Step 9: Capture step-2 structure (dry-run probe) — NO commit[/bold cyan]")
            step2_dom = _capture_step2(page)
            # Re-screenshot after the probe (dropdowns closed again).
            shot = _screenshot(page, nik) or shot
            # STOP here — nothing that commits is clicked (no "Daftarkan dengan
            # NIK", no "Selesai").
        else:
            # LIVE path: fill step 2 ("Isi data pendukung") from the assembled
            # values. Then either STOP (commit disabled) at outcome "step2_filled",
            # or proceed through step 3 (Daftarkan dengan NIK = THE COMMIT) +
            # best-effort Konfirmasi Hadir → outcome "created".
            step2 = reg.get("step2")
            if not step2:
                raise RuntimeError("live mode requires reg.step2 (assembled step-2 values)")
            console.print("[bold cyan]Step 9: Fill step-2 (Isi data pendukung)[/bold cyan]")
            _fill_step2(page, step2)
            shot = _screenshot(page, nik) or shot
            if not reg.get("commit"):
                outcome = "step2_filled"  # fill-only: nothing committed
            else:
                ticket = _step3_select_and_commit(page, nik)
                hadir = _konfirmasi_hadir(
                    page, base_url, reg["nama"], nik, ticket, reg.get("exam_date")
                )
                shot = _screenshot(page, nik) or shot
                extra["ticket"] = ticket
                extra["hadir"] = hadir
                outcome = "created"

    return outcome, served_detail, step2_dom, shot, extra


# ---------------------------------------------------------------------------
# Main flow
# ---------------------------------------------------------------------------
def run(args) -> dict:
    cfg_path = Path(args.config) if args.config else Path(os.environ.get("SCRAPER_CONFIG", ""))
    cfg = _load_config(cfg_path)
    base_url = cfg.get("base_url", "https://sehatindonesiaku.kemkes.go.id")
    headless = cfg.get("headless", True)
    dry_run_probe = bool(cfg.get("dry_run_probe", False))

    reg = cfg.get("register") or {}
    nik = reg.get("nik") or cfg.get("nik")
    if not nik:
        raise ValueError("config.register.nik is required")

    OUTPUT_PATH = Path(args.output) if args.output else None
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    SESSION_DIR.mkdir(parents=True, exist_ok=True)

    result = {
        "nik": nik,
        "dry_run_probe": dry_run_probe,
        "outcome": "error",
        "served_detail": None,
        "step2_dom": None,
        "ticket": None,
        "hadir": None,
        "screenshot": None,
        "elapsed_seconds": 0.0,
        "captcha_seconds": 0.0,
        "error": None,
    }
    t0 = time.monotonic()

    with sync_playwright() as p:
        slow_mo = 0 if headless else 50
        context = None
        page = None
        try:
            context = _launch_persistent_with_retry(p, headless=headless, slow_mo=slow_mo)
            page = context.pages[0] if context.pages else context.new_page()
            restore_saved_auth_state(context, page)
            page.set_default_timeout(cfg.get("timeout", 60000))

            captcha_duration = login(
                page, base_url, cfg.get("credentials", {}),
                headless=headless, config=cfg,
            )
            save_auth_state(context, page, base_url)
            result["captcha_seconds"] = round(captcha_duration or 0.0, 2)

            outcome, served_detail, step2_dom, shot, extra = _register_flow(
                page, base_url, reg, dry_run_probe
            )
            result["outcome"] = outcome
            result["served_detail"] = served_detail
            result["step2_dom"] = step2_dom
            result["ticket"] = extra.get("ticket")
            result["hadir"] = extra.get("hadir")
            result["screenshot"] = shot
            return result
        except Exception as e:
            console.print(f"[bold red]Error: {e}[/bold red]")
            result["outcome"] = "error"
            result["error"] = str(e)
            if page is not None:
                try:
                    result["screenshot"] = _screenshot(page, nik) or result["screenshot"]
                except Exception:
                    pass
            raise
        finally:
            result["elapsed_seconds"] = round(time.monotonic() - t0, 2)
            try:
                if context is not None:
                    context.close()
            except Exception:
                pass
            if OUTPUT_PATH:
                try:
                    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
                    with open(OUTPUT_PATH, "w") as f:
                        json.dump(result, f, ensure_ascii=False, indent=2)
                except Exception as exc:
                    console.print(f"[yellow]Could not write output: {exc}[/yellow]")


def main():
    parser = argparse.ArgumentParser(
        description="ASIK CKG register — create a new patient in ASIK (with dry-run probe)"
    )
    parser.add_argument("--config", type=str, default=None, help="Path to config JSON (or SCRAPER_CONFIG env)")
    parser.add_argument("--output", type=str, default=None, help="Output JSON path")
    args = parser.parse_args()
    try:
        run(args)
    except Exception:
        sys.exit(1)


if __name__ == "__main__":
    main()
