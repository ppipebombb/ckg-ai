import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Enum as SAEnum
from sqlalchemy import Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import SoftDeleteMixin, TimestampMixin, UUIDPKMixin

if TYPE_CHECKING:
    from app.models.puskesmas import Puskesmas


class LoopTrigger(str, enum.Enum):
    MANUAL = "manual"    # a human hit "Run now" on one puskesmas
    NIGHTLY = "nightly"  # the scheduled triage query picked it up


class LoopRunStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    # Terminal outcomes the dashboard surfaces.
    COVERED = "covered"            # gate ran live, scraper matched — no fix needed
    NO_DATA = "no_data"            # live portal has no patients on probed weekdays
    NEEDS_REVIEW = "needs_review"  # a fix PR is open, waiting on a human
    MERGED = "merged"              # auto-mode merged the fix
    PR_REJECTED = "pr_rejected"    # a fix PR was closed unmerged — re-fires on the next nightly sweep
    # Code changed and the branch is pushed, but auto_open_pr was off (config or
    # per-run): work is safe on GitHub, a human opens the PR from the dashboard.
    CHANGES_READY = "changes_ready"
    BAD_CREDS = "bad_creds"        # login failed — a human must refresh creds
    # Terminal error/abort.
    FAILED = "failed"
    CANCELLED = "cancelled"


class LoopRun(UUIDPKMixin, TimestampMixin, SoftDeleteMixin, Base):
    """One run of the loop agent against ONE puskesmas.

    Mirrors ScrapeJob: a summary row the dashboard lists and keeps forever.
    The heavy per-event reasoning/tool stream lives in LoopRunEvent (pruned).
    """

    __tablename__ = "loop_runs"

    puskesmas_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("puskesmas.id"),
        nullable=False,
    )
    trigger: Mapped[LoopTrigger] = mapped_column(
        SAEnum(LoopTrigger, name="loop_trigger", values_callable=lambda x: [e.value for e in x]),
        nullable=False,
    )
    # Admin who hit "Run now"; NULL for a nightly run (no human).
    triggered_by_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    status: Mapped[LoopRunStatus] = mapped_column(
        SAEnum(LoopRunStatus, name="loop_run_status", values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=LoopRunStatus.PENDING,
    )
    # Git ref the container checks out before running. NULL = current master.
    # The WAF acceptance test pins this to "10db694^" to reproduce the pre-fix tree.
    pin_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Per-run PR decision, resolved at creation: NULL = follow
    # loop_config.auto_open_pr (nightly runs); manual runs store the explicit
    # choice from the Run dialog. Resolved once so a config change mid-run
    # cannot flip what the runner does at finish.
    open_pr: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    # Deterministic container name "loop-run-<id>" so a watchdog/kill can find it
    # by name without PID hunting (§11.3).
    container_name: Mapped[str | None] = mapped_column(String(96), nullable=True)
    celery_task_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Filled from the container's LOOP_RESULT report at the end of the run.
    test_date: Mapped[str | None] = mapped_column(String(16), nullable=True)
    live_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    scraped_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # covered / gap / no_data / bad_login — the deterministic gate's verdict.
    decision: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # The gate's gap report (module/section names + counts, no patient data).
    gap_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The agent's ASIK coverage report (PROMPT STEP 6): a list of
    # {form, frm_code, status: mapped|absent|candidate, ...} objects. NULL =
    # this run never captured the portal (bad_login / no_data / error) or
    # predates the coverage mission — "not hunted", not "nothing found".
    coverage_findings: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    branch_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    pr_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # In-container reviewer (approve / request_changes / none).
    review_verdict: Mapped[str | None] = mapped_column(String(16), nullable=True)
    review_comments: Mapped[str | None] = mapped_column(Text, nullable=True)

    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Liveness: the task bumps this every N seconds; a watchdog kills a run whose
    # heartbeat has gone stale (§11.3).
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Running count of persisted events, so a runaway session can be capped (§11.4).
    event_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    puskesmas: Mapped["Puskesmas"] = relationship()


class LoopRunEvent(UUIDPKMixin, Base):
    """One line/event from the agent's OpenCode stream.

    High-volume, disposable child table — persisted so the dashboard can replay a
    run after a refresh (§11.3), then pruned by age (§11.4). No soft-delete: these
    rows are throwaway; git + the PR hold the durable detail of any fix.
    """

    __tablename__ = "loop_run_events"

    loop_run_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("loop_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)  # monotonic per run
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="log")
    text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
