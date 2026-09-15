"""
recon_skrining.py — enumerate the "Klaster & Siklus Hidup → Formulir Skrining"
battery for ONE EPUS region, READ-ONLY.

Why: the main scraper walks the clinical module tabs but skips the dedicated
CKG screening forms (box-KlasterSiklusHidup is blocklisted). Those forms hold
the questionnaire data the ASIK "CKG vs ePus" sheet marks "Belum ada di ePus"
(PHQ-4 Kesehatan Jiwa, SKILAS/ADL lansia, PPOK PUMA, cancer-risk, TB risk, …).
This tool maps the battery so the scraper + converter can be built against
real structure, not guesses.

Data model (verified 2026-06-04, all 3 regions):
  - HUB:   POST /klaster_siklushidup/{pelayanan_id}/getlist
           body  tahun=YYYY&pelayanan_id=<pid>&_token=<csrf>
           → JSON {data:[ {key, nama, route, klaster:[{id, skrining_id,
                            kesimpulan, hasil_skrining, warna_badge, tanggal}]}, …]}
           klaster.length>0  ⇒ that screening has a SAVED record (DONE).
  - VIEW:  GET /{route}/edit/{record_id}      (most screenings)
           per-key quirks exist (gejala_tbc route=/skrining/tbc; phq_4 uses
           /edit/{pid}?header={id}); this tool PROBES candidates and records
           which one works, so we don't hardcode wrong.
  - /{route}/create/{pid} is the BLANK form (prefills vitals only) — not saved data.

All requests are GET or the getlist read-POST. NEVER posts a save. The auto-save
POST /klaster_siklushidup/{id} only fires on a real-browser /show load (JS); the
APIRequest fetches here run no JS, so it never fires.

Usage:
  python tools/recon_skrining.py --base-url https://jaksel.epuskesmas.id \
      --email <e> --password <p> --pids-file /tmp/jaksel_pids.json \
      --tahun 2026 --max-pids 120 --out output/skrining_catalog_jaksel.json
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # scrapers/epus

from playwright.sync_api import sync_playwright  # noqa: E402
from rich.console import Console  # noqa: E402

from helpers import login  # noqa: E402
from patient_scraper import _parse_tabs_batch  # noqa: E402

console = Console()


def _load_pids(path: str) -> list[str]:
    raw = json.loads(Path(path).read_text())
    out = []
    for item in raw:
        if isinstance(item, dict):
            pid = item.get("pid") or item.get("pelayanan_id")
        else:
            pid = item
        if pid:
            out.append(str(pid))
    return out


def _csrf_token(ctx, base_url: str) -> str:
    """Laravel CSRF token from any authed page's <meta name=csrf-token>."""
    resp = ctx.request.get(f"{base_url}/home", timeout=60000)
    html = resp.text()
    import re
    m = re.search(r'name="csrf-token"\s+content="([^"]+)"', html)
    return m.group(1) if m else ""


def _getlist(ctx, base_url: str, pid: str, tahun: str, token: str) -> list[dict]:
    """POST getlist; return the screening list (each: key, nama, route, klaster[])."""
    url = f"{base_url}/klaster_siklushidup/{pid}/getlist"
    try:
        resp = ctx.request.post(
            url,
            form={"tahun": tahun, "pelayanan_id": pid, "_token": token},
            headers={
                "X-CSRF-TOKEN": token,
                "X-Requested-With": "XMLHttpRequest",
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "Referer": f"{base_url}/klaster_siklushidup/{pid}",
            },
            timeout=60000,
        )
        if resp.status != 200:
            return []
        body = resp.json()
    except Exception:
        return []
    data = body.get("data") if isinstance(body, dict) else None
    if isinstance(data, dict):
        data = list(data.values())
    if not isinstance(data, list):
        return []
    return [v for v in data if isinstance(v, dict) and "route" in v]


def _edit_candidates(route: str, rec: dict, pid: str) -> list[str]:
    """Ordered candidate VIEW urls for a saved screening record."""
    rid = rec.get("id")
    sid = rec.get("skrining_id")
    c = []
    if rid is not None:
        c += [f"{route}/edit/{rid}", f"{route}/edit/{rid}/{pid}",
              f"{route}/edit/{pid}?header={rid}"]
    if sid is not None:
        c += [f"{route}/edit/{sid}", f"{route}/edit/{sid}/{pid}"]
    c += [f"{route}/{pid}"]  # gejala_tbc-style
    # de-dup preserving order
    seen, out = set(), []
    for u in c:
        if u not in seen:
            seen.add(u); out.append(u)
    return out


def _probe_view(ctx, base_url: str, route: str, rec: dict, pid: str):
    """Return (working_url, html) for the saved screening, or (None, None)."""
    for path in _edit_candidates(route, rec, pid):
        url = base_url + path if path.startswith("/") else f"{base_url}/{path}"
        try:
            resp = ctx.request.get(url, timeout=60000)
            if resp.status != 200:
                continue
            html = resp.text()
        except Exception:
            continue
        if "tidak ditemukan" in html.lower():
            continue
        # require it to look like a form with at least one checked control
        if ("checked" in html) or html.count("<input") > 5:
            return path, html
    return None, None


def _answered(page, html: str) -> dict:
    """Cheap raw extraction of ANSWERED fields (checked radios + filled
    inputs/selects), independent of the tab parser — used to judge whether the
    existing parser captures the screening's table-layout questions."""
    js = r"""(html) => {
      const d = new DOMParser().parseFromString(html, 'text/html');
      const out = {radios:{}, vals:{}}; const seen = new Set();
      d.querySelectorAll('input[type=radio]').forEach(r=>{
        if(seen.has(r.name))return; seen.add(r.name);
        const g=[...d.querySelectorAll(`input[type=radio][name="${r.name}"]`)];
        const c=g.find(x=>x.hasAttribute('checked'));
        if(c){const lbl=(c.closest('label')?.textContent||c.getAttribute('value')||'').replace(/\s+/g,' ').trim();
          out.radios[r.name]=lbl.slice(0,30);}
      });
      d.querySelectorAll('select').forEach(s=>{const o=s.querySelector('option[selected]');
        if(o){const t=(o.textContent||'').trim(); if(t&&!/^[-\s]*pilih/i.test(t)) out.vals[s.getAttribute('name')||'?']=t.slice(0,30);}});
      d.querySelectorAll('input[type=text],input[type=number],textarea').forEach(el=>{
        const v=el.getAttribute('value'); if(v&&v.trim()) out.vals[el.getAttribute('name')||'?']=v.trim().slice(0,30);});
      return out;
    }"""
    try:
        return page.evaluate(js, html)
    except Exception:
        return {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--email", required=True)
    ap.add_argument("--password", required=True)
    ap.add_argument("--pids-file", required=True)
    ap.add_argument("--tahun", default="2026")
    ap.add_argument("--max-pids", type=int, default=120)
    ap.add_argument("--samples-per-key", type=int, default=2,
                    help="how many filled examples to fetch+parse per screening key")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    pids = _load_pids(args.pids_file)[: args.max_pids]
    console.print(f"[cyan]{args.base_url}[/cyan] — {len(pids)} pids, tahun={args.tahun}")

    catalog: dict[str, dict] = {}
    done_counts: dict[str, int] = defaultdict(int)
    n_patients_with_done = 0

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(locale="id-ID", timezone_id="Asia/Jakarta")
        page = ctx.new_page()
        try:
            login(page, args.base_url, {"email": args.email, "password": args.password})
            token = _csrf_token(ctx, args.base_url)
            if not token:
                console.print("[red]No CSRF token — aborting[/red]"); return
            console.print(f"  token ok ({token[:8]}…)")

            for i, pid in enumerate(pids, 1):
                screenings = _getlist(ctx, args.base_url, pid, args.tahun, token)
                any_done = False
                for s in screenings:
                    key = s.get("key") or "?"
                    route = s.get("route") or ""
                    nama = s.get("nama") or s.get("label") or ""
                    recs = s.get("klaster") or []
                    cat = catalog.setdefault(key, {
                        "nama": nama, "route": route, "done_count": 0,
                        "regions": args.base_url, "edit_url_pattern": None,
                        "samples": [], "record_fields_seen": {},
                    })
                    if not cat["nama"] and nama:
                        cat["nama"] = nama
                    if recs:
                        any_done = True
                        cat["done_count"] += len(recs)
                        done_counts[key] += 1
                        # capture the metadata keys present on records (kesimpulan etc.)
                        for r in recs:
                            for k in r.keys():
                                cat["record_fields_seen"][k] = cat["record_fields_seen"].get(k, 0) + 1
                        # fetch a few filled examples per key
                        if len(cat["samples"]) < args.samples_per_key:
                            url, html = _probe_view(ctx, args.base_url, route, recs[0], pid)
                            if url and html:
                                cat["edit_url_pattern"] = cat["edit_url_pattern"] or _pattern_of(url, recs[0], pid)
                                parsed = _parse_tabs_batch(page, [html])[0]
                                ans = _answered(page, html)
                                cat["samples"].append({
                                    "pid": pid, "url": url,
                                    "parser_sections": {k: list(v.keys()) for k, v in (parsed.get("fields") or {}).items()},
                                    "parser_n_fields": sum(len(v) for v in (parsed.get("fields") or {}).values()),
                                    "parser_tables": list((parsed.get("tables") or {}).keys()),
                                    "answered_radios": ans.get("radios", {}),
                                    "answered_vals": ans.get("vals", {}),
                                })
                if any_done:
                    n_patients_with_done += 1
                if i % 20 == 0:
                    console.print(f"  …{i}/{len(pids)} pids, {len(catalog)} screening types seen")
                time.sleep(0.05)
        finally:
            browser.close()

    out = {
        "base_url": args.base_url, "tahun": args.tahun,
        "n_pids": len(pids), "n_patients_with_done": n_patients_with_done,
        "done_patient_counts": dict(sorted(done_counts.items(), key=lambda kv: -kv[1])),
        "catalog": catalog,
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, ensure_ascii=False, indent=1))
    console.print(f"[green]wrote {args.out}[/green] — {len(catalog)} screening types, "
                  f"{n_patients_with_done}/{len(pids)} patients with ≥1 done")


def _pattern_of(url: str, rec: dict, pid: str) -> str:
    """Describe which placeholder the working url used (for the per-key map)."""
    rid, sid = str(rec.get("id")), str(rec.get("skrining_id"))
    pat = url
    if rid and rid != "None":
        pat = pat.replace("/" + rid, "/{id}")
    if sid and sid != "None":
        pat = pat.replace("/" + sid, "/{skrining_id}")
    pat = pat.replace("/" + str(pid), "/{pid}").replace("=" + str(pid), "={pid}")
    return pat


if __name__ == "__main__":
    main()
