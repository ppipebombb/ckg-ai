"""One-time backfill: link cross-date ASIK_ONLY / EPUS_ONLY pairs.

The current matcher only collapses rows that share an exact filter_date.
In production, ASIK is recorded days–weeks after EPUS for the same visit,
so the same NIK lands in `asik_only` and `epus_only` on different dates and
never gets matched. The audit in TEBET_MATCH_AUDIT.md found 6,963 such pairs
in Tebet alone.

This script walks the existing data and links each unambiguous pair using
the new `match_group_id` column (migration 0017_patient_match_group_id):

For every (puskesmas_id, nik) that has BOTH an `asik_only` row and an
`epus_only` row within ±WINDOW days of each other:
  1. Pick the closest pair (ASIK row, EPUS row). Skip the (puskesmas, nik)
     entirely if the nearest pair is ambiguous (two candidates equidistant).
  2. Optional safety: skip if names disagree.
  3. Allocate a fresh `match_group_id` UUID. Write it to both rows.
  4. Copy each side's blob to the other: scraped_asik_data → EPUS row,
     scraped_epus_data → ASIK row.
  5. Flip both rows to MATCHED.

Both rows keep their own filter_date so lag analytics survive.

Idempotent — re-running finds zero candidates because the second pass sees
the previously-linked rows as MATCHED, not _only, and skips them.

Usage:
  cd backend
  python -m scripts.backfill_cross_date_match_groups --dry-run
  python -m scripts.backfill_cross_date_match_groups
  python -m scripts.backfill_cross_date_match_groups --puskesmas <UUID> --window 7
  python -m scripts.backfill_cross_date_match_groups --window 30 --skip-name-check
"""
from __future__ import annotations

import argparse
import logging
import uuid
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.patient import MatchStatus, Patient

log = logging.getLogger("backfill_cross_date_match_groups")


def _candidate_keys(
    db: Session, puskesmas_id: uuid.UUID | None
) -> list[tuple[uuid.UUID, str]]:
    """Return (puskesmas_id, nik) pairs that have at least one asik_only row
    AND at least one epus_only row. Soft-delete auto-filter excludes deleted
    rows from the SELECT.
    """
    asik_q = (
        select(Patient.puskesmas_id, Patient.nik)
        .where(Patient.match_status == MatchStatus.ASIK_ONLY)
        .distinct()
    )
    epus_q = (
        select(Patient.puskesmas_id, Patient.nik)
        .where(Patient.match_status == MatchStatus.EPUS_ONLY)
        .distinct()
    )
    if puskesmas_id is not None:
        asik_q = asik_q.where(Patient.puskesmas_id == puskesmas_id)
        epus_q = epus_q.where(Patient.puskesmas_id == puskesmas_id)
    stmt = asik_q.intersect(epus_q).order_by(
        Patient.puskesmas_id, Patient.nik
    )
    return list(db.execute(stmt).all())


def _pick_pair(
    db: Session,
    puskesmas_id: uuid.UUID,
    nik: str,
    window_days: int,
    skip_name_check: bool,
) -> tuple[Patient, Patient, int] | None:
    """For one (puskesmas, nik), pick the unambiguously closest
    (asik_only_row, epus_only_row) pair within ±window_days.

    Returns (asik_row, epus_row, day_diff) on success. day_diff is
    epus.filter_date - asik.filter_date (negative = epus earlier).

    Returns None when:
      - no pair within window
      - the nearest pair distance is tied (ambiguous)
      - names disagree and skip_name_check is False
    """
    asik_rows = list(
        db.scalars(
            select(Patient).where(
                Patient.puskesmas_id == puskesmas_id,
                Patient.nik == nik,
                Patient.match_status == MatchStatus.ASIK_ONLY,
                Patient.match_group_id.is_(None),
            )
        )
    )
    epus_rows = list(
        db.scalars(
            select(Patient).where(
                Patient.puskesmas_id == puskesmas_id,
                Patient.nik == nik,
                Patient.match_status == MatchStatus.EPUS_ONLY,
                Patient.match_group_id.is_(None),
            )
        )
    )
    if not asik_rows or not epus_rows:
        return None
    # All in-window pairs sorted by absolute day-diff.
    pairs: list[tuple[Patient, Patient, int]] = []
    for a in asik_rows:
        for e in epus_rows:
            d = (e.filter_date - a.filter_date).days
            if abs(d) <= window_days:
                pairs.append((a, e, d))
    if not pairs:
        return None
    pairs.sort(key=lambda t: (abs(t[2]), t[0].filter_date, t[1].filter_date))
    if len(pairs) >= 2 and abs(pairs[0][2]) == abs(pairs[1][2]):
        # Tie — different EPUS rows equally close to the same ASIK row, or
        # different ASIK rows equally close to the same EPUS row. Leave the
        # whole (puskesmas, nik) for manual review.
        return None
    a, e, d = pairs[0]
    if not skip_name_check:
        if a.nama.strip().lower() != e.nama.strip().lower():
            return None
    return a, e, d


def _link_pair(
    db: Session, asik: Patient, epus: Patient
) -> None:
    """Allocate one match_group_id, copy blobs both ways, flip both to MATCHED.

    epus_tandai_ckg is left on the EPUS-side row only (the ASIK row keeps it
    NULL). The Visit Summary count collapses cross-date twins by
    match_group_id anyway, so the same visit is never double-counted.
    """
    gid = uuid.uuid4()
    now = datetime.now(UTC)
    # ASIK row gets the EPUS blob — but NOT epus_tandai_ckg.
    db.execute(
        update(Patient)
        .where(Patient.id == asik.id, Patient.deleted_at.is_(None))
        .values(
            scraped_epus_data=epus.scraped_epus_data,
            match_status=MatchStatus.MATCHED,
            match_group_id=gid,
            updated_at=now,
        )
    )
    # EPUS row gets the ASIK blob.
    db.execute(
        update(Patient)
        .where(Patient.id == epus.id, Patient.deleted_at.is_(None))
        .values(
            scraped_asik_data=asik.scraped_asik_data,
            match_status=MatchStatus.MATCHED,
            match_group_id=gid,
            updated_at=now,
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would change without writing.",
    )
    parser.add_argument(
        "--window",
        type=int,
        default=7,
        help="Max |day_diff| between ASIK and EPUS rows to count as the same visit (default 7).",
    )
    parser.add_argument(
        "--puskesmas",
        type=str,
        default=None,
        help="Restrict to one puskesmas UUID. Default = all.",
    )
    parser.add_argument(
        "--skip-name-check",
        action="store_true",
        help="Pair even when nama differs. Default is to skip name mismatches.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Stop after linking N pairs (0 = unlimited). Useful for staged rollouts.",
    )
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    if args.window <= 0:
        log.error("--window must be > 0")
        return
    puskesmas_id = uuid.UUID(args.puskesmas) if args.puskesmas else None

    db: Session = SessionLocal()
    try:
        keys = _candidate_keys(db, puskesmas_id)
        log.info("found %d (puskesmas, nik) candidate keys", len(keys))

        linked = 0
        skipped_no_window_pair = 0
        skipped_ambiguous = 0
        skipped_name_mismatch = 0
        failed = 0

        for pid, nik in keys:
            if args.limit and linked >= args.limit:
                log.info("hit --limit=%d, stopping", args.limit)
                break
            try:
                picked = _pick_pair(
                    db, pid, nik, args.window, args.skip_name_check,
                )
                if picked is None:
                    # Drill into why for accurate counters.
                    asik_count = db.scalar(
                        select(func.count()).select_from(Patient).where(
                            Patient.puskesmas_id == pid,
                            Patient.nik == nik,
                            Patient.match_status == MatchStatus.ASIK_ONLY,
                            Patient.match_group_id.is_(None),
                        )
                    ) or 0
                    epus_count = db.scalar(
                        select(func.count()).select_from(Patient).where(
                            Patient.puskesmas_id == pid,
                            Patient.nik == nik,
                            Patient.match_status == MatchStatus.EPUS_ONLY,
                            Patient.match_group_id.is_(None),
                        )
                    ) or 0
                    if asik_count == 0 or epus_count == 0:
                        # Was linked by a previous iteration / already grouped.
                        continue
                    # Either window-miss, ambiguous, or name mismatch — log
                    # under one bucket. Re-pick with skip_name_check=True to
                    # disambiguate which.
                    second = _pick_pair(db, pid, nik, args.window, skip_name_check=True)
                    if second is None:
                        # Still none → window miss or ambiguous (we can't
                        # easily tell apart cheaply; lump them).
                        skipped_no_window_pair += 1
                    else:
                        # Pair found only when ignoring names → name mismatch.
                        skipped_name_mismatch += 1
                    continue
                asik, epus, day_diff = picked
                if args.dry_run:
                    log.info(
                        "LINK puskesmas=%s nik=%s asik_date=%s epus_date=%s diff=%+dd [DRY-RUN]",
                        pid, nik, asik.filter_date, epus.filter_date, day_diff,
                    )
                else:
                    _link_pair(db, asik, epus)
                    db.commit()
                    log.info(
                        "linked puskesmas=%s nik=%s asik_date=%s epus_date=%s diff=%+dd",
                        pid, nik, asik.filter_date, epus.filter_date, day_diff,
                    )
                linked += 1
            except Exception:
                db.rollback()
                failed += 1
                log.exception("FAILED puskesmas=%s nik=%s", pid, nik)

        log.info(
            "summary: linked=%d skipped_no_window=%d skipped_name_mismatch=%d failed=%d window=%dd%s",
            linked,
            skipped_no_window_pair,
            skipped_name_mismatch,
            failed,
            args.window,
            " [DRY-RUN]" if args.dry_run else "",
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
