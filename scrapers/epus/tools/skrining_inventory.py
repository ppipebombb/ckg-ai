"""
skrining_inventory.py — field inventory of the Formulir Skrining battery for
ONE region, using the REAL scraper functions (_fetch_skrining +
_attach_skrining_detail). For each screening key, aggregates across done
patients: the union of `detail` field names (edit-page, {name:value}) and
`record` field names (getlist klaster record), each with a sample value.

This is the reference for writing epus_to_asik screening mappers and for the
Excel/PDF "Belum ada di ePus" cross-check. Read-only.

Usage:
  python tools/skrining_inventory.py --base-url https://jaksel.epuskesmas.id \
    --email <e> --password <p> --pids-file /tmp/jaksel_pids.json \
    --max-pids 120 --out output/skrining_inventory_jaksel.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from playwright.sync_api import sync_playwright  # noqa: E402
from rich.console import Console  # noqa: E402

from helpers import login  # noqa: E402
from patient_scraper import (  # noqa: E402
    _attach_skrining_detail, _csrf_token, _fetch_skrining,
)

console = Console()
_META = {
    "id", "header_id", "tanggal", "created_at", "updated_at", "created_by",
    "updated_by", "nm_petugas", "petugas_id", "skrining_id", "pelayanan_id",
    "warna_badge", "dokter_id", "changes", "noerm", "pasien", "nama",
    "nama_petugas", "petugas_nama", "no_rekam_medis", "no-rekam-medis",
    "nama-pasien", "pasien_id", "tanggal-lahir", "tanggal_lahir", "nik",
    "jenis_kelamin", "no_hp", "alamat", "umur_pasien", "pekerjaan", "data_imt",
}


def _load_pids(path):
    raw = json.loads(Path(path).read_text())
    return [str(x.get("pid") if isinstance(x, dict) else x) for x in raw]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--email", required=True)
    ap.add_argument("--password", required=True)
    ap.add_argument("--pids-file", required=True)
    ap.add_argument("--max-pids", type=int, default=120)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    pids = _load_pids(args.pids_file)[: args.max_pids]

    inv: dict[str, dict] = {}
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        ctx = b.new_context(locale="id-ID", timezone_id="Asia/Jakarta")
        page = ctx.new_page()
        try:
            login(page, args.base_url, {"email": args.email, "password": args.password})
            home = ctx.request.get(f"{args.base_url}/home", timeout=60000)
            csrf = _csrf_token(home.text())
            cookie = "; ".join(f"{c['name']}={c['value']}" for c in ctx.cookies())
            ua = "Mozilla/5.0 epus-v2/inventory"
            for i, pid in enumerate(pids, 1):
                raw = _fetch_skrining(
                    base_url=args.base_url, cookie_header=cookie, user_agent=ua,
                    pelayanan_id=pid, csrf=csrf, year="2026",
                    referer=f"{args.base_url}/pelayanan/show/{pid}",
                )
                skr = _attach_skrining_detail(page, raw)
                for key, v in skr.items():
                    e = inv.setdefault(key, {
                        "nama": v.get("nama"), "route": v.get("route"),
                        "n": 0, "detail_fields": {}, "record_fields": {},
                    })
                    e["n"] += 1
                    for fn, fv in (v.get("detail") or {}).items():
                        if fn in _META:
                            continue
                        if fn not in e["detail_fields"] and fv not in (None, ""):
                            e["detail_fields"][fn] = str(fv)[:40]
                    for rec in (v.get("records") or [])[:1]:
                        for fn, fv in rec.items():
                            if fn in _META:
                                continue
                            if fn not in e["record_fields"] and fv not in (None, ""):
                                e["record_fields"][fn] = str(fv)[:40]
                if i % 30 == 0:
                    console.print(f"  …{i}/{len(pids)}  ({len(inv)} screening types)")
        finally:
            b.close()
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(inv, ensure_ascii=False, indent=1))
    console.print(f"[green]wrote {args.out}[/green] — {len(inv)} screening types")


if __name__ == "__main__":
    main()
