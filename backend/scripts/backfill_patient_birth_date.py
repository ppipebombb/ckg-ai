"""One-time denormalization: populate Patient.birth_date from existing
scraped_epus_data / scraped_asik_data blobs WITHOUT a re-scrape.

The umur/age list filter needs a queryable birth_date, but the birth date only
lives inside the encrypted blobs. Going forward the scrape write-path
(crud/patient.py) sets the column; this script fills it for rows that existed
before the column landed.

Precedence is EPUS-wins, else ASIK (services/birthdate.py) — the same rule the
merge uses for identitas. Rows with no parseable birth date in either blob keep
birth_date = NULL (counted under "no_date") and are excluded whenever an age
bound is active.

DB-only — no network, no Playwright. Idempotent + resumable: re-running just
rewrites the same value.

Run it inside the backend/worker container (has the DB + decryption key):

  docker exec -it ckg-ai-celery_worker-1 \
      python -m scripts.backfill_patient_birth_date --dry-run --limit 50
  docker exec -it ckg-ai-celery_worker-1 \
      python -m scripts.backfill_patient_birth_date --puskesmas <UUID>
  docker exec -it ckg-ai-celery_worker-1 python -m scripts.backfill_patient_birth_date

Progress prints to stdout every batch (processed / from_epus / from_asik /
no_date / errors).
"""
from __future__ import annotations

import argparse
import logging
import uuid

from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session, load_only

from app.core.security import decrypt_json
from app.database import SessionLocal
from app.models.patient import Patient
from app.services.birthdate import birth_date_from_asik, birth_date_from_epus

log = logging.getLogger("backfill_patient_birth_date")


def _row_ids(db: Session, only: uuid.UUID | None, limit: int) -> list[uuid.UUID]:
    stmt = (
        select(Patient.id)
        .where(
            or_(
                Patient.scraped_epus_data.isnot(None),
                Patient.scraped_asik_data.isnot(None),
            ),
            Patient.deleted_at.is_(None),
        )
        .order_by(Patient.id)
    )
    if only is not None:
        stmt = stmt.where(Patient.puskesmas_id == only)
    if limit:
        stmt = stmt.limit(limit)
    return list(db.scalars(stmt))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Read + report, write nothing.")
    parser.add_argument("--puskesmas", type=str, default=None, help="Restrict to one puskesmas UUID.")
    parser.add_argument("--batch-size", type=int, default=500, help="Rows per DB commit batch (default 500).")
    parser.add_argument("--limit", type=int, default=0, help="Cap total rows (0 = all). For testing.")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    only = uuid.UUID(args.puskesmas) if args.puskesmas else None

    totals = {"processed": 0, "from_epus": 0, "from_asik": 0, "no_date": 0, "errors": 0}
    db: Session = SessionLocal()
    try:
        row_ids = _row_ids(db, only, args.limit)
        log.info("%d candidate rows%s", len(row_ids), " [DRY-RUN]" if args.dry_run else "")
        for start in range(0, len(row_ids), args.batch_size):
            batch = row_ids[start : start + args.batch_size]
            rows = db.scalars(
                select(Patient)
                .options(load_only(
                    Patient.id, Patient.scraped_epus_data, Patient.scraped_asik_data,
                ))
                .where(Patient.id.in_(batch), Patient.deleted_at.is_(None))
            ).all()
            for row in rows:
                try:
                    epus = decrypt_json(row.scraped_epus_data) if row.scraped_epus_data else None
                    asik = decrypt_json(row.scraped_asik_data) if row.scraped_asik_data else None
                except Exception:
                    totals["errors"] += 1
                    continue
                bd = birth_date_from_epus(epus)
                source = "from_epus"
                if bd is None:
                    bd = birth_date_from_asik(asik)
                    source = "from_asik"
                if bd is None:
                    totals["no_date"] += 1
                    continue
                totals[source] += 1
                totals["processed"] += 1
                if not args.dry_run:
                    db.execute(
                        update(Patient)
                        .where(Patient.id == row.id, Patient.deleted_at.is_(None))
                        .values(birth_date=bd, updated_at=func.now())
                    )
            if not args.dry_run:
                db.commit()
            log.info(
                "%d/%d rows | from_epus=%d from_asik=%d no_date=%d errors=%d%s",
                min(start + args.batch_size, len(row_ids)), len(row_ids),
                totals["from_epus"], totals["from_asik"], totals["no_date"], totals["errors"],
                " [DRY-RUN]" if args.dry_run else "",
            )
        log.info(
            "DONE: processed=%d from_epus=%d from_asik=%d no_date=%d errors=%d%s",
            totals["processed"], totals["from_epus"], totals["from_asik"],
            totals["no_date"], totals["errors"], " [DRY-RUN]" if args.dry_run else "",
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
