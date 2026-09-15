import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.orm import Session, load_only

from app.models.loop_run import LoopRun, LoopRunEvent, LoopRunStatus, LoopTrigger
from app.models.puskesmas import Puskesmas


def create(
    db: Session,
    puskesmas_id: uuid.UUID,
    trigger: LoopTrigger,
    triggered_by_id: uuid.UUID | None,
    pin_ref: str | None = None,
    open_pr: bool | None = None,
) -> LoopRun:
    obj = LoopRun(
        puskesmas_id=puskesmas_id,
        trigger=trigger,
        triggered_by_id=triggered_by_id,
        status=LoopRunStatus.PENDING,
        pin_ref=pin_ref,
        open_pr=open_pr,
    )
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


def mark_running(
    db: Session,
    obj: LoopRun,
    celery_task_id: str,
    container_name: str,
    started_at: datetime,
) -> None:
    obj.status = LoopRunStatus.RUNNING
    obj.celery_task_id = celery_task_id
    obj.container_name = container_name
    obj.started_at = started_at
    obj.heartbeat_at = started_at
    db.commit()


def heartbeat(db: Session, obj: LoopRun, at: datetime) -> None:
    obj.heartbeat_at = at
    db.commit()


def mark_finished(
    db: Session,
    obj: LoopRun,
    status: LoopRunStatus,
    finished_at: datetime,
    *,
    decision: str | None = None,
    test_date: str | None = None,
    live_count: int | None = None,
    scraped_count: int | None = None,
    gap_summary: str | None = None,
    coverage_findings: list | None = None,
    branch_name: str | None = None,
    pr_url: str | None = None,
    review_verdict: str | None = None,
    review_comments: str | None = None,
    duration_seconds: float | None = None,
) -> None:
    obj.status = status
    obj.finished_at = finished_at
    if decision is not None:
        obj.decision = decision
    if test_date is not None:
        obj.test_date = test_date
    if live_count is not None:
        obj.live_count = live_count
    if scraped_count is not None:
        obj.scraped_count = scraped_count
    if gap_summary is not None:
        obj.gap_summary = gap_summary
    # Distinct from None: an explicit [] (portal captured, nothing found) must
    # overwrite, while an absent key on old-shaped verdicts leaves NULL intact.
    if coverage_findings is not None:
        obj.coverage_findings = coverage_findings
    if branch_name is not None:
        obj.branch_name = branch_name
    if pr_url is not None:
        obj.pr_url = pr_url
    if review_verdict is not None:
        obj.review_verdict = review_verdict
    if review_comments is not None:
        obj.review_comments = review_comments
    if duration_seconds is not None:
        obj.duration_seconds = duration_seconds
    db.commit()


def mark_failed(db: Session, obj: LoopRun, error_message: str, finished_at: datetime) -> None:
    obj.status = LoopRunStatus.FAILED
    obj.error_message = error_message
    obj.finished_at = finished_at
    db.commit()


def mark_cancelled(db: Session, obj: LoopRun) -> None:
    obj.status = LoopRunStatus.CANCELLED
    obj.finished_at = datetime.now(UTC)
    db.commit()


def mark_puskesmas_checked(db: Session, puskesmas_id: uuid.UUID, at: datetime) -> None:
    """Stamp last_checked_at = the last time a run reached a verdict. Since the
    nightly matrix (select_nightly_targets) keys off the latest run STATUS, this
    stamp is informational only. UPDATE, so add the soft-delete guard explicitly
    (root CLAUDE.md §6)."""
    db.execute(
        update(Puskesmas)
        .where(Puskesmas.id == puskesmas_id, Puskesmas.deleted_at.is_(None))
        .values(last_checked_at=at)
    )
    db.commit()


# Nightly retry matrix (Akbar, 2026-09-02). A portal whose LATEST run reached a
# conclusion (covered / needs_review / merged) is done — never nightly-refired.
# These transient/rejected outcomes retry on the next sweep. `cancelled` is a
# deliberate human stop, so it is NOT here (use Run-now to retry). `no_data`
# also retries but only past NO_DATA_COOLDOWN_DAYS — a dormant portal probing
# five weekdays every night is pure noise.
NIGHTLY_RETRY_STATUSES = (
    LoopRunStatus.BAD_CREDS,
    LoopRunStatus.FAILED,
    LoopRunStatus.PR_REJECTED,
)
NO_DATA_COOLDOWN_DAYS = 7


def select_nightly_targets(db: Session, budget: int) -> list[uuid.UUID]:
    """The nightly sweep query: puskesmas with EPUS url + creds whose LATEST run
    is retryable — never run, bad_creds, failed, pr_rejected, or a no_data older
    than the cooldown — with no active loop run, oldest onboarded first, capped
    to the budget. Concluded portals (covered / needs_review / merged) are never
    re-picked (PLAN §4.1; matrix per Akbar 2026-09-02)."""
    active = (
        select(LoopRun.puskesmas_id)
        .where(
            LoopRun.status.in_([LoopRunStatus.PENDING, LoopRunStatus.RUNNING]),
            LoopRun.deleted_at.is_(None),
        )
        .scalar_subquery()
    )
    latest_status = (
        select(LoopRun.status)
        .where(
            LoopRun.puskesmas_id == Puskesmas.id,
            LoopRun.deleted_at.is_(None),
        )
        .order_by(LoopRun.created_at.desc(), LoopRun.id.desc())
        .limit(1)
        .scalar_subquery()
    )
    no_data_ready = and_(
        latest_status == LoopRunStatus.NO_DATA,
        or_(
            Puskesmas.last_checked_at.is_(None),
            Puskesmas.last_checked_at < datetime.now(UTC) - timedelta(days=NO_DATA_COOLDOWN_DAYS),
        ),
    )
    stmt = (
        select(Puskesmas.id)
        .where(
            Puskesmas.deleted_at.is_(None),
            Puskesmas.epus_url.isnot(None),
            Puskesmas.epus_cred.isnot(None),
            Puskesmas.id.not_in(active),
            or_(
                latest_status.is_(None),
                latest_status.in_(NIGHTLY_RETRY_STATUSES),
                no_data_ready,
            ),
        )
        .order_by(Puskesmas.created_at.asc())
        .limit(budget)
    )
    return list(db.scalars(stmt).all())


# Statuses that are blocked on a human: a PR to merge/reject, creds to fix,
# or pushed changes waiting for their PR to be opened.
_NEEDS_ACTION_STATUSES = (
    LoopRunStatus.NEEDS_REVIEW,
    LoopRunStatus.BAD_CREDS,
    LoopRunStatus.CHANGES_READY,
)


def count_needs_action(db: Session) -> int:
    # Exclude orphaned runs (their puskesmas soft-deleted) to match the list's
    # INNER JOIN guard. The auto soft-delete filter does NOT fire on a
    # func.count() select, so the puskesmas guard is explicit here.
    return db.scalar(
        select(func.count()).select_from(LoopRun).join(LoopRun.puskesmas).where(
            LoopRun.status.in_(_NEEDS_ACTION_STATUSES),
            LoopRun.deleted_at.is_(None),
            Puskesmas.deleted_at.is_(None),
        )
    ) or 0


def count_running(db: Session) -> int:
    return db.scalar(
        select(func.count()).select_from(LoopRun).join(LoopRun.puskesmas).where(
            LoopRun.status.in_((LoopRunStatus.PENDING, LoopRunStatus.RUNNING)),
            LoopRun.deleted_at.is_(None),
            Puskesmas.deleted_at.is_(None),
        )
    ) or 0


def list_needs_review_prs(db: Session) -> list[LoopRun]:
    """needs_review runs that opened a PR — the reconcile input set."""
    return list(db.scalars(
        select(LoopRun)
        .options(load_only(
            LoopRun.id, LoopRun.status, LoopRun.pr_url, LoopRun.branch_name,
        ))
        .where(
            LoopRun.status == LoopRunStatus.NEEDS_REVIEW,
            LoopRun.pr_url.isnot(None),
            LoopRun.deleted_at.is_(None),
        )
    ).all())


def set_status(db: Session, obj: LoopRun, status: LoopRunStatus) -> None:
    obj.status = status
    db.commit()


def append_event(
    db: Session,
    loop_run_id: uuid.UUID,
    seq: int,
    kind: str,
    text: str,
    at: datetime,
) -> None:
    """Persist one stream event, then bump the run's event_count. Persist-first so
    a browser refresh replays the full run from the DB (§11.3)."""
    db.add(
        LoopRunEvent(
            loop_run_id=loop_run_id,
            seq=seq,
            kind=kind,
            text=text,
            created_at=at,
        )
    )
    db.execute(
        update(LoopRun)
        .where(LoopRun.id == loop_run_id)
        .values(event_count=LoopRun.event_count + 1)
    )
    db.commit()
