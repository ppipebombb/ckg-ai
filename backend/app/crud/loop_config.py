from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.loop_config import LoopConfig, LoopMergeMode


def get_or_create(db: Session) -> LoopConfig:
    """The loop_config singleton — seeded with defaults on first read."""
    obj = db.scalar(select(LoopConfig).limit(1))
    if obj is None:
        obj = LoopConfig()
        db.add(obj)
        db.commit()
        db.refresh(obj)
    return obj


def update(
    db: Session,
    obj: LoopConfig,
    *,
    merge_mode: LoopMergeMode | None = None,
    auto_deploy: bool | None = None,
    auto_open_pr: bool | None = None,
    nightly_budget: int | None = None,
    max_fix_iterations: int | None = None,
    max_review_iterations: int | None = None,
    nightly_enabled: bool | None = None,
) -> LoopConfig:
    if merge_mode is not None:
        obj.merge_mode = merge_mode
    if auto_deploy is not None:
        obj.auto_deploy = auto_deploy
    if auto_open_pr is not None:
        obj.auto_open_pr = auto_open_pr
    if nightly_budget is not None:
        obj.nightly_budget = nightly_budget
    if max_fix_iterations is not None:
        obj.max_fix_iterations = max_fix_iterations
    if max_review_iterations is not None:
        obj.max_review_iterations = max_review_iterations
    if nightly_enabled is not None:
        obj.nightly_enabled = nightly_enabled
    db.commit()
    db.refresh(obj)
    return obj
