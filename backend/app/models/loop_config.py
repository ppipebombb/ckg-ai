import enum

from sqlalchemy import Boolean, Enum as SAEnum, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import TimestampMixin, UUIDPKMixin


class LoopMergeMode(str, enum.Enum):
    """How the loop agent's PR is merged (PLAN §4.10).

    - MANUAL (default, safest): the agent opens the PR after the gate + reviewer
      are green, then STOPS. A human merges in GitHub. The GitHub token is scoped
      to push + PR only.
    - AUTO (hands-off): the agent opens the PR; the reviewer + deterministic gate
      run; if changes are requested it iterates up to max_review_iterations, then
      auto-merges once green. Never merges red. Auto-merge is NOT auto-deploy.
    """
    MANUAL = "manual"
    AUTO = "auto"


class LoopConfig(UUIDPKMixin, TimestampMixin, Base):
    """Singleton behavioural settings for the loop agent (PLAN §5.3).

    One row for the whole feature — model + key come from llm_config role flags;
    this holds the behaviour knobs. Dashboard-editable, no deploy to change.
    Accessed via crud.get_or_create so the row is seeded lazily on first read.
    """

    __tablename__ = "loop_config"

    merge_mode: Mapped[LoopMergeMode] = mapped_column(
        SAEnum(LoopMergeMode, name="loop_merge_mode", values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=LoopMergeMode.MANUAL,
    )
    # PLACEHOLDER ONLY (PLAN §4.11) — stored, not acted on in v1. No code reads it.
    auto_deploy: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # When a run produces code: True (default) opens the PR as before; False
    # pushes the branch only and parks the run in changes_ready — the admin
    # opens the PR from the dashboard. Overridable per manual run.
    auto_open_pr: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Max puskesmas the nightly trigger dispatches per night.
    nightly_budget: Mapped[int] = mapped_column(Integer, nullable=False, default=20)
    # Gate→fix→gate cycles per run before giving up (verdict stays failed).
    # Safety ceiling, not a target: the loop always stops as soon as the gate
    # is green. Also bounded by LOOP_RUN_TIMEOUT_SECONDS.
    max_fix_iterations: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    # Reviewer→address cycles per run before giving up (PR still opens).
    max_review_iterations: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    # Whether the scheduled nightly trigger runs at all. Off by default.
    nightly_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
