"""One-time backfill: merge legacy orphan ASIK_ONLY rows into their sibling
EPUS_ONLY rows so they end up MATCHED — the state the new ASIK upsert
(`_upsert_asik` in app/crud/patient.py) would have produced if the records had
been scraped under the new EPUS→ASIK cron flow.

For every (puskesmas_id, nik, filter_date) group that contains BOTH:
  * an orphan ASIK row  — scraped_asik_data IS NOT NULL AND scraped_epus_data IS NULL
  * an EPUS-only row    — scraped_epus_data IS NOT NULL AND scraped_asik_data IS NULL

the script:
  1. takes the orphan's scraped_asik_data (latest orphan by updated_at if more
     than one exists),
  2. writes that blob into every EPUS-only sibling in the group and flips them
     to MATCHED,
  3. soft-deletes the orphan ASIK row(s).

Groups that don't fit the pattern (only ASIK_ONLY, only EPUS_ONLY, already
MATCHED, etc.) are left alone. Already-MATCHED siblings are not touched.

Idempotent — re-running after a successful pass finds zero groups.

Usage:
  cd backend
  python -m scripts.fix_orphan_asik_rows --dry-run   # preview only
  python -m scripts.fix_orphan_asik_rows             # apply
"""
from __future__ import annotations

import argparse
import logging
from datetime import UTC, datetime

from sqlalchemy import and_, func, select, update
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.patient import MatchStatus, Patient

log = logging.getLogger("fix_orphan_asik_rows")


_ASIK_ORPHAN = and_(
    Patient.scraped_asik_data.isnot(None),
    Patient.scraped_epus_data.is_(None),
)
_EPUS_ORPHAN = and_(
    Patient.scraped_epus_data.isnot(None),
    Patient.scraped_asik_data.is_(None),
)


def _find_candidate_groups(db: Session) -> list[tuple]:
    """Return (puskesmas_id, nik, filter_date) tuples for groups containing
    both an orphan ASIK row and an orphan EPUS row.

    Soft-delete auto-filter (app/core/soft_delete.py) already restricts to live
    rows on the SELECT, which is what we want.
    """
    stmt = (
        select(Patient.puskesmas_id, Patient.nik, Patient.filter_date)
        .group_by(Patient.puskesmas_id, Patient.nik, Patient.filter_date)
        .having(
            func.bool_or(_ASIK_ORPHAN),
            func.bool_or(_EPUS_ORPHAN),
        )
    )
    return list(db.execute(stmt).all())


def _fix_group(
    db: Session,
    puskesmas_id,
    nik: str,
    filter_date,
    dry_run: bool,
) -> tuple[int, int]:
    """Returns (epus_rows_updated, orphan_rows_deleted)."""
    rows = db.execute(
        select(
            Patient.id,
            Patient.scraped_asik_data,
            Patient.scraped_epus_data,
            Patient.ruangan,
            Patient.updated_at,
        )
        .where(
            Patient.puskesmas_id == puskesmas_id,
            Patient.nik == nik,
            Patient.filter_date == filter_date,
        )
        .order_by(Patient.updated_at.desc())
    ).all()

    asik_orphans = [
        r for r in rows
        if r.scraped_asik_data is not None and r.scraped_epus_data is None
    ]
    epus_targets = [
        r for r in rows
        if r.scraped_epus_data is not None and r.scraped_asik_data is None
    ]
    if not asik_orphans or not epus_targets:
        # Another worker may have raced in and fixed the group already.
        return 0, 0

    # Latest orphan's blob is canonical (matches new ASIK upsert's "last write wins").
    canonical_blob = asik_orphans[0].scraped_asik_data

    if dry_run:
        return len(epus_targets), len(asik_orphans)

    now = datetime.now(UTC)
    db.execute(
        update(Patient)
        .where(
            Patient.id.in_([r.id for r in epus_targets]),
            Patient.deleted_at.is_(None),
        )
        .values(
            scraped_asik_data=canonical_blob,
            match_status=MatchStatus.MATCHED,
            updated_at=now,
        )
    )
    db.execute(
        update(Patient)
        .where(
            Patient.id.in_([r.id for r in asik_orphans]),
            Patient.deleted_at.is_(None),
        )
        .values(deleted_at=now, updated_at=now)
    )
    return len(epus_targets), len(asik_orphans)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would change without writing.",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    db: Session = SessionLocal()
    try:
        groups = _find_candidate_groups(db)
        log.info(
            "found %d candidate (puskesmas, nik, filter_date) group(s)",
            len(groups),
        )

        total_merged = 0
        total_deleted = 0
        failed_groups = 0
        for puskesmas_id, nik, filter_date in groups:
            try:
                merged, deleted = _fix_group(
                    db, puskesmas_id, nik, filter_date, args.dry_run,
                )
                if not args.dry_run:
                    db.commit()
                total_merged += merged
                total_deleted += deleted
                log.info(
                    "puskesmas=%s nik=%s date=%s → merged %d EPUS row(s), "
                    "soft-deleted %d orphan ASIK row(s)%s",
                    puskesmas_id, nik, filter_date,
                    merged, deleted,
                    " [DRY-RUN]" if args.dry_run else "",
                )
            except Exception:
                db.rollback()
                failed_groups += 1
                log.exception(
                    "FAILED puskesmas=%s nik=%s date=%s",
                    puskesmas_id, nik, filter_date,
                )

        log.info(
            "summary: %d EPUS row(s) promoted to MATCHED, "
            "%d orphan ASIK row(s) soft-deleted, %d group(s) failed%s",
            total_merged, total_deleted, failed_groups,
            " [DRY-RUN]" if args.dry_run else "",
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
