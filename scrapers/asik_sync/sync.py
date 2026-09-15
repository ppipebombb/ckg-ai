"""
=============================================================================
ASIK CKG Sync — push merged_data into ASIK forms via Playwright
=============================================================================
Reads merged_data for a single patient from a config JSON, logs into ASIK,
searches the patient by NIK across Belum/Sedang/Selesai Pemeriksaan tabs,
clicks "Mulai", and for every Pemeriksaan Mandiri / Pelayanan Nakes form
whose section slug matches a key in `merged_data["sections"]`, fills the
SurveyJS form and clicks Kirim.

Form-fill semantics:
  - Match `.sd-question` label (number/asterisk-stripped) against
    `merged_data["sections"][slug][i]["merged_key"]`.
  - merged_value=null ⇒ skip (do not fill).
  - radio: click the `<label.sd-selectbase__label>` whose visible text equals
    the merged_value (case-insensitive).
  - number: native value setter + dispatch input/change/blur events so
    SurveyJS picks it up.
  - dropdown (`.sd-dropdown`): click to open then click matching option.
  - Iteratively re-process to reveal `visibleIf`-conditional fields.

Submit:
  - Click `input.sd-navigation__complete-btn` (value="Kirim").
  - Wait for redirect back to /ckg-pelayanan/detail-pemeriksaan.

Output JSON:
  { metadata: {...}, patient_found: bool, patient_tab: str|null,
    forms: [ {layanan, slug, kind, status, filled, skipped, error} ] }
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

from playwright.sync_api import sync_playwright, Page, TimeoutError as PWTimeout  # noqa: E402
from rich.console import Console  # noqa: E402

from helpers import (  # noqa: E402
    SCREENSHOT_DIR,
    SESSION_DIR,
    APIInterceptor,
    launch_persistent_context,
    restore_saved_auth_state,
    save_auth_state,
    login,
    navigate_to_pelayanan,
    close_popups,
    verify_session,
)

console = Console()

ASIK_PATIENT_LIST_PATH = "/ckg-pelayanan"
DETAIL_PATH_PREFIX = "/ckg-pelayanan/detail-pemeriksaan"
FORM_HOST = "form.kemkes.go.id"

# Ceiling for a page transition (Mulai → detail page, Input Data → form host).
# It is a CEILING, not a delay, so a generous value costs nothing when ASIK is
# fast. `run()` raises it for shared-session mode: at K=3 the post-Mulai
# navigation blew the original fixed 20 s on 2 of 3 concurrent workers while the
# third completed normally, i.e. the budget was tuned for one browser rather
# than ASIK refusing the load.
_NAV_TIMEOUT_MS = 20000
_NAV_TIMEOUT_SHARED_MS = 45000


def _load_config(config_path: Path) -> dict:
    if not config_path.exists():
        raise FileNotFoundError(f"config not found: {config_path}")
    with open(config_path) as f:
        return json.load(f)


def _slugify_form(form_name: str) -> str:
    """Mirror backend/app/tasks/merge.py:_slugify_form exactly."""
    if form_name == "identitas_pasien":
        return form_name
    s = form_name.lower().replace("=>", " di_atas ")
    s = re.sub(r"[()/&\-]", " ", s)
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return s.strip("_")


def _clean_question_label(text: str) -> str:
    s = (text or "").replace(" ", " ")
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"^\d+\.\s*", "", s).strip()
    s = re.sub(r"\s*\*\s*$", "", s).strip()
    return s


# ---------------------------------------------------------------------------
# Patient search + tab navigation
# ---------------------------------------------------------------------------
def _current_filter_label(page: Page) -> str | None:
    """Return the search dropdown's currently-selected label (Nama/NIK/Nomor Tiket/Mitra)."""
    return page.evaluate(
        """() => {
            // Dropdown trigger sits before the search textbox in DOM order.
            const inp = document.querySelector('input[placeholder*="NIK" i], input[placeholder*="nama" i], input[placeholder*="Masukkan" i], input[placeholder*="Nomor" i], input[placeholder*="Mitra" i]');
            if (!inp) return null;
            const ph = (inp.getAttribute('placeholder') || '').toLowerCase();
            if (ph.includes('nik')) return 'NIK';
            if (ph.includes('nama')) return 'Nama';
            if (ph.includes('nomor') || ph.includes('tiket')) return 'Nomor Tiket';
            if (ph.includes('mitra')) return 'Mitra';
            return null;
        }"""
    )


def _select_nik_filter(page: Page) -> None:
    """Switch the search dropdown to NIK. Idempotent: returns early if already NIK."""
    if _current_filter_label(page) == "NIK":
        return
    # Open the dropdown by clicking the current selection (Nama/Nomor Tiket/Mitra)
    page.evaluate(
        """() => {
            const labels = ['Nama', 'Nomor Tiket', 'Mitra', 'NIK'];
            const els = Array.from(document.querySelectorAll('*'));
            for (const lbl of labels) {
                const trigger = els.find(e => e.children.length === 0 && e.innerText && e.innerText.trim() === lbl && e.offsetParent);
                if (!trigger) continue;
                let p = trigger;
                for (let i = 0; i < 5 && p; i++) {
                    if (p.onclick || (p.className && /cursor-pointer/.test(p.className))) break;
                    p = p.parentElement;
                }
                (p || trigger).click();
                return lbl;
            }
            return null;
        }"""
    )
    page.wait_for_timeout(400)
    clicked = page.evaluate(
        """() => {
            const els = Array.from(document.querySelectorAll('*'));
            const opt = els.find(e => e.children.length === 0 && e.innerText && e.innerText.trim() === 'NIK' && e.offsetParent);
            if (!opt) return false;
            opt.click();
            return true;
        }"""
    )
    if not clicked:
        raise RuntimeError("could not click NIK option in search dropdown")
    page.wait_for_timeout(400)


def _fill_search_input(page: Page, nik: str) -> None:
    """Type NIK into the live search input using real keyboard events.

    The Vue search component validates per-keystroke ("NIK Hanya Bisa Angka")
    and only fires the list refresh when keystrokes go through native event
    handlers — JS dispatch alone is rejected. Use Playwright's keyboard so
    keydown/keypress/input/keyup carry real `isTrusted=true` semantics.
    """
    sel = (
        'input[placeholder*="NIK" i], '
        'input[placeholder*="nama" i], '
        'input[placeholder*="Masukkan" i], '
        'input[placeholder*="Nomor" i]'
    )
    locator = page.locator(sel).first
    try:
        locator.click(timeout=5000)
    except Exception:
        # Fall back to focusing via JS if click is intercepted
        page.evaluate(
            f"() => {{ const i = document.querySelector('{sel}'); if (i) i.focus(); }}"
        )
    # Clear via real selectAll + Delete (preserves Vue state)
    page.keyboard.press("Control+A")
    page.keyboard.press("Delete")
    page.wait_for_timeout(100)
    # Type each digit; small delay lets per-keystroke validators run
    page.keyboard.type(nik, delay=15)
    page.wait_for_timeout(300)
    page.keyboard.press("Enter")


def _click_tab(page: Page, tab_name: str) -> bool:
    return page.evaluate(
        """(name) => {
            const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_ELEMENT, null);
            let best = null, bestDepth = -1;
            const depth = (e) => { let d = 0, p = e; while (p.parentElement) { p = p.parentElement; d++; } return d; };
            while (walker.nextNode()) {
                const el = walker.currentNode;
                const own = Array.from(el.childNodes).filter(n => n.nodeType === 3).map(n => n.textContent.trim()).join(' ').trim();
                const inner = (el.innerText || '').trim();
                if ((own === name || (inner.startsWith(name) && inner.length < name.length + 15)) && el.offsetParent !== null) {
                    const d = depth(el);
                    if (d > bestDepth) { bestDepth = d; best = el; }
                }
            }
            if (best) { best.scrollIntoView({block:'center'}); best.click(); return true; }
            return false;
        }""",
        tab_name,
    )


def _find_mulai_button_count(page: Page) -> int:
    return page.evaluate(
        """() => Array.from(document.querySelectorAll('button')).filter(b => b.innerText.trim() === 'Mulai' && b.offsetParent).length"""
    )


def _read_active_tab_count(page: Page) -> int | None:
    """Parse the active tab's badge — e.g. 'Sedang Pemeriksaan 1' or '29'.

    Returns the integer count, or None if it cannot be parsed.
    """
    return page.evaluate(
        """() => {
            const tabs = ['Belum Pemeriksaan', 'Sedang Pemeriksaan', 'Selesai Pemeriksaan'];
            for (const t of tabs) {
                const els = Array.from(document.querySelectorAll('*')).filter(e =>
                    e.offsetParent !== null && e.innerText && e.innerText.trim().startsWith(t) && e.innerText.trim().length < t.length + 15
                );
                for (const el of els) {
                    // Only consider tab headers (clickable, has cursor-pointer or role="tab")
                    const cls = (el.className || '').toString();
                    if (!/cursor-pointer|tab/i.test(cls) && el.getAttribute('role') !== 'tab') continue;
                    const txt = el.innerText.trim();
                    const m = txt.match(/(\\d+)\\s*$/);
                    if (m) return parseInt(m[1]);
                }
            }
            return null;
        }"""
    )


# ---------------------------------------------------------------------------
# Authoritative "is the search filter actually applied?" check
#
# The old predicate — `badge == 1 or mulai_count == 1` — accepts ANY tab that
# happens to hold exactly one patient, even when the NIK filter silently never
# applied. `_click_mulai_by_name` then falls back to the sole Mulai button
# regardless of name, and its `rowText.includes(target)` is vacuously true when
# `expected_name` is "" (reachable: `_rebuild_identitas` drops the Nama row when
# both sides are null). Net effect: this whole patient's merged data can be
# submitted onto a DIFFERENT patient's screening. That is the worst thing this
# tool can do, so the DOM heuristic is no longer what decides.
#
# `POST /api/pkg/specific-search/layanan-ckg` is what the NIK box actually
# fires, and its response carries `patient_nik` per row. Comparing against that
# is exact and independent of which columns the table renders.
#
# NOT `list-claim` (verified live 2026-07-22): the search fires BOTH, but
# list-claim is the *unfiltered* page list — it returned all 10 rows of the date
# while the search returned the 1 matching row. Gating on list-claim rejects
# every tab. `specific-search` is also tab-scoped (0 rows on the wrong tab, 1 on
# the right one), which is exactly the per-tab signal this loop needs.
# ---------------------------------------------------------------------------
_SEARCH_ENDPOINT_NEEDLE = "specific-search"


def _extract_search_rows(body) -> list[dict] | None:
    """Rows from a specific-search response body.

    Each row carries `nik` (for identity verification) and `screening_date`
    (for the ASIK-year gate — the same field every list-claim row carries, and
    the value ASIK echoes back in the /detail-screening request).

    Returns `[]` for a recognised-but-empty result set (a genuinely empty tab)
    and `None` when the shape is not recognised — the caller must treat those
    two differently: empty means "not here", unknown means "cannot verify".
    """
    if not isinstance(body, dict):
        return None
    data = body.get("data")
    rows = None
    if isinstance(data, list):
        rows = data
    elif isinstance(data, dict):
        for key in ("data", "list", "rows", "items", "records"):
            if isinstance(data.get(key), list):
                rows = data[key]
                break
    if rows is None:
        return None
    out: list[dict] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        nik = row.get("patient_nik") or row.get("nik")
        sdate = row.get("screening_date")
        out.append({
            "nik": str(nik).strip() if nik is not None else "",
            "screening_date": str(sdate).strip() if sdate is not None else None,
            "name": str(row.get("patient_full_name") or "").strip(),
        })
    return out


def _asik_year_skip(matched_rows: list[dict], filter_date: str | None) -> tuple[bool, list[str]]:
    """Decide the ASIK-year gate for a located patient.

    Returns ``(should_skip, distinct_row_years)``. ``should_skip`` is True only
    when we have an ePus year AND at least one matched row's screening_date year,
    and the ePus year is in NONE of them — i.e. the only ASIK screening(s) for
    this NIK are a different year's visit. When there is nothing to compare (no
    ``filter_date``, or no ``screening_date`` on any row) it is False; the caller
    treats "cannot verify" as proceed-with-warning, not skip.
    """
    epus_year = str(filter_date)[:4] if filter_date else None
    row_years = sorted({
        r["screening_date"][:4]
        for r in matched_rows
        if r.get("screening_date")
    })
    should_skip = bool(epus_year and row_years and epus_year not in row_years)
    return should_skip, row_years


def _wait_search_rows(
    page: Page, interceptor, since: int, timeout_ms: int = 5000
) -> list[dict] | None:
    """Rows of the newest specific-search response captured AFTER index `since`.

    Scoping to responses that arrived after the caller's mark is what makes this
    a check on THIS search rather than on a stale response from a previous tab.
    """
    elapsed = 0
    while True:
        found: list[dict] | None = None
        for entry in interceptor.all_responses[since:]:
            if _SEARCH_ENDPOINT_NEEDLE not in (entry.get("url") or ""):
                continue
            rows = _extract_search_rows(entry.get("body"))
            if rows is not None:
                found = rows  # keep scanning — we want the LAST one
        if found is not None:
            return found
        if elapsed >= timeout_ms:
            return None
        page.wait_for_timeout(100)
        elapsed += 100


def _click_mulai_by_name(page: Page, expected_name: str) -> bool:
    """Click Mulai for the row whose first cell text matches expected_name.

    Falls back to clicking btns[0] only when there's exactly one Mulai button
    visible (i.e. filter narrowed to one row).
    """
    return page.evaluate(
        """(expectedName) => {
            const norm = (s) => (s || '').trim().toLowerCase().replace(/\\s+/g, ' ');
            const target = norm(expectedName);
            const btns = Array.from(document.querySelectorAll('button')).filter(b => b.innerText.trim() === 'Mulai' && b.offsetParent);
            if (btns.length === 0) return false;
            // An empty target makes `rowText.includes(target)` vacuously true, so
            // the name loop would "match" the first row it walks. Skip straight to
            // the single-button fallback instead of pretending we matched a name.
            if (target) {
            // Try exact name match by walking up to TR and checking row text
            for (const b of btns) {
                let p = b;
                while (p && p.tagName !== 'TR') p = p.parentElement;
                if (!p) continue;
                const rowText = norm(p.innerText);
                if (rowText.includes(target)) {
                    b.scrollIntoView({block:'center'});
                    b.click();
                    return true;
                }
            }
            }
            // Fallback: only one Mulai → click it
            if (btns.length === 1) {
                btns[0].scrollIntoView({block:'center'});
                btns[0].click();
                return true;
            }
            return false;
        }""",
        expected_name,
    )


def _start_pemeriksaan(page: Page) -> bool:
    """Start the exam session for a patient found in 'Belum Pemeriksaan'.

    Such a patient is registered + marked hadir but NOT yet examined, so the
    Pelayanan Nakes forms are LOCKED — only the Pemeriksaan Mandiri self-assessment
    fills (its Kirim persists; a Nakes fill silently does not). Click 'Mulai
    Pemeriksaan' → the confirm dialog (Tanggal Pemeriksaan is forced to today, the
    only selectable day for an H-1 registration) → 'Simpan'. The Nakes forms then
    unlock on the SAME detail page. Labels verified with the client 2026-08-19.

    Only the create path reaches a Belum-tab patient (a matched patient has an ASIK
    screening already → found in Sedang/Selesai), so the caller gates this on the tab.
    Returns True when both clicks landed; best-effort — a miss is logged, not raised."""
    clicked = False
    for loc in (
        page.get_by_role("button", name=re.compile(r"mulai pemeriksaan", re.I)),
        page.get_by_text(re.compile(r"^\s*Mulai Pemeriksaan\s*$", re.I)),
    ):
        try:
            if loc.count() and loc.first.is_visible():
                loc.first.scroll_into_view_if_needed(timeout=2000)
                loc.first.click(timeout=5000)
                clicked = True
                break
        except Exception:
            continue
    if not clicked:
        console.print("    [yellow]'Mulai Pemeriksaan' not found — Nakes forms stay locked[/yellow]")
        return False
    page.wait_for_timeout(1500)
    # Confirm dialog: Tanggal Pemeriksaan defaults to today (only selectable day) → 'Simpan'.
    for loc in (
        page.get_by_role("button", name=re.compile(r"^\s*simpan\s*$", re.I)),
        page.get_by_text(re.compile(r"^\s*Simpan\s*$", re.I)),
    ):
        try:
            if loc.count() and loc.first.is_visible():
                loc.first.click(timeout=5000)
                page.wait_for_timeout(2500)
                console.print("    started exam (Mulai Pemeriksaan → Simpan) — Nakes forms unlocked")
                return True
        except Exception:
            continue
    console.print("    [yellow]'Simpan' (confirm exam date) not found after 'Mulai Pemeriksaan'[/yellow]")
    return False


# ---------------------------------------------------------------------------
# Patient detail page — enumerate forms
# ---------------------------------------------------------------------------
def _enumerate_forms(page: Page) -> list[dict]:
    """Return [{kind, layanan, idx, needs_toggle}] in DOM-order.

    Includes both enabled (`<button>`) and toggle-disabled (`<div>` with text
    "Input Data") nakes rows. `needs_toggle=True` means the Diperiksa
    checkbox is unchecked + not disabled and must be flipped to Ya before
    the row's Input Data becomes clickable.

    `idx` is the ordinal among nakes rows that have an Input Data anchor
    (button OR div), so `_click_input_data` can locate the same row after
    re-snapshotting.
    """
    return page.evaluate(
        """() => {
            const results = [];
            let mandiriIdx = 0, nakesIdx = 0;
            // Mandiri: TR rows containing an enabled Input Data <button>.
            const mandiriRows = Array.from(document.querySelectorAll('tr')).filter(tr => {
                const b = Array.from(tr.querySelectorAll('button')).find(x => x.innerText.trim() === 'Input Data');
                return b && b.offsetParent !== null;
            });
            for (const tr of mandiriRows) {
                const cells = tr.querySelectorAll('td');
                const layanan = cells[0]?.innerText?.trim() || null;
                if (!layanan) continue;
                results.push({ kind: 'mandiri', layanan, idx: mandiriIdx++, needs_toggle: false });
            }
            // Nakes: div.grid.grid-cols-5 rows whose anchor cell shows "Input Data"
            // (either as a real <button> or a <div class="cursor-not-allowed">).
            // Nakes rows have exactly 4 children — col-span-2 layanan, Diperiksa,
            // Status, Aksi. Match the Aksi cell (children[3]) text rather than
            // any text in the row, so the header row ("Aksi") and stray
            // grid-cols-5 elsewhere on the page are excluded.
            const nakesRows = Array.from(document.querySelectorAll('div.grid.grid-cols-5'))
                .filter(r => {
                    if (r.offsetParent === null) return false;
                    const aksi = r.children[3];
                    if (!aksi) return false;
                    return /input\\s*data/i.test((aksi.innerText || '').trim());
                });
            // For each nakes row the visible label is the PAKET (sub-section)
            // name. ASIK groups pakets under a parent <button> accordion header
            // (the layanan name e.g. "Skrining Gizi, Tekanan Darah, …"). The
            // paket rows live inside a sibling `<div class="space-y-*">`; the
            // parent label is its previousElementSibling's textContent. Capture
            // both so the section-index lookup can disambiguate paket slugs
            // that collide across multiple parent layanans.
            const parentLabelOf = (row) => {
                let p = row;
                for (let i = 0; i < 8 && p; i++) {
                    const prev = p.previousElementSibling;
                    if (prev && (prev.tagName === 'BUTTON' || prev.tagName === 'DIV')) {
                        const t = (prev.innerText || prev.textContent || '').trim();
                        if (t && t.length > 4 && t.length < 200) {
                            // first non-empty line — strips count badges
                            return t.split(/\\r?\\n/).map(s => s.trim()).find(s => s) || null;
                        }
                    }
                    p = p.parentElement;
                }
                return null;
            };
            for (const r of nakesRows) {
                const cell = r.querySelector('.col-span-2');
                const layanan = cell?.innerText?.trim();
                if (!layanan) continue;
                const cb = r.querySelector('input[type="checkbox"]');
                const needsToggle = !!(cb && !cb.checked && !cb.disabled);
                results.push({
                    kind: 'nakes',
                    layanan,
                    parent_layanan: parentLabelOf(r),
                    idx: nakesIdx++,
                    needs_toggle: needsToggle,
                });
            }
            return results;
        }"""
    )


# ---------------------------------------------------------------------------
# Row identity
#
# `_enumerate_forms` used to run ONCE, and its `idx` was then replayed into
# `_flip_diperiksa_toggle` / `_click_input_data` for the rest of the patient.
# But every submit re-renders the detail page, and both locators recompute the
# row list live — a nakes row whose Input Data anchor appears or disappears
# shifts every index after it, so a stale `idx` silently addresses a DIFFERENT
# form. Identity (kind, layanan, parent_layanan) survives a re-render; an
# ordinal does not. `occurrence` disambiguates the rare case where one identity
# legitimately appears more than once.
# ---------------------------------------------------------------------------
def _form_identity(entry: dict) -> tuple:
    return (entry.get("kind"), entry.get("layanan"), entry.get("parent_layanan"))


def _stamp_occurrences(forms: list[dict]) -> list[dict]:
    counts: dict[tuple, int] = {}
    for form in forms:
        key = _form_identity(form)
        form["occurrence"] = counts.get(key, 0)
        counts[key] = form["occurrence"] + 1
    return forms


def _resolve_current_row(rows: list[dict], target: dict) -> dict | None:
    """`target`'s row in a FRESH enumeration, or None if it is gone."""
    key = _form_identity(target)
    matches = [r for r in rows if _form_identity(r) == key]
    occurrence = target.get("occurrence", 0)
    return matches[occurrence] if occurrence < len(matches) else None


def _flip_diperiksa_toggle(page: Page, kind: str, idx: int) -> bool:
    """Click the Diperiksa <label> for the idx-th nakes row (kind=nakes only).

    Mirrors the row-locator logic in `_click_input_data` so the same idx
    resolves to the same row. No-op (returns False) if the row's checkbox
    is already checked or disabled.
    """
    if kind != "nakes":
        return False
    return page.evaluate(
        """({idx}) => {
            const rows = Array.from(document.querySelectorAll('div.grid.grid-cols-5'))
                .filter(r => {
                    if (r.offsetParent === null) return false;
                    const aksi = r.children[3];
                    return aksi && /input\\s*data/i.test((aksi.innerText || '').trim());
                });
            const row = rows[idx];
            if (!row) return false;
            const cb = row.querySelector('input[type="checkbox"]');
            if (!cb || cb.checked || cb.disabled) return false;
            const label = cb.closest('label');
            const target = label || cb;
            target.scrollIntoView({block:'center'});
            target.click();
            return true;
        }""",
        {"idx": idx},
    )


def _wait_input_data_button(page: Page, kind: str, idx: int, timeout_ms: int = 10000) -> bool:
    """Poll until the idx-th nakes row's Input Data anchor is a clickable <button>.

    Only meaningful for nakes rows (mandiri rows always start with a real button).
    """
    assert kind == "nakes", "_wait_input_data_button only applies to nakes rows"
    deadline = time.monotonic() + (timeout_ms / 1000)
    while time.monotonic() < deadline:
        ok = page.evaluate(
            """({idx}) => {
                const rows = Array.from(document.querySelectorAll('div.grid.grid-cols-5'))
                    .filter(r => {
                        if (r.offsetParent === null) return false;
                        const aksi = r.children[3];
                        return aksi && /input\\s*data/i.test((aksi.innerText || '').trim());
                    });
                const row = rows[idx];
                if (!row) return false;
                const btn = Array.from(row.querySelectorAll('button')).find(b => b.innerText.trim() === 'Input Data' && b.offsetParent);
                return !!btn;
            }""",
            {"idx": idx},
        )
        if ok:
            return True
        page.wait_for_timeout(150)
    return False


def _click_input_data(page: Page, kind: str, idx: int) -> bool:
    """Click the idx-th Input Data button of the given kind.

    Row indexing matches `_enumerate_forms`: nakes rows count every row that
    has an Input Data anchor (button OR div), in DOM-order. Caller MUST flip
    the Diperiksa toggle first if `needs_toggle` was True for this row.
    """
    return page.evaluate(
        """({kind, idx}) => {
            if (kind === 'mandiri') {
                const trs = Array.from(document.querySelectorAll('tr')).filter(tr => {
                    const b = Array.from(tr.querySelectorAll('button')).find(x => x.innerText.trim() === 'Input Data');
                    return b && b.offsetParent !== null;
                });
                const tr = trs[idx];
                if (!tr) return false;
                const btn = Array.from(tr.querySelectorAll('button')).find(b => b.innerText.trim() === 'Input Data');
                if (!btn) return false;
                btn.scrollIntoView({block:'center'});
                btn.click();
                return true;
            }
            const rows = Array.from(document.querySelectorAll('div.grid.grid-cols-5'))
                .filter(r => {
                    if (r.offsetParent === null) return false;
                    const aksi = r.children[3];
                    return aksi && /input\\s*data/i.test((aksi.innerText || '').trim());
                });
            const row = rows[idx];
            if (!row) return false;
            const btn = Array.from(row.querySelectorAll('button')).find(b => b.innerText.trim() === 'Input Data' && b.offsetParent);
            if (!btn) return false;
            btn.scrollIntoView({block:'center'});
            btn.click();
            return true;
        }""",
        {"kind": kind, "idx": idx},
    )


# ---------------------------------------------------------------------------
# Form fill — SurveyJS
# ---------------------------------------------------------------------------
def _wait_for_form_loaded(page: Page, timeout_ms: int = 20000) -> bool:
    try:
        page.wait_for_selector('.sd-question[data-name], .sd-question[id^="sq_"]', timeout=timeout_ms)
        return True
    except PWTimeout:
        return False


# The form engine ships the patient's EXISTING answers in a separate XHR
# (`.../cha-formbuilder/.../get/skrining-layanan`, AES ciphertext that SurveyJS
# decrypts and applies). The question LABELS are already in the static HTML at
# DOMContentLoaded, so `_wait_for_form_loaded` returning True proves nothing
# about the answers.
#
# On the read path that race made two radios flip between "Ya"/"Tidak"/None
# across identical runs, and it was fixed with this gate (see
# `asik/patient_scraper.py:_batch_read_forms_via_tabs` and asik/CLAUDE.md).
# The WRITE path never got the fix, and here the same race is destructive, not
# just noisy: with answers not yet applied, every already-answered required
# field reads as empty, so `_fill_required_defaults` writes a plausible
# fabricated default ("Negatif", "Normal", 120) over the real clinical answer
# and Kirim persists it — logged to `asik_default_fills` as if intended.
#
# Same gate as the read path, stricter consequence: if the XHR does not arrive
# we refuse to fill or submit this form at all (`answers_unconfirmed`) rather
# than proceeding on an unproven DOM.
# Briefly raised to 30s on 2026-07-27 to test whether an OLD screening's form
# was merely SLOW to deliver answers. It is not: at 30s the same patient still
# reported `never requested` on every form (36 forms, 0 submitted, 828s vs 410s
# at 10s — three times the wait, identical result). A full capture of every
# form.kemkes.go.id response for one 2025 screening showed only static chunks,
# CSS, fonts and the page document — NO answer-fetch request on any endpoint,
# so there is no other URL for the gate's needle to watch either.
#
# Back to 10s: on the failure path this is paid PER FORM, so the larger value
# only made a doomed run three times slower. Do not raise it again to chase
# `answers_unconfirmed` — latency is ruled out. The open question is whether
# those forms render with answers inlined (Next.js SSR) or genuinely blank,
# which decides whether filling them is safe; until that is answered the gate
# must keep refusing (ASIK holds real values for these screenings — measured
# 93 non-empty fields on patient dc7c2ce3 / 2025-02-13).
_ANSWER_XHR_TIMEOUT_MS = 10000
# Settle after the XHR so SurveyJS finishes applying the decrypted answers. The
# read path validated 120 ms across 3 zero-diff runs; use a wider margin here
# because a late-applied answer on the write path is not merely misread — it is
# overwritten and submitted.
_ANSWER_SETTLE_MS = 200


class _AnswerGate:
    """Flips `seen` when the form's answer XHR returns 200.

    Must be armed BEFORE the navigation that loads the form — subscribing after
    `goto`/click risks missing a fast response. One instance per form; call
    `detach()` in a finally so 35 forms don't leak 35 listeners onto the page.
    """

    def __init__(self, page: Page):
        self.page = page
        self.seen = False
        self.url: str | None = None
        # Diagnostics for the failure path. "the XHR was never requested" and
        # "it was requested and came back 404" are the same `answers_unconfirmed`
        # to the caller but need OPPOSITE fixes — the first means the form has no
        # stored answers to race against (so the guard's premise does not hold),
        # the second means an auth/lifetime problem on the form host. Without
        # these two fields the failure message cannot tell them apart, which is
        # exactly where the 2025 backfill investigation stalled on 2026-07-27.
        self.observed = 0
        self.last_status: int | None = None
        page.on("response", self._on_response)

    def _on_response(self, resp) -> None:
        try:
            url = resp.url
            # `submit/<program_code>/skrining-layanan` (the WRITE endpoint) also
            # contains the needle — only the read counts as "answers delivered".
            if "skrining-layanan" not in url or "/submit/" in url:
                return
            self.observed += 1
            self.last_status = resp.status
            if resp.status == 200:
                self.seen = True
                self.url = url
        except Exception:
            pass

    def wait(self, timeout_ms: int = _ANSWER_XHR_TIMEOUT_MS, poll_ms: int = 30) -> bool:
        elapsed = 0
        while not self.seen and elapsed < timeout_ms:
            self.page.wait_for_timeout(poll_ms)
            elapsed += poll_ms
        if self.seen:
            self.page.wait_for_timeout(_ANSWER_SETTLE_MS)
        return self.seen

    def detach(self) -> None:
        try:
            self.page.remove_listener("response", self._on_response)
        except Exception:
            pass


def _read_form_questions(page: Page) -> list[dict]:
    """Return [{label, dataName, hasRadios, hasNumber, hasDropdown, choices}]."""
    return page.evaluate(
        """() => {
            const qs = Array.from(document.querySelectorAll('.sd-question'));
            return qs.map(q => {
                const titleEl = q.querySelector('.sd-question__title');
                const rawLabel = titleEl?.innerText?.replace(/\\s+/g,' ').trim() || '';
                const dataName = q.getAttribute('data-name') || q.id;
                const radios = Array.from(q.querySelectorAll('input[type="radio"]')).map(r => ({
                    label: r.closest('label')?.innerText?.trim() || '',
                }));
                const checkboxes = Array.from(q.querySelectorAll('input[type="checkbox"]')).map(c => ({
                    label: c.closest('label')?.innerText?.trim() || '',
                }));
                const hasNumber = !!q.querySelector('input[type="number"]');
                const hasText = !!q.querySelector('input[type="text"], textarea');
                const hasDropdown = !!q.querySelector('.sd-dropdown, .sv-dropdown');
                return { rawLabel, dataName, radios, checkboxes, hasNumber, hasText, hasDropdown };
            });
        }"""
    )


def _fill_radio(page: Page, data_name: str, value: str) -> bool:
    """Select the radio option whose visible text equals `value`, via a native click.

    JS `.click()` on the label proved unreliable for some SurveyJS radiogroups (the
    real-data 'Tidak batuk' answer never registered). A native Playwright click on
    the exact-text option label fires trusted events, auto-scrolls, and waits for
    actionability. The question is matched by data-name OR id (some carry only id).
    """
    val = str(value).strip()
    q = page.locator(
        f'.sd-question[data-name="{data_name}"], .sd-question[id="{data_name}"]'
    ).first
    exact = re.compile(rf"^\s*{re.escape(val)}\s*$", re.I)
    for sel in ("label.sd-selectbase__label", "label", '[role="radio"]'):
        try:
            opt = q.locator(sel).filter(has_text=exact).first
            if opt.count() == 0:
                continue
            opt.scroll_into_view_if_needed(timeout=3000)
            opt.click(timeout=3000)
            return True
        except Exception:
            continue
    return False


def _fill_number(page: Page, data_name: str, value) -> bool:
    return page.evaluate(
        """({dataName, value}) => {
            const q = document.querySelector(`.sd-question[data-name="${CSS.escape(dataName)}"]`)
                || document.getElementById(dataName);
            if (!q) return false;
            const inp = q.querySelector('input[type="number"], input.sd-input');
            if (!inp) return false;
            const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
            setter.call(inp, String(value));
            inp.dispatchEvent(new Event('input', {bubbles: true}));
            inp.dispatchEvent(new Event('change', {bubbles: true}));
            inp.dispatchEvent(new Event('blur', {bubbles: true}));
            return true;
        }""",
        {"dataName": data_name, "value": value},
    )


def _fill_text(page: Page, data_name: str, value) -> bool:
    return page.evaluate(
        """({dataName, value}) => {
            const q = document.querySelector(`.sd-question[data-name="${CSS.escape(dataName)}"]`)
                || document.getElementById(dataName);
            if (!q) return false;
            const inp = q.querySelector('input[type="text"], textarea, input.sd-input');
            if (!inp) return false;
            const setter = Object.getOwnPropertyDescriptor(inp.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype, 'value').set;
            setter.call(inp, String(value));
            inp.dispatchEvent(new Event('input', {bubbles: true}));
            inp.dispatchEvent(new Event('change', {bubbles: true}));
            inp.dispatchEvent(new Event('blur', {bubbles: true}));
            return true;
        }""",
        {"dataName": data_name, "value": value},
    )


def _fill_dropdown(page: Page, data_name: str, value: str) -> bool:
    """Select a SurveyJS dropdown option using native Playwright clicks.

    Filling several dropdowns back-to-back (the 6 GPAQ questions) was unreliable
    with JS `.click()`: some selections never committed. Native locator clicks fire
    trusted pointer events, auto-scroll, and wait for actionability, which SurveyJS
    registers reliably. We scope the option to THIS dropdown's own list (via the
    trigger's `aria-controls`) so a neighbouring popup's "Tidak" can't be clicked by
    mistake, then confirm the widget lost its `--empty` modifier. Returns False if
    it did not commit — the caller retries on the next pass.
    """
    val = str(value).strip()
    q = page.locator(
        f'.sd-question[data-name="{data_name}"], .sd-question[id="{data_name}"]'
    ).first
    trigger = q.locator('.sd-dropdown, [role="combobox"]').first
    exact = re.compile(rf"^\s*{re.escape(val)}\s*$", re.I)
    for _ in range(3):
        try:
            page.keyboard.press("Escape")  # close any lingering popup
        except Exception:
            pass
        page.wait_for_timeout(150)
        try:
            trigger.scroll_into_view_if_needed(timeout=3000)
            trigger.click(timeout=3000)
        except Exception:
            continue
        # Scope options to this trigger's own list when SurveyJS exposes it.
        try:
            list_id = trigger.get_attribute("aria-controls")
        except Exception:
            list_id = None
        if list_id:
            opts = page.locator(f'[id="{list_id}"]').locator(
                '.sv-list__item, .sd-list__item, [role="option"]'
            )
        else:
            opts = page.locator('.sv-list__item, .sd-list__item, [role="option"]')
        try:
            opts.filter(has_text=exact).first.click(timeout=3000)
        except Exception:
            try:
                page.keyboard.press("Escape")
            except Exception:
                pass
            continue
        try:
            page.keyboard.press("Escape")
        except Exception:
            pass
        page.wait_for_timeout(150)
        try:
            if q.locator('.sd-dropdown:not(.sd-dropdown--empty)').count() > 0:
                return True
        except Exception:
            pass
    return False


def _click_kirim(page: Page) -> bool:
    return page.evaluate(
        """() => {
            const btn = document.querySelector('input.sd-navigation__complete-btn[value="Kirim"]');
            if (!btn) return false;
            btn.scrollIntoView({block:'center'});
            btn.click();
            return true;
        }"""
    )


def _confirm_kirim_dialog(page: Page) -> bool:
    """ASIK shows a "Apakah Anda Yakin..." confirmation modal after Kirim.
    Click the affirmative button (Ya/Iya/Simpan/Konfirmasi/Yakin).
    """
    page.wait_for_timeout(600)
    return page.evaluate(
        """() => {
            const want = ['Ya, Simpan', 'Ya Simpan', 'Iya, Simpan', 'Yakin', 'Ya', 'Iya', 'Simpan', 'Konfirmasi', 'OK'];
            const btns = Array.from(document.querySelectorAll('button, input[type="button"]')).filter(b => b.offsetParent !== null);
            for (const want_text of want) {
                const target = btns.find(b => {
                    const t = (b.innerText || b.value || '').trim();
                    return t === want_text || t.toLowerCase() === want_text.toLowerCase();
                });
                if (target) { target.click(); return want_text; }
            }
            return null;
        }"""
    )


def _read_form_validation_errors(page: Page) -> list[str]:
    return page.evaluate(
        """() => {
            const errs = [];
            document.querySelectorAll('.sd-question__erbox, .sd-error, [role="alert"]').forEach(e => {
                const t = (e.innerText || '').trim();
                if (t && !errs.includes(t)) errs.push(t);
            });
            return errs;
        }"""
    ) or []


def _required_coverage(page: Page) -> dict:
    """Inspect every visible .sd-question and report which required ones are unfilled.

    Returns {required: int, unfilled: [labels]}. Uses the same answered-detection
    rules as `_read_form_questions` to avoid false negatives.
    """
    return page.evaluate(
        """() => {
            const norm = (t) => (t || '').replace(/\\s+/g,' ').trim();
            const cleanLabel = (t) => norm(t).replace(/^\\d+\\.\\s*/, '').replace(/\\s*\\*\\s*$/, '').trim();
            const qs = Array.from(document.querySelectorAll('.sd-question'));
            const visible = qs.filter(q => q.offsetParent !== null);
            let required = 0;
            const unfilled = [];
            for (const q of visible) {
                const titleEl = q.querySelector('.sd-question__title');
                const titleText = norm(titleEl?.innerText || '');
                // Required marker: header has an asterisk OR class includes required.
                const isRequired = /\\*\\s*$/.test(titleText) || (q.className || '').includes('sd-question--required');
                if (!isRequired) continue;
                required++;
                const answered = (
                    !!q.querySelector('input[type="radio"]:checked') ||
                    !!q.querySelector('input[type="checkbox"]:checked') ||
                    Array.from(q.querySelectorAll('input[type="number"], input[type="text"], textarea, input.sd-input'))
                        .some(i => (i.value || '').trim() !== '') ||
                    !!q.querySelector('.sd-dropdown__value, .sd-dropdown__filter-string-input')?.textContent?.trim() ||
                    Array.from(q.querySelectorAll('select')).some(s => s.value && s.value.trim() !== '')
                );
                if (!answered) unfilled.push(cleanLabel(titleText));
            }
            return { required, unfilled };
        }"""
    )


# ---------------------------------------------------------------------------
# Consent modal, launch-retry, and default-fill (make the sync submittable)
# ---------------------------------------------------------------------------
# Negative / normal keywords for the live fallback when a required question is not
# in the documented default map. Most-specific first.
_DEFAULT_SAFE_KEYWORDS = (
    "tidak ada", "tidak sama sekali", "tidak batuk", "negatif", "normal",
    "non ", "tidak", "belum",
)

# Disease-present / abnormal result words. The live fallback must NEVER auto-select
# one of these for a required question (a fabricated positive diagnosis is the worst
# failure of this tool) — mirrors app/services/asik_defaults._is_disease_option so a
# question ASIK renders that the map doesn't cover (drift) still fails safe.
_DEFAULT_DISEASE_KEYWORDS = ("positif", "reaktif", "abnormal", "kusta", "bakteriologis", "klinis")
_DEFAULT_NEGATION_TOKENS = ("non", "tidak", "bukan", "negatif")


def _looks_disease_option(text: str) -> bool:
    t = (text or "").lower()
    if any(neg in t for neg in _DEFAULT_NEGATION_TOKENS):
        return False
    return any(w in t for w in _DEFAULT_DISEASE_KEYWORDS)


def _pick_safe_option(options: list[str]) -> str | None:
    """Choose the clinically-safe option from a live option list, or None.

    A negative/normal keyword wins; otherwise the first non-disease option; never a
    positive/abnormal finding. Shared by the map-miss fallback and the live dropdown
    fallback so both layers apply the same policy as the backend default map.

    Disease-present options are excluded FIRST — otherwise the "normal" keyword would
    match "Abnormal" (substring) and select a fabricated abnormal finding. Mirrors
    app/services/asik_defaults._is_disease_option being applied before the keyword net.
    """
    opts = [o for o in (options or []) if o]
    if not opts:
        return None
    safe = [o for o in opts if not _looks_disease_option(o)]
    if not safe:
        return None
    for kw in _DEFAULT_SAFE_KEYWORDS:
        for o in safe:
            if kw in o.lower():
                return o
    return safe[0]


def _normalize_default_label(label: str) -> str:
    """Canonical form matching backend app/services/asik_defaults.normalize_label."""
    s = (label or "").replace(" ", " ")
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"^\d+\.\s*", "", s)
    s = re.sub(r"\s*\*\s*$", "", s)
    return s.strip().lower()


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

    The sync shares the per-puskesmas Chromium profile with the ASIK scrape; two
    processes cannot open one user-data-dir at once. If a scrape holds it, wait and
    retry rather than fail — the cron flow runs them sequentially, but a manual sync
    during a scheduled scrape would otherwise crash.
    """
    last_exc: Exception | None = None
    for i in range(attempts):
        try:
            return launch_persistent_context(p, headless=headless, slow_mo=slow_mo)
        except Exception as exc:
            last_exc = exc
            console.print(
                f"[yellow]persistent profile busy (attempt {i + 1}/{attempts}); "
                f"a scrape may be using this puskesmas session — waiting {delay:.0f}s[/yellow]"
            )
            time.sleep(delay)
    raise last_exc  # type: ignore[misc]


def _unfilled_required_questions(page: Page) -> list[dict]:
    """Visible, REQUIRED, still-unanswered questions with widget info.

    Returns [{label, dataName, kind, options}]. Same required + answered detection
    as `_required_coverage` so we default exactly the fields that would block Kirim.
    """
    return page.evaluate(
        """() => {
            const norm = (t) => (t || '').replace(/\\s+/g,' ').trim();
            const clean = (t) => norm(t).replace(/^\\d+\\.\\s*/, '').replace(/\\s*\\*\\s*$/, '').trim();
            const qs = Array.from(document.querySelectorAll('.sd-question')).filter(q => q.offsetParent !== null);
            const out = [];
            for (const q of qs) {
                const titleEl = q.querySelector('.sd-question__title');
                const titleText = norm(titleEl && titleEl.innerText);
                const required = !!q.querySelector('.sd-question__required-text')
                    || /\\*\\s*$/.test(titleText)
                    || (q.className || '').includes('sd-question--required');
                if (!required) continue;
                const answered = (
                    !!q.querySelector('input[type="radio"]:checked') ||
                    !!q.querySelector('input[type="checkbox"]:checked') ||
                    Array.from(q.querySelectorAll('input[type="number"], input[type="text"], textarea, input.sd-input'))
                        .some(i => (i.value || '').trim() !== '') ||
                    !!(q.querySelector('.sd-dropdown__value, .sd-dropdown__filter-string-input') || {}).textContent &&
                       (q.querySelector('.sd-dropdown__value, .sd-dropdown__filter-string-input').textContent || '').trim() !== '' ||
                    Array.from(q.querySelectorAll('select')).some(s => s.value && s.value.trim() !== '')
                );
                if (answered) continue;
                const dataName = q.getAttribute('data-name') || q.id;
                const radios = Array.from(q.querySelectorAll('input[type="radio"]'));
                const checks = Array.from(q.querySelectorAll('input[type="checkbox"]'));
                const hasNumber = !!q.querySelector('input[type="number"]');
                const hasText = !!q.querySelector('input[type="text"], textarea');
                const hasDropdown = !!q.querySelector('.sd-dropdown, [role="combobox"]');
                let kind = 'unknown', options = [];
                if (radios.length) { kind = 'radio'; options = radios.map(r => norm(r.closest('label') && r.closest('label').innerText)); }
                else if (checks.length) { kind = 'checkbox'; options = checks.map(c => norm(c.closest('label') && c.closest('label').innerText)); }
                else if (hasDropdown) { kind = 'dropdown'; }
                else if (hasNumber) { kind = 'number'; }
                else if (hasText) { kind = 'text'; }
                out.push({ label: clean(titleText), dataName, kind, options });
            }
            return out;
        }"""
    ) or []


# Behavioural follow-up NUMBERS that appear on LIVE ASIK but are absent from the audited
# mapping (drift), so they carry no documented default. GPAQ reveals these once an activity
# is answered "Ya" (from real data): how many days/week and minutes/day. They are
# activity-frequency values, NOT clinical measurements — safe to default minimally so the
# form can submit. Matched by substring against the normalized live label. Deliberately
# narrow: we still return None (never fabricate) for any OTHER unknown number (Hb, BP, …).
_DRIFT_NUMBER_DEFAULTS = (
    ("berapa hari dalam satu minggu", 1),   # days per week (valid 1–7)
    ("berapa menit", 30),                    # minutes per day (a modest, in-range duration)
)


def _resolve_default(question: dict, default_values: dict) -> object | None:
    """Safe default value for one required question, or None if we must not fill it.

    Prefers the documented map (built from asik_form_mapping.json); falls back to a
    live heuristic for questions the map doesn't cover (ASIK drift). A number with no
    documented default returns None — we never fabricate an unknown measurement, except
    the narrow behavioural activity-frequency follow-ups in `_DRIFT_NUMBER_DEFAULTS`.
    """
    norm = _normalize_default_label(question.get("label", ""))
    entry = default_values.get(norm)
    if entry and entry.get("value") is not None:
        return entry["value"]
    kind = question.get("kind")
    options = [o for o in (question.get("options") or []) if o]
    if kind in ("radio", "checkbox", "dropdown") and options:
        # No safe keyword → first non-disease option; never fabricate a positive/
        # abnormal finding (None → field stays blank so the form fails the coverage
        # check rather than submitting a false result).
        return _pick_safe_option(options)
    if kind == "text":
        return "-"
    if kind == "number":
        for needle, val in _DRIFT_NUMBER_DEFAULTS:
            if needle in norm:
                return val
    return None


def _read_dropdown_options(page: Page, data_name: str) -> list[str]:
    """Open a SurveyJS dropdown, read its option texts, and close it.

    `_unfilled_required_questions` can't list a dropdown's options (SurveyJS renders
    them only once opened), so a required dropdown NOT in the documented map (ASIK
    drift, e.g. the GPAQ questions missing from the audited mapping) had no options to
    fall back on and was left blank. Reading them live lets `_pick_safe_option` choose.
    """
    q = page.locator(
        f'.sd-question[data-name="{data_name}"], .sd-question[id="{data_name}"]'
    ).first
    trigger = q.locator('.sd-dropdown, [role="combobox"]').first
    try:
        trigger.scroll_into_view_if_needed(timeout=3000)
        trigger.click(timeout=3000)
    except Exception:
        return []
    page.wait_for_timeout(200)
    try:
        list_id = trigger.get_attribute("aria-controls")
    except Exception:
        list_id = None
    scope = page.locator(f'[id="{list_id}"]') if list_id else page
    try:
        texts = scope.locator(".sv-list__item, .sd-list__item, [role='option']").all_inner_texts()
    except Exception:
        texts = []
    try:
        page.keyboard.press("Escape")
    except Exception:
        pass
    return [t.strip() for t in texts if t and t.strip()]


def _fill_required_defaults(page: Page, default_values: dict, max_passes: int = 4) -> list[dict]:
    """Fill every required-but-empty field with a safe default; return what we set.

    Loops so a default that reveals a `visibleIf` child gets the new field filled
    too. Returns [{question, value, kind}] for logging into asik_default_fills.
    """
    recorded: list[dict] = []
    seen: set[str] = set()
    for _ in range(max_passes):
        questions = _unfilled_required_questions(page)
        progress = False
        for q in questions:
            data_name = q.get("dataName")
            if not data_name or data_name in seen:
                continue
            value = _resolve_default(q, default_values)
            kind = q.get("kind")
            if value is None and kind == "dropdown":
                # Map miss on a dropdown (drift): read its live options and pick safe.
                value = _pick_safe_option(_read_dropdown_options(page, data_name))
            if value is None:
                continue
            if kind in ("radio", "checkbox"):
                ok = _fill_radio(page, data_name, str(value))
            elif kind == "dropdown":
                ok = _fill_dropdown(page, data_name, str(value))
            elif kind == "number":
                ok = _fill_number(page, data_name, value)
            elif kind == "text":
                ok = _fill_text(page, data_name, value)
            else:
                ok = _fill_radio(page, data_name, str(value))
            if ok:
                seen.add(data_name)
                recorded.append({"question": q.get("label"), "value": value, "kind": kind})
                progress = True
                page.wait_for_timeout(120)
        if not progress:
            break
    return recorded


def _click_kembali(page: Page) -> bool:
    return page.evaluate(
        """() => {
            const btns = Array.from(document.querySelectorAll('button')).filter(b => b.innerText.trim() === 'Kembali ke Halaman Utama');
            if (btns.length === 0) return false;
            btns[0].click();
            return true;
        }"""
    )


def _build_section_index(merged_data: dict) -> dict:
    """Slug → list of {merged_key, merged_value}. Skip null values upfront.

    Accepts three shapes:
      1. merged_data NESTED — `{"sections": {<slug>: {"layanan_label": "...",
         "sub_sections": {<paket_slug>: {"label": "...", "items": [...]}}}}}`
         (current LLM merge pipeline output).
      2. merged_data FLAT (legacy) — `{"sections": {<slug>: [{merged_key,
         merged_value, ...}, ...]}}` (pre-2026-05-11 output).
      3. asik_preview — `{<form_name>: {<field>: <value>, ...}}` emitted
         directly by the ``epus_to_asik`` converter
         (shape served by `/patients/{id}/asik-preview`).

    Dual-key indexing for nested shape: emits BOTH the parent layanan slug
    (mapped to all items across sub-sections — back-compat with the legacy
    flat shape) AND each paket slug (mapped to only that paket's items).
    Reason: ASIK's `Pelayanan oleh Nakes` UI lists rows by PAKET label, not
    parent layanan, so the runtime row enumerator slugifies paket names. The
    paket-slug index hits exactly. When a paket slug already exists from a
    prior parent layanan (same paket name appears under multiple parents),
    items are merge-deduplicated by `merged_key` (first-seen wins — the
    parent layanan slug retains the full bag).
    """
    out: dict[str, list[dict]] = {}

    def _coerce_items(raw: list) -> list[dict]:
        keep: list[dict] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            if item.get("merged_value") is None:
                continue
            keep.append({
                "merged_key": item.get("merged_key"),
                "merged_value": item.get("merged_value"),
                # Stamped by the backend (app/tasks/sync.py) using merge.py's
                # own `_values_equal`. True ⇒ ASIK already holds this exact
                # value, so a form where EVERY item is True is a no-op submit.
                "same_as_asik": bool(item.get("same_as_asik")),
            })
        return keep

    def _merge_dedup(existing: list[dict], extra: list[dict]) -> list[dict]:
        seen = {it.get("merged_key") for it in existing}
        for it in extra:
            mk = it.get("merged_key")
            if mk in seen:
                continue
            existing.append(it)
            seen.add(mk)
        return existing

    sections = (merged_data or {}).get("sections")
    if isinstance(sections, dict):
        for slug, payload in sections.items():
            if isinstance(payload, list):
                keep = _coerce_items(payload)
                if keep:
                    out[slug] = keep
                continue
            if not isinstance(payload, dict):
                continue
            sub_map = payload.get("sub_sections") or {}
            if not isinstance(sub_map, dict):
                continue
            parent_bag: list[dict] = []
            for paket_slug, sub_payload in sub_map.items():
                if not isinstance(sub_payload, dict):
                    continue
                sub_keep = _coerce_items(sub_payload.get("items") or [])
                if not sub_keep:
                    continue
                parent_bag.extend(sub_keep)
                if not paket_slug or not isinstance(paket_slug, str):
                    continue
                existing = out.get(paket_slug)
                if existing is None:
                    out[paket_slug] = list(sub_keep)
                else:
                    _merge_dedup(existing, sub_keep)
            if parent_bag:
                out[slug] = parent_bag
        return out
    # asik_preview shape — keys are full form names, values are field→value dicts.
    # Index by slug so `_match_section_items` (which slugifies the live ASIK
    # form title) compares apples-to-apples.
    if isinstance(merged_data, dict):
        for form_name, fields in merged_data.items():
            if not isinstance(fields, dict):
                continue
            keep = []
            for k, v in fields.items():
                if v is None or v == "":
                    continue
                keep.append({"merged_key": k, "merged_value": v})
            if keep:
                out[_slugify_form(form_name)] = keep
    return out


_NORMALIZE_TOKENS = (
    # gender
    "_laki_laki", "_laki", "_perempuan",
    # age qualifiers
    "_dewasa_lansia", "_dewasa", "_lansia",
    "_18_39_tahun", "_18_24_tahun", "_25_39_tahun",
    "_di_atas_40_tahun", "_di_atas_40_thn", "_di_atas_45_tahun",
    "_di_atas_40", "_40_tahun",
    # filler
    "_hanya_diisi_apabila_merokok_atau_terpapar_asap_rokok",
    "_untuk_daerah_endemis_atau_berisiko_frambusia",
    "_khusus_usia_di_atas_40_thn_dan_penyandang_ht_dan_atau_dm",
    "_hanya_untuk_di_atas_40_tahun",
    # composite slugs that group multiple ASIK forms together
    "_kusta_skabies", "_frambusia_kusta_skabies",
)


def _normalize_slug(slug: str) -> str:
    """Strip gender/age/filler tokens from slug for cross-sex / cross-age match.

    Also normalises ASIK abbreviation drift: live ASIK uses "TB" while xlsx
    spec / converter uses "Tuberkulosis". Both forms must produce the same
    normalised slug so `_match_section_items` finds the converter section.
    """
    s = slug
    # ASIK ↔ xlsx abbreviation aliases — applied first so subsequent token
    # stripping sees the canonical form. Note: `\b` does not match between
    # `_` and a letter (underscore is a word char), so split-rejoin on `_`.
    s = "_".join("tb" if tok == "tuberkulosis" else tok for tok in s.split("_"))
    # Apply repeatedly until no token strips
    changed = True
    while changed:
        changed = False
        for tok in _NORMALIZE_TOKENS:
            if s.endswith(tok):
                s = s[: -len(tok)]
                changed = True
            if tok.lstrip("_") in s and ("_" + tok.lstrip("_") + "_") in ("_" + s + "_"):
                # interior occurrence
                s = s.replace(tok, "")
                changed = True
        s = re.sub(r"_+", "_", s).strip("_")
    return s


def _match_section_items(merged_sections: dict, form_slug: str) -> list[dict]:
    """Find items by slug, falling back to prefix + normalized + substring matches.

    The merge prompt emits slugs from a curated EPUS_BREADCRUMBS table while
    ASIK form titles are slugified live — so `pemeriksaan_kadar_co` (merge)
    must match `pemeriksaan_kadar_co_hanya_diisi_apabila_...` (ASIK), and
    `gizi_bb_tb_lingkar_perut_perempuan` (merge) must match
    `gizi_bb_tb_lingkar_perut_laki_laki` (ASIK display).

    Substring fallback handles xlsx-vs-ASIK form-name drift where the ASIK
    display name is a SUFFIX (not prefix) of the converter's xlsx-spec name —
    e.g. ASIK ``Penapisan Risiko Kanker Paru`` is a tail of the xlsx
    ``Skrining Kanker Paru (Laki-Laki >=45 Tahun) - Penapisan Risiko
    Kanker Paru``.
    """
    if form_slug in merged_sections:
        return merged_sections[form_slug]
    # Prefix-match either direction
    for key, items in merged_sections.items():
        if form_slug.startswith(key) or key.startswith(form_slug):
            return items
    # Normalized equality (strip gender/age/filler tokens from both sides)
    target = _normalize_slug(form_slug)
    if target:
        for key, items in merged_sections.items():
            if _normalize_slug(key) == target:
                return items
        # Normalized prefix
        for key, items in merged_sections.items():
            nk = _normalize_slug(key)
            if not nk:
                continue
            if target.startswith(nk) or nk.startswith(target):
                return items
    # Substring fallback — ASIK display name is a suffix or interior token
    # span of the converter's xlsx-spec name. Require min token length to
    # avoid trivial matches (e.g. "hati" inside many other slugs).
    if len(form_slug) >= 12:
        for key, items in merged_sections.items():
            if "_" + form_slug + "_" in "_" + key + "_" or "_" + form_slug == "_" + key[-len(form_slug):]:
                return items
    if target and len(target) >= 12:
        for key, items in merged_sections.items():
            nk = _normalize_slug(key)
            if not nk:
                continue
            if "_" + target + "_" in "_" + nk + "_" or nk.endswith(target):
                return items
    return []


def _fill_form_iteratively(page: Page, items: list[dict], max_passes: int = 4) -> tuple[int, int]:
    """Iteratively fill until no new fields get filled (handles visibleIf reveals).

    Returns (filled_count, skipped_count).
    """
    filled = 0
    skipped = 0
    used_keys: set[str] = set()
    for pass_num in range(1, max_passes + 1):
        questions = _read_form_questions(page)
        progress = False
        for q in questions:
            label = _clean_question_label(q.get("rawLabel", ""))
            if not label:
                continue
            data_name = q.get("dataName")
            if not data_name:
                continue
            # Match merged_key against question label (case-insensitive, trimmed)
            match = next(
                (it for it in items if (it["merged_key"] or "").strip().lower() == label.strip().lower()),
                None,
            )
            if match is None or data_name in used_keys:
                continue
            value = match["merged_value"]
            ok = False
            if q.get("radios"):
                ok = _fill_radio(page, data_name, str(value))
            elif q.get("hasDropdown"):
                ok = _fill_dropdown(page, data_name, str(value))
            elif q.get("hasNumber"):
                ok = _fill_number(page, data_name, value)
            elif q.get("hasText"):
                ok = _fill_text(page, data_name, value)
            else:
                # Last-resort: try radio (some checkbox/radio variants)
                ok = _fill_radio(page, data_name, str(value))
            if ok:
                used_keys.add(data_name)
                filled += 1
                progress = True
                page.wait_for_timeout(150)
        if not progress:
            break
    # Items not matched → skipped
    for it in items:
        # Approximate skip count = items whose label never matched
        # (we counted filled above; rest are skipped)
        pass
    skipped = len(items) - filled
    return filled, max(skipped, 0)


# ---------------------------------------------------------------------------
# Per-form orchestration
# ---------------------------------------------------------------------------
def _process_form(page: Page, **kwargs) -> dict:
    """Arm the answer-XHR gate for exactly this form, then run the real body.

    The gate must be subscribed BEFORE the click that navigates to the form
    host, and torn down on every exit path (`_process_form_inner` returns from
    a dozen places, and 35 forms per patient would otherwise leave 35 live
    listeners on the page).
    """
    gate = _AnswerGate(page)
    try:
        return _process_form_inner(page, gate, **kwargs)
    finally:
        gate.detach()


def _process_form_inner(
    page: Page,
    gate: "_AnswerGate",
    *,
    base_url: str,
    kind: str,
    layanan: str,
    idx: int,
    needs_toggle: bool,
    merged_sections: dict,
    detail_url: str,
    default_values: dict,
    parent_layanan: str | None = None,
    dry_run: bool = False,
    prune_unchanged: bool = False,
) -> dict:
    # `layanan` is the PAKET label (sub-section in ASIK's Pelayanan oleh
    # Nakes list). `parent_layanan` is the accordion-header label above it
    # (the form's parent name). merged_sections is indexed dual-key by both
    # paket slug and parent layanan slug — try paket first, then fall back
    # to parent so we catch legacy flat data and asik_preview shape.
    paket_slug = _slugify_form(layanan)
    parent_slug = _slugify_form(parent_layanan) if parent_layanan else None
    items = _match_section_items(merged_sections, paket_slug)
    matched_slug = paket_slug
    if not items and parent_slug:
        items = _match_section_items(merged_sections, parent_slug)
        if items:
            matched_slug = parent_slug
    record = {
        "layanan": layanan,
        "slug": paket_slug,
        "parent_layanan": parent_layanan,
        "parent_slug": parent_slug,
        "matched_slug": matched_slug if items else None,
        "kind": kind,
        "status": "skipped_no_section",
        "filled": 0,
        "skipped": 0,
        "submitted": False,
        "defaults": [],
        "would_prune": False,
        "answers_xhr": None,
        "error": None,
    }
    if not items:
        parent_disp = f" parent={parent_layanan!r}" if parent_layanan else ""
        console.print(
            f"      [dim]skip ({kind}): {layanan} (no slug match; tried paket={paket_slug}, parent={parent_slug}){parent_disp}[/dim]"
        )
        return record

    # Elimination: ASIK already holds every value we would push, so opening,
    # filling and submitting this form is a ~13 s no-op. `same_as_asik` is
    # stamped per item by the backend using merge.py's `_values_equal` (the
    # same comparator that decided the merge), and is False whenever
    # `asik_value` is null — so "ASIK has nothing here" can never look prunable.
    # `identitas_pasien` is never pruned: it is the patient-identity anchor and
    # cheap to re-affirm.
    record["would_prune"] = (
        matched_slug != "identitas_pasien"
        and all(bool(it.get("same_as_asik")) for it in items)
    )
    if record["would_prune"] and prune_unchanged:
        record["status"] = "skipped_unchanged"
        console.print(
            f"      [dim]skip ({kind}): {layanan} — all {len(items)} values already match ASIK[/dim]"
        )
        return record

    console.print(
        f"      [cyan]→ {kind}: {layanan} (matched={matched_slug}, {len(items)} fields"
        f"{', would_prune' if record['would_prune'] else ''})[/cyan]"
    )

    # Flip Diperiksa toggle to "Ya" if the row started as "Tidak". Vue swaps
    # the disabled <div> for a real <button> after the click.
    if needs_toggle:
        flipped = _flip_diperiksa_toggle(page, kind, idx)
        if not flipped:
            record["status"] = "toggle_failed"
            record["error"] = "could not flip Diperiksa toggle to Ya"
            return record
        if not _wait_input_data_button(page, kind, idx):
            record["status"] = "toggle_no_button"
            record["error"] = "Diperiksa flipped but Input Data button never appeared"
            return record
        console.print(f"          [dim]flipped Diperiksa → Ya[/dim]")

    # Click Input Data → form.kemkes.go.id
    clicked = _click_input_data(page, kind, idx)
    if not clicked:
        record["status"] = "no_button"
        record["error"] = "Input Data button not found"
        return record

    # Wait for form host
    try:
        page.wait_for_url(lambda u: FORM_HOST in u, timeout=_NAV_TIMEOUT_MS)
    except PWTimeout:
        record["status"] = "form_load_timeout"
        record["error"] = "form page did not load"
        return record

    if not _wait_for_form_loaded(page):
        record["status"] = "form_load_timeout"
        record["error"] = "SurveyJS form did not render"
        # Try to navigate back
        try:
            page.go_back()
            page.wait_for_url(lambda u: DETAIL_PATH_PREFIX in u, timeout=10000)
        except Exception:
            page.goto(detail_url, wait_until="domcontentloaded")
        return record

    # Answers land in a separate XHR, AFTER the labels are in the DOM. Fill
    # before it arrives and every answered required field reads as empty, so
    # `_fill_required_defaults` overwrites real clinical answers with fabricated
    # defaults (see `_AnswerGate`). This replaces a blind 800 ms sleep that
    # merely made the race usually-win.
    if not gate.wait():
        record["status"] = "answers_unconfirmed"
        record["answers_xhr_observed"] = gate.observed
        record["answers_xhr_status"] = gate.last_status
        detail = (
            f"{gate.observed} response(s), last status {gate.last_status}"
            if gate.observed
            else "never requested"
        )
        record["error"] = (
            "existing answers never arrived (get/skrining-layanan not seen in "
            f"{_ANSWER_XHR_TIMEOUT_MS} ms; {detail}) — refusing to fill or submit"
        )
        console.print(f"          [red]{record['error']}[/red]")
        try:
            page.go_back()
            page.wait_for_url(lambda u: DETAIL_PATH_PREFIX in u, timeout=10000)
        except Exception:
            page.goto(detail_url, wait_until="domcontentloaded")
        return record
    record["answers_xhr"] = gate.url

    filled, skipped = _fill_form_iteratively(page, items)
    record["filled"] = filled
    record["skipped"] = skipped

    if filled == 0:
        # 0 real answers for this form → skip it entirely. We do NOT submit a form
        # made up purely of defaults; one real answer is enough to keep + submit it.
        record["status"] = "skipped_no_real_data"
        try:
            page.go_back()
            page.wait_for_url(lambda u: DETAIL_PATH_PREFIX in u, timeout=10000)
        except Exception:
            page.goto(detail_url, wait_until="domcontentloaded")
        return record

    # Fill a SAFE DEFAULT for every REQUIRED field we have no data for, then re-check.
    # This replaces the old "abandon on any unfilled required" behavior — ASIK forces
    # required questions, so we default + log them (asik_default_fills) and submit.
    defaults_applied = _fill_required_defaults(page, default_values)
    record["defaults"] = defaults_applied
    if defaults_applied:
        console.print(
            f"          [magenta]default-filled {len(defaults_applied)} required field(s)[/magenta]"
        )

    # Pre-Kirim coverage check: if a required field is STILL empty (no safe default
    # available, e.g. an unknown number ASIK added), submitting would fail — back out.
    cov = _required_coverage(page) or {}
    unfilled_required = cov.get("unfilled") or []
    if unfilled_required:
        record["status"] = "incomplete_data"
        record["error"] = (
            f"required fields with no safe default: {', '.join(unfilled_required)[:300]}"
        )
        console.print(
            f"          [yellow]incomplete (no default): {record['error']}[/yellow]"
        )
        try:
            page.go_back()
            page.wait_for_url(lambda u: DETAIL_PATH_PREFIX in u, timeout=10000)
        except Exception:
            page.goto(detail_url, wait_until="domcontentloaded")
        return record

    # dry_run: everything required is filled and the form WOULD submit, but skip
    # Kirim so testing doesn't mutate ASIK.
    if dry_run:
        record["status"] = "would_submit"
        record["submitted"] = False
        try:
            page.go_back()
            page.wait_for_url(lambda u: DETAIL_PATH_PREFIX in u, timeout=10000)
        except Exception:
            page.goto(detail_url, wait_until="domcontentloaded")
        return record

    # Listen for SurveyJS POST submit response so we know it actually persisted.
    submit_response = {"status": None, "url": None}

    def _on_response(resp):
        # Form posts go to form.kemkes.go.id POST endpoints (skrining-layanan
        # / submit / save). Capture any 2xx POST originating from the form host.
        try:
            if resp.request.method != "POST":
                return
            if FORM_HOST not in resp.url:
                return
            if 200 <= resp.status < 300:
                # Prefer the latest one
                submit_response["status"] = resp.status
                submit_response["url"] = resp.url
        except Exception:
            pass

    page.context.on("response", _on_response)
    try:
        # Click Kirim
        if not _click_kirim(page):
            record["status"] = "no_kirim_button"
            record["error"] = "Kirim button not visible"
            try:
                page.go_back()
                page.wait_for_url(lambda u: DETAIL_PATH_PREFIX in u, timeout=10000)
            except Exception:
                page.goto(detail_url, wait_until="domcontentloaded")
            return record

        # Some Kirim flows pop a confirmation modal — click it.
        confirmed = _confirm_kirim_dialog(page)
        if confirmed:
            console.print(f"          confirmed via: {confirmed}")

        # Wait for redirect back to detail-pemeriksaan (redirectUrl in form URL)
        redirected = False
        try:
            page.wait_for_url(lambda u: DETAIL_PATH_PREFIX in u, timeout=30000)
            redirected = True
        except PWTimeout:
            pass

        # Cross-check: did the form actually submit via XHR?
        page.wait_for_timeout(800)
        if submit_response["status"] is not None:
            console.print(
                f"          submit XHR {submit_response['status']} {submit_response['url']}"
            )

        if redirected:
            # SurveyJS only navigates after onComplete fires (i.e. submission
            # succeeded). XHR detection is best-effort; redirect is canonical.
            record["status"] = "submitted"
            record["submitted"] = True
        else:
            # Stayed on form host → likely validation error.
            errs = _read_form_validation_errors(page)
            if errs:
                record["status"] = "validation_error"
                record["error"] = "; ".join(errs)[:1000]
                console.print(f"          [red]validation: {record['error']}[/red]")
            elif FORM_HOST in page.url:
                record["status"] = "validation_error"
                record["error"] = "Kirim did not redirect (validation?)"
            else:
                record["status"] = "submit_unknown"
            try:
                if FORM_HOST in page.url:
                    page.go_back()
            except Exception:
                page.goto(detail_url, wait_until="domcontentloaded")
    finally:
        try:
            page.context.remove_listener("response", _on_response)
        except Exception:
            pass

    page.wait_for_timeout(1500)
    # Re-close popups in case "Pengaturan Pelayanan" returns
    close_popups(page, silent=True)
    return record


# ---------------------------------------------------------------------------
# Main flow
# ---------------------------------------------------------------------------
def run(args) -> dict:
    cfg_path = Path(args.config) if args.config else Path(os.environ.get("SCRAPER_CONFIG", ""))
    cfg = _load_config(cfg_path)
    base_url = cfg.get("base_url", "https://sehatindonesiaku.kemkes.go.id")
    headless = cfg.get("headless", True)
    nik = cfg.get("nik")
    if not nik:
        raise ValueError("config.nik is required")
    merged_data = cfg.get("merged_data") or {}
    merged_sections = _build_section_index(merged_data)
    if not merged_sections:
        console.print("[yellow]Warning: merged_data has no sections; nothing to fill[/yellow]")

    # {normalized_label: {value, kind}} safe defaults for required-but-missing fields.
    default_values = cfg.get("default_values") or {}
    # dry_run: fill everything (incl. defaults) but never click Kirim (safe testing).
    dry_run = bool(cfg.get("dry_run", False))
    # Skip forms whose every value ASIK already holds. OFF by default: the first
    # runs report `would_prune` per form without acting on it, so the real
    # elimination rate is measured before anything stops being submitted.
    prune_unchanged = bool(cfg.get("prune_unchanged", False))
    # ASIK's list is date-range-scoped (default = current week); set it to the
    # patient's screening date so a past-date patient is actually found.
    filter_date = cfg.get("filter_date")

    OUTPUT_PATH = Path(args.output) if args.output else None

    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    SESSION_DIR.mkdir(parents=True, exist_ok=True)

    result = {
        "metadata": {
            "scraped_at": datetime.now().isoformat(),
            "nik": nik,
            "base_url": base_url,
            "available_slugs": sorted(merged_sections.keys()),
        },
        "patient_found": False,
        "patient_tab": None,
        "skipped": False,
        "skip_reason": None,
        "forms": [],
    }
    t0 = time.monotonic()
    captcha_duration = 0.0

    # "shared": this process is one of K running concurrently against ONE ASIK
    # login. It must use a NON-persistent context (the persistent user_data_dir
    # is a single-process lock) and must never call login() — a second login
    # invalidates the session server-side for all K mid-write. See Phase C.
    shared_session = cfg.get("session_mode") == "shared"
    if shared_session:
        global _NAV_TIMEOUT_MS
        _NAV_TIMEOUT_MS = _NAV_TIMEOUT_SHARED_MS

    with sync_playwright() as p:
        slow_mo = 0 if headless else 50
        if shared_session:
            browser = p.chromium.launch(headless=headless, slow_mo=slow_mo)
            context = browser.new_context(
                viewport={"width": 1920, "height": 1080},
                locale="id-ID",
                timezone_id="Asia/Jakarta",
            )
            page = context.new_page()
            # Cookies + localStorage/sessionStorage from the state files the
            # bootstrap patient wrote. Read-only: K workers must not race to
            # rewrite them, so `save_auth_state` is skipped below.
            restore_saved_auth_state(context, page)
        elif cfg.get("use_session", True):
            context = _launch_persistent_with_retry(p, headless=headless, slow_mo=slow_mo)
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
            if shared_session:
                # Probe instead of logging in, and FAIL rather than recover: a
                # re-login here would silently kill the other K-1 workers'
                # session, several of which may be mid-form. The batch's
                # bootstrap patient owns the login; this worker only borrows it.
                if not verify_session(context, base_url):
                    # Flagged, not just raised: the shared token has a limited
                    # life (measured ~30 min on a saved snapshot), so the batch
                    # must be able to tell "this session went stale, re-login
                    # and requeue" apart from "this patient failed". `finally`
                    # writes `result`, so the flag reaches the caller.
                    result["session_dead"] = True
                    raise RuntimeError(
                        "shared ASIK session is not valid (session_mode=shared "
                        "never logs in — the batch bootstrap must refresh it)"
                    )
                console.print("\n[bold cyan]Step 1: Login[/bold cyan]")
                console.print("  [green]Using the batch's shared session[/green]")
                captcha_duration = 0.0
            else:
                captcha_duration = login(
                    page, base_url, cfg.get("credentials", {}),
                    headless=headless, config=cfg,
                )
                if cfg.get("use_session", True):
                    save_auth_state(context, page, base_url)

            navigate_to_pelayanan(page, base_url)
            close_popups(page)
            # Cold-session privacy-consent modal that close_popups doesn't target.
            _dismiss_consent_modal(page)
            # Deliberately NO date filter. ASIK's screening for this NIK lands
            # days/weeks off the ePus date (and sometimes in a different year),
            # so scoping the list to the ePus date hides it — the "NIK tidak
            # ditemukan" failures. We locate by NIK across ALL dates, then read
            # the matched row's screening_date and only fill when its YEAR
            # matches the ePus year (the guard replaces the old wrong-week
            # protection, and NIK equality is a stronger wrong-patient check
            # than a date window ever was).

            # Determine expected patient name from merged_data identitas section.
            # Identitas may be flat (legacy) or nested {sub_sections: {...: {items}}}.
            ident_payload = (merged_data.get("sections") or {}).get("identitas_pasien")
            ident: list[dict] = []
            if isinstance(ident_payload, list):
                ident = [it for it in ident_payload if isinstance(it, dict)]
            elif isinstance(ident_payload, dict):
                for sub in (ident_payload.get("sub_sections") or {}).values():
                    if isinstance(sub, dict):
                        for it in sub.get("items") or []:
                            if isinstance(it, dict):
                                ident.append(it)
            expected_name = ""
            for it in ident:
                if (it.get("merged_key") or "").lower().strip() == "nama":
                    expected_name = str(it.get("merged_value") or "").strip()
                    break
            console.print(f"\n[bold cyan]Searching NIK={nik} (expected name='{expected_name}')[/bold cyan]")

            _select_nik_filter(page)
            _mark = len(interceptor.all_responses)
            _fill_search_input(page, nik)
            page.wait_for_timeout(2500)
            _wait_search_rows(page, interceptor, _mark)

            # Find patient across tabs — only accept when filter is provably applied:
            # tab badge count == visible Mulai count == 1 (or row text contains name).
            #
            # Try the tab the patient is most likely to be in FIRST — each miss
            # costs >=4 s of fixed waits below. Which tab that is depends on how
            # old the target date is, and getting this backwards makes things
            # slower, so it keys off the date rather than a fixed order:
            #   * old date (backfill) -> screening long finished -> "Selesai".
            #     Measured 11/11 on sampled prod jobs, and a live Cipondoh probe
            #     on 2026-06-14 returned Belum=0, Sedang=0, Selesai=12.
            #   * recent date (daily cron, 3-day lookback) -> often still open ->
            #     "Belum". Confirmed on a live dry run: a 2-day-old patient was
            #     found in "Belum Pemeriksaan".
            # Only the ORDER changes; all three are still tried, and the
            # badge/mulai predicate that decides acceptance is untouched.
            _age_days = None
            if filter_date:
                try:
                    _age_days = (
                        datetime.now().date() - datetime.strptime(filter_date, "%Y-%m-%d").date()
                    ).days
                except ValueError:
                    _age_days = None
            if _age_days is not None and _age_days >= 7:
                tabs = ["Selesai Pemeriksaan", "Sedang Pemeriksaan", "Belum Pemeriksaan"]
            else:
                tabs = ["Belum Pemeriksaan", "Sedang Pemeriksaan", "Selesai Pemeriksaan"]
            patient_tab = None
            matched_rows: list[dict] = []
            saw_any_search = False
            for tab in tabs:
                console.print(f"  Trying tab: {tab}")
                _click_tab(page, tab)
                page.wait_for_timeout(1500)
                # Tab switch can reset the dropdown back to Nama; re-select NIK
                # and re-fire the search.
                _select_nik_filter(page)
                mark = len(interceptor.all_responses)
                _fill_search_input(page, nik)
                page.wait_for_timeout(2500)
                search_rows = _wait_search_rows(page, interceptor, mark)
                search_niks = None if search_rows is None else [r["nik"] for r in search_rows]
                badge = _read_active_tab_count(page)
                mulai_count = _find_mulai_button_count(page)
                cur_filter = _current_filter_label(page)
                console.print(
                    f"    filter={cur_filter} badge={badge} mulai_buttons={mulai_count} "
                    f"search_rows={'?' if search_niks is None else len(search_niks)}"
                )
                if search_niks is None:
                    # No parseable specific-search for THIS search. We cannot prove the
                    # filter applied, so we must not accept the tab on the DOM
                    # heuristic alone — that is the wrong-patient path.
                    console.print(
                        "    [yellow]no parseable specific-search response — cannot verify "
                        "the NIK filter applied; skipping this tab[/yellow]"
                    )
                    continue
                saw_any_search = True
                if not search_niks:
                    continue  # genuinely empty tab
                foreign = sorted({n for n in search_niks if n != nik})
                if foreign:
                    # Filter did not (fully) apply: rows for other patients are
                    # still listed. Clicking Mulai here could open someone else.
                    console.print(
                        f"    [yellow]filter not applied — {len(foreign)} foreign NIK(s) "
                        f"still listed; skipping this tab[/yellow]"
                    )
                    continue
                patient_tab = tab
                matched_rows = [r for r in search_rows if r["nik"] == nik]
                break

            if patient_tab is None:
                result["patient_found"] = False
                if not saw_any_search:
                    # Distinct from "not on ASIK": we never got a readable
                    # specific-search, so this is a scraper/site problem and a
                    # retry is worthwhile — not a missing patient.
                    result["error"] = (
                        "could not verify the NIK filter in any tab: no parseable "
                        "specific-search response was captured"
                    )
                    console.print(f"[red]{result['error']}[/red]")
                else:
                    # Parseable search, NIK in no tab → the screening genuinely is
                    # not in ASIK. Product rule: skip (their data problem), not a
                    # retry-worthy failure.
                    result["skipped"] = True
                    result["skip_reason"] = "not_found"
                    result["error"] = (
                        "NIK not present in any ASIK tab — skip (ASIK data missing)"
                    )
                    console.print(f"[yellow]{result['error']}[/yellow]")
                return result

            result["patient_found"] = True
            result["patient_tab"] = patient_tab

            # ── ASIK-year gate ──────────────────────────────────────────────
            # The NIK matched, but ASIK's screening may be a DIFFERENT visit than
            # the ePus one we hold merged data for (e.g. ePus 2025 vs ASIK 2026).
            # Fill ONLY when a matched row's screening_date year equals the ePus
            # (filter_date) year; otherwise skip — never push one year's data onto
            # another year's screening.
            epus_year = str(filter_date)[:4] if filter_date else None
            year_skip, row_years = _asik_year_skip(matched_rows, filter_date)
            result["asik_screening_dates"] = sorted({
                r["screening_date"] for r in matched_rows if r.get("screening_date")
            })
            if year_skip:
                result["skipped"] = True
                result["skip_reason"] = "year_mismatch"
                result["error"] = (
                    f"ASIK screening year(s) {row_years} != ePus year {epus_year} "
                    f"— different visit, skip"
                )
                console.print(f"  [yellow]{result['error']}[/yellow]")
                return result
            if len(row_years) > 1:
                # This NIK has ASIK screenings in >1 year (one of which matches
                # the ePus year). `_click_mulai_by_name` opens by NAME, which
                # cannot tell the years apart, so filling risks landing on the
                # wrong year's screening. Rather than guess, skip. (Rare — needs
                # the same person screened in two years, both currently listed.)
                result["skipped"] = True
                result["skip_reason"] = "ambiguous_multi_year"
                result["error"] = (
                    f"NIK has ASIK screenings in multiple years {row_years} "
                    f"(ePus {epus_year}) — cannot target one safely, skip"
                )
                console.print(f"  [yellow]{result['error']}[/yellow]")
                return result
            if not row_years:
                # No screening_date on the matched row(s) → we cannot verify the
                # ASIK year. Never fill on an unverified year (that is how one
                # year's data lands on another year's screening). Safe skip. If a
                # dry-run shows these EN MASSE the field moved and the search-row
                # read needs fixing — but no data was corrupted meanwhile.
                result["skipped"] = True
                result["skip_reason"] = "no_screening_date"
                result["error"] = (
                    "no screening_date on matched search row(s) — cannot verify "
                    "year, skip"
                )
                console.print(f"  [yellow]{result['error']}[/yellow]")
                return result
            console.print(
                f"  [green]Patient found in: {patient_tab} "
                f"(ASIK {row_years or ['?']} / ePus {epus_year})[/green]"
            )

            if not _click_mulai_by_name(page, expected_name):
                raise RuntimeError(
                    "Mulai click failed — could not match row by name "
                    f"'{expected_name}' and fallback (single Mulai) did not apply"
                )

            page.wait_for_url(lambda u: DETAIL_PATH_PREFIX in u, timeout=_NAV_TIMEOUT_MS)
            page.wait_for_timeout(2000)
            detail_url = page.url
            close_popups(page, silent=True)

            # A create-flow patient is in 'Belum Pemeriksaan' (registered + hadir, exam
            # not started) → the Pelayanan Nakes forms are locked and their fills don't
            # persist. Start the exam ONCE here so Nakes unlocks; matched patients are
            # already examined (Sedang/Selesai) so they skip this and normal sync is
            # unchanged.
            if patient_tab == "Belum Pemeriksaan":
                if _start_pemeriksaan(page):
                    close_popups(page, silent=True)
                    page.wait_for_timeout(1500)

            forms = _stamp_occurrences(_enumerate_forms(page))
            console.print(f"  Detected {len(forms)} forms on detail page")

            # `forms` is the work list; `current_rows` is where those rows live
            # RIGHT NOW. They diverge as soon as a submit re-renders the page,
            # so re-enumerate whenever the previous form touched the DOM. Forms
            # that clicked nothing (~23 of ~35 per patient) leave it untouched,
            # so this costs ~7-12 extra DOM walks per patient, not 35.
            current_rows = forms
            dom_dirty = False

            for f in forms:
                if dom_dirty:
                    current_rows = _stamp_occurrences(_enumerate_forms(page))
                    dom_dirty = False
                row = _resolve_current_row(current_rows, f)
                if row is None:
                    console.print(
                        f"      [red]row vanished after a re-render: "
                        f"{f['kind']}: {f['layanan']}[/red]"
                    )
                    result["forms"].append({
                        "layanan": f.get("layanan"),
                        "slug": _slugify_form(f.get("layanan") or ""),
                        "parent_layanan": f.get("parent_layanan"),
                        "kind": f.get("kind"),
                        "status": "row_vanished",
                        "filled": 0,
                        "skipped": 0,
                        "submitted": False,
                        "defaults": [],
                        "error": "row no longer present on the detail page",
                    })
                    continue
                if row["idx"] != f["idx"]:
                    # The exact bug this guard exists for: the row moved, so the
                    # enumerated ordinal now addresses a DIFFERENT form.
                    console.print(
                        f"      [yellow]row index drifted {f['idx']} → {row['idx']} "
                        f"for {f['kind']}: {f['layanan']}[/yellow]"
                    )
                rec = _process_form(
                    page,
                    base_url=base_url,
                    kind=row["kind"],
                    layanan=row["layanan"],
                    idx=row["idx"],
                    needs_toggle=bool(row.get("needs_toggle")),
                    merged_sections=merged_sections,
                    detail_url=detail_url,
                    default_values=default_values,
                    parent_layanan=row.get("parent_layanan"),
                    dry_run=dry_run,
                    prune_unchanged=prune_unchanged,
                )
                result["forms"].append(rec)
                # After submit / back, ensure we are on detail page; some forms
                # cause the redirect to drop the modal-cleared state, so always
                # re-clear popups before the next form's button click.
                if DETAIL_PATH_PREFIX not in page.url:
                    try:
                        page.goto(detail_url, wait_until="domcontentloaded", timeout=_NAV_TIMEOUT_MS)
                    except Exception:
                        pass
                # These two outcomes return from _process_form without clicking
                # ANYTHING (no toggle, no Input Data) — the page never moved and
                # no modal can have been raised, so the settle + popup sweep are
                # pure cost. They are also the common case: ~23 of ~35 forms per
                # patient are `skipped_no_section`, and close_popups falls through
                # to 8 sequential locator probes when it finds nothing to close.
                # Anything that navigated, submitted, or touched a toggle still
                # settles exactly as before.
                if rec.get("status") not in (
                    "skipped_no_section", "no_button", "skipped_unchanged"
                ):
                    dom_dirty = True
                    page.wait_for_timeout(800)
                    close_popups(page, silent=True)

            elapsed = round(time.monotonic() - t0, 2)
            result["metadata"]["elapsed_seconds"] = elapsed
            result["metadata"]["captcha_seconds"] = round(captcha_duration, 2)
            return result
        except Exception as e:
            console.print(f"[bold red]Error: {e}[/bold red]")
            try:
                page.screenshot(path=str(SCREENSHOT_DIR / "sync_error.png"))
            except Exception:
                pass
            result.setdefault("error", str(e))
            raise
        finally:
            try:
                if browser is not None:
                    browser.close()
                else:
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
    parser = argparse.ArgumentParser(description="ASIK CKG sync — push merged_data into ASIK forms")
    parser.add_argument("--config", type=str, default=None, help="Path to config JSON (or SCRAPER_CONFIG env)")
    parser.add_argument("--output", type=str, default=None, help="Output JSON path")
    args = parser.parse_args()
    try:
        run(args)
    except Exception:
        sys.exit(1)


if __name__ == "__main__":
    main()
