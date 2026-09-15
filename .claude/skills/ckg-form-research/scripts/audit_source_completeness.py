#!/usr/bin/env python3
"""audit_source_completeness.py — does the SCRAPER capture everything the LIVE site serves?

Every OTHER audit checks the CONVERTER against our DB. None checks the SCRAPER against
the live portal — which is exactly the seam the 2026-06-05 jaksel miss lived in (its
new-build Anamnesa bar listed only ~15 of ~33 modules, so bar-only discovery silently
dropped 17 data-bearing tabs/patient — incl. the converter-consumed Konseling HIV / TB
Paru / PKPR — for the LARGEST region; no DB-side audit could see it).

This closes that seam. Per region (EPUS is multi-instance), read-only, no captcha:

  CHECK 1 — TABS (the jaksel class).  Runs the REAL production discovery
    (patient_scraper._extract_tab_bar ∪ _merge_known_modules) for sampled patients,
    then force-probes a candidate superset of modules. Flags:
      • a module that returns DATA but production discovery would MISS  → MUST-FIX
      • a module a region's bar lists that is NOT in _KNOWN_MODULES     → MUST-FIX
        (a build that hides it would lose it — add it to the safety-net union)

  CHECK 2 — SHOW SECTIONS.  Inventories server-rendered, data-bearing tables on
    /pelayanan/show and flags any NOT covered by _parse_show_html or the
    intentionally-skipped allowlist (redundant #content visit-summary) → TRIAGE.

  CHECK 3 — AJAX LOADERS.  Censuses read endpoints the page's inline scripts fire and
    flags new ones not on the captured / intentionally-skipped allowlist → TRIAGE.

Exit: 0 clean · 1 MUST-FIX (real scraper gap) · 3 TRIAGE-only (new section/loader to
review) · 2 ERROR (login / no data / infra).
"""
import argparse
import re
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

# _regions sets up backend import path + loads .env (CWD-independent).
from _regions import region_inventory  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.models.puskesmas import Puskesmas  # noqa: E402
from app.crud import puskesmas as pcrud  # noqa: E402
from sqlalchemy import select  # noqa: E402

# scraper package (helpers.* + patient_scraper) — add scrapers/epus to path.
REPO = Path(__file__).resolve().parents[4]
EPUS = REPO / "scrapers" / "epus"
sys.path.insert(0, str(EPUS))
import helpers.auth as auth  # noqa: E402
from helpers.browser import APIInterceptor  # noqa: E402
import patient_scraper as ps  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

# Show-page tables we already capture OR intentionally skip (redundant #content
# visit-summary that mirrors the module tabs). Anything data-bearing and NOT here
# is surfaced for triage. Keyed by table id and/or exact heading text.
_SHOW_TABLES_KNOWN = {
    # captured by _parse_show_html
    "table_pasien", "table_warna_penyakit", "table_risiko_kehamilan", "table_skrining",
    "table_riwayat", "table_alergi",
    "Data Pasien", "Penyakit Khusus", "Risiko Kehamilan", "Data Skrining",
    "Riwayat Pasien", "Alergi Pasien",
    # #content visit-summary — redundant with module tabs, intentionally not double-captured
    "table_data_anamnesa", "table_data_diagnosa", "table_data_periksafisik",
    "table_data_resep", "table_data_laboratorium", "table_data_rujukan_internal",
    "table_data_rujukan_external", "table_pendaftaran",
    # visible widgets that mirror a captured tab (triaged 2026-06-05 → redundant):
    "tabelRiwayat",   # "Riwayat PTM pada Diri Sendiri/Keluarga" widget == PTM tab fields
    "Mata",           # eye-exam summary == `mata` tab + PTM Gangguan Penglihatan (both captured)
}
# Modules handled OUTSIDE the tab-union pipeline (so "not in _KNOWN_MODULES" is fine):
# cppt is fetched via patient_scraper._fetch_cppt (the `cppt` key — its module tab is an
# empty XHR-loaded shell) and is in every region's bar, so the union never needs it.
_TABS_HANDLED_ELSEWHERE = {"cppt"}

# AJAX read endpoints we capture or intentionally skip. New reads not matching any
# of these substrings are surfaced for triage.
_AJAX_CAPTURED = ("getdatapkg", "/getlist", "/cppt/")
_AJAX_SKIP = (  # cross-visit / external / per-row detail / writes-we-avoid — see RESEARCH_STATUS
    "showriwayat", "getriwayaticare", "getdatariwayat", "laboratorium/getdatariwayat",
    "getresumeranap", "attachment/index", "tindakan/detail-information", "diagnosa/riwayat",
    "skrininghepb", "/add_pkg", "obatpasien/getdatastokdariruangan",
    "diagnosa/config/rujukanlab", "/create/", "/edit/", "klastersiklushidup",
    # klaster auto-SAVE write we deliberately never fire (the getlist READ is captured above,
    # matched first by _AJAX_CAPTURED, so this skip never shadows it):
    "klaster_siklushidup/",
)
_WRITE_HINTS = ("/store", "/save", "/kirim", "/update", "/delete", "/destroy", "/proses",
                "/send", "/setcall", "/switch", "sinkron", "inhealth", "sisrute",
                "jejaring", "update_jadwal", "delete_pkg")
_NONPATIENT = ("notifikasi", "/login", "/logout", "/home", "loket", "profil")

_INVENTORY_JS = r"""
(html) => {
  const doc = new DOMParser().parseFromString(html, 'text/html');
  const clean = s => (s||'').replace(/\s+/g,' ').trim();
  function titleOf(t){
    const tc=t.querySelector('thead tr:first-child td[colspan],thead tr:first-child th[colspan]');
    if(tc&&clean(tc.textContent)) return clean(tc.textContent);
    let s=t.previousElementSibling,h=0;
    while(s&&h<3){if(s.tagName==='LABEL'&&clean(s.textContent))return clean(s.textContent);s=s.previousElementSibling;h++;}
    const p=t.parentElement; if(p){const pl=p.querySelector(':scope > label'); if(pl&&clean(pl.textContent))return clean(pl.textContent);}
    const box=t.closest('.box,.panel'); if(box){const hd=box.querySelector('.box-header,.panel-heading'); if(hd)return clean(hd.textContent).slice(0,45);}
    return '';
  }
  const content = doc.getElementById('content');
  const out=[];
  doc.querySelectorAll('table').forEach(t=>{
    let ne=0; t.querySelectorAll('tbody tr').forEach(tr=>{if(clean(tr.textContent))ne++;});
    // in_content = inside the read-only #content visit-record SUMMARY (Data Anamnesa /
    // Pemeriksaan Fisik / Mata / Diagnosa / Resep / Lab / Assesmen / Status Fisis / Riwayat
    // PTM widget …). Every such box mirrors a module tab we already capture, so the caller
    // skips them — only data-bearing tables OUTSIDE #content are real candidate misses.
    const in_content = !!(content && content.contains(t));
    out.push({id:t.id||'', title:titleOf(t).slice(0,48), nonempty:ne, in_content});
  });
  return out;
}
"""


def _ajax_urls(html):
    out = []
    for m in re.finditer(r'\$\.ajax\s*\(\s*\{(.*?)\}\s*\)', html, re.S):
        u = re.search(r'url\s*:\s*["\'`]([^"\'`]+)', m.group(1))
        meth = re.search(r'(?:method|type)\s*:\s*["\']([^"\']+)', m.group(1))
        if u:
            out.append(((meth.group(1) if meth else "GET").upper(), u.group(1)))
    for pat, meth in [(r'\$\.get\s*\(\s*["\'`]([^"\'`]+)', "GET"),
                      (r'\$\.post\s*\(\s*["\'`]([^"\'`]+)', "POST"),
                      (r'\.load\s*\(\s*["\'`]([^"\'`]+)', "GET"),
                      (r'axios\.\w+\s*\(\s*["\'`]([^"\'`]+)', "GET"),
                      (r'fetch\s*\(\s*["\'`]([^"\'`]+)', "GET")]:
        for m in re.finditer(pat, html):
            out.append((meth, m.group(1)))
    return out


def _classify_ajax(url):
    u = url.lower()
    if any(s in u for s in _WRITE_HINTS):
        return "write"
    if any(s in u for s in _NONPATIENT):
        return "nonpatient"
    if any(s in u for s in _AJAX_CAPTURED):
        return "captured"
    if any(s in u for s in _AJAX_SKIP):
        return "skip"
    return "NEW-read"


def _find_date_ids(page, interc, base):
    base_d = date.today()
    for off in range(0, 14):
        d = (base_d - timedelta(days=off)).strftime("%d-%m-%Y")
        interc.clear()
        auth.navigate_to_pelayanan(page, base, tanggal=d, status_periksa="3",
                                   ruangan_id="0001", limit="100")
        page.wait_for_timeout(2200)
        recs = ((interc.latest_datatable() or {}).get("data") or {}).get("records") or []
        ids = [str(r.get("id")) for r in recs if r.get("id")]
        if ids:
            return d, ids
    return None, []


def audit_region(pw, name, base, cred, per_region):
    print(f"\n##### {name}  {base}", flush=True)
    findings = {"must_fix": [], "triage": []}
    ctx = pw.chromium.launch_persistent_context(
        user_data_dir=tempfile.mkdtemp(prefix="asc-"), headless=True,
        locale="id-ID", timezone_id="Asia/Jakarta")
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    try:
        auth.login(page, base, cred, headless=True)
        interc = APIInterceptor()
        page.on("response", interc.on_response)
        used, ids = _find_date_ids(page, interc, base)
        if not ids:
            print("  ERROR: no records on any recent date — cannot audit", flush=True)
            return None, findings
        ids = ids[:per_region]
        cookie = ps._cookie_header_from_context(ctx)
        bar_modules_region = set()
        for pid in ids:
            boot = f"{base}/anamnesa/create/{pid}?from='pelayanan'&action='edit'"
            bhtml = ps._parallel_fetch([boot], cookie_header=cookie,
                                       user_agent=ps._USER_AGENT, max_workers=1)[boot][1]
            if not bhtml:
                continue
            bar = ps._extract_tab_bar(page, bhtml, pelayanan_id=pid)
            bar_mods = {t["module"] for t in bar}
            bar_modules_region |= bar_mods
            prod = {t["module"] for t in ps._merge_known_modules(bar, base_url=base, pelayanan_id=pid)}

            # CHECK 1: force-probe modules NOT in production discovery; any with data = MISS.
            probe = [m for m in ps._KNOWN_MODULES if m not in prod]
            # also probe modules seen in OTHER regions' bars (cross-region superset)
            probe += [m for m in bar_modules_region if m not in prod and m not in probe]
            if probe:
                urls = {m: ps._module_url(base, m, pid) for m in probe}
                resp = ps._parallel_fetch(list(urls.values()), cookie_header=cookie,
                                          user_agent=ps._USER_AGENT, max_workers=10, retries=0)
                htmls, mods = [], []
                for m, u in urls.items():
                    h = resp[u][1]
                    if h and "halaman tidak ditemukan" not in h.lower():
                        htmls.append(h); mods.append(m)
                parsed = ps._parse_tabs_batch(page, htmls) if htmls else []
                for m, pr in zip(mods, parsed):
                    nf = sum(1 for sec in (pr.get("fields") or {}).values()
                             for v in sec.values() if v not in (None, "", {}, []))
                    nt = sum(len(r) for r in (pr.get("tables") or {}).values())
                    if nf + nt > 0:
                        findings["must_fix"].append(
                            f"MODULE MISSED: '{m}' returns data ({nf} fields/{nt} table-rows) "
                            f"for pid={pid} but production discovery would NOT fetch it")

            # CHECK 2: server-rendered show tables not captured / not allowlisted.
            show = f"{base}/pelayanan/show/{pid}"
            shtml = ps._parallel_fetch([show], cookie_header=cookie,
                                       user_agent=ps._USER_AGENT, max_workers=1)[show][1]
            if shtml:
                for t in page.evaluate(_INVENTORY_JS, shtml):
                    if t["nonempty"] <= 1:
                        continue  # template/empty
                    if t.get("in_content"):
                        continue  # #content visit-summary — mirrors a captured module tab
                    if t["id"] in _SHOW_TABLES_KNOWN or t["title"] in _SHOW_TABLES_KNOWN:
                        continue
                    findings["triage"].append(
                        f"SHOW SECTION: id='{t['id']}' title='{t['title']}' "
                        f"({t['nonempty']} data rows) not captured/allowlisted (pid={pid})")
                for meth, u in _ajax_urls(shtml):
                    if _classify_ajax(u) == "NEW-read":
                        norm = re.sub(r"/\d+", "/{id}", u.split("?")[0])
                        findings["triage"].append(f"AJAX READ: {meth} {norm} (pid={pid})")

        # CHECK 1b: bar modules not in the safety-net union → a build hiding them loses data.
        new_mods = bar_modules_region - set(ps._KNOWN_MODULES) - {"anamnesa"} - _TABS_HANDLED_ELSEWHERE
        if new_mods:
            findings["must_fix"].append(
                f"NEW MODULE(S) in this region's bar not in _KNOWN_MODULES: {sorted(new_mods)} "
                f"— add to patient_scraper._KNOWN_MODULES so a build hiding them still fetches them")
        print(f"  date={used} sampled={len(ids)} bar_modules={len(bar_modules_region)} "
              f"must_fix={len(findings['must_fix'])} triage={len(set(findings['triage']))}", flush=True)
        return bar_modules_region, findings
    except Exception as e:
        body = ""
        try:
            body = (page.content() or "").lower()
        except Exception:
            pass
        if any(m in body for m in ("pemeriksaan keamanan", "cloudflare", "security check",
                                   "verifikasi bahwa anda", "challenge-platform")):
            print("  ERROR: CLOUDFLARE bot-challenge on login — this is an INFRA block, NOT a "
                  "scraper gap. Back off automated logins (the daily pass does 1/region, so this "
                  "usually means the IP is flagged) or warm a session; re-run later. Reported as "
                  "ERROR (not 'clean') so the gate stays INCOMPLETE.", flush=True)
        else:
            import traceback
            print(f"  ERROR {type(e).__name__}: {e}", flush=True)
            traceback.print_exc()
        return None, None
    finally:
        try:
            ctx.close()
        except Exception:
            pass


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", default="epus")
    ap.add_argument("--per-region", type=int, default=3, help="patients sampled per region")
    ap.add_argument("--regions", nargs="*", default=None, help="restrict to url/name substrings")
    args = ap.parse_args()
    if args.source != "epus":
        print("Only --source epus is supported (EPUS-specific show/module structure).")
        return 2

    db = SessionLocal()
    inv = region_inventory(db, "epus")
    if args.regions:
        needles = [r.lower() for r in args.regions]
        inv = [r for r in inv if any(n in str(r["url"]).lower() or n in str(r["name"]).lower() for n in needles)]
    regions = []
    for r in inv:
        p = db.scalar(select(Puskesmas).where(Puskesmas.id == r["puskesmas_id"]))
        try:
            cred = pcrud.get_cred_decrypted(p, "epus")
        except Exception:
            cred = None
        if cred and cred.get("email") and cred.get("password"):
            regions.append((r["name"], f"https://{p.epus_url}", cred))
    db.close()

    if not regions:
        print("ERROR: no EPUS regions with credentials found.")
        return 2

    all_must, all_triage, errors = [], set(), 0
    union_bar = set()
    with sync_playwright() as pw:
        for name, base, cred in regions:
            bar, f = audit_region(pw, name, base, cred, args.per_region)
            if f is None:
                errors += 1
                continue
            if bar:
                union_bar |= bar
            all_must += [f"[{name}] {m}" for m in f["must_fix"]]
            all_triage |= {f"[{name}] {t}" for t in f["triage"]}

    print("\n" + "=" * 70)
    print("SOURCE-COMPLETENESS — SCRAPER vs LIVE")
    print("=" * 70)
    print(f"regions audited: {len(regions) - errors}/{len(regions)}  "
          f"union bar-modules: {len(union_bar)}  known-union: {len(ps._KNOWN_MODULES)}")
    if all_must:
        print(f"\nMUST-FIX ({len(all_must)}):")
        for m in all_must:
            print("  -", m)
    if all_triage:
        print(f"\nTRIAGE ({len(all_triage)}):")
        for t in sorted(all_triage):
            print("  -", t)
    if not all_must and not all_triage:
        print("\nclean — scraper captures every module/section/read the live site serves.")

    if errors and not all_must:
        print(f"\n[exit 2] {errors} region(s) failed to audit (login/data).")
        return 2
    if all_must:
        return 1
    if all_triage:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
