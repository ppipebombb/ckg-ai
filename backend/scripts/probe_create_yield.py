#!/usr/bin/env python
"""Dry-run yield probe for the ASIK "create new patient" feature.

Runs the create-flow's registration slice in PROBE mode over a puskesmas'
`epus_only + tandai_ckg` population: for each candidate it logs in, fills step-1,
clicks Selanjutnya, reads the guard, and commits NOTHING. The registration guard
("Individu sudah menerima layanan") is the only reliable "already in ASIK?"
detector (see documents/create-patient-asik/FINDINGS.md §2/§3b), so this is how
we measure the genuine new-registration yield — and the first candidate that
reaches step 2 captures the Alamat picker DOM we have never seen.

    cd backend
    python scripts/probe_create_yield.py --puskesmas cipondoh --limit 15 --headed
    python scripts/probe_create_yield.py --puskesmas tebet --limit 30      # headless

READ-ONLY on ASIK in --dry-run (the default): no patient is created.
"""
import argparse
import json
import logging
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session, load_only

from app.database import SessionLocal
from app.models.puskesmas import Puskesmas
from app.tasks.create_patient import probe_batch

# scripts/ -> backend/ -> repo root
REPO_ROOT = Path(__file__).resolve().parents[2]
STEP2_CAPTURE_PATH = REPO_ROOT / "documents" / "create-patient-asik" / "step2_capture.json"


def _resolve_puskesmas(db: Session, needle: str) -> Puskesmas:
    matches = list(db.scalars(
        select(Puskesmas)
        .options(load_only(Puskesmas.id, Puskesmas.name))
        .where(Puskesmas.name.ilike(f"%{needle}%"))
        .order_by(Puskesmas.name)
    ).all())
    if not matches:
        raise SystemExit(f"No puskesmas matches name ~ '{needle}'")
    if len(matches) > 1:
        names = ", ".join(p.name for p in matches)
        print(f"NOTE: {len(matches)} puskesmas matched '{needle}' [{names}] — using '{matches[0].name}'")
    return matches[0]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--puskesmas", required=True, help="Name substring (ILIKE match).")
    parser.add_argument("--limit", type=int, default=15, help="Max candidates to probe (default 15).")
    parser.add_argument(
        "--headless", dest="headless", action="store_true", default=True,
        help="Run Chromium headless (default).",
    )
    parser.add_argument("--headed", dest="headless", action="store_false", help="Show the browser.")
    parser.add_argument(
        "--dry-run", dest="dry_run", action="store_true", default=True,
        help="Probe only, create nothing (default).",
    )
    parser.add_argument(
        "--no-dry-run", dest="dry_run", action="store_false",
        help="(reserved) disable dry-run — the live create path is not wired yet.",
    )
    parser.add_argument(
        "--adults-only", dest="adults_only", action="store_true", default=False,
        help="Probe only 18+ candidates (exclude balita/children who can't be created).",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    db: Session = SessionLocal()
    try:
        pk = _resolve_puskesmas(db, args.puskesmas)
        print(f"Puskesmas: {pk.name} ({pk.id})")
        print(f"Mode: {'DRY-RUN (no create)' if args.dry_run else 'LIVE'}  "
              f"headless={args.headless}  limit={args.limit}  adults_only={args.adults_only}\n")

        result = probe_batch(
            db, pk.id, limit=args.limit, dry_run=args.dry_run, headless=args.headless,
            adults_only=args.adults_only,
        )
    finally:
        db.close()

    tally = result["tally"]
    probed = result["probed"]
    niks = result["would_create_niks"]

    print("\n===== PROBE SUMMARY =====")
    print(f"Puskesmas : {result['puskesmas_name']}")
    print(f"Probed    : {probed}")
    print(f"  would_create    : {tally['would_create']}")
    print(f"  already_served  : {tally['already_served']}")
    print(f"  dukcapil_invalid: {tally['dukcapil_invalid']}")
    print(f"  error           : {tally['error']}")
    if probed:
        pct = 100.0 * tally["would_create"] / probed
        print(f"  → genuine-new yield: {tally['would_create']}/{probed} ({pct:.1f}%)")

    if niks:
        print(f"\nwould_create NIKs ({len(niks)}):")
        for nik in niks:
            print(f"  {nik}")
    else:
        print("\nwould_create NIKs: (none)")

    step2 = result.get("step2_dom")
    if step2:
        STEP2_CAPTURE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STEP2_CAPTURE_PATH.write_text(json.dumps(step2, indent=2, ensure_ascii=False))
        print(f"\nstep2_dom captured → {STEP2_CAPTURE_PATH}")
    else:
        print("\nstep2_dom captured: NO (no candidate reached step 2)")


if __name__ == "__main__":
    main()
