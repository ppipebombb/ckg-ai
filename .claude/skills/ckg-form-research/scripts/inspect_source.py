"""Dump one patient's decrypted SOURCE record + what the converter extracts.

Use during mapping (step 3): see the raw source shape next to the converter's
ASIK-shaped output, so you can spot fields the source has but the converter
doesn't yet map.

Usage:
  backend/.venv/bin/python inspect_source.py --source epus [--nik NIK]
"""
import argparse
import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[4] / "backend"
sys.path.insert(0, str(BACKEND))


def _load_env():
    import os
    env = BACKEND / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_env()

import importlib                                # noqa: E402
from sqlalchemy import select, func            # noqa: E402
from sqlalchemy.orm import load_only           # noqa: E402
from app.database import SessionLocal          # noqa: E402
from app.core.security import decrypt_json     # noqa: E402
from app.models.patient import Patient, MatchStatus  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default="epus")
    ap.add_argument("--nik", default=None)
    ap.add_argument("--column", default=None)
    args = ap.parse_args()
    column = args.column or f"scraped_{args.source}_data"
    data_col = getattr(Patient, column)
    convert = getattr(importlib.import_module(f"app.services.{args.source}_to_asik"),
                      f"{args.source}_to_asik")

    db = SessionLocal()
    q = select(Patient).options(load_only(Patient.nik, Patient.nama, data_col)).where(
        Patient.deleted_at.is_(None), data_col.isnot(None))
    if args.nik:
        q = q.where(Patient.nik == args.nik)
    else:
        q = q.where(Patient.match_status == MatchStatus.MATCHED).order_by(func.random())
    p = db.scalar(q.limit(1))
    if not p:
        print("no matching patient with that source data"); sys.exit(1)
    raw = decrypt_json(getattr(p, column))
    converted = convert(raw)
    db.close()

    print(f"=== {p.nik} {p.nama}  source={args.source} ===\n")
    print("----- RAW SOURCE (top-level shape) -----")
    print(json.dumps(raw, ensure_ascii=False, indent=1)[:6000])
    print("\n----- CONVERTER OUTPUT (forms -> fields) -----")
    for form, fields in converted.items():
        filled = {k: v for k, v in (fields or {}).items() if v is not None}
        print(f"  {form}  ({len(filled)}/{len(fields or {})} filled)")
        for k, v in list(filled.items())[:6]:
            print(f"      {k[:60]} = {v!r}")


if __name__ == "__main__":
    main()
