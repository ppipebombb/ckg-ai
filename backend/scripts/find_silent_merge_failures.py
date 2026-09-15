#!/usr/bin/env python
"""Find merge jobs that were silently mismarked SUCCESS while patients failed.

Before the merge-status fix, run_merge unconditionally marked a job SUCCESS even
when every per-patient merge failed (e.g. during the gpt-oss 530 outage). Those
jobs read as "done" but wrote no merged_data. This READ-ONLY script lists the
affected (puskesmas, date_filter) ranges so you can re-merge them once the LLM
provider is healthy — feed the ranges into a force-remerge backfill or the
date-range merge flow.

    cd backend
    python scripts/find_silent_merge_failures.py            # grouped summary
    python scripts/find_silent_merge_failures.py --dates    # also list each date

Two buckets are reported:
  * fully-missed  : status=success, succeeded=0, failed>0  (nothing merged)
  * partial       : status=success, succeeded>0, failed>0  (some patients missed)

It does NOT modify any rows.
"""
import argparse

from sqlalchemy import func, select

from app.database import SessionLocal
from app.models.merge_job import MergeJob, MergeStatus
from app.models.puskesmas import Puskesmas


def _summary(db, *, fully_missed: bool):
    cond = [
        MergeJob.status == MergeStatus.SUCCESS,
        MergeJob.failed_count > 0,
        MergeJob.deleted_at.is_(None),
    ]
    if fully_missed:
        cond.append(MergeJob.succeeded_count == 0)
    else:
        cond.append(MergeJob.succeeded_count > 0)
    return db.execute(
        select(
            Puskesmas.name,
            func.min(MergeJob.date_filter),
            func.max(MergeJob.date_filter),
            func.count(MergeJob.id),
            func.coalesce(func.sum(MergeJob.failed_count), 0),
        )
        .join(Puskesmas, Puskesmas.id == MergeJob.puskesmas_id)
        .where(*cond)
        .group_by(Puskesmas.name)
        .order_by(Puskesmas.name)
    ).all()


def _dates(db):
    return db.execute(
        select(
            Puskesmas.name,
            MergeJob.date_filter,
            MergeJob.succeeded_count,
            MergeJob.failed_count,
            MergeJob.created_at,
        )
        .join(Puskesmas, Puskesmas.id == MergeJob.puskesmas_id)
        .where(
            MergeJob.status == MergeStatus.SUCCESS,
            MergeJob.failed_count > 0,
            MergeJob.deleted_at.is_(None),
        )
        .order_by(Puskesmas.name, MergeJob.date_filter)
    ).all()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dates", action="store_true", help="list each affected date row")
    args = ap.parse_args()

    db = SessionLocal()
    try:
        for label, fully in (("FULLY MISSED (succeeded=0)", True),
                             ("PARTIAL (some succeeded)", False)):
            rows = _summary(db, fully_missed=fully)
            print(f"\n=== {label} ===")
            if not rows:
                print("  (none)")
                continue
            print(f"  {'puskesmas':<28} {'from':<12} {'to':<12} {'jobs':>5} {'patients_missed':>16}")
            for name, dmin, dmax, jobs, missed in rows:
                print(f"  {name:<28} {dmin or '-':<12} {dmax or '-':<12} {jobs:>5} {missed:>16}")

        if args.dates:
            print("\n=== AFFECTED DATE ROWS (status=success, failed>0) ===")
            for name, date_filter, ok, fail, created in _dates(db):
                print(f"  {name:<28} {date_filter or '-':<12} ok={ok} fail={fail}  created={created}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
