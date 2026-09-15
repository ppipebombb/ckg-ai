"""
enrich_db_skrining.py — re-scrape a SAMPLE of existing matched patients with the
new scraper and update their ``scraped_epus_data`` in place, so the DB sample
carries ``skrining_klaster`` + ``cppt`` for the skill verification gates.

Targeted enrichment (NOT the full list-scrape flow): for N matched patients per
region that already have both scraped_epus_data + scraped_asik_data, decrypt to
get the pelayanan_id, re-fetch the detail (same visit, now incl. the Formulir
Skrining battery + CPPT), and overwrite the blob. Read-only against the portal
(the scraper never writes there); the only DB write is the per-patient
scraped_epus_data update (explicit deleted_at guard per project §6).

Usage (creds resolved from DB per region):
  backend/.venv/bin/python scrapers/epus/tools/enrich_db_skrining.py --per-region 50
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

EPUS_DIR = Path(__file__).resolve().parent.parent
BACKEND = EPUS_DIR.parent.parent / "backend"
sys.path.insert(0, str(EPUS_DIR))
sys.path.insert(0, str(BACKEND))


def _load_env():
    env = BACKEND / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_env()

from sqlalchemy import func, select, update  # noqa: E402
from sqlalchemy.orm import load_only  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402
from rich.console import Console  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.core.security import decrypt_json, encrypt_json  # noqa: E402
from app.models.patient import MatchStatus, Patient  # noqa: E402
from app.models.puskesmas import Puskesmas  # noqa: E402

from helpers import login  # noqa: E402
from patient_scraper import scrape_patient_detail  # noqa: E402

console = Console()


def _targets(db, puskesmas_id, n):
    rows = db.execute(
        select(Patient.id, Patient.nik, Patient.scraped_epus_data)
        .where(
            Patient.puskesmas_id == puskesmas_id,
            Patient.scraped_epus_data.isnot(None),
            Patient.scraped_asik_data.isnot(None),
            Patient.match_status == MatchStatus.MATCHED,
        )
        .order_by(func.random())
        .limit(n)
    ).all()
    out = []
    for pk, nik, blob in rows:
        try:
            pid = decrypt_json(blob).get("pelayanan_id")
        except Exception:
            pid = None
        if pid:
            out.append((pk, nik, str(pid)))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-region", type=int, default=50)
    ap.add_argument("--regions", nargs="*", default=["kotabekasi", "kotatangerang", "jaksel"])
    args = ap.parse_args()

    db = SessionLocal()
    pus = db.scalars(
        select(Puskesmas).options(
            load_only(Puskesmas.id, Puskesmas.name, Puskesmas.epus_url, Puskesmas.epus_cred)
        )
    ).all()

    total_done = total_skr = 0
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        for needle in args.regions:
            pk_pus = next((x for x in pus if needle in (x.epus_url or "")), None)
            if not pk_pus:
                console.print(f"[yellow]no puskesmas for {needle}[/yellow]")
                continue
            base = "https://" + pk_pus.epus_url
            cred = decrypt_json(pk_pus.epus_cred)
            targets = _targets(db, pk_pus.id, args.per_region)
            console.print(f"\n[cyan]{pk_pus.name} ({base})[/cyan] — {len(targets)} patients")
            ctx = browser.new_context(locale="id-ID", timezone_id="Asia/Jakarta")
            page = ctx.new_page()
            try:
                login(page, base, {"email": cred.get("email") or cred.get("username"),
                                   "password": cred.get("password")})
                for i, (pk, nik, pid) in enumerate(targets, 1):
                    try:
                        detail = scrape_patient_detail(ctx, page, base_url=base, pelayanan_id=pid)
                    except Exception as e:
                        console.print(f"  [{i}] pid={pid} scrape ERR: {str(e)[:60]}")
                        continue
                    n_skr = len(detail.get("skrining_klaster") or {})
                    db.execute(
                        update(Patient)
                        .where(Patient.id == pk, Patient.deleted_at.is_(None))
                        .values(scraped_epus_data=encrypt_json(detail))
                    )
                    db.commit()
                    total_done += 1
                    total_skr += 1 if n_skr else 0
                    if i % 10 == 0:
                        console.print(f"  …{i}/{len(targets)} (this run: {total_done} updated, "
                                      f"{total_skr} with ≥1 screening)")
            finally:
                ctx.close()
        browser.close()
    db.close()
    console.print(f"\n[green]done[/green] — {total_done} patients enriched, "
                  f"{total_skr} have ≥1 completed screening")


if __name__ == "__main__":
    main()
