"""
Per-patient detail scraper for epus-v2.

For each list record we have a `pelayanan_id` (record["id"]). This module:

  1. GET /pelayanan/show/{pelayanan_id}  -- returns the full HTML page.
     - We use context.request.get() so NO JavaScript runs. This is important:
       visiting the page in a real tab auto-fires POST /klaster_siklushidup/{id}
       which is a WRITE, violating the read-only safety rule. Fetching the
       raw HTML is strictly read-only.
     - From the HTML we extract:
         * Data Pasien (table#table_pasien)
         * Penyakit Khusus (panel "Penyakit Khusus" → array table)
         * Risiko Kehamilan (panel "Risiko Kehamilan" → array table)
         * Riwayat Pasien (illness history) + Alergi Pasien (allergies) →
           region-robust `{jenis, nama, tanggal}` lists. Two builds: the new
           one (jaksel/Tebet) uses `table_riwayat` / `table_alergi` (with a
           Tanggal column); the old one (kotabekasi/kotatangerang) renders a
           `<label>`-titled id-less 2-column table (no Tanggal). Located by
           id-hint OR exact heading text so both builds work.
         * Data Skrining (legacy "skrining" module index, table#table_skrining)
           → `{skrining, tanggal, keterangan, detail_href}` per row. Captures
           the historical-screening index (ILP rows overlap skrining_klaster;
           legacy rows carry a detail_href to the per-screening page, which is
           NOT auto-fetched).
         * Tab anchors (Anamnesa → Pemantauan Anestesi & Bedah — 31 buttons).
           Each tab's href is /{module}/{create|edit|...}/{pelayanan_id}?from=...
           and is always rendered server-side, so we don't need to click
           anything to discover them.

  2. Tab discovery is DYNAMIC-FIRST, with a known-module safety net.
     We bootstrap by fetching /anamnesa/create/{pid} and extracting its
     tab-bar anchors (so a NEW/renamed module is picked up automatically —
     no code change). BUT the Anamnesa bar is per-build incomplete: the new
     (jaksel) build lists only ~15 of the ~33 modules that GET /{module}/
     create/{pid} actually serves with data, so pure bar discovery dropped
     ~17 tabs/patient for the largest region (incl. the converter-consumed
     Konseling HIV / TB Paru / PKPR). So `_merge_known_modules` UNIONS the
     bar discovery with `_KNOWN_MODULES` — every known module is fetched
     regardless of which ones a build's bar renders; a module that doesn't
     apply to a patient/region 404s and is dropped (no error stub). All 3
     regions now scrape ~33–34 tabs. (See _merge_known_modules; verified
     live 2026-06-05.)

     Each tab page is a large HTML form. We mirror data_pasien's clean
     shape: `{ "<Section Heading>": { "<Question Label>": <answer>, … } }`.
     Question labels come from the `.form-group > .control-label` text
     (the label the user actually reads on screen). Section headings
     come from the ancestor `.box` / `.panel` / `fieldset`'s header.

     Answer formatting is type-specific:
       - text / number / date  → string value (or null when empty)
       - textarea              → trimmed text content (or null)
       - select                → text of `option[selected]` (or null for
                                 placeholder options like "- PILIH -")
       - radio group           → option label of the checked radio (or null)
       - checkbox (single)     → true/false
       - checkbox group        → { optionLabel: true/false, … }

     When multiple controls in the same section share one question label
     (e.g. Lama Sakit → 3 inputs for tahun/bulan/hari), the answer is a
     sub-dict keyed by the last bracket segment of the form name.

     We filter out (via `isHidden` / container blocklists):
       - inputs with `type="hidden"` or `class="hidden"` / `d-none`
         (database IDs, CSRF tokens, JSON config blobs, etc.);
       - controls inside boilerplate modals (print, consent, antrol,
         resume, gallery, navbar);
       - sections whose heading matches `_BOILERPLATE_SECTION_PREFIXES`.

All HTML parsing runs inside Playwright via DOMParser (`page.evaluate`) —
DOMParser doesn't execute scripts, so this is safe even if tab pages embed
inline <script> blocks. No BeautifulSoup dep.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from urllib.parse import quote

import httpx

from playwright.sync_api import BrowserContext, Page
from rich.console import Console

console = Console()


# ---------------------------------------------------------------------------
# Safety — defense-in-depth. If anything ever does end up navigating to
# /pelayanan/show/{id} with JS enabled, these routes block the writes.
# ---------------------------------------------------------------------------
DANGEROUS_URL_SUBSTRINGS = (
    "/klaster_siklushidup/",
    "/pelayanan/save",
    "/pelayanan/kirim",
    "/pelayanan/update",
    "/pelayanan/delete",
)


def install_write_guard(context: BrowserContext):
    """Abort any request that looks like a write operation.

    Opt-in defense-in-depth. The main detail-scrape flow uses raw HTTP
    GETs (no JS), so this is only relevant if future callers do page
    navigations.
    """
    def guard(route, request):
        url = request.url.lower()
        method = request.method.upper()
        if method == "POST" and any(frag in url for frag in DANGEROUS_URL_SUBSTRINGS):
            console.print(f"  [yellow]Blocked write: {method} {request.url[:140]}[/yellow]")
            return route.abort()
        return route.continue_()
    context.route("**/*", guard)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
# Plain browser UA — NO custom token. The Poso portal (poso.epuskesmas.id) has a
# WAF rule that 403s any request whose UA contains "epus-v2/scraper" (verified
# 2026-08-19: that exact suffix → 403 on /pelayanan/show/*; every clean browser
# UA → 200). The httpx deep-scrape fetches show/anamnesa/tab pages with this UA,
# so the suffix silently 403'd every per-patient fetch for Poso → empty
# data_pasien → all records skipped as "missing NIK". The other regions accept
# any UA; keep this a clean browser string so a per-region WAF can't single it out.
_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def scrape_patient_detail(
    context: BrowserContext,
    page: Page,
    *,
    base_url: str,
    pelayanan_id: str,
    max_parallel_fetches: int = 10,
    **_ignored,  # accept legacy kwargs (csrf_token, filter_date) without breaking callers
) -> dict[str, Any]:
    """Scrape the detail page for one pelayanan record.

    Fast path:
      1. Sequential: `GET /pelayanan/show/{pid}` + `GET /anamnesa/create/{pid}?…`.
         The Anamnesa response is the tab-discovery bootstrap AND the Anamnesa
         tab's own content, so it's used twice.
      2. Parallel (ThreadPool, stdlib urllib): fetch every other discovered
         tab URL concurrently. Cookies come from `context.cookies()` so auth
         is preserved without going through Playwright's sync IPC.
      3. Batch parse: all tab HTMLs (Anamnesa + the parallel-fetched ones)
         are parsed in a single `page.evaluate` call, avoiding one IPC
         round-trip per tab.
    """
    show_url = f"{base_url}/pelayanan/show/{pelayanan_id}"
    bootstrap_url = (
        f"{base_url}/anamnesa/create/{pelayanan_id}"
        f"?from='pelayanan'&action='edit'"
    )

    # Step 1: show + anamnesa bootstrap, in parallel (2 fetches).
    cookie_header = _cookie_header_from_context(context)
    initial = _parallel_fetch(
        [show_url, bootstrap_url],
        cookie_header=cookie_header,
        user_agent=_USER_AGENT,
        max_workers=2,
    )
    show_status, show_html, show_err = initial[show_url]
    if show_err or not show_html:
        raise RuntimeError(f"Failed to fetch {show_url}: {show_err or f'HTTP {show_status}'}")
    boot_status, bootstrap_html, boot_err = initial[bootstrap_url]
    if boot_err or not bootstrap_html:
        raise RuntimeError(f"Failed to fetch {bootstrap_url}: {boot_err or f'HTTP {boot_status}'}")

    show_parsed = _parse_show_html(page, show_html)
    discovered = _extract_tab_bar(page, bootstrap_html, pelayanan_id=pelayanan_id)
    discovered = _merge_known_modules(discovered, base_url=base_url, pelayanan_id=pelayanan_id)

    # Step 2: parallel-fetch every tab EXCEPT Anamnesa (we already have it).
    other_tabs = [t for t in discovered if t["module"] != "anamnesa"]
    other_urls = [t["url"] for t in other_tabs]
    responses = _parallel_fetch(
        other_urls,
        cookie_header=cookie_header,
        referer=show_url,
        user_agent=_USER_AGENT,
        max_workers=max_parallel_fetches,
    ) if other_urls else {}

    # Step 3: batch-parse Anamnesa + all successful tab HTMLs in one shot.
    # Keep a parallel list of (label, module, url) so we can stitch the
    # parsed results back with their metadata.
    to_parse: list[tuple[str, str, str, str]] = []  # (label, module, url, html)
    failures: list[tuple[str, str, str, str]] = []  # (label, module, url, err_msg)

    anamnesa_label = next((t["label"] for t in discovered if t["module"] == "anamnesa"), "Anamnesa")
    to_parse.append((anamnesa_label, "anamnesa", bootstrap_url, bootstrap_html))

    for tab in other_tabs:
        status, body, err = responses[tab["url"]]
        bad = err or not body or (body and "halaman tidak ditemukan" in body.lower())
        if bad:
            # Safety-net (probed) modules that don't apply to this patient/region
            # return 404 / a soft-404 page — drop silently, no error stub.
            if tab.get("probed"):
                continue
            failures.append((tab["label"], tab["module"], tab["url"],
                             err or f"HTTP {status}"))
        else:
            to_parse.append((tab["label"], tab["module"], tab["url"], body))

    htmls = [item[3] for item in to_parse]
    parsed_list = _parse_tabs_batch(page, htmls) if htmls else []

    tabs: dict[str, Any] = {}
    for (label, module, url, _), parsed in zip(to_parse, parsed_list):
        tabs[label] = {"url": url, "module": module, **parsed}
    for label, module, url, err_msg in failures:
        tabs[label] = {"url": url, "module": module, "error": err_msg}

    ckg = _fetch_ckg(
        show_html,
        base_url=base_url,
        cookie_header=cookie_header,
        user_agent=_USER_AGENT,
        referer=show_url,
    )

    # Formulir Skrining battery + CPPT — read-only, from the same show page's
    # CSRF token + visit year. Both degrade to empty on any failure.
    csrf = _csrf_token(show_html)
    year = _visit_year(show_html)
    skrining = _attach_skrining_detail(page, _fetch_skrining(
        base_url=base_url, cookie_header=cookie_header, user_agent=_USER_AGENT,
        pelayanan_id=str(pelayanan_id), csrf=csrf, year=year, referer=show_url,
    ))
    cppt = _fetch_cppt(
        base_url=base_url, cookie_header=cookie_header, user_agent=_USER_AGENT,
        pelayanan_id=str(pelayanan_id), year=year, referer=show_url,
    )
    # Data Skrining detail pages (read-only) — one fetch per legacy row's
    # detail_href, parsed with the tab form parser. Mutates the list in place.
    data_skrining_rows = show_parsed.get("data_skrining") or []
    _fetch_data_skrining_details(
        page, data_skrining_rows, base_url=base_url, cookie_header=cookie_header,
        user_agent=_USER_AGENT, referer=show_url, max_parallel_fetches=max_parallel_fetches,
    )
    # Bayi-only: recover ikterus classification (mtbm) + PJB pulse-ox form.
    _augment_bayi_forms(
        page, tabs, base_url=base_url, cookie_header=cookie_header,
        pelayanan_id=str(pelayanan_id), show_parsed=show_parsed, to_parse=to_parse,
    )

    return {
        "pelayanan_id": pelayanan_id,
        "data_pasien": show_parsed.get("data_pasien") or {},
        "penyakit_khusus": show_parsed.get("penyakit_khusus") or [],
        "risiko_kehamilan": show_parsed.get("risiko_kehamilan") or [],
        "riwayat_pasien": show_parsed.get("riwayat_pasien") or [],
        "alergi": show_parsed.get("alergi") or [],
        "data_skrining": data_skrining_rows,
        "rujukan": show_parsed.get("rujukan") or {},
        "surat_keterangan": show_parsed.get("surat_keterangan") or {},
        "ckg": ckg,
        "skrining_klaster": skrining,
        "cppt": cppt,
        "tabs": tabs,
    }


# ---------------------------------------------------------------------------
# Batched concurrent scrape across N patients
# ---------------------------------------------------------------------------
# Output shape per patient is byte-identical to scrape_patient_detail().
# Outer parallelism is at the fetch level only. page.evaluate parse stays on
# main thread (Playwright sync API is not thread-safe).
#
# Per chunk of `max_patient_workers` patients:
#   Stage 1 — fetch (show + anam) for all chunk patients in ONE ThreadPool.
#   Discovery — main thread calls _extract_tab_bar(page, anam_html) per pid.
#   Stage 2 — fetch every chunk patient's tab URLs together in ONE ThreadPool.
#   Stage 3 — main thread runs _parse_show_html + _parse_tabs_batch per pid.
#
# Failure isolation: any per-patient exception is captured into
# {pelayanan_id, error: …} so chunk-mates still complete.
# Pipeline mode (default ON; EPUS_PIPELINE=0 → the old chunk-at-a-time path).
# The per-patient bottleneck is the page.evaluate parse (~1.3s/patient, serial
# on the single Playwright page), NOT the fetches (already parallel httpx). So
# while the main thread PARSES chunk k on the page, a background thread PREFETCHES
# chunk k+1's tab + secondary HTML (pure httpx, no page touch). This hides the
# fetch behind the parse — the data is byte-identical because the SAME discovery,
# URLs, fetches and parses run; only their timing overlaps.
_PIPELINE_ENABLED = os.environ.get("EPUS_PIPELINE", "1") == "1"


def scrape_patients_concurrent(
    context: BrowserContext,
    page: Page,
    *,
    base_url: str,
    pelayanan_ids: list[str],
    max_parallel_fetches: int = 10,
    max_patient_workers: int = 3,
    on_progress=None,  # called as on_progress(pelayanan_id, completed, total)
) -> list[dict[str, Any]]:
    cookie_header = _cookie_header_from_context(context)
    total = len(pelayanan_ids)
    out: list[dict[str, Any]] = []
    completed = 0
    chunk_size = max(1, max_patient_workers)
    chunks = [
        [str(p) for p in pelayanan_ids[i:i + chunk_size]]
        for i in range(0, total, chunk_size)
    ]

    def _progress(chunk):
        nonlocal completed
        for pid in chunk:
            completed += 1
            if on_progress is not None:
                on_progress(pid, completed, total)

    # Non-pipelined fallback (single chunk has nothing to overlap with).
    if not _PIPELINE_ENABLED or len(chunks) <= 1:
        for chunk in chunks:
            out.extend(_process_patient_chunk(
                page, base_url=base_url, cookie_header=cookie_header,
                pelayanan_ids=chunk, max_parallel_fetches=max_parallel_fetches,
                chunk_workers=chunk_size,
            ))
            _progress(chunk)
        return out

    # Pipelined: prep+discover (page) → submit IO (bg) → assemble (page) while the
    # NEXT chunk's IO runs in the background.
    with ThreadPoolExecutor(max_workers=1) as io_pool:
        prelim_cur = _prep_chunk(
            page, base_url=base_url, cookie_header=cookie_header,
            pelayanan_ids=chunks[0], chunk_workers=chunk_size,
        )
        io_fut = io_pool.submit(
            _fetch_chunk_io, base_url=base_url, cookie_header=cookie_header,
            prelim=prelim_cur, max_parallel_fetches=max_parallel_fetches,
            chunk_workers=chunk_size,
        )
        for k, chunk in enumerate(chunks):
            try:
                io_cur = io_fut.result()
            except Exception as e:
                # Defensive: the bg IO future should never raise (every fetcher
                # degrades internally), but if it ever does, don't fail the whole
                # job — reprocess this chunk via the self-contained inline path.
                console.print(f"  [yellow]pipeline IO failed for chunk {k}: {e}; "
                              f"reprocessing inline[/yellow]")
                io_cur = None
            # Kick the NEXT chunk's IO so it overlaps THIS chunk's parse below.
            if k + 1 < len(chunks):
                prelim_next = _prep_chunk(
                    page, base_url=base_url, cookie_header=cookie_header,
                    pelayanan_ids=chunks[k + 1], chunk_workers=chunk_size,
                )
                io_fut = io_pool.submit(
                    _fetch_chunk_io, base_url=base_url, cookie_header=cookie_header,
                    prelim=prelim_next, max_parallel_fetches=max_parallel_fetches,
                    chunk_workers=chunk_size,
                )
            else:
                prelim_next = None
            if io_cur is None:
                out.extend(_process_patient_chunk(
                    page, base_url=base_url, cookie_header=cookie_header,
                    pelayanan_ids=chunk, max_parallel_fetches=max_parallel_fetches,
                    chunk_workers=chunk_size,
                ))
            else:
                out.extend(_assemble_chunk(
                    page, base_url=base_url, cookie_header=cookie_header,
                    prelim=prelim_cur, io=io_cur, max_parallel_fetches=max_parallel_fetches,
                ))
            _progress(chunk)
            prelim_cur = prelim_next
    return out


# --- Pipeline phases (split out of _process_patient_chunk; same logic, reordered
#     so the page-free IO of one chunk can run while the page parses another) ---
def _prep_chunk(
    page: Page, *, base_url: str, cookie_header: str,
    pelayanan_ids: list[str], chunk_workers: int,
) -> dict[str, dict]:
    """Page phase: fetch show+anam (stage1) and run tab-bar discovery. Returns a
    per-pid prelim bundle. Discovery stays on the page so the URL set is byte-for
    -byte what the non-pipelined path produces."""
    show_urls = {pid: f"{base_url}/pelayanan/show/{pid}" for pid in pelayanan_ids}
    anam_urls = {
        pid: f"{base_url}/anamnesa/create/{pid}?from='pelayanan'&action='edit'"
        for pid in pelayanan_ids
    }
    stage1 = _parallel_fetch(
        list(show_urls.values()) + list(anam_urls.values()),
        cookie_header=cookie_header, user_agent=_USER_AGENT,
        max_workers=max(2, chunk_workers * 2),
    )
    prelim: dict[str, dict] = {}
    for pid in pelayanan_ids:
        a_st, a_body, a_err = stage1[anam_urls[pid]]
        if a_err or not a_body:
            disc = []
        else:
            try:
                disc = _extract_tab_bar(page, a_body, pelayanan_id=pid)
            except Exception as e:
                console.print(
                    f"  [yellow]tab-discovery failed for {pid}: {e}; "
                    f"falling back to known modules[/yellow]"
                )
                disc = []
        prelim[pid] = {
            "show_url": show_urls[pid], "anam_url": anam_urls[pid],
            "show": stage1[show_urls[pid]], "anam": stage1[anam_urls[pid]],
            "tabs": _merge_known_modules(disc, base_url=base_url, pelayanan_id=pid),
        }
    return prelim


def _fetch_chunk_io(
    *, base_url: str, cookie_header: str, prelim: dict[str, dict],
    max_parallel_fetches: int, chunk_workers: int,
) -> dict[str, Any]:
    """Page-free IO phase (safe to run on a background thread): fetch every tab
    URL (stage2) plus each patient's ckg/skrin/cppt. These secondary fetchers
    degrade internally, but we still isolate per-pid so one failure can't break
    the chunk's IO future."""
    all_tab_urls = [
        t["url"] for pb in prelim.values() for t in pb["tabs"]
        if t["module"] != "anamnesa"
    ]

    def do_stage2():
        if not all_tab_urls:
            return {}
        return _parallel_fetch(
            all_tab_urls, cookie_header=cookie_header, user_agent=_USER_AGENT,
            max_workers=min(len(all_tab_urls), max(1, max_parallel_fetches)),
        )

    def do_sec(pid):
        pb = prelim[pid]
        s_st, s_body, s_err = pb["show"]
        if s_err or not s_body:
            return pid, {"ckg": None, "skrin": {}, "cppt": None, "err": None}
        try:
            ckg = _fetch_ckg(
                s_body, base_url=base_url, cookie_header=cookie_header,
                user_agent=_USER_AGENT, referer=pb["show_url"],
            )
            csrf = _csrf_token(s_body)
            year = _visit_year(s_body)
            skrin = _fetch_skrining(
                base_url=base_url, cookie_header=cookie_header, user_agent=_USER_AGENT,
                pelayanan_id=str(pid), csrf=csrf, year=year, referer=pb["show_url"],
            )
            cppt = _fetch_cppt(
                base_url=base_url, cookie_header=cookie_header, user_agent=_USER_AGENT,
                pelayanan_id=str(pid), year=year, referer=pb["show_url"],
            )
            return pid, {"ckg": ckg, "skrin": skrin, "cppt": cppt, "err": None}
        except Exception as e:
            return pid, {"err": str(e)}

    sec: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=max(2, chunk_workers + 1)) as pool:
        stage2_fut = pool.submit(do_stage2)
        sec_futs = [pool.submit(do_sec, pid) for pid in prelim]
        stage2 = stage2_fut.result()
        for f in sec_futs:
            pid, data = f.result()
            sec[pid] = data
    return {"stage2": stage2, "sec": sec}


def _assemble_chunk(
    page: Page, *, base_url: str, cookie_header: str,
    prelim: dict[str, dict], io: dict[str, Any], max_parallel_fetches: int,
) -> list[dict[str, Any]]:
    """Page phase: parse show + tabs, attach prefetched secondary data, fetch+parse
    the data_skrining details (needs parse_show first), and build each patient dict.
    Output shape is byte-identical to _process_patient_chunk."""
    stage2 = io["stage2"]
    sec = io["sec"]
    out: list[dict[str, Any]] = []
    for pid, pb in prelim.items():
        try:
            s_url, a_url = pb["show_url"], pb["anam_url"]
            s_st, s_body, s_err = pb["show"]
            if s_err or not s_body:
                raise RuntimeError(f"Failed to fetch {s_url}: {s_err or f'HTTP {s_st}'}")
            a_st, a_body, a_err = pb["anam"]
            if a_err or not a_body:
                raise RuntimeError(f"Failed to fetch {a_url}: {a_err or f'HTTP {a_st}'}")
            sec_pid = sec.get(pid) or {}
            if sec_pid.get("err"):
                raise RuntimeError(f"secondary fetch failed: {sec_pid['err']}")

            discovered = pb["tabs"]
            anam_label = next(
                (t["label"] for t in discovered if t["module"] == "anamnesa"),
                "Anamnesa",
            )
            to_parse: list[tuple[str, str, str, str]] = [
                (anam_label, "anamnesa", a_url, a_body)
            ]
            failures: list[tuple[str, str, str, str]] = []
            for t in discovered:
                if t["module"] == "anamnesa":
                    continue
                st, body, err = stage2[t["url"]]
                bad = err or not body or (body and "halaman tidak ditemukan" in body.lower())
                if bad:
                    if t.get("probed"):
                        continue
                    failures.append((t["label"], t["module"], t["url"], err or f"HTTP {st}"))
                else:
                    to_parse.append((t["label"], t["module"], t["url"], body))

            htmls = [item[3] for item in to_parse]
            parsed_list = _parse_tabs_batch(page, htmls) if htmls else []
            tabs_out: dict[str, Any] = {}
            for (label, module, url, _), parsed in zip(to_parse, parsed_list):
                tabs_out[label] = {"url": url, "module": module, **parsed}
            for label, module, url, err_msg in failures:
                tabs_out[label] = {"url": url, "module": module, "error": err_msg}

            show_parsed = _parse_show_html(page, s_body)
            ckg = sec_pid.get("ckg")
            skrining = _attach_skrining_detail(page, sec_pid.get("skrin") or {})
            cppt = sec_pid.get("cppt")
            data_skrining_rows = show_parsed.get("data_skrining") or []
            _fetch_data_skrining_details(
                page, data_skrining_rows, base_url=base_url, cookie_header=cookie_header,
                user_agent=_USER_AGENT, referer=s_url, max_parallel_fetches=max_parallel_fetches,
            )
            _augment_bayi_forms(
                page, tabs_out, base_url=base_url, cookie_header=cookie_header,
                pelayanan_id=str(pid), show_parsed=show_parsed, to_parse=to_parse,
            )
            out.append({
                "pelayanan_id": pid,
                "data_pasien": show_parsed.get("data_pasien") or {},
                "penyakit_khusus": show_parsed.get("penyakit_khusus") or [],
                "risiko_kehamilan": show_parsed.get("risiko_kehamilan") or [],
                "riwayat_pasien": show_parsed.get("riwayat_pasien") or [],
                "alergi": show_parsed.get("alergi") or [],
                "data_skrining": data_skrining_rows,
                "rujukan": show_parsed.get("rujukan") or {},
                "surat_keterangan": show_parsed.get("surat_keterangan") or {},
                "ckg": ckg,
                "skrining_klaster": skrining,
                "cppt": cppt,
                "tabs": tabs_out,
            })
        except Exception as e:
            out.append({"pelayanan_id": pid, "error": str(e)})
    return out


def _process_patient_chunk(
    page: Page,
    *,
    base_url: str,
    cookie_header: str,
    pelayanan_ids: list[str],
    max_parallel_fetches: int,
    chunk_workers: int,
) -> list[dict[str, Any]]:
    show_urls = {pid: f"{base_url}/pelayanan/show/{pid}" for pid in pelayanan_ids}
    anam_urls = {
        pid: f"{base_url}/anamnesa/create/{pid}?from='pelayanan'&action='edit'"
        for pid in pelayanan_ids
    }
    s1_urls = list(show_urls.values()) + list(anam_urls.values())
    stage1 = _parallel_fetch(
        s1_urls,
        cookie_header=cookie_header,
        user_agent=_USER_AGENT,
        max_workers=max(2, chunk_workers * 2),
    )

    per_pid_tabs: dict[str, list[dict[str, str]]] = {}
    for pid in pelayanan_ids:
        a_st, a_body, a_err = stage1[anam_urls[pid]]
        if a_err or not a_body:
            disc = []
        else:
            # This discovery loop runs OUTSIDE the per-patient try/except in the
            # assembly loop below, so an exception here would abort the whole
            # run. Isolate it: on failure degrade to the known-module safety net
            # for this pid (same as the no-body fallback above) instead of
            # killing every remaining patient.
            try:
                disc = _extract_tab_bar(page, a_body, pelayanan_id=pid)
            except Exception as e:
                console.print(
                    f"  [yellow]tab-discovery failed for {pid}: {e}; "
                    f"falling back to known modules[/yellow]"
                )
                disc = []
        # Union with the known-module safety net so builds whose Anamnesa bar
        # under-lists modules (jaksel) still fetch every known module.
        per_pid_tabs[pid] = _merge_known_modules(disc, base_url=base_url, pelayanan_id=pid)

    all_tab_urls: list[str] = []
    for pid in pelayanan_ids:
        for t in per_pid_tabs[pid]:
            if t["module"] != "anamnesa":
                all_tab_urls.append(t["url"])
    if all_tab_urls:
        # Cap concurrent tab fetches at max_parallel_fetches (NOT multiplied
        # by chunk_workers). Bursting 30+ concurrent reqs to one host triggers
        # server-side throttling — slows responses for the whole burst.
        stage2 = _parallel_fetch(
            all_tab_urls,
            cookie_header=cookie_header,
            user_agent=_USER_AGENT,
            max_workers=min(len(all_tab_urls), max(1, max_parallel_fetches)),
        )
    else:
        stage2 = {}

    out: list[dict[str, Any]] = []
    for pid in pelayanan_ids:
        try:
            s_url = show_urls[pid]
            a_url = anam_urls[pid]
            s_st, s_body, s_err = stage1[s_url]
            if s_err or not s_body:
                raise RuntimeError(f"Failed to fetch {s_url}: {s_err or f'HTTP {s_st}'}")
            a_st, a_body, a_err = stage1[a_url]
            if a_err or not a_body:
                raise RuntimeError(f"Failed to fetch {a_url}: {a_err or f'HTTP {a_st}'}")

            discovered = per_pid_tabs[pid]
            anam_label = next(
                (t["label"] for t in discovered if t["module"] == "anamnesa"),
                "Anamnesa",
            )

            to_parse: list[tuple[str, str, str, str]] = [
                (anam_label, "anamnesa", a_url, a_body)
            ]
            failures: list[tuple[str, str, str, str]] = []
            for t in discovered:
                if t["module"] == "anamnesa":
                    continue
                st, body, err = stage2[t["url"]]
                bad = err or not body or (body and "halaman tidak ditemukan" in body.lower())
                if bad:
                    # Probed safety-net module that doesn't apply here → drop silently.
                    if t.get("probed"):
                        continue
                    failures.append((t["label"], t["module"], t["url"], err or f"HTTP {st}"))
                else:
                    to_parse.append((t["label"], t["module"], t["url"], body))

            htmls = [item[3] for item in to_parse]
            parsed_list = _parse_tabs_batch(page, htmls) if htmls else []

            tabs_out: dict[str, Any] = {}
            for (label, module, url, _), parsed in zip(to_parse, parsed_list):
                tabs_out[label] = {"url": url, "module": module, **parsed}
            for label, module, url, err_msg in failures:
                tabs_out[label] = {"url": url, "module": module, "error": err_msg}

            show_parsed = _parse_show_html(page, s_body)
            ckg = _fetch_ckg(
                s_body,
                base_url=base_url,
                cookie_header=cookie_header,
                user_agent=_USER_AGENT,
                referer=s_url,
            )
            csrf = _csrf_token(s_body)
            year = _visit_year(s_body)
            skrining = _attach_skrining_detail(page, _fetch_skrining(
                base_url=base_url, cookie_header=cookie_header, user_agent=_USER_AGENT,
                pelayanan_id=str(pid), csrf=csrf, year=year, referer=s_url,
            ))
            cppt = _fetch_cppt(
                base_url=base_url, cookie_header=cookie_header, user_agent=_USER_AGENT,
                pelayanan_id=str(pid), year=year, referer=s_url,
            )
            data_skrining_rows = show_parsed.get("data_skrining") or []
            _fetch_data_skrining_details(
                page, data_skrining_rows, base_url=base_url, cookie_header=cookie_header,
                user_agent=_USER_AGENT, referer=s_url, max_parallel_fetches=max_parallel_fetches,
            )
            _augment_bayi_forms(
                page, tabs_out, base_url=base_url, cookie_header=cookie_header,
                pelayanan_id=str(pid), show_parsed=show_parsed, to_parse=to_parse,
            )
            out.append({
                "pelayanan_id": pid,
                "data_pasien": show_parsed.get("data_pasien") or {},
                "penyakit_khusus": show_parsed.get("penyakit_khusus") or [],
                "risiko_kehamilan": show_parsed.get("risiko_kehamilan") or [],
                "riwayat_pasien": show_parsed.get("riwayat_pasien") or [],
                "alergi": show_parsed.get("alergi") or [],
                "data_skrining": data_skrining_rows,
                "rujukan": show_parsed.get("rujukan") or {},
                "surat_keterangan": show_parsed.get("surat_keterangan") or {},
                "ckg": ckg,
                "skrining_klaster": skrining,
                "cppt": cppt,
                "tabs": tabs_out,
            })
        except Exception as e:
            out.append({"pelayanan_id": pid, "error": str(e)})
    return out


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------
# We have two fetch paths:
#
#   - `_fetch_html(context, url)` — Playwright's `context.request.get`.
#     Used for the handful of sequential fetches at the start of each
#     patient (show page + Anamnesa bootstrap) where we need auth through
#     the same cookie jar that's also tracking things like CSRF.
#
#   - `_parallel_fetch(urls, cookie_header)` — stdlib `urllib` run through
#     a `ThreadPoolExecutor`. Playwright's sync API is single-threaded
#     (blocks on IPC to the browser), so we can't parallelize through it.
#     Extracting cookies once per patient into a `Cookie:` header lets us
#     use plain HTTP with any number of worker threads — major speedup
#     when fetching 30+ tab pages per patient.
#
# Both are read-only. No JS ever runs against these responses. Cookies
# are read from `context.cookies()` which does not mutate anything.

def _fetch_html(context: BrowserContext, url: str, *, referer: str | None = None) -> str:
    """Fetch a URL's raw body. Uses the context's cookies so auth is
    automatic. No JS is executed — this is safe against auto-firing write
    XHRs like /klaster_siklushidup/{id}."""
    headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    if referer:
        headers["Referer"] = referer
    resp = context.request.get(url, timeout=60000, headers=headers)
    if resp.status != 200:
        raise RuntimeError(f"Failed to fetch {url}: HTTP {resp.status}")
    return resp.text()


def _cookie_header_from_context(context: BrowserContext) -> str:
    """Build a 'Cookie: …' header string from the browser context's cookie
    jar. Called once per patient; passed to every parallel worker."""
    parts = []
    for c in context.cookies():
        name = c.get("name")
        value = c.get("value", "")
        if name:
            parts.append(f"{name}={value}")
    return "; ".join(parts)


_DEFAULT_FETCH_TIMEOUT = float(os.environ.get("EPUS_FETCH_TIMEOUT", "30"))
_DEFAULT_FETCH_RETRIES = int(os.environ.get("EPUS_FETCH_RETRIES", "2"))
_DEFAULT_BACKOFF_BASE = float(os.environ.get("EPUS_FETCH_BACKOFF_BASE", "1.0"))
_DEFAULT_POOL_SIZE = int(os.environ.get("EPUS_FETCH_POOL", "20"))
# HTTP/2 multiplexes a patient's ~33 tab GETs over one connection (the ePus
# portals are Cloudflare-fronted and negotiate h2). Benchmarked OFF by default
# after measuring it on all three portals: on a FAST origin (kotabekasi) it's
# ~1.2x faster and byte-identical, but on a SLOW origin (jaksel) the extra
# in-flight concurrency makes Cloudflare throttle MORE — net SLOWER (retries)
# and it raised the transient drop-rate on valid detail pages (see the dsd
# retry note below). Since jaksel is the throughput bottleneck, h2 is opt-in:
# set EPUS_HTTP2=1 only for deployments whose origins are fast.
_HTTP2_ENABLED = os.environ.get("EPUS_HTTP2", "0") == "1"
_TRANSIENT_HTTP_CODES = {408, 425, 429, 500, 502, 503, 504}


_http_client: httpx.Client | None = None
_http_client_lock = threading.Lock()


def _get_http_client() -> httpx.Client:
    """Lazy singleton httpx.Client with HTTP/2 multiplexing + keepalive + gzip.

    HTTP/2 (default; EPUS_HTTP2=0 to disable) collapses a patient's ~33 tab
    GETs onto one multiplexed connection — ~1.7x faster than the HTTP/1.1
    10-connection cap with zero change to response bodies (verified
    byte-identical). Persistent connections amortize the TLS handshake and
    `Accept-Encoding: gzip, deflate` cuts HTML bytes ~5x. Thread-safe per
    httpx docs. Lifetime = scraper subprocess lifetime; OS releases sockets
    on exit. Degrades to HTTP/1.1 if the optional `h2` package is missing.
    """
    global _http_client
    if _http_client is None:
        with _http_client_lock:
            if _http_client is None:
                use_h2 = _HTTP2_ENABLED
                if use_h2:
                    try:
                        import h2  # noqa: F401  (httpx needs it for http2=True)
                    except ImportError:
                        console.print(
                            "  [yellow]EPUS_HTTP2=1 but 'h2' not installed — "
                            "falling back to HTTP/1.1[/yellow]"
                        )
                        use_h2 = False
                _http_client = httpx.Client(
                    http2=use_h2,
                    follow_redirects=True,
                    timeout=httpx.Timeout(_DEFAULT_FETCH_TIMEOUT),
                    limits=httpx.Limits(
                        max_connections=_DEFAULT_POOL_SIZE,
                        max_keepalive_connections=_DEFAULT_POOL_SIZE,
                        keepalive_expiry=300.0,
                    ),
                    # Client-level defaults; per-request headers override.
                    headers={
                        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                        "Accept-Encoding": "gzip, deflate",
                    },
                )
    return _http_client


def _parallel_fetch(
    urls: list[str],
    *,
    cookie_header: str,
    referer: str | None = None,
    user_agent: str,
    max_workers: int = 10,
    timeout: float = _DEFAULT_FETCH_TIMEOUT,
    retries: int = _DEFAULT_FETCH_RETRIES,
    transient_codes: "frozenset[int] | set[int]" = _TRANSIENT_HTTP_CODES,
) -> dict[str, tuple[int, str | None, str | None]]:
    """Fetch every URL concurrently via shared httpx.Client (HTTP/1.1 +
    keepalive + gzip). Drop-in replacement for the previous urllib impl.

    Returns ``{url: (status, body, error)}``. Exactly one of ``body`` or
    ``error`` is non-None per entry:
      - success → ``(200, html, None)``
      - HTTP error → ``(code, None, "HTTP {code}")``
      - transport error → ``(0, None, str(exc))``

    Retry policy: on timeouts, transport errors, and HTTP 408/425/429/5xx,
    retry up to ``retries`` extra times with exponential backoff
    (``base × 2^attempt`` + url-hash jitter). Tuned via env vars
    ``EPUS_FETCH_TIMEOUT`` (default 30s), ``EPUS_FETCH_RETRIES`` (default 2),
    ``EPUS_FETCH_BACKOFF_BASE`` (default 1.0s), ``EPUS_FETCH_POOL``
    (default 20 connections).
    """
    per_request_headers: dict[str, str] = {
        "Cookie": cookie_header,
        "User-Agent": user_agent,
    }
    if referer:
        per_request_headers["Referer"] = referer

    client = _get_http_client()

    def fetch_once(url: str):
        try:
            r = client.get(url, headers=per_request_headers, timeout=timeout)
        except (httpx.ReadTimeout, httpx.ConnectTimeout, httpx.WriteTimeout,
                httpx.PoolTimeout, httpx.NetworkError, httpx.RemoteProtocolError) as e:
            return (0, None, f"{type(e).__name__}: {e}", True)
        except Exception as e:
            return (0, None, f"{type(e).__name__}: {e}", False)
        if r.status_code < 400:
            try:
                body = r.text
            except UnicodeDecodeError:
                body = r.content.decode("utf-8", errors="replace")
            return (r.status_code, body, None, False)
        return (
            r.status_code,
            None,
            f"HTTP {r.status_code}",
            r.status_code in transient_codes,
        )

    def fetch_one(url: str):
        last = (0, None, "no attempts", False)
        for attempt in range(retries + 1):
            status, body, err, transient = fetch_once(url)
            if err is None:
                return url, (status, body, None)
            last = (status, body, err, transient)
            if not transient or attempt == retries:
                break
            sleep_s = _DEFAULT_BACKOFF_BASE * (2 ** attempt) + ((hash(url) % 100) / 1000.0)
            time.sleep(sleep_s)
        return url, (last[0], last[1], last[2])

    out: dict[str, tuple[int, str | None, str | None]] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        for url, result in pool.map(fetch_one, urls):
            out[url] = result
    return out


# ---------------------------------------------------------------------------
# Tab discovery — dynamic, from the Anamnesa page's tab bar.
#
# Rationale: we tested multiple candidate "source of truth" pages:
#   - /pelayanan/show/{pid}            — unreliable (renders only 2–8 tab
#                                        anchors depending on patient state)
#   - /anamnesa/create/{pid}?…         — reliable: always renders the full
#                                        tab bar across every patient tested
#   - /konfigurasiform, /master, …     — no JSON module manifest exists
#
# So the scraper fetches the Anamnesa page once per patient and extracts
# its tab-bar anchors. Since the Anamnesa response is already needed for
# the Anamnesa tab's own fields, this adds zero extra fetches.
#
# What counts as a "tab anchor":
#   - <a href> whose path contains the current pelayanan_id as the last
#     segment (strips out global nav like /loket/panggilantrean,
#     /user/profile which have no pid),
#   - visible text 1..60 chars (strips icon-only links like CPPT),
#   - first match per module slug (dedupe repeated entries).
#
# If Kemkes adds a new module or renames one, the next run picks it up
# automatically — no code change needed.
_GLOBAL_NAV_MODULES = {
    # These appear in the Anamnesa page but are site nav, not patient tabs.
    "loket", "user", "pelayanan", "home", "logout",
    "laporan", "laporansipukp1", "laporansipukp2",
    "konfigurasiform", "konfigurasilayanankhusus",
}


_TAB_BAR_JS = r"""
({ html, pid }) => {
    const doc = new DOMParser().parseFromString(html, 'text/html');
    const out = [];
    const seen = new Set();

    for (const a of doc.querySelectorAll('a[href]')) {
        const href = a.getAttribute('href') || '';
        if (!href) continue;
        let url;
        try {
            url = new URL(href, 'https://kotabekasi.epuskesmas.id');
        } catch (e) { continue; }
        const path = url.pathname;

        // Path must contain the pelayanan_id — that's what separates patient
        // tabs (/anamnesa/create/197732) from global nav (/loket, /home).
        // Accept any path that ends with the pid (after an optional action
        // segment like create / edit / create_pengkajian).
        const segs = path.split('/').filter(Boolean);
        if (segs.length < 2) continue;
        if (segs[segs.length - 1] !== String(pid)) continue;

        const mod = segs[0].toLowerCase();
        if (seen.has(mod)) continue;

        const text = (a.innerText || '').replace(/\s+/g, ' ').trim();
        // Require visible text — icon-only links (CPPT's note viewer, +/edit
        // icons) have empty innerText and aren't part of the main tab bar.
        if (!text || text.length > 60) continue;

        seen.add(mod);
        out.push({ module: mod, label: text, url: url.toString() });
    }
    return out;
}
"""


def _extract_tab_bar(page: Page, html: str, *, pelayanan_id: str) -> list[dict[str, str]]:
    discovered = page.evaluate(
        _TAB_BAR_JS,
        {"html": html, "pid": str(pelayanan_id)},
    )
    # Drop global-nav entries that slipped through (e.g. if a nav link
    # happens to end in the pid). None of the 31 real modules collide with
    # _GLOBAL_NAV_MODULES, so this is a safe additional guard.
    return [t for t in discovered if t["module"] not in _GLOBAL_NAV_MODULES]


# ---------------------------------------------------------------------------
# Known-module safety net — Anamnesa-bar discovery is NECESSARY (catches a new /
# renamed module automatically) but NOT SUFFICIENT: the per-region builds list
# DIFFERENT subsets of modules in their Anamnesa tab bar. Verified live 2026-06-05:
# jaksel's new build lists only ~15 of the ~33 modules that GET /{module}/create/
# {pid} actually serves WITH DATA, so pure bar-discovery silently dropped 17 tabs
# per patient for the LARGEST region (covid19, tbparu, mata, konselinghiv,
# periksaiva/ims, pkpr, psikologi, kohort, mtbsv2, imunisasi, kb, caten,
# odontogram, periksagizi, anestesibedah, kartubayi). kotabekasi/kotatangerang
# list them, jaksel doesn't.
#
# Fix: union the bar-discovery with this known-module set so EVERY known module is
# fetched regardless of which ones a build's bar happens to render. Discovery stays
# dynamic (a module in the bar but NOT here is still picked up → future modules
# auto-handled); this union just guarantees we never MISS a known module on a
# build that hides it. URL templates mirror the patterns the bars use; a module
# that genuinely doesn't apply to a patient/region returns 404 and is dropped
# (probed-only modules don't leave error stubs — see the callers).
_KNOWN_MODULE_URL_TMPL = {
    # modules whose route is NOT /{m}/create/{pid}
    "haji": "{base}/haji/{pid}",
    "pal": "{base}/pal/{pid}",
    "askep": "{base}/askep/create_pengkajian/{pid}",
}
_DEFAULT_MODULE_URL_TMPL = "{base}/{m}/create/{pid}?from='pelayanan'&action='edit'"
_KNOWN_MODULES = (
    "anamnesa", "diagnosa", "resep", "alkes", "obatpasien", "odontogram",
    "laboratorium", "tindakan", "mtbsv2", "mtbm", "imunisasi", "kartubayi", "keur", "kb",
    "pkpr", "kohort", "periksagizi", "tbparu", "periksaims", "konselinghiv",
    "askep", "periksaiva", "kpsp", "caten", "ptm", "mata", "pengkajianresikojatuh",
    "prima", "psikologi", "pal", "haji", "covid19", "diare", "anestesibedah",
)
# `mtbm` (Manajemen Terpadu Bayi Muda — young-infant) added 2026-06-25: it is a
# DISTINCT module from `mtbsv2` (MTBS = balita sakit) and holds the newborn exam,
# incl. the Pemeriksaan Jantung Bawaan pulse-oximetry (SpO2 tangan/kaki) the ASIK
# bayi form needs. The Anamnesa bar under-lists it (verified live jaksel 2026-06-25:
# /mtbm/create/{pid} serves the form but the bar only renders MTBS), so the bayi
# PJB source was silently dropped. Non-bayi patients 404 and are dropped (probed).


def _module_url(base_url: str, module: str, pelayanan_id: str) -> str:
    tmpl = _KNOWN_MODULE_URL_TMPL.get(module, _DEFAULT_MODULE_URL_TMPL)
    return tmpl.format(base=base_url, m=module, pid=pelayanan_id)


def _merge_known_modules(
    discovered: list[dict[str, str]], *, base_url: str, pelayanan_id: str
) -> list[dict[str, str]]:
    """Union bar-discovered tabs with the known-module safety net. Bar tabs keep
    their real href + label; safety-net additions are flagged ``probed=True`` so
    a caller can drop them (instead of emitting an error stub) when they 404."""
    seen = {t["module"] for t in discovered}
    out = [dict(t) for t in discovered]
    for m in _KNOWN_MODULES:
        if m in seen:
            continue
        out.append({
            "module": m,
            "label": m.replace("_", " ").title(),
            "url": _module_url(base_url, m, str(pelayanan_id)),
            "probed": True,
        })
    return out


# ---------------------------------------------------------------------------
# Bayi (newborn) supplement — ikterus classification + PJB pulse-oximetry
# ---------------------------------------------------------------------------
# Two newborn data sources need special handling (see the ckg-form-research skill,
# RESEARCH_STATUS.md -> "Bayi baru lahir / newborn registry"):
#   * Ikterus — the `mtbm` (Manajemen Terpadu Bayi Muda) tab IS scraped, but its
#     classification <select> (MtbmDetail[klasifikasi]) is applied by JS from an
#     inline `var json` / `var data` (setDataDetail), so the no-JS parse reads it
#     EMPTY. We recover the saved detail by parsing that embedded JSON.
#   * PJB pulse-ox — the "Skrining Penyakit Jantung Bawaan" form lives at
#     /skriningpjb/create/{pid}, served as full HTML only WITHOUT an
#     X-Requested-With header (our _parallel_fetch sends none; WITH it Laravel
#     returns a dokter-dropdown JSON instead). It is NOT in the Anamnesa bar and
#     returns a ~116 KB form for EVERY patient, so it must be fetched ONLY for
#     bayi — never added to _KNOWN_MODULES.
# Both are gated on a bayi record and fully guarded: any failure leaves the
# patient's other data untouched (no worse than today).

_BAYI_NAME_RE = re.compile(r"^\s*bayi\b", re.I)
_BAYI_UMUR_RE = re.compile(r"^\s*0\s*(thn|tahun)\b", re.I)


def _is_bayi_record(show_parsed: dict[str, Any]) -> bool:
    """A newborn record: nama begins with "BAYI " or Umur reads "0 Thn ...".
    Bayi carry the PARENT's NIK, so never key bayi logic on NIK — use these."""
    dp = show_parsed.get("data_pasien") or {}
    nama = str(dp.get("Nama Pasien") or dp.get("Nama") or "")
    if _BAYI_NAME_RE.match(nama):
        return True
    return bool(_BAYI_UMUR_RE.match(str(dp.get("Umur") or "")))


def _extract_saved_detail(html: str | None) -> Any:
    """Best-effort decode of the JS-embedded saved detail a bayi form applies via
    setDataDetail()/.val() — the source of the ikterus classification and the PJB
    readings that are NOT server-rendered into the inputs. Reads `var json = "...";`
    (a JS string literal holding JSON) or `var data = [...];`. Returns the decoded
    structure, or None when absent/empty/unparseable. Never raises."""
    if not html:
        return None
    try:
        m = re.search(r'var\s+json\s*=\s*("(?:[^"\\]|\\.)*")\s*;', html)
        if m:
            inner = json.loads(m.group(1))  # JS string literal -> the JSON text
            if isinstance(inner, str) and inner.strip():
                val = json.loads(inner)
                if val not in (None, [], {}):
                    return val
    except Exception:
        pass
    try:
        m2 = re.search(r'var\s+data\s*=\s*(\[.*\]|\{.*\})\s*;', html, re.S)
        if m2:
            val = json.loads(m2.group(1))
            if val not in (None, [], {}):
                return val
    except Exception:
        pass
    return None


def _augment_bayi_forms(
    page: Page,
    tabs: dict[str, Any],
    *,
    base_url: str,
    cookie_header: str,
    pelayanan_id: str,
    show_parsed: dict[str, Any],
    to_parse: list[tuple[str, str, str, str]],
) -> None:
    """Bayi-only, in place: (1) attach the mtbm tab's saved detail (JS-applied
    ikterus classification); (2) fetch + parse the PJB pulse-ox form. Fully
    guarded — on any failure `tabs` is left as-is."""
    try:
        if not _is_bayi_record(show_parsed):
            return
    except Exception:
        return

    # (1) mtbm saved detail — the ikterus classification lives here (JS-applied).
    try:
        mtbm_body = next((b for (_l, m, _u, b) in to_parse if m == "mtbm"), None)
        if mtbm_body:
            sd = _extract_saved_detail(mtbm_body)
            if sd is not None:
                for t in tabs.values():
                    if isinstance(t, dict) and t.get("module") == "mtbm":
                        t["saved_detail"] = sd
                        break
    except Exception:
        pass

    # (2) PJB pulse-ox — bayi-only extra fetch. WITHOUT an XHR header Laravel
    #     serves the HTML form (not the dokter-dropdown JSON).
    try:
        pjb_url = (
            f"{base_url}/skriningpjb/create/{pelayanan_id}"
            f"?from='pelayanan'&action='edit'"
        )
        resp = _parallel_fetch(
            [pjb_url], cookie_header=cookie_header, user_agent=_USER_AGENT,
            max_workers=1,
        )
        _st, body, _err = resp[pjb_url]
        if body and "halaman tidak ditemukan" not in body.lower():
            parsed_list = _parse_tabs_batch(page, [body])
            pjb = parsed_list[0] if parsed_list else {}
            sd = _extract_saved_detail(body)
            if sd is not None:
                pjb["saved_detail"] = sd
            tabs["Skrining PJB"] = {"url": pjb_url, "module": "skriningpjb", **pjb}
    except Exception as e:
        console.print(
            f"  [yellow]bayi PJB fetch failed for {pelayanan_id}: {e}[/yellow]"
        )


# ---------------------------------------------------------------------------
# /pelayanan/show/{id} parser
# ---------------------------------------------------------------------------
# The show page is the source of data_pasien, penyakit_khusus, and
# risiko_kehamilan. Tab buttons are NOT used — see _TAB_URL_ORDER above.
_SHOW_PARSE_JS = r"""
(html) => {
    const doc = new DOMParser().parseFromString(html, 'text/html');

    // ── Data Pasien ──
    function parseLabelValueTable(table) {
        const out = {};
        if (!table) return out;
        table.querySelectorAll('tr').forEach(tr => {
            const cells = Array.from(tr.children).filter(c => c.tagName === 'TD' || c.tagName === 'TH');
            for (let i = 0; i + 2 < cells.length; i += 3) {
                const label = (cells[i].innerText || '').trim();
                const sep = (cells[i+1].innerText || '').trim();
                if (!label || sep !== ':') continue;
                const value = (cells[i+2].innerText || '').trim();
                if (value || !(label in out)) out[label] = value;
            }
        });
        return out;
    }

    // ── Penyakit Khusus / Risiko Kehamilan (panel + array table) ──
    function parseArrayTable(table) {
        if (!table) return [];
        const headers = [];
        const headRow = table.querySelector('thead tr');
        if (headRow) {
            headRow.querySelectorAll('td, th').forEach(c => headers.push((c.innerText||'').trim()));
        }
        const rows = [];
        table.querySelectorAll('tbody tr').forEach(tr => {
            const cells = Array.from(tr.children).filter(c => c.tagName === 'TD' || c.tagName === 'TH');
            if (cells.length === 1) {
                const t = (cells[0].innerText||'').trim().toLowerCase();
                if (t.includes('tidak ditemukan')) return;
            }
            if (!cells.length) return;
            const row = {};
            cells.forEach((c, i) => {
                const key = headers[i] || `col_${i}`;
                row[key] = (c.innerText||'').trim();
            });
            rows.push(row);
        });
        return rows;
    }

    function tableUnderPanel(title) {
        const panels = doc.querySelectorAll('.panel');
        for (const p of panels) {
            const h = p.querySelector('.panel-heading');
            if (!h) continue;
            const t = (h.innerText||'').trim();
            if (t === title || t.startsWith(title)) return p.querySelector('table');
        }
        return null;
    }

    // ── Rujukan + Surat Keterangan ──
    // These modules have NO editable tab (/rujukan/create/{id} → 404), so their
    // only source is the read-only "Data <Module>" tables in the normally-hidden
    // #content visit-record summary (already inside the /show HTML). Scoped to
    // #content and explicitly NOT the cross-visit history accordion
    // (data_riwayat / "Kunjungan … Terakhir") so we capture only THIS visit.
    const summaryRoot = doc.getElementById('content') || doc;
    function inRiwayat(el) {
        let a = el.parentElement;
        while (a) {
            const id = a.id || '';
            const cls = (typeof a.className === 'string' ? a.className : '') || '';
            if (/riwayat|kunjungan/i.test(id + ' ' + cls)) return true;
            a = a.parentElement;
        }
        return false;
    }
    function dataSectionTable(headingRe) {
        for (const b of summaryRoot.querySelectorAll('.box, .panel, fieldset')) {
            if (inRiwayat(b)) continue;
            const hd = b.querySelector('.box-header, .box-title, .panel-heading, .panel-title, h3, h4, h5, legend');
            const h = hd ? (hd.innerText || '').trim() : '';
            if (headingRe.test(h)) { const t = b.querySelector('table'); if (t) return t; }
        }
        return null;
    }
    function parseDataTable(table) {
        if (!table) return [];
        const headers = [];
        const headRow = table.querySelector('thead tr') || table.querySelector('tr');
        if (headRow) headRow.querySelectorAll('td, th').forEach(c => headers.push((c.innerText||'').trim()));
        const body = table.querySelector('tbody')
            ? Array.from(table.querySelectorAll('tbody tr'))
            : Array.from(table.querySelectorAll('tr')).slice(1);
        const rows = [];
        body.forEach(tr => {
            const cells = Array.from(tr.children).filter(c => c.tagName === 'TD' || c.tagName === 'TH');
            if (!cells.length) return;
            if (cells.length === 1) {
                const t = (cells[0].innerText||'').trim().toLowerCase();
                if (!t || t.includes('tidak ditemukan') || t.includes('belum ada')) return;
            }
            const row = {}; let any = false;
            cells.forEach((c, i) => {
                const key = (headers[i] || `col_${i}`).replace(/\s+/g, ' ');
                if (/^(aksi|action|#)$/i.test(key)) return;   // drop labelled action column
                const v = (c.innerText||'').trim().replace(/\s+/g, ' ');
                // drop the unlabelled action-button column (its only content is a
                // link/button label like "show link" / "Lihat" / "Detail").
                if (/^col_\d+$/.test(key) &&
                    /^(show link|lihat|detail|edit|hapus|delete|view|unduh|download|cetak|show)$/i.test(v)) return;
                row[key] = v; if (v) any = true;
            });
            if (any) rows.push(row);
        });
        return rows;
    }

    // ── Riwayat Pasien / Alergi Pasien (left-sidebar history tables) ──
    // Two ePuskesmas builds render these differently:
    //   new (jaksel/Tebet): <table id="table_riwayat"> / <table id="table_alergi">
    //     with a 2-row thead (title row + "Jenis … | Nama … | Tanggal").
    //     Alergi has a trailing checkbox column.
    //   old (kotabekasi/kotatangerang): NO id; a <label><b>Riwayat Pasien</b></label>
    //     precedes a 2-column table (Jenis | value — no Tanggal). Same for Alergi.
    // So locate the table by id-hint OR exact heading text, then map every row to
    // a region-stable {jenis, nama, tanggal} (tanggal=null when the build omits it).
    function txt(el) { return (el && (el.innerText || el.textContent) || '').replace(/\s+/g, ' ').trim(); }
    function labeledTable(idHint, titleRe) {
        if (idHint) { const t = doc.getElementById(idHint); if (t) return t; }
        for (const t of doc.querySelectorAll('table')) {
            const tc = t.querySelector('thead tr:first-child td[colspan], thead tr:first-child th[colspan]');
            if (tc && titleRe.test(txt(tc))) return t;
            let sib = t.previousElementSibling, hops = 0;
            while (sib && hops < 3) {
                if (sib.tagName === 'LABEL' && titleRe.test(txt(sib))) return t;
                sib = sib.previousElementSibling; hops++;
            }
            const p = t.parentElement;
            if (p) { const pl = p.querySelector(':scope > label'); if (pl && titleRe.test(txt(pl))) return t; }
        }
        return null;
    }
    function parseHistoryTable(table) {
        if (!table) return [];
        // Column row = LAST <tr> in thead (new build: 2nd row; old build: only row).
        const headRows = table.querySelectorAll('thead tr');
        const headRow = headRows.length ? headRows[headRows.length - 1] : null;
        const headCells = headRow ? Array.from(headRow.children).filter(c => c.tagName === 'TD' || c.tagName === 'TH') : [];
        // Keep only data columns: header has text AND no form control (drops the
        // checkbox/action column in the new-build Alergi table).
        const keep = headCells.map(c => !!txt(c) && !c.querySelector('input,button'));
        const out = [];
        table.querySelectorAll('tbody tr').forEach(tr => {
            const tds = Array.from(tr.children).filter(c => c.tagName === 'TD' || c.tagName === 'TH');
            if (!tds.length) return;
            const vals = [];
            tds.forEach((td, i) => { if (keep[i] !== false) vals.push(txt(td)); });
            const jenis = vals[0] || null, nama = vals[1] || null, tanggal = vals[2] || null;
            if (!jenis && !nama) return;        // skip empty / separator rows
            out.push({ jenis, nama, tanggal });
        });
        return out;
    }

    // ── Data Skrining (legacy "skrining" module index — table_skrining) ──
    // Server-rendered in all 3 regions. Each row is EITHER an ILP row (no hidden
    // inputs; keterangan "Skrining ILP" — overlaps skrining_klaster) OR a legacy
    // row (hidden Skrining[n][skrining]/[tanggal] + a "show link" to the detail
    // page). The first tbody row is an empty "add-new" template (has a
    // <select name="skrining">) and is skipped. This parses the index only;
    // each row's `detail_href` (per-screening detail page) is then fetched +
    // attached as `detail` by `_fetch_data_skrining_details` (post-parse).
    function parseDataSkrining(table) {
        if (!table) return [];
        const out = [];
        table.querySelectorAll('tbody tr').forEach(tr => {
            if (tr.querySelector('select[name="skrining"]')) return;   // add-new template
            const skrIn = tr.querySelector('input[name$="[skrining]"]');
            const tglIn = tr.querySelector('input[name$="[tanggal]"]');
            const tds = Array.from(tr.children).filter(c => c.tagName === 'TD');
            const skrining = ((skrIn ? skrIn.getAttribute('value') : txt(tds[0])) || '').trim() || null;
            const tanggal = ((tglIn ? tglIn.getAttribute('value') : txt(tds[1])) || '').trim() || null;
            const keterangan = txt(tds[2]) || null;     // "Skrining ILP" or blank
            const a = tr.querySelector('a[href]');
            if (!skrining && !tanggal) return;           // skip empty placeholder rows
            out.push({ skrining, tanggal, keterangan, detail_href: a ? a.getAttribute('href') : null });
        });
        return out;
    }

    return {
        data_pasien: parseLabelValueTable(doc.getElementById('table_pasien')),
        penyakit_khusus: parseArrayTable(tableUnderPanel('Penyakit Khusus')),
        risiko_kehamilan: parseArrayTable(tableUnderPanel('Risiko Kehamilan')),
        riwayat_pasien: parseHistoryTable(labeledTable('table_riwayat', /^Riwayat Pasien$/i)),
        alergi: parseHistoryTable(labeledTable('table_alergi', /^Alergi Pasien$/i)),
        data_skrining: parseDataSkrining(doc.getElementById('table_skrining')),
        rujukan: {
            external: parseDataTable(dataSectionTable(/^Data Rujukan External/i)),
            internal: parseDataTable(dataSectionTable(/^Data Rujukan Internal/i)),
        },
        surat_keterangan: {
            sakit: parseDataTable(dataSectionTable(/^Data Surat Keterangan Sakit/i)),
            sehat: parseDataTable(dataSectionTable(/^Data Surat Keterangan Sehat/i)),
        },
    };
}
"""


# ── CKG (Cek Kesehatan Gratis) ──
# The CKG panel is populated client-side by an async POST to
# /pelayanan/getdatapkg fired by the inline getPelayananPkg() script, so the
# table is ABSENT from the raw show HTML (which we fetch without running JS).
# We extract the call's params from that inline script and replay the POST
# read-only to read CKG status. Endpoint is a read despite being POST
# (Laravel convention) and is not in DANGEROUS_URL_SUBSTRINGS.
_CKG_MONTHS_ID = {
    "01": "Januari", "02": "Februari", "03": "Maret", "04": "April",
    "05": "Mei", "06": "Juni", "07": "Juli", "08": "Agustus",
    "09": "September", "10": "Oktober", "11": "November", "12": "Desember",
}


def _iso_to_id_display(iso: str) -> str:
    """'2026-04-27' → '27 April 2026'. Falls back to the input on mismatch."""
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", iso or "")
    if not m:
        return iso
    y, mo, d = m.groups()
    return f"{int(d)} {_CKG_MONTHS_ID.get(mo, mo)} {y}"


def _fetch_ckg(
    show_html: str,
    *,
    base_url: str,
    cookie_header: str,
    user_agent: str,
    referer: str | None = None,
) -> dict[str, Any]:
    """Replay POST /pelayanan/getdatapkg using params embedded in the show
    page's inline getPelayananPkg() script. Returns
    ``{"sudah_ckg": bool, "tanggal": [{"iso", "display"}, …]}``.

    CKG (Cek Kesehatan Gratis) is a per-YEAR program. getdatapkg returns the
    patient's CKG records across ALL years, each tagged with a `year`. We
    scope to the year of the visit being scraped (the `tanggal` param = the
    pelayanan date): a 2025 CKG record does NOT count as "sudah CKG" for a
    2026 visit. So `sudah_ckg` is True only when a CKG record exists in the
    visit's own year.

    Returns the empty default on any parse/transport failure so a CKG hiccup
    never aborts the patient's scrape.
    """
    default = {"sudah_ckg": False, "tanggal": []}
    i = show_html.find("function getPelayananPkg")
    if i < 0:
        return default
    blob = show_html[i:i + 1000]
    pid = (re.search(r'id\s*=\s*"([^"]+)"', blob) or [None, None])[1]
    typ = (re.search(r'type\s*=\s*"([^"]*)"', blob) or [None, None])[1]
    tgl = (re.search(r'tanggal\s*=\s*"([^"]+)"', blob) or [None, None])[1]
    tok = (re.search(r"_token:\s*'([^']+)'", blob) or [None, None])[1]
    if not (pid and tgl and tok):
        return default
    target_year = tgl[:4]  # year of the visit being scraped
    headers = {
        "Cookie": cookie_header,
        "User-Agent": user_agent,
        "X-Requested-With": "XMLHttpRequest",
        "Accept": "application/json, text/javascript, */*; q=0.01",
    }
    if referer:
        headers["Referer"] = referer
    try:
        r = _get_http_client().post(
            f"{base_url}/pelayanan/getdatapkg",
            data={"_token": tok, "id": pid, "type": typ or "pasien", "tanggal": tgl},
            headers=headers,
            timeout=_DEFAULT_FETCH_TIMEOUT,
        )
        if r.status_code >= 400:
            return default
        payload = json.loads(r.text)
    except Exception:
        return default
    msgs = payload.get("message") if isinstance(payload, dict) else None
    tanggal = []
    for m in msgs or []:
        if not isinstance(m, dict):
            continue
        iso = m.get("tanggal")
        if not iso:
            continue
        # Scope to the visit's year. Prefer the explicit `year` field; fall
        # back to the ISO date's leading year.
        item_year = str(m.get("year") or iso[:4])
        if item_year != target_year:
            continue
        tanggal.append({"iso": iso, "display": _iso_to_id_display(iso)})
    return {"sudah_ckg": bool(tanggal), "tanggal": tanggal}


# ---------------------------------------------------------------------------
# Klaster & Siklus Hidup — Formulir Skrining battery (CKG screening forms)
# ---------------------------------------------------------------------------
# These are EPUS's own CKG screening forms (Skrining Hipertensi / DM / TBC /
# PPOK-PUMA / Kesehatan Jiwa PHQ-4 / SKILAS / ADL-Barthel / cancer-risk / …).
# They are NOT in the module tab bar — the /pelayanan/show page renders them in
# the box-KlasterSiklusHidup card (which the show-parser blocklists). They hold
# the questionnaire data the ASIK "CKG vs ePus" sheet marks "Belum ada di ePus".
#
# READ-ONLY access (verified 2026-06-04, all 3 regions):
#   HUB  POST /klaster_siklushidup/{pid}/getlist  body tahun&pelayanan_id&_token
#        → {data:[ {key, nama, route, klaster:[{id, skrining_id, header_id,
#                    kesimpulan/skor/klasifikasi_ht/…}]} ]}.  POST but a READ.
#        klaster.length>0  ⇒  that screening is DONE (saved record present).
#   The saved answers live in TWO places, captured BOTH:
#     1. the getlist `klaster` RECORD itself — instrument screenings carry every
#        item there (ADL → 11 Barthel items+score; SKILAS → 14 items; HT →
#        klasifikasi_ht; DM → kesimpulan/skor; PHQ-4 → skor/interpretasi; …).
#        This is the reliable, no-JS-needed source — always kept.
#     2. the /edit/ page — adds the per-question radio detail some screenings
#        render statically (DM anamnesis risk factors, penglihatan, payudara
#        lifestyle). Best-effort: PROBE candidate edit-url patterns (they vary:
#        /{route}/edit/{id} | /edit/{id}/{pid} | /edit/{pid}?header={id}); keep
#        the first that returns a populated form. Some forms apply answers via
#        JS (absent from raw HTML) — those are covered by source #1.
#
# The auto-save POST /klaster_siklushidup/{id} only fires when a REAL browser
# loads /show (its on-load JS). These fetches run no JS, so it never fires. We
# never POST a save. (DANGEROUS_URL_SUBSTRINGS still guards the browser path.)
_SKRINING_SOAP_COLS = (
    "tanggal", "dokter", "subjective", "objective", "assessment",
    "plan", "tandatangan",
)


def _csrf_token(html: str) -> str | None:
    """Laravel CSRF token from the show page — <meta name=csrf-token> first,
    else the inline getPelayananPkg() `_token` (same session value)."""
    m = re.search(r'name="csrf-token"\s+content="([^"]+)"', html)
    if m:
        return m.group(1)
    m = re.search(r"_token:\s*'([^']+)'", html)
    return m.group(1) if m else None


def _visit_year(show_html: str) -> str:
    """Year of the visit being scraped, from the getPelayananPkg `tanggal`
    (YYYY-MM-DD). Falls back to the current year. Drives getlist's `tahun`."""
    i = show_html.find("function getPelayananPkg")
    if i >= 0:
        m = re.search(r'tanggal\s*=\s*"(\d{4})-', show_html[i:i + 1000])
        if m:
            return m.group(1)
    from datetime import datetime
    return str(datetime.now().year)


def _strip_html(v: Any) -> str | None:
    if v is None:
        return None
    s = re.sub(r"<[^>]+>", " ", str(v))
    s = re.sub(r"\s+", " ", s).strip()
    return s or None


def _skrining_edit_candidates(route: str, rec: dict, pid: str) -> list[str]:
    """Ordered candidate VIEW urls for a saved screening record. Most use
    /{route}/edit/{id}; a few /{route}/edit/{id}/{pid}; PHQ-4-style use
    /{route}/edit/{pid}?header={header_id}. We try in order, keep first that
    yields a populated form (the getlist record covers the rest)."""
    rid = rec.get("id")
    sid = rec.get("skrining_id")
    hid = rec.get("header_id")
    c: list[str] = []
    if rid is not None:
        c += [f"{route}/edit/{rid}", f"{route}/edit/{rid}/{pid}"]
    if hid is not None:
        c += [f"{route}/edit/{pid}?header={hid}"]
    if rid is not None:
        c += [f"{route}/edit/{pid}?header={rid}"]
    if sid is not None:
        c += [f"{route}/edit/{sid}", f"{route}/edit/{sid}/{pid}"]
    # gejala_tbc-style view: route + /{pid} (no /edit/). Tried LAST so the
    # /edit/ patterns (which render the saved record for most screenings) win
    # first; for screenings whose /edit/ 404s this serves the populated form.
    c += [f"{route}/{pid}"]
    seen, out = set(), []
    for u in c:
        if u and u not in seen:
            seen.add(u)
            out.append(u)
    return out


def _header_ids(rec: dict) -> list:
    """Scalar header ids from a screening record's ``header_id``. PHQ-4 stores a
    list ``[{"id": N}, …]`` — one header per section (PHQ-2 + GAD-2), and each
    header is a SEPARATE ``/edit/{pid}?header={id}`` page. Returns [] when the
    form has no header (the common case — those use ``/{route}/edit/{id}``)."""
    h = rec.get("header_id")
    if h is None:
        return []
    if isinstance(h, str) and h.strip().startswith("["):
        try:
            import json as _json
            h = _json.loads(h)
        except Exception:
            return []
    ids: list = []
    if isinstance(h, list):
        for x in h:
            v = x.get("id") if isinstance(x, dict) else x
            if v is not None:
                ids.append(v)
    elif isinstance(h, (int, str)):
        ids.append(h)
    return ids


def _fetch_skrining(
    *,
    base_url: str,
    cookie_header: str,
    user_agent: str,
    pelayanan_id: str,
    csrf: str | None,
    year: str,
    referer: str | None = None,
) -> dict[str, Any]:
    """Read the Formulir Skrining battery for one pelayanan. Returns
    ``{key: {nama, route, done, records:[...], edit_url, edit_html}}`` for
    EVERY screening the getlist offers this patient — done OR not. A not-done
    form is recorded as a stub (``done=False``, empty ``records``) so the
    per-patient catalog of OFFERED forms is complete: which forms a patient
    qualifies for varies by siklus-hidup (age/sex), so "no record this visit"
    must still be captured, not silently dropped. Saved ``/edit/`` detail is
    fetched only for done forms (a not-done form has no saved record). The
    blank QUESTION structure of never-done forms is identical across patients,
    so it is catalogued once-per-region by tools/recon_skrining.py, not re-fetched
    per patient here. ``edit_html`` is raw HTML for the caller to batch-parse
    (or None). Degrades to ``{}`` on any failure — never aborts the patient."""
    if not csrf:
        return {}
    post_headers = {
        "Cookie": cookie_header, "User-Agent": user_agent,
        "X-CSRF-TOKEN": csrf, "X-Requested-With": "XMLHttpRequest",
        "Accept": "application/json, text/javascript, */*; q=0.01",
    }
    if referer:
        post_headers["Referer"] = referer
    client = _get_http_client()
    try:
        r = client.post(
            f"{base_url}/klaster_siklushidup/{pelayanan_id}/getlist",
            data={"tahun": year, "pelayanan_id": pelayanan_id, "_token": csrf},
            headers=post_headers, timeout=_DEFAULT_FETCH_TIMEOUT,
        )
        if r.status_code >= 400:
            return {}
        body = r.json()
    except Exception:
        return {}
    data = body.get("data") if isinstance(body, dict) else None
    if isinstance(data, dict):
        data = list(data.values())
    if not isinstance(data, list):
        return {}

    get_headers = {
        "Cookie": cookie_header, "User-Agent": user_agent,
        "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
    }
    if referer:
        get_headers["Referer"] = referer

    out: dict[str, Any] = {}
    for s in data:
        if not isinstance(s, dict):
            continue
        recs = s.get("klaster") or []
        if not isinstance(recs, list):
            recs = []
        route = s.get("route") or ""
        key = s.get("key") or route or "?"
        entry = {
            "nama": s.get("nama") or s.get("label"),
            "route": route,
            "done": bool(recs),   # this patient has a saved record for this form
            "records": recs,
            "edit_url": None,
            "edit_html": None,
        }
        # Fetch the saved /edit/ detail ONLY for done forms — a not-done form
        # has no saved record (its /edit/ 404s; /create/ would emit a blank
        # form, captured once-per-region by the catalog tool, not here). The
        # stub above still records that this form was OFFERED to the patient.
        if route and recs:
            # Header-based forms (PHQ-4 = 2 headers: PHQ-2 + GAD-2) split their
            # answers across one edit page PER header. ``header_id`` is a list
            # there — fetch each ``?header={id}`` page and concatenate so the
            # JS-answer extractor sees every section. The no-header / record-id
            # URLs 500 for these. Other forms have no header_id → [] → the
            # standard candidate probing below.
            hids = _header_ids(recs[0])
            if hids:
                parts = []
                for hid in hids:
                    url = f"{base_url}/{route.lstrip('/')}/edit/{pelayanan_id}?header={hid}"
                    try:
                        er = client.get(url, headers=get_headers, timeout=_DEFAULT_FETCH_TIMEOUT)
                    except Exception:
                        continue
                    if er.status_code < 400 and "halaman tidak ditemukan" not in er.text.lower():
                        parts.append(er.text)
                if parts:
                    entry["edit_url"] = f"{route}/edit/{pelayanan_id}?header=*"
                    entry["edit_html"] = "\n<!--EPUS-HEADER-SPLIT-->\n".join(parts)
            if not entry["edit_html"]:
                for path in _skrining_edit_candidates(route, recs[0], str(pelayanan_id)):
                    url = base_url + (path if path.startswith("/") else "/" + path)
                    try:
                        er = client.get(url, headers=get_headers, timeout=_DEFAULT_FETCH_TIMEOUT)
                        if er.status_code >= 400:
                            continue
                        t = er.text
                    except Exception:
                        continue
                    # Reject ONLY the real 404 page (its <title> is "Halaman tidak
                    # ditemukan"). A populated form may contain "tidak ditemukan"
                    # in a hidden empty sub-panel, so don't match that substring.
                    if "halaman tidak ditemukan" in t.lower():
                        continue
                    if t.count("<input") > 5 or "checked=" in t:
                        entry["edit_url"] = path
                        entry["edit_html"] = t
                        break
        out[key] = entry
    return out


# Screening-form parser — the questionnaire questions live in TABLE layouts
# (No | Pertanyaan | Jawaban-radios), NOT in .form-group/.control-label, so the
# module-tab parser (_FORM_PARSE_BATCH_JS) extracts nothing here. This pulls
# every ANSWERED control keyed by its input `name` (descriptive + region-stable:
# "anamnesis[Kebiasaan makan manis]", "makan_asin", "mata_luar", …). Only
# server-rendered selections (`checked` attr / option[selected]) are seen —
# JS-applied answers are covered by the getlist record instead.
_SKRINING_PARSE_JS = r"""
(htmls) => {
  function parseOne(html) {
    const d = new DOMParser().parseFromString(html, 'text/html');
    const out = {};
    const clean = s => (s || '').replace(/ /g,' ').replace(/\s+/g,' ').trim();
    // radios grouped by name → checked option's label
    const radios = {};
    d.querySelectorAll('input[type=radio]').forEach(r => {
      const n = r.getAttribute('name'); if (!n) return;
      (radios[n] = radios[n] || []).push(r);
    });
    for (const n in radios) {
      const c = radios[n].find(x => x.hasAttribute('checked'));
      if (c) {
        const lbl = clean(c.closest('label') ? c.closest('label').textContent : '') || c.getAttribute('value');
        if (lbl) out[n] = lbl;
      }
    }
    // single checkboxes → true when checked
    d.querySelectorAll('input[type=checkbox]').forEach(cb => {
      const n = cb.getAttribute('name'); if (!n || n in out) return;
      if (cb.hasAttribute('checked')) out[n] = true;
    });
    // selects → selected non-placeholder option text
    d.querySelectorAll('select').forEach(s => {
      const n = s.getAttribute('name'); if (!n) return;
      const o = s.querySelector('option[selected]'); if (!o) return;
      const t = clean(o.textContent);
      if (t && !/^[-\s]*(pilih|select)\b/i.test(t)) out[n] = t;
    });
    // text/number/textarea with a value
    d.querySelectorAll('input[type=text], input[type=number], input:not([type]), textarea').forEach(el => {
      const n = el.getAttribute('name'); if (!n || n in out) return;
      let v = el.tagName === 'TEXTAREA' ? clean(el.textContent) : (el.getAttribute('value') || '').trim();
      if (v) out[n] = v;
    });
    return out;
  }
  return htmls.map(parseOne);
}
"""


def _parse_skrining_batch(page: Page, htmls: list[str]) -> list[dict[str, Any]]:
    return page.evaluate(_SKRINING_PARSE_JS, htmls)


def _norm_q(t: Any) -> str:
    """Normalise a question label for stable matching (lowercase, collapse all
    non-alphanumerics) — EPUS vs ASIK differ only by whitespace/punctuation."""
    return re.sub(r"[^a-z0-9]+", " ", str(t or "").lower()).strip()


def _extract_js_answers(html: str) -> dict[str, Any]:
    """Saved answers that the screening form applies via JavaScript (so they are
    absent from the no-JS DOM parse — why ``detail`` was empty for PHQ-4 / PUMA /
    payudara). Three observed mechanisms (verified live 2026-06-05):
      1. Vue ``viewData`` JSON (PHQ-4): join ``skriningDetail`` (skor_jawaban) to
         ``pertanyaan`` (text) by ``skrining_pertanyaan_id`` →
         ``{"q::<normalized question>": <skor 0-3>}``.
      2. jQuery ``$('input[name="X"][value="Y"]').prop("checked", true)`` (PUMA,
         payudara, …) → ``{X: "Y"}`` (the saved radio selection).
      3. jQuery ``$('select[name="X"]').val("Y")`` → ``{X: "Y"}``.
    Best-effort; returns {} on any failure. Keys are namespaced (``q::``) for the
    Vue questions so they cannot collide with plain field names."""
    out: dict[str, Any] = {}
    if not html:
        return out
    # 1) Vue viewData JSON — may appear MULTIPLE times (PHQ-4 concatenates one
    #    header page per section, each with its own viewData).
    pos = 0
    while True:
        i = html.find("viewData", pos)
        if i < 0:
            break
        s = html.find("{", i)
        if s < 0:
            break
        depth, end = 0, None
        for j in range(s, min(len(html), s + 40000)):
            c = html[j]
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    end = j + 1
                    break
        pos = end if end else (s + 1)
        if not end:
            continue
        try:
            import json as _json
            vd = _json.loads(html[s:end])
        except Exception:
            continue
        if not isinstance(vd, dict):
            continue
        qtext: dict[Any, str] = {}
        # PHQ-4 shape: pertanyaan[].questions[]. formulir shape (faktor_risiko,
        # fungsi_ginjal, catin, …): questions live in a flat `formulir` list.
        for sec in vd.get("pertanyaan") or []:
            for q in (sec.get("questions") if isinstance(sec, dict) else None) or []:
                if isinstance(q, dict) and q.get("id") is not None:
                    qtext[q["id"]] = q.get("pertanyaan") or ""
        for q in vd.get("formulir") or []:
            if isinstance(q, dict) and q.get("id") is not None:
                qtext[q["id"]] = q.get("pertanyaan") or ""
        for d in vd.get("skriningDetail") or []:
            if not isinstance(d, dict):
                continue
            t = qtext.get(d.get("skrining_pertanyaan_id"))
            if not t:
                continue
            # PHQ-4: skor_jawaban (0-3, may be 0). formulir shape: the chosen
            # option text (skrining_jawaban.jawaban) or a free-text value.
            sk = d.get("skor_jawaban")
            if sk is None:
                sk = d.get("jawaban_freetext")
                sj = d.get("skrining_jawaban")
                if sk in (None, "") and isinstance(sj, dict):
                    sk = sj.get("jawaban")
            if sk is not None and sk != "":
                out.setdefault("q::" + _norm_q(t), sk)
    # 2) jQuery .prop('checked', true) on a specific radio value. The selector is
    #    a quoted string ``$('input[name="X"][value="Y"]')`` so a closing quote sits
    #    before the ``)`` — allow it. Also accept .attr('checked', ...).
    for nm, val in re.findall(
        r"""input\[name=["']([^"']+)["']\]\[value=["']([^"']*)["']\]\s*["']?\s*\)\s*\.(?:prop|attr)\(\s*["']checked["']\s*,\s*(?:true|["']checked["'])""",
        html,
    ):
        if val != "" and nm not in out:
            out[nm] = val
    # 3) jQuery .val('X') on a select
    for nm, val in re.findall(
        r"""select\[name=["']([^"']+)["']\]\s*["']?\s*\)\s*\.val\(\s*["']([^"']+)["']""", html
    ):
        if nm not in out:
            out[nm] = val
    return out


def _attach_skrining_detail(page: Page, skrining: dict[str, Any]) -> dict[str, Any]:
    """Batch-parse each screening's edit_html into ``detail`` ({name:value}),
    drop the raw html, and keep the structured records. Main-thread (page.evaluate).
    Also merges JS-applied answers (``_extract_js_answers``) that the no-JS DOM
    parse cannot see — these FILL gaps, never override a real parsed value."""
    if not skrining:
        return {}
    keys = [k for k, v in skrining.items() if v.get("edit_html")]
    parsed = _parse_skrining_batch(page, [skrining[k]["edit_html"] for k in keys]) if keys else []
    detail_by_key = dict(zip(keys, parsed))
    out: dict[str, Any] = {}
    for key, v in skrining.items():
        recs = v.get("records") or []
        detail = dict(detail_by_key.get(key, {}) or {})
        eh = v.get("edit_html")
        if eh:
            for k2, val in _extract_js_answers(eh).items():
                detail.setdefault(k2, val)
        out[key] = {
            "nama": v.get("nama"),
            "route": v.get("route"),
            "done": bool(recs),   # not-done forms are recorded as stubs (empty records)
            "records": recs,
            "edit_url": v.get("edit_url"),
            "detail": detail,
        }
    return out


def _fetch_cppt(
    *,
    base_url: str,
    cookie_header: str,
    user_agent: str,
    pelayanan_id: str,
    year: str,
    referer: str | None = None,
) -> list[dict[str, Any]]:
    """Replay the CPPT DataTables XHR over a wide date window → SOAP rows
    ``[{tanggal, dokter, subjective, objective, assessment, plan}, …]``.
    The raw /cppt/{pid} HTML carries only an empty table shell (rows load via
    this XHR), which is why the module-tab capture sees CPPT as ``{}``."""
    cols = "&".join(
        f"columns[{i}][data]={c}" for i, c in enumerate(_SKRINING_SOAP_COLS)
    )
    fw = quote(f"01/01/2020 - 31/12/{year}")
    url = f"{base_url}/cppt/{pelayanan_id}?{cols}&page=1&limit=100&filter_waktu={fw}"
    headers = {
        "Cookie": cookie_header, "User-Agent": user_agent,
        "X-Requested-With": "XMLHttpRequest",
        "Accept": "application/json, text/javascript, */*; q=0.01",
    }
    if referer:
        headers["Referer"] = referer
    try:
        r = _get_http_client().get(url, headers=headers, timeout=_DEFAULT_FETCH_TIMEOUT)
        if r.status_code >= 400:
            return []
        body = r.json()
    except Exception:
        return []
    data = body.get("data") if isinstance(body, dict) else None
    recs = None
    if isinstance(data, dict):
        recs = data.get("records")
    elif isinstance(data, list):
        recs = data
    if not isinstance(recs, list):
        return []
    out = []
    for rec in recs:
        if not isinstance(rec, dict):
            continue
        row = {c: _strip_html(rec.get(c)) for c in _SKRINING_SOAP_COLS if c != "tandatangan"}
        if any(row.values()):
            out.append(row)
    return out


def _fetch_data_skrining_details(
    page: Page,
    data_skrining: list[dict[str, Any]],
    *,
    base_url: str,
    cookie_header: str,
    user_agent: str,
    referer: str | None = None,
    max_parallel_fetches: int = 10,
) -> list[dict[str, Any]]:
    """Fetch + parse each Data Skrining row's ``detail_href`` and attach the
    parsed form as ``row["detail"]``. Mutates ``data_skrining`` in place and
    returns it.

    The detail pages are the SAME Laravel form shape as the module tabs, so we
    reuse the tab form parser (``_parse_tabs_batch`` → ``{fields, tables}``).
    Read-only: fetched via raw HTTP (no JS), identical to the tab-fetch path.
    On success → ``row["detail"] = {fields, tables}``; on failure →
    ``row["detail_error"] = "HTTP {code}"`` (compact, kept out of ``detail``).

    These records belong to PAST screenings (the href id is the saved
    screening-record id, not the current pelayanan_id), so they add cross-visit
    history the module tabs don't carry. Rows without a ``detail_href`` (ILP
    rows — already covered by ``skrining_klaster``) are left untouched.

    Empirically (verified live 2026-06-05, jaksel + kotatangerang): the
    module-specific links (``/covid19/create/{id}``, …) render and parse, but
    the GENERIC legacy ``/skrining/create/{id}`` route returns HTTP 500 on a
    direct GET — those screenings (Obesitas/Hipertensi/DM/TBC/Lansia) have no
    standalone detail page; their data is the row itself plus the current
    visit's module tab. We still attempt every href (no per-type heuristic) so
    a region where that route works is covered automatically.

    We retry true-transient failures (429/timeout/network/503/502/504) but NOT
    HTTP 500: the dead ``/skrining/create`` links return a deterministic 500, so
    retrying them would back-off-retry ~19 dead links 2× per patient — a huge,
    pointless slowdown. Excluding 500 from ``transient_codes`` keeps the
    dead-link fast-path while RECOVERING the valid module detail pages
    (``/ptm/create/…`` etc.) that previously dropped permanently on a transient
    Cloudflare throttle (``retries=0`` turned a throttle into silent data loss —
    rare on HTTP/1.1, more frequent under high concurrency)."""
    rows = [r for r in (data_skrining or []) if isinstance(r, dict) and r.get("detail_href")]
    if not rows:
        return data_skrining
    uniq = list(dict.fromkeys(r["detail_href"] for r in rows))
    resp = _parallel_fetch(
        uniq, cookie_header=cookie_header, referer=referer, user_agent=user_agent,
        max_workers=min(len(uniq), max(1, max_parallel_fetches)),
        retries=2, transient_codes=_TRANSIENT_HTTP_CODES - {500},
    )
    ok_urls = [u for u in uniq if resp[u][1] and not resp[u][2]]
    parsed = _parse_tabs_batch(page, [resp[u][1] for u in ok_urls]) if ok_urls else []
    by_url = dict(zip(ok_urls, parsed))
    for r in rows:
        u = r["detail_href"]
        if u in by_url:
            r["detail"] = by_url[u]
        else:
            st, _body, err = resp.get(u, (0, None, "not fetched"))
            r["detail_error"] = err or f"HTTP {st}"
    return data_skrining


def _parse_show_html(page: Page, html: str) -> dict[str, Any]:
    return page.evaluate(_SHOW_PARSE_JS, html)


# Section-heading blocklist — prefixes of sections that always come from the
# boilerplate modals/widgets every tab ships (print modal, consent modal,
# antrol countdown, resume, gallery). These are NOT patient data.
_BOILERPLATE_SECTION_PREFIXES = (
    "Cetak",
    "Pengaturan Jadwal",
    "Jadwal",
    "Resume Medis",
    "Persetujuan",
    "Informed Consent",
    "Tindakan",  # the informed-consent tindakan modal
    "Notifikasi",
    "Tambah Foto",
    "Gallery",
    "Panggil Antrean",
    "Profil",
    "Logout",
    "Pengaturan",
    "Ambil Data",
    "Belum ada",
    "Memuat",
    "Cari",
    "Filter",
)

# DOM container ids / classes that hold modals/widgets. Anything under these
# should be filtered out — they aren't the patient-facing form.
_BOILERPLATE_CONTAINER_IDS = (
    "modalCetakSurat", "modalPersetujuanPenolakan",
    "informationModalForm2", "galleryApp", "modalRespAntrol",
    "modalRespPendaftaranAntrol", "modalCountDownAntrol",
    "modalCountDownMulaiPelayananBpjs", "modalResumeRawatInap",
    "data_riwayat", "riwayat_kunjungan_bpjs", "modalCppt",
    "modalBroadcastNotif", "navbar", "isiNotifBroadcast",
    "jadwal_antrian_jam_html", "box-KlasterSiklusHidup",
    "user_skriningklastersiklushidup", "lihat_skriningklastersiklushidup",
    "content_pelayanan_pkg", "content_data_pkg",
)


# Batch version: parse N tab HTMLs in a single page.evaluate call. Saves
# Playwright IPC round-trips (one ~5ms round-trip per tab × 32 tabs × 150
# patients = ~25 seconds of pure IPC overhead per run).
#
# Extraction model — mirrors data_pasien's clean shape:
#   output = { "<Section Heading>": { "<Question Label>": <answer>, … }, … }
#
# For each visible form control (skipping type="hidden" and anything inside
# a modal / global-nav container):
#   - SECTION = nearest ancestor .box/.panel/fieldset's heading text
#   - QUESTION = the .control-label / label in the same .form-group
#   - ANSWER   = type-specific:
#       text / number / date  → value (or null when empty)
#       textarea              → trimmed text content (or null)
#       select                → text of option[selected] (or null)
#       radio group           → option label of the checked radio (or null)
#       checkbox (single)     → true/false (the question IS the label)
#       checkbox group        → { optionLabel: true/false, … }
#   - When N controls in the same section share a question label
#     (e.g. Lama Sakit has 3 inputs — tahun, bulan, hari), the answer is
#     an object keyed by the control name's last bracket segment.
_FORM_PARSE_BATCH_JS = r"""
({ htmls, skipSectionPrefixes, skipContainerIds, nameHints }) => {
    const sectionSkipPrefixes = skipSectionPrefixes;
    const containerIdSkip = new Set(skipContainerIds);
    // nameHints: { "<input name>": {section, question, [valueMap]} }
    // Used as a fallback when the input has no .control-label OR is in a
    // section whose header doesn't apply. Lets us surface hidden-label
    // PTM lab fields (HbA1c, SGOT, LDL, EKG, refraksi, retina, carta…)
    // without modifying the JS parser per-field.
    const labelHints = nameHints || {};

    function cleanText(s) {
        return (s || '').replace(/ /g, ' ').replace(/\s+/g, ' ').trim();
    }
    function nameLeaf(name) {
        if (!name) return null;
        const re = /\[([^\]]*)\]/g;
        let last = null, m;
        while ((m = re.exec(name)) !== null) last = m[1] || null;
        return last || name;
    }

    function parseOne(html) {
        const doc = new DOMParser().parseFromString(html, 'text/html');

        function isHidden(el) {
            // Type-hidden inputs are definitely hidden.
            const tprop = (el.getAttribute && el.getAttribute('type') || '').toLowerCase();
            if (tprop === 'hidden') return true;
            // The control itself has Bootstrap's `.hidden` utility class —
            // this is how epuskesmas renders hidden id/pelayanan_id helpers
            // like <input class="hidden form-control" name="X[id]">.
            if (el.classList) {
                if (el.classList.contains('hidden')) return true;
                if (el.classList.contains('d-none')) return true;
            }
            // Inline display:none on the control itself.
            const style = el.getAttribute && el.getAttribute('style') || '';
            if (/display\s*:\s*none/i.test(style)) return true;
            if (/visibility\s*:\s*hidden/i.test(style)) return true;
            // We do NOT walk ancestors — Bootstrap collapse panels (.collapse
            // without .in) wrap real user questions that the browser expands
            // on click. Excluding those would drop valid patient data.
            return false;
        }

        function isInBoilerplateContainer(el) {
            let n = el;
            while (n && n !== doc.documentElement) {
                if (n.id && containerIdSkip.has(n.id)) return true;
                if (n.classList && n.classList.contains('modal')) return true;
                n = n.parentElement;
            }
            return false;
        }

        // Heading text of one .box/.panel/fieldset — '' when the box HAS a
        // header but it yields no text (headerless box), null when the box
        // has no header element at all. Shared by sectionHeading() and
        // isRealTindakanFormBox() so both walk boxes with identical
        // semantics.
        function boxHeadingText(box) {
            const header = box.querySelector(
                ':scope > .box-header, :scope > .panel-heading, :scope > legend'
            );
            if (!header) return null;
            // Heading extraction — in order of specificity:
            //   1. <h3>/<h4>/<h5>/.box-title/.panel-title → their own textContent.
            //   2. <label><b>text</b></label> → <b> text only (skip
            //      checkbox "Tidak Ada" siblings on box-header accordions).
            //   3. fallback: header's textContent (trimmed to first line).
            let text = null;
            const inner = header.querySelector(
                ':scope .box-title, :scope .panel-title, :scope > h3, :scope > h4, :scope > h5, :scope legend'
            );
            if (inner) {
                text = cleanText(inner.textContent || '');
            } else {
                // Try: first <b>/<strong> inside a direct-child <label>.
                const boldLabel = header.querySelector(':scope > label > b, :scope > label > strong');
                if (boldLabel) {
                    text = cleanText(boldLabel.textContent || '');
                }
            }
            if (!text) {
                // Fall back to header's own direct text nodes only (skip
                // nested checkboxes/labels).
                const parts = [];
                for (const child of header.childNodes) {
                    if (child.nodeType === 3) {  // text node
                        const t = cleanText(child.textContent || '');
                        if (t) parts.push(t);
                    }
                }
                text = parts.join(' ').trim();
            }
            if (text) {
                // Strip trailing ":" or "*".
                text = text.replace(/[:*\s]+$/, '');
            }
            return text;
        }

        function sectionHeading(el) {
            // Walk up to the nearest .box / .panel / fieldset and grab its header.
            let box = el.closest('.box, .panel, fieldset');
            // Some real form boxes ship an EMPTY header (`&nbsp;` only — poso
            // Psikologi staff/Keluhan block, 2026-09). Remember that we saw
            // one: if no ancestor yields a heading either, emit a synthetic
            // section instead of null (null = control dropped entirely).
            let sawHeaderlessBox = false;
            while (box) {
                const text = boxHeadingText(box);
                if (text) return text;
                if (text === '') sawHeaderlessBox = true;
                box = box.parentElement && box.parentElement.closest('.box, .panel, fieldset');
            }
            // No ancestor yielded a heading, but the control DID live inside
            // a real (headerless) form box — keep the fields under a
            // deterministic synthetic section instead of dropping them.
            return sawHeaderlessBox ? '(no heading)' : null;
        }

        function questionLabel(el) {
            const group = el.closest('.form-group');
            if (!group) return null;
            // Prefer an explicit control-label. Don't pick up labels that
            // wrap the input itself (those are option labels for radios /
            // checkboxes).
            const labs = group.querySelectorAll('label, .control-label');
            for (const lab of labs) {
                if (lab.contains(el)) continue;
                let text = cleanText(lab.textContent || '');
                // Strip trailing "*" (required marker) + any empty <span>s
                text = text.replace(/\s*\*+\s*$/, '').replace(/\s*:\s*$/, '');
                if (text) return text;
            }
            return null;
        }

        function isBoilerplateSection(heading) {
            if (!heading) return false;
            for (const p of sectionSkipPrefixes) {
                if (heading.startsWith(p)) return true;
            }
            return false;
        }

        // "Tindakan" is blocklisted because the informed-consent widget ships
        // with that heading. Poso (2026-09) heads its REAL Tindakan form box
        // (dokter_nama_bpjs / perawat_nama / jumlah / hasil …) the same way,
        // so the heading alone cannot decide — the whole staff/Jumlah form was
        // silently dropped there. FAIL CLOSED: unskip the section only on
        // POSITIVE evidence of the real form — one of its signature input
        // names (dokter_nama_bpjs / perawat_nama) inside the box that
        // supplied the "Tindakan" heading (walking through headerless boxes
        // exactly like sectionHeading does). A consent-widget variant with
        // renamed inputs, different spelling, or inputs living in a nested /
        // sibling box stays blocklisted — an unrecognized box can never
        // unskip itself.
        const TINDAKAN_EVIDENCE_SELECTOR =
            'input[name="dokter_nama_bpjs"], select[name="dokter_nama_bpjs"], textarea[name="dokter_nama_bpjs"], ' +
            'input[name$="[dokter_nama_bpjs]"], select[name$="[dokter_nama_bpjs]"], textarea[name$="[dokter_nama_bpjs]"], ' +
            'input[name="perawat_nama"], select[name="perawat_nama"], textarea[name="perawat_nama"], ' +
            'input[name$="[perawat_nama]"], select[name$="[perawat_nama]"], textarea[name$="[perawat_nama]"]';

        function isRealTindakanFormBox(el) {
            let box = el.closest('.box, .panel, fieldset');
            while (box) {
                if (box.querySelector(TINDAKAN_EVIDENCE_SELECTOR)) return true;
                // Stop at the box that supplied the heading (the one the
                // `section` text came from) — never look into unrelated
                // outer boxes for evidence.
                if (boxHeadingText(box)) return false;
                box = box.parentElement && box.parentElement.closest('.box, .panel, fieldset');
            }
            return false;
        }

        function isSkippableSection(el, section) {
            if (!isBoilerplateSection(section)) return false;
            if (section && section.indexOf('Tindakan') === 0 && isRealTindakanFormBox(el)) {
                return false;
            }
            return true;
        }

        // ── Pass 1: collect every visible control keyed by (section, question) ──
        const buckets = {};  // key "section||question" -> {section, question, items:[]}
        const pushedNames = new Set();  // every control name Pass 1 captured
        function push(section, question, item) {
            const key = section + '' + question;
            if (!buckets[key]) buckets[key] = { section, question, items: [] };
            buckets[key].items.push(item);
            if (item && item.name) pushedNames.add(item.name);
        }

        const controls = doc.querySelectorAll('input, textarea, select');
        for (const el of controls) {
            if (isHidden(el)) continue;
            if (isInBoilerplateContainer(el)) continue;
            const type = (el.getAttribute('type') || el.type || 'text').toLowerCase();
            const name = el.getAttribute('name') || '';
            const hint = labelHints[name];

            let section = sectionHeading(el);
            let question = questionLabel(el);

            // Hint override: when a hint is provided for this exact `name`,
            // ALWAYS prefer the hint's section/question over the auto-detected
            // ones. Required for fields where multiple radio groups inside
            // the same panel share the same .control-label (e.g.
            // "Mata Kanan" appears under both Katarak and Kelainan
            // Refraksi sub-headers in Gangguan Penglihatan, collapsing
            // both to one bucket without override). Auto-detection is the
            // fallback when no hint exists.
            if (hint) {
                if (hint.section) section = hint.section;
                if (hint.question) question = hint.question;
            }

            if (!section) continue;
            if (isSkippableSection(el, section)) continue;
            if (!question) continue;

            const tag = el.tagName;

            if (type === 'radio') {
                const wrap = el.closest('label');
                const optionText = wrap ? cleanText(wrap.textContent) : (el.getAttribute('value') || '');
                push(section, question, {
                    kind: 'radio', name, option: optionText,
                    value: el.getAttribute('value'),
                    checked: el.hasAttribute('checked'),
                });
                continue;
            }
            if (type === 'checkbox') {
                const wrap = el.closest('label');
                const optionText = wrap ? cleanText(wrap.textContent) : (el.getAttribute('value') || '');
                push(section, question, {
                    kind: 'checkbox', name, option: optionText,
                    value: el.getAttribute('value'),
                    checked: el.hasAttribute('checked'),
                });
                continue;
            }

            // text / number / date / textarea / select
            let value = null;
            if (tag === 'TEXTAREA') {
                value = cleanText(el.textContent || '') || null;
            } else if (tag === 'SELECT') {
                // Some builds mark BOTH the placeholder and the real value
                // `selected` (poso 2026-09: <option value="" selected>Pilih</option>
                // + <option value="0" selected>[0] Mandiri</option>). Per HTML
                // spec the browser resolves that to the LAST selected option —
                // querySelector would take the first (the placeholder) and
                // silently null a real answer. Take the last, so single-
                // selected selects behave exactly as before.
                //
                // NO implicit first-option fallback: a select with no
                // option[selected] stays null. Verified live on poso
                // (2026-09-01): its covid19 `kontak_jk` carries no [selected]
                // and always renders Laki-laki first — for FEMALE patients
                // too — so the displayed first option is the browser's
                // default for an empty contact-tracing row, not the
                // patient's answer; recording it would flip null→wrong value
                // on every portal with plain unanswered selects.
                const opts = el.querySelectorAll('option[selected]');
                const opt = opts.length ? opts[opts.length - 1] : null;
                if (opt) {
                    const optValue = opt.getAttribute('value') || '';
                    const t = cleanText(opt.textContent || '');
                    // Placeholder options (value="", or starts with "- PILIH -",
                    // "Pilih ", "- Select -") aren't answers — emit null.
                    if (optValue === '' || /^-?\s*(pilih|select)\b/i.test(t)) {
                        value = null;
                    } else {
                        value = t || null;
                    }
                }
            } else {
                const v = el.getAttribute('value');
                value = (v === null || v === '') ? null : v;
            }
            push(section, question, { kind: 'scalar', name, value });
        }

        // ── Pass 2: flatten buckets into { section: { question: answer } } ──
        const sections = {};
        for (const bucket of Object.values(buckets)) {
            const { section, question, items } = bucket;
            const kinds = new Set(items.map(i => i.kind));

            sections[section] = sections[section] || {};
            let answer;

            if (kinds.size === 1 && items[0].kind === 'radio') {
                const chosen = items.find(i => i.checked);
                answer = chosen ? (chosen.option || chosen.value || null) : null;
            } else if (kinds.size === 1 && items[0].kind === 'checkbox') {
                if (items.length === 1) {
                    answer = items[0].checked
                        ? (items[0].option || items[0].value || true)
                        : null;
                } else {
                    // Grouped checkboxes: each option becomes its own yes/no.
                    const obj = {};
                    for (const it of items) {
                        const key = it.option || it.value || '_';
                        obj[key] = it.checked;
                    }
                    answer = obj;
                }
            } else {
                // scalars (possibly multiple sharing one question label)
                if (items.length === 1) {
                    answer = items[0].value;
                } else {
                    const obj = {};
                    for (const it of items) {
                        let key = nameLeaf(it.name);
                        if (!key || key === '_') continue;
                        // Strip a `lama_` / `tanggal_` prefix so Lama Sakit
                        // reads {tahun, bulan, hari} instead of {lama_sakit_*}.
                        key = key.replace(/^(lama_sakit_|lama_|tanggal_)/, '');
                        if (it.kind === 'radio' || it.kind === 'checkbox') {
                            // In a mixed bucket a choice control must
                            // contribute its CHECKED state, never its raw
                            // value attribute — an unchecked radio/checkbox
                            // otherwise records its option value as a
                            // patient answer (poso 2026-09: IVA Status
                            // Kawin recorded "JANDA", Psikologi Motorik
                            // "lainnya", MTBS Tindakan "OPV-3/IPV" while
                            // every one of those controls is unchecked).
                            // Checked radios follow the radio-only branch's
                            // semantics (option label first).
                            if (!it.checked) continue;
                            obj[key] = it.option || it.value || null;
                        } else {
                            obj[key] = it.value;
                        }
                    }
                    // Collapse single-key dicts back to scalar.
                    const objKeys = Object.keys(obj);
                    answer = objKeys.length === 1 ? obj[objKeys[0]] : obj;
                }
            }

            sections[section][question] = answer;
        }

        // ── Pass 2.5: thead-less label:value QUESTION tables ──
        // Some builds render whole question groups as a <table> whose rows
        // are  td(label.control-label) + td(radios / select / inputs)  with
        // NO <thead> and NO .form-group wrapper — invisible to Pass 1
        // (requires .form-group) and to Pass 3 (requires <thead>). Poso
        // (2026-09) serves its entire Anamnesa block "Status Fisis/
        // Neurologis/ Mental, Biologis, Psikososiospiritual dan Ekonomi"
        // this way (15 questions: Agama/Kepercayaan, Pekerjaan, Status
        // Perkawinan, Sosial ekonomi, …) — all with real checked answers.
        // Emit each row as section > question > answer, using the same
        // value semantics as Pass 1 (radio → checked option's label,
        // select → last-selected non-placeholder option text, input → value).
        // Additive: a page without such tables yields exactly the old output.
        for (const tbl of doc.querySelectorAll('table')) {
            if (tbl.querySelector('thead')) continue;          // Pass 3's grids
            if (tbl.closest('table') !== tbl) continue;         // skip nested
            if (isInBoilerplateContainer(tbl)) continue;
            const section = sectionHeading(tbl);
            if (!section || isSkippableSection(tbl, section)) continue;

            const rowAnswers = [];  // [question, answer] once validated
            let questionRowCount = 0;
            for (const tr of tbl.querySelectorAll('tr')) {
                const lbl = tr.querySelector('td label.control-label');
                if (!lbl) continue;
                const q = cleanText(lbl.textContent || '')
                    .replace(/\s*\*+\s*$/, '').replace(/\s*:\s*$/, '');
                if (!q) continue;
                questionRowCount++;

                // Answer cells: every td after the label's td.
                const tds = Array.from(tr.querySelectorAll(':scope > td'));
                const labelTd = lbl.closest('td');
                const answerTds = tds.slice(tds.indexOf(labelTd) + 1);

                // Group the row's controls: radios/checkboxes by name,
                // each scalar control individually (order preserved).
                const groups = [];
                const byKey = {};
                for (const td of answerTds) {
                    for (const el of td.querySelectorAll('input, select, textarea')) {
                        if (isHidden(el)) continue;
                        const t = (el.getAttribute('type') || 'text').toLowerCase();
                        const tag = el.tagName;
                        const name = el.getAttribute('name') || '';
                        // Dedupe only NAMED controls — nameless readonly
                        // displays (Pekerjaan, Jaminan, Status Perkawinan)
                        // all share name '' and would drop each other.
                        if (name && pushedNames.has(name)) continue;
                        const isChoice = t === 'radio' || t === 'checkbox';
                        // <select> has no type attribute — classify by tag.
                        const kind = tag === 'SELECT' ? 'select'
                            : isChoice ? t : 'text';
                        const key = isChoice ? (t + '' + name) : (kind + '' + name);
                        if (!byKey[key]) {
                            byKey[key] = { kind, name, els: [] };
                            groups.push(byKey[key]);
                        }
                        byKey[key].els.push(el);
                    }
                }
                if (!groups.length) continue;

                const resolve = (g) => {
                    const els = g.els;
                    if (g.kind === 'radio') {
                        const chosen = els.find(e => e.hasAttribute('checked'));
                        if (!chosen) return null;
                        const wrap = chosen.closest('label');
                        return (wrap && cleanText(wrap.textContent)) ||
                            chosen.getAttribute('value') || null;
                    }
                    if (g.kind === 'checkbox') {
                        if (els.length === 1) {
                            const e = els[0];
                            if (!e.hasAttribute('checked')) return null;
                            const wrap = e.closest('label');
                            return (wrap && cleanText(wrap.textContent)) ||
                                e.getAttribute('value') || true;
                        }
                        const obj = {};
                        for (const e of els) {
                            const wrap = e.closest('label');
                            const k = (wrap && cleanText(wrap.textContent)) ||
                                e.getAttribute('value') || '_';
                            obj[k] = e.hasAttribute('checked');
                        }
                        return obj;
                    }
                    if (g.kind === 'select') {
                        // Last [selected] wins (see the Pass 1 note). No
                        // implicit first-option fallback — an unanswered
                        // select stays null, never a browser default.
                        const opts = els[0].querySelectorAll('option[selected]');
                        const opt = opts.length ? opts[opts.length - 1] : null;
                        if (!opt) return null;
                        const optValue = opt.getAttribute('value') || '';
                        const t = cleanText(opt.textContent || '');
                        if (optValue === '' || /^-?\s*(pilih|select)\b/i.test(t)) return null;
                        return t || null;
                    }
                    // text / textarea
                    const e = els[0];
                    if (e.tagName === 'TEXTAREA') return cleanText(e.textContent || '') || null;
                    const v = e.getAttribute('value');
                    return (v === null || v === '') ? null : v;
                };

                let answer;
                if (groups.length === 1) {
                    answer = resolve(groups[0]);
                } else {
                    // Radio group + follow-up inputs (e.g. *_jelaskan) share
                    // the row label: emit {leaf: value, …} like Pass 2 does.
                    const obj = {};
                    for (const g of groups) {
                        const leaf = nameLeaf(g.name) || '_';
                        obj[leaf] = resolve(g);
                    }
                    answer = obj;
                }
                for (const g of groups) pushedNames.add(g.name);
                rowAnswers.push([q, answer]);
            }

            // Guard: ≥2 question rows distinguishes a question table from
            // generic display tables (which carry no .control-label).
            if (questionRowCount >= 2 && rowAnswers.length) {
                sections[section] = sections[section] || {};
                for (const [q, a] of rowAnswers) {
                    if (sections[section][q] === undefined) sections[section][q] = a;
                }
            }
        }

        // ── Pass 3: editable-grid tables (Resep, Pemakaian Obat, etc.) ──
        // These tables list CRUD-ed entities (one drug per row, one diagnosis
        // per row) with text/number/select inputs in cells. Each row becomes
        // a dict keyed by the table's <thead> headers.
        //
        // Heuristic for "data grid":
        //   - Has <thead> with at least one cell that has visible text.
        //   - Has <tbody> with at least one row whose cells yield non-empty
        //     values (skips template rows of unsaved forms).
        //   - At least one cell has a non-radio/non-checkbox control or a
        //     non-empty text node — separates from radio-grid forms (Skrining)
        //     which are already captured by Pass 1 as `fields`.
        //   - Not inside a boilerplate container / boilerplate section.
        //
        // Cell value: select → selected option text (skip placeholder);
        //   visible input → value; else → cleaned innerText.
        function cellValue(td) {
            // If the cell has form controls, the controls are the value
            // source. Plain innerText fallback would concatenate every
            // <option> text in a <select>, leaking the option list as
            // "data" for empty rows.
            const controls = td.querySelectorAll('input, textarea, select');
            const visibleControls = [];
            for (const c of controls) {
                const t = (c.getAttribute('type') || c.type || 'text').toLowerCase();
                if (t === 'radio' || t === 'checkbox') continue;
                if (isHidden(c)) continue;
                visibleControls.push(c);
            }
            if (visibleControls.length) {
                const vals = [];
                for (const c of visibleControls) {
                    if (c.tagName === 'SELECT') {
                        // Only take selected option (skip placeholder).
                        // Last `[selected]` wins (see the fields-pass note:
                        // poso marks placeholder AND value selected). No
                        // implicit first-option fallback — an unanswered
                        // select stays null, never a browser default.
                        const opts = c.querySelectorAll('option[selected]');
                        const opt = opts.length ? opts[opts.length - 1] : null;
                        if (!opt) continue;
                        const optValue = opt.getAttribute('value') || '';
                        const t = cleanText(opt.textContent || '');
                        if (optValue === '' || /^-?\s*(pilih|select)\b/i.test(t)) continue;
                        if (t) vals.push(t);
                    } else if (c.tagName === 'TEXTAREA') {
                        const v = cleanText(c.textContent || '');
                        if (v) vals.push(v);
                    } else {
                        const v = c.getAttribute('value') || '';
                        if (v) vals.push(v);
                    }
                }
                return vals.join(' ');
            }
            // No controls — static display cell (e.g. row number, "Loading…").
            return cleanText(td.innerText || td.textContent || '');
        }

        function rowHasNonRadioControl(tr) {
            const ctrls = tr.querySelectorAll('input, textarea, select');
            for (const c of ctrls) {
                const t = (c.getAttribute('type') || c.type || 'text').toLowerCase();
                if (t === 'radio' || t === 'checkbox') continue;
                return true;
            }
            // No controls at all → could be a static display row (still data).
            // CAVEAT: a separator/spacer row (zero controls) inside an
            // otherwise radio-only Skrining table will flag the whole
            // table as "data" and let it leak into Pass 3. ePus Skrining
            // tables currently put radios in every row, so we accept the
            // risk. Revisit if false-positive tables appear in output.
            return ctrls.length === 0;
        }

        const tables = {};
        const docTables = doc.querySelectorAll('table');
        const usedKeys = new Set();
        for (const tbl of docTables) {
            if (isInBoilerplateContainer(tbl)) continue;
            const section = sectionHeading(tbl);
            if (section && isSkippableSection(tbl, section)) continue;

            // Skip nested tables — only process tables that are not inside
            // another table (Bootstrap modal templates etc.).
            if (tbl.closest('table') !== tbl) continue;

            const headRow = tbl.querySelector(':scope > thead > tr');
            if (!headRow) continue;
            const rawHeaders = [];
            headRow.querySelectorAll(':scope > td, :scope > th').forEach((c) => {
                rawHeaders.push(cleanText(c.innerText || c.textContent || ''));
            });
            if (!rawHeaders.some(h => h)) continue;
            // De-dup duplicate header text so two cells with the same
            // <th> text do not collapse onto one key in the row dict
            // (last-cell-wins data loss). Empty headers stay empty —
            // they are dropped per-cell below.
            const headerSeen = new Map();
            const headers = rawHeaders.map((h) => {
                if (!h) return '';
                const n = (headerSeen.get(h) || 0) + 1;
                headerSeen.set(h, n);
                return n === 1 ? h : `${h} (${n})`;
            });

            const bodyRows = tbl.querySelectorAll(':scope > tbody > tr');
            if (!bodyRows.length) continue;

            // Skip radio/checkbox-only tables (Skrining) — fields pass
            // already captures them.
            let dataRowFound = false;
            for (const tr of bodyRows) {
                if (rowHasNonRadioControl(tr)) { dataRowFound = true; break; }
            }
            if (!dataRowFound) continue;

            const rows = [];
            for (const tr of bodyRows) {
                const cells = tr.querySelectorAll(':scope > td, :scope > th');
                if (!cells.length) continue;
                const row = {};
                let hasValue = false;
                cells.forEach((td, i) => {
                    const headerName = headers[i] || '';
                    const val = cellValue(td);
                    // No header text → checkbox/row-action column. Drop
                    // unconditionally; these are never patient data.
                    if (!headerName) return;
                    row[headerName] = val;
                    if (val) hasValue = true;
                });
                if (hasValue) rows.push(row);
            }
            if (!rows.length) continue;

            // Pick a key for the table — prefer the section heading, else
            // fall back to a synthetic one. Disambiguate duplicates.
            let key = section || `Tabel ${Object.keys(tables).length + 1}`;
            let baseKey = key;
            let n = 2;
            while (usedKeys.has(key)) {
                key = `${baseKey} (${n++})`;
            }
            usedKeys.add(key);
            tables[key] = rows;
        }

        return { fields: sections, tables };
    }
    return htmls.map(parseOne);
}
"""


# Cap total HTML bytes handed to a SINGLE page.evaluate. A patient with many
# large tabs (a bloated shared sidebar can make every tab 2–7 MB) would
# otherwise have all ~34 DOM trees built in the renderer at once — measured at
# a ~7 GB renderer spike for one 73-MB-of-tabs patient (Tebet pelayanan_id
# 1677062, #451/690 for 2025-01-02), enough to OOM-crash the renderer
# (TargetClosedError) mid-run. Splitting into byte-bounded sub-batches caps the
# peak to ~one budget's worth of DOM (<200 MB). Normal patients (<2 MB of tabs
# total) still parse in one evaluate, so the common path is unchanged. Output
# is identical: the parser JS does `htmls.map(parseOne)` with a fresh DOMParser
# per html — no cross-html state — so concatenating sub-batch results in order
# is byte-for-byte equivalent to one big call.
_PARSE_BATCH_BYTE_BUDGET = 2 * 1024 * 1024  # 2 MB of HTML per page.evaluate

# Laravel tab pages are ~half inline <script>/<style> (chart configs, select2
# init, datatables bootstrapping). The field extractor only walks
# .form-group/.control-label/inputs/selects — it never reads <script>/<style>/
# <noscript>, and DOMParser doesn't execute them anyway. Stripping them before
# the page.evaluate parse roughly halves the bytes crossing the CDP boundary
# AND the DOMParser node count → fewer 2 MB batches + faster parse, with
# byte-identical extracted output (verified). Toggle off via EPUS_STRIP_HTML=0.
_STRIP_HTML_NOISE = os.environ.get("EPUS_STRIP_HTML", "1") == "1"
_NOISE_TAG_RE = re.compile(
    r"<(script|style|noscript)\b[^>]*>.*?</\1\s*>", re.IGNORECASE | re.DOTALL
)


def _strip_html_noise(html: str) -> str:
    """Remove <script>/<style>/<noscript> blocks. Non-greedy, so a tag that
    contains a stray closing-tag-in-string only truncates early — the leftover
    is inert text the extractor never reads, so it's still data-safe."""
    if not html:
        return html
    return _NOISE_TAG_RE.sub("", html)


def _parse_tabs_batch(page: Page, htmls: list[str]) -> list[dict[str, Any]]:
    if _STRIP_HTML_NOISE:
        htmls = [_strip_html_noise(h) for h in htmls]
    out: list[dict[str, Any]] = []
    i, n = 0, len(htmls)
    while i < n:
        # Always take at least one html, so a single tab larger than the
        # budget still gets parsed (alone) rather than dropped.
        batch = [htmls[i]]
        size = len(htmls[i])
        i += 1
        while i < n and size + len(htmls[i]) <= _PARSE_BATCH_BYTE_BUDGET:
            size += len(htmls[i])
            batch.append(htmls[i])
            i += 1
        out.extend(_parse_tabs_evaluate(page, batch))
    return out


def _parse_tabs_evaluate(page: Page, htmls: list[str]) -> list[dict[str, Any]]:
    return page.evaluate(
        _FORM_PARSE_BATCH_JS,
        {
            "htmls": htmls,
            "skipSectionPrefixes": list(_BOILERPLATE_SECTION_PREFIXES),
            "skipContainerIds": list(_BOILERPLATE_CONTAINER_IDS),
            "nameHints": _NAME_HINTS,
        },
    )


# ─── Hidden-label fallback for PTM module form fields ────────────────────────
#
# Several EPUS PTM sub-forms render <input>/<textarea>/<select> controls
# WITHOUT a sibling .control-label — they live inside collapsed accordion
# panels or unlabeled cells (Lab numerics, EKG result, refraksi/lensa/retina
# detail, carta CV %, UBM Form). The ASIK CKG converter needs these values
# to fill Skrining Laboratorium / Skrining Jantung EKG / Skrining Telinga
# dan Mata refraksi / Prediksi Risiko Jantung Stroke / Perilaku Merokok
# Kadar CO forms.
#
# Live form audit 2026-05-10 against pelayanan_id 199138 enumerated every
# `<input name="Ptm[*]">` and mapped it to the human label visible on the
# rendered page. Each entry: full input `name` → {section, question}.
# JS parser uses these as a fallback when (a) the input has no label, OR
# (b) the auto-detected section is wrong.
#
# Section names are the headings the scraper would emit if a label were
# present — keeps consistency with the existing "PTM > <section> > <field>"
# breadcrumb shape used by epus_to_asik.py.

#
# Section names below MATCH the rendered PTM page's actual `.box-header`
# text — verified live 2026-05-10 against pelayanan_id 197732. Keeping the
# real headers (Fungsi Hati / Profil Lipid / Ginjal / Kardiovaskular / Mata
# / Saraf dan Otot) means epus_to_asik.py reads the same path it would see
# if a user inspected the form, and avoids inventing synthetic sections
# that drift from the source.
_NAME_HINTS: dict[str, dict[str, str]] = {
    # ── PTM > Pemeriksaan (HbA1c renders with a real .control-label, but
    #     hint pinning makes the dependency explicit for the converter).
    "Ptm[hba1c]":            {"section": "Pemeriksaan", "question": "HbA1c"},
    # ── PTM > Fungsi Hati
    "Ptm[sgot]":             {"section": "Fungsi Hati", "question": "SGOT"},
    "Ptm[sgot_v2]":          {"section": "Fungsi Hati", "question": "SGOT (kategori)"},
    "Ptm[sgpt]":             {"section": "Fungsi Hati", "question": "SGPT"},
    "Ptm[sgpt_v2]":          {"section": "Fungsi Hati", "question": "SGPT (kategori)"},
    "Ptm[hati_rujuk_rs]":    {"section": "Fungsi Hati", "question": "Rujuk RS (Hati)"},
    # ── PTM > Ginjal
    "Ptm[ureum]":            {"section": "Ginjal", "question": "Ureum"},
    "Ptm[ureum_v2]":         {"section": "Ginjal", "question": "Ureum (kategori)"},
    "Ptm[kreatinin]":        {"section": "Ginjal", "question": "Kreatinin"},
    "Ptm[kreatinin_v2]":     {"section": "Ginjal", "question": "Kreatinin (kategori)"},
    "Ptm[egfr]":             {"section": "Ginjal", "question": "eGFR"},
    "Ptm[proteinuria]":      {"section": "Ginjal", "question": "Proteinuria"},
    "Ptm[proteinuria_v2]":   {"section": "Ginjal", "question": "Proteinuria (kategori)"},
    "Ptm[ket_proteinuria]":  {"section": "Ginjal", "question": "Keterangan Proteinuria"},
    "Ptm[ginjal_rujuk_rs]":  {"section": "Ginjal", "question": "Rujuk RS (Ginjal)"},
    # ── PTM > Profil Lipid
    "Ptm[cholesterol_total]":{"section": "Profil Lipid", "question": "Cholesterol Total"},
    "Ptm[cholesterol_total_v2]":{"section": "Profil Lipid", "question": "Cholesterol Total (kategori)"},
    "Ptm[ldl]":              {"section": "Profil Lipid", "question": "LDL"},
    "Ptm[ldl_v2]":           {"section": "Profil Lipid", "question": "LDL (kategori)"},
    "Ptm[hdl]":              {"section": "Profil Lipid", "question": "HDL"},
    "Ptm[hdl_v2]":           {"section": "Profil Lipid", "question": "HDL (kategori)"},
    "Ptm[trigliserida]":     {"section": "Profil Lipid", "question": "Trigliserida"},
    "Ptm[trigliserida_v2]":  {"section": "Profil Lipid", "question": "Trigliserida (kategori)"},
    "Ptm[profil_lipid_rujuk_rs]": {"section": "Profil Lipid", "question": "Rujuk RS (Profil Lipid)"},
    # ── PTM > Skrining (one organ)
    "Ptm[skrining_ginjal_satu_organ]": {"section": "Skrining", "question": "Skrining Ginjal Satu Organ"},
    # ── PTM > Rontgen
    "Ptm[rontgen]":          {"section": "Rontgen", "question": "Rontgen"},
    # ── PTM > Kardiovaskular (EKG + Carta + rujuk RS)
    "Ptm[ekg]":              {"section": "Kardiovaskular", "question": "Hasil EKG (deskripsi)"},
    "Ptm[ekg_v2]":           {"section": "Kardiovaskular", "question": "Hasil EKG"},
    "Ptm[carta]":            {"section": "Kardiovaskular", "question": "Prediksi Risiko Penyakit Kardiovaskular"},
    "Ptm[kardiovaskuler_rujuk_rs]": {"section": "Kardiovaskular", "question": "Rujuk RS (Kardiovaskular)"},
    # ── PTM > Edukasi (Edukasi Carta lives in its own box per live DOM)
    "Ptm[edukasi_carta]":    {"section": "Edukasi", "question": "Edukasi Carta"},
    # ── PTM > Mata (refraksi / lensa / retina detail level — separate from Gangguan Penglihatan)
    "Ptm[refraksi]":         {"section": "Mata", "question": "Refraksi"},
    "Ptm[refraksi_knn]":     {"section": "Mata", "question": "Refraksi (Kanan/Kiri)"},
    "Ptm[lensa]":            {"section": "Mata", "question": "Lensa (Katarak)"},
    "Ptm[lensa_knn]":        {"section": "Mata", "question": "Lensa (Kanan/Kiri)"},
    "Ptm[retina]":           {"section": "Mata", "question": "Retina (Funduskopi)"},
    "Ptm[retina_knn]":       {"section": "Mata", "question": "Retina (Kanan/Kiri)"},
    "Ptm[mata_rujuk_rs]":    {"section": "Mata", "question": "Rujuk RS (Mata)"},
    # ── PTM > Saraf dan Otot (DM komplikasi)
    "Ptm[ulkus_diabetikum]": {"section": "Saraf dan Otot", "question": "Ulkus Diabetikum (deskripsi)"},
    "Ptm[ulkus_diabetikum_v2]": {"section": "Saraf dan Otot", "question": "Ulkus Diabetikum"},
    "Ptm[neuropati_dm_v2]":  {"section": "Saraf dan Otot", "question": "Neuropati DM"},
    "Ptm[motorik]":          {"section": "Saraf dan Otot", "question": "Motorik"},
    "Ptm[ket_motorik]":      {"section": "Saraf dan Otot", "question": "Keterangan Motorik"},
    "Ptm[sensorik]":         {"section": "Saraf dan Otot", "question": "Sensorik"},
    "Ptm[ket_sensorik]":     {"section": "Saraf dan Otot", "question": "Keterangan Sensorik"},
    "Ptm[saraf_dan_otot_rujuk_rs]": {"section": "Saraf dan Otot", "question": "Rujuk RS (Saraf dan Otot)"},
    # ── PTM > Form UBM (the controls already render under .control-label;
    #     hints are belt-and-braces for layout drift).
    "Ptm[ubm_konseling]":    {"section": "Form UBM", "question": "Konseling"},
    "Ptm[ubm_car]":          {"section": "Form UBM", "question": "CAR"},
    "Ptm[ubm_rujuk]":        {"section": "Form UBM", "question": "Rujuk UBM"},
    "Ptm[ubm_kondisi]":      {"section": "Form UBM", "question": "Kondisi"},
    # ── PTM > Gangguan Penglihatan / Pendengaran sub-blocks
    # Three Mata-Kanan/Kiri/Rujuk-RS radio groups (Katarak + Kelainan
    # Refraksi) share identical .control-label text inside the same
    # outer panel, so the auto-detector collapses them to one bucket.
    # Hint overrides force unique question keys per sub-block. The same
    # pattern applies to Pendengaran (Curiga Tuli Kongenital + OMSK/Congek
    # + Serumen all share Telinga Kanan/Kiri/Rujuk RS labels).
    "Ptm[katarak_kanan]":    {"section": "Gangguan Penglihatan", "question": "Katarak Mata Kanan"},
    "Ptm[katarak_kiri]":     {"section": "Gangguan Penglihatan", "question": "Katarak Mata Kiri"},
    "Ptm[katarak_rujuk_rs]": {"section": "Gangguan Penglihatan", "question": "Katarak Rujuk RS"},
    "Ptm[refraksi_kanan]":   {"section": "Gangguan Penglihatan", "question": "Refraksi Mata Kanan"},
    "Ptm[refraksi_kiri]":    {"section": "Gangguan Penglihatan", "question": "Refraksi Mata Kiri"},
    "Ptm[refraksi_rujuk_rs]":{"section": "Gangguan Penglihatan", "question": "Refraksi Rujuk RS"},
    "Ptm[congek_kanan]":     {"section": "Gangguan Pendengaran", "question": "Congek Telinga Kanan"},
    "Ptm[congek_kiri]":      {"section": "Gangguan Pendengaran", "question": "Congek Telinga Kiri"},
    "Ptm[congek_rujuk_rs]":  {"section": "Gangguan Pendengaran", "question": "Congek Rujuk RS"},
    "Ptm[serumen_kanan]":    {"section": "Gangguan Pendengaran", "question": "Serumen Telinga Kanan"},
    "Ptm[serumen_kiri]":     {"section": "Gangguan Pendengaran", "question": "Serumen Telinga Kiri"},
    "Ptm[serumen_rujuk_rs]": {"section": "Gangguan Pendengaran", "question": "Serumen Rujuk RS"},
    "Ptm[tuli_kongenital_kanan]": {"section": "Gangguan Pendengaran", "question": "Tuli Kongenital Telinga Kanan"},
    "Ptm[tuli_kongenital_kiri]":  {"section": "Gangguan Pendengaran", "question": "Tuli Kongenital Telinga Kiri"},
    "Ptm[tuli_kongenital_rujuk_rs]": {"section": "Gangguan Pendengaran", "question": "Tuli Kongenital Rujuk RS"},
}
