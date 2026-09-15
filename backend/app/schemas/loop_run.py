import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.loop_config import LoopMergeMode
from app.models.loop_run import LoopRunStatus, LoopTrigger


class LoopRunStart(BaseModel):
    puskesmas_id: uuid.UUID
    # Git ref to check out inside the container before running. None = master.
    # Used by the WAF acceptance test to pin the pre-fix tree ("10db694^").
    pin_ref: str | None = Field(default=None, max_length=64)
    # Per-run PR decision. None = follow loop_config.auto_open_pr.
    open_pr: bool | None = None


class LoopCoverageFindingOut(BaseModel):
    form: str | None = None
    frm_code: str | None = None
    status: str | None = None
    questions: list[str] = []
    epus_source: str | None = None
    evidence: str | None = None
    tabs_checked: list[str] = []
    off_list: bool = False


class LoopRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    puskesmas_id: uuid.UUID
    puskesmas_name: str
    trigger: LoopTrigger
    triggered_by_id: uuid.UUID | None = None
    status: LoopRunStatus
    pin_ref: str | None = None
    open_pr: bool | None = None
    container_name: str | None = None
    celery_task_id: str | None = None
    test_date: str | None = None
    live_count: int | None = None
    scraped_count: int | None = None
    decision: str | None = None
    gap_summary: str | None = None
    coverage_findings: list[LoopCoverageFindingOut] | None = None
    branch_name: str | None = None
    pr_url: str | None = None
    review_verdict: str | None = None
    review_comments: str | None = None
    duration_seconds: float | None = None
    heartbeat_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error_message: str | None = None
    event_count: int
    created_at: datetime
    updated_at: datetime


class LoopRunLogOut(BaseModel):
    lines: list[str]


class LoopRunSummaryOut(BaseModel):
    needs_action: int
    running: int


class LoopCoverageSummaryOut(BaseModel):
    total_questions: int
    mapped: int
    open: int
    documented_sourceless: int
    not_live: int
    label_drift: int
    deleted: int
    runs_with_findings: int
    forms_reported_absent: int
    generated_at: str
    ledger_updated: str


class LoopReconcileOut(BaseModel):
    checked: int
    merged: int
    rejected: int


class LoopConfigOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    merge_mode: LoopMergeMode
    auto_deploy: bool
    auto_open_pr: bool
    nightly_budget: int
    max_fix_iterations: int
    max_review_iterations: int
    nightly_enabled: bool
    created_at: datetime
    updated_at: datetime


class LoopConfigUpdate(BaseModel):
    merge_mode: LoopMergeMode | None = None
    # Stored but unused in v1 (PLAN §4.11) — configurable ahead of the discussion.
    auto_deploy: bool | None = None
    auto_open_pr: bool | None = None
    nightly_budget: int | None = Field(default=None, ge=1, le=1000)
    max_fix_iterations: int | None = Field(default=None, ge=1, le=50)
    max_review_iterations: int | None = Field(default=None, ge=1, le=50)
    nightly_enabled: bool | None = None
