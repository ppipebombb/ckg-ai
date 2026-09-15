"""One-time denormalization: populate Patient.epus_tandai_ckg from existing
scraped_epus_data blobs WITHOUT a re-scrape.

The CKG "sudah CKG" flag lives inside the encrypted EPUS blob at
``blob["ckg"]["sudah_ckg"]`` (added by the scraper / backfill_ckg.py). The
Visit Summary now counts it from a denormalized boolean column
``patients.epus_tandai_ckg`` so it doesn't have to decrypt every blob. This
script reads the flag straight from the blob and writes the column.

DB-only — no EPUS network, no Playwright. For every live patient row with an
EPUS blob it decrypts, reads ``ckg.sudah_ckg``, and updates the column.

DEPENDS ON backfill_ckg.py: blobs scraped before the CKG feature have no
``ckg`` key. Those rows are left with epus_tandai_ckg = NULL (counted under
"no_ckg"). Run backfill_ckg.py first to populate the key, then this.

Idempotent + resumable: re-running just rewrites the same column value.

Run it inside the backend/worker container (has the DB + decryption key):

  docker exec -it ckg-ai-celery_worker-1 \
      python -m scripts.backfill_epus_tandai_ckg --dry-run --limit 50
  docker exec -it ckg-ai-celery_worker-1 \
      python -m scripts.backfill_epus_tandai_ckg --puskesmas <UUID>
  docker exec -it ckg-ai-celery_worker-1 python -m scripts.backfill_epus_tandai_ckg

Progress prints to stdout every batch (processed / ya / tidak / no_ckg / errors).
"""
from __future__ import annotations

import argparse
import logging
import uuid

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, load_only

from app.core.security import decrypt_json
from app.database import SessionLocal
from app.models.patient import Patient

log = logging.getLogger("backfill_epus_tandai_ckg")


def _extract_tandai_ckg(blob: object) -> bool | None:
    """ckg.sudah_ckg from a decrypted EPUS blob. None when no ckg key."""
    if not isinstance(blob, dict):
        return None
    ckg = blob.get("ckg")
    if not isinstance(ckg, dict) or "sudah_ckg" not in ckg:
        return None
    return bool(ckg.get("sudah_ckg"))


def _row_ids(db: Session, only: uuid.UUID | None, limit: int) -> list[uuid.UUID]:
    stmt = (
        select(Patient.id)
        .where(
            Patient.scraped_epus_data.isnot(None),
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

    totals = {"processed": 0, "ya": 0, "tidak": 0, "no_ckg": 0, "errors": 0}
    db: Session = SessionLocal()
    try:
        row_ids = _row_ids(db, only, args.limit)
        log.info("%d candidate rows%s", len(row_ids), " [DRY-RUN]" if args.dry_run else "")
        for start in range(0, len(row_ids), args.batch_size):
            batch = row_ids[start : start + args.batch_size]
            rows = db.scalars(
                select(Patient)
                .options(load_only(Patient.id, Patient.scraped_epus_data))
                .where(Patient.id.in_(batch), Patient.deleted_at.is_(None))
            ).all()
            for row in rows:
                try:
                    blob = decrypt_json(row.scraped_epus_data)
                except Exception:
                    totals["errors"] += 1
                    continue
                val = _extract_tandai_ckg(blob)
                if val is None:
                    totals["no_ckg"] += 1
                    continue
                totals["ya" if val else "tidak"] += 1
                totals["processed"] += 1
                if not args.dry_run:
                    db.execute(
                        update(Patient)
                        .where(Patient.id == row.id, Patient.deleted_at.is_(None))
                        .values(epus_tandai_ckg=val, updated_at=func.now())
                    )
            if not args.dry_run:
                db.commit()
            log.info(
                "%d/%d rows | ya=%d tidak=%d no_ckg=%d errors=%d%s",
                min(start + args.batch_size, len(row_ids)), len(row_ids),
                totals["ya"], totals["tidak"], totals["no_ckg"], totals["errors"],
                " [DRY-RUN]" if args.dry_run else "",
            )
        log.info(
            "DONE: processed=%d ya=%d tidak=%d no_ckg=%d errors=%d%s",
            totals["processed"], totals["ya"], totals["tidak"],
            totals["no_ckg"], totals["errors"], " [DRY-RUN]" if args.dry_run else "",
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
