import time
import uuid
from datetime import UTC, datetime

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, contains_eager, load_only

from app.api.deps import (
    Principal,
    get_current_admin_id,
    get_db,
    get_principal_from_query,
)
from app.api.pagination import Page, PageParams, page_params, paginate
from app.celery_app import celery_app
from app.config import settings
from app.core.rate_limit import redis_client
from app.crud import loop_config as config_crud
from app.crud import loop_run as crud
from app.models.loop_run import LoopRun, LoopRunEvent, LoopRunStatus, LoopTrigger
from app.models.puskesmas import Puskesmas
from app.schemas.loop_run import (
    LoopConfigOut,
    LoopConfigUpdate,
    LoopCoverageSummaryOut,
    LoopReconcileOut,
    LoopRunLogOut,
    LoopRunOut,
    LoopRunStart,
    LoopRunSummaryOut,
)
from app.services import coverage_hunt
from app.services.github_pr import open_pr_for_run, reconcile_needs_review

router = APIRouter(prefix="/loop", tags=["loop-agent"])

_LOG_BACKLOG_MAX = 1000
_LOG_BACKLOG_DEFAULT = 300

_RUN_OUT_COLS = (
    LoopRun.id, LoopRun.puskesmas_id, LoopRun.trigger, LoopRun.triggered_by_id,
    LoopRun.status, LoopRun.pin_ref, LoopRun.open_pr,
    LoopRun.container_name, LoopRun.celery_task_id,
    LoopRun.test_date, LoopRun.live_count, LoopRun.scraped_count, LoopRun.decision,
    LoopRun.gap_summary, LoopRun.coverage_findings, LoopRun.branch_name, LoopRun.pr_url,
    LoopRun.review_verdict, LoopRun.review_comments, LoopRun.duration_seconds,
    LoopRun.heartbeat_at, LoopRun.started_at, LoopRun.finished_at,
    LoopRun.error_message, LoopRun.event_count, LoopRun.created_at, LoopRun.updated_at,
)


def _to_out(run: LoopRun, puskesmas_name: str) -> LoopRunOut:
    return LoopRunOut(
        id=run.id,
        puskesmas_id=run.puskesmas_id,
        puskesmas_name=puskesmas_name,
        trigger=run.trigger,
        triggered_by_id=run.triggered_by_id,
        status=run.status,
        pin_ref=run.pin_ref,
        open_pr=run.open_pr,
        container_name=run.container_name,
        celery_task_id=run.celery_task_id,
        test_date=run.test_date,
        live_count=run.live_count,
        scraped_count=run.scraped_count,
        decision=run.decision,
        gap_summary=run.gap_summary,
        coverage_findings=run.coverage_findings,
        branch_name=run.branch_name,
        pr_url=run.pr_url,
        review_verdict=run.review_verdict,
        review_comments=run.review_comments,
        duration_seconds=run.duration_seconds,
        heartbeat_at=run.heartbeat_at,
        started_at=run.started_at,
        finished_at=run.finished_at,
        error_message=run.error_message,
        event_count=run.event_count,
        created_at=run.created_at,
        updated_at=run.updated_at,
    )


@router.get("/config", response_model=LoopConfigOut)
def get_config(
    db: Session = Depends(get_db),
    admin_id: uuid.UUID = Depends(get_current_admin_id),
) -> LoopConfigOut:
    return LoopConfigOut.model_validate(config_crud.get_or_create(db))


@router.patch("/config", response_model=LoopConfigOut)
def update_config(
    body: LoopConfigUpdate,
    db: Session = Depends(get_db),
    admin_id: uuid.UUID = Depends(get_current_admin_id),
) -> LoopConfigOut:
    obj = config_crud.get_or_create(db)
    updated = config_crud.update(
        db, obj,
        merge_mode=body.merge_mode,
        auto_deploy=body.auto_deploy,
        auto_open_pr=body.auto_open_pr,
        nightly_budget=body.nightly_budget,
        max_fix_iterations=body.max_fix_iterations,
        max_review_iterations=body.max_review_iterations,
        nightly_enabled=body.nightly_enabled,
    )
    return LoopConfigOut.model_validate(updated)


@router.post("/runs", response_model=LoopRunOut, status_code=status.HTTP_201_CREATED)
def start_run(
    body: LoopRunStart,
    db: Session = Depends(get_db),
    admin_id: uuid.UUID = Depends(get_current_admin_id),
) -> LoopRunOut:
    """Run the loop agent now against ONE puskesmas — bypasses the trigger query
    and cooldown (§4.3). The WAF acceptance test is this endpoint against Poso
    with pin_ref set."""
    row = db.execute(
        select(Puskesmas.name, Puskesmas.epus_url, Puskesmas.epus_cred.isnot(None))
        .where(Puskesmas.id == body.puskesmas_id)
    ).one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Puskesmas not found")
    puskesmas_name, epus_url, has_cred = row
    if not epus_url:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "puskesmas has no epus_url")
    if not has_cred:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "epus credentials not set for this puskesmas")

    try:
        # Resolve the per-run PR decision NOW: the explicit dialog choice wins,
        # otherwise the config default — frozen for this run so a config change
        # mid-run cannot flip what the runner does at finish.
        effective_open_pr = (
            body.open_pr if body.open_pr is not None
            else config_crud.get_or_create(db).auto_open_pr
        )
        run = crud.create(
            db,
            puskesmas_id=body.puskesmas_id,
            trigger=LoopTrigger.MANUAL,
            triggered_by_id=admin_id,
            pin_ref=body.pin_ref,
            open_pr=effective_open_pr,
        )
    except IntegrityError as e:
        # uq_loop_runs_active_per_puskesmas — a run is already pending/running.
        db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "run loop aktif sudah ada untuk puskesmas ini",
        ) from e
    try:
        celery_app.send_task("loop_agent.run_one", args=[str(run.id)])
    except Exception as e:
        crud.mark_failed(db, run, f"broker unreachable: {e}"[:2000], datetime.now(UTC))
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "loop broker unavailable") from e
    return _to_out(run, puskesmas_name)


@router.get("/runs", response_model=Page[LoopRunOut])
def list_runs(
    params: PageParams = Depends(page_params),
    puskesmas_id: uuid.UUID | None = Query(None),
    run_status: LoopRunStatus | None = Query(None, alias="status"),
    trigger: LoopTrigger | None = Query(None),
    needs_action: bool = Query(False),
    db: Session = Depends(get_db),
    admin_id: uuid.UUID = Depends(get_current_admin_id),
) -> Page[LoopRunOut]:
    stmt = (
        select(LoopRun)
        .join(LoopRun.puskesmas)
        .options(
            load_only(*_RUN_OUT_COLS),
            contains_eager(LoopRun.puskesmas).load_only(Puskesmas.name),
        )
        .order_by(LoopRun.created_at.desc())
    )
    if puskesmas_id is not None:
        stmt = stmt.where(LoopRun.puskesmas_id == puskesmas_id)
    if run_status is not None:
        stmt = stmt.where(LoopRun.status == run_status)
    if trigger is not None:
        stmt = stmt.where(LoopRun.trigger == trigger)
    if needs_action:
        # The "waiting on a human" filter (§12.1): a PR is open, creds are
        # bad, or changes are parked waiting for the PR to be opened.
        stmt = stmt.where(LoopRun.status.in_(
            (LoopRunStatus.NEEDS_REVIEW, LoopRunStatus.BAD_CREDS, LoopRunStatus.CHANGES_READY),
        ))
    items, total, pages = paginate(db, stmt, params)
    return Page[LoopRunOut](
        items=[_to_out(r, r.puskesmas.name) for r in items],
        total=total,
        page=params.page,
        size=params.size,
        pages=pages,
    )


@router.get("/runs/summary", response_model=LoopRunSummaryOut)
def runs_summary(
    db: Session = Depends(get_db),
    admin_id: uuid.UUID = Depends(get_current_admin_id),
) -> LoopRunSummaryOut:
    return LoopRunSummaryOut(
        needs_action=crud.count_needs_action(db),
        running=crud.count_running(db),
    )


@router.get("/coverage/summary", response_model=LoopCoverageSummaryOut)
def coverage_summary(
    db: Session = Depends(get_db),
    admin_id: uuid.UUID = Depends(get_current_admin_id),
) -> LoopCoverageSummaryOut:
    """Fleet progress toward 'every ASIK question mapped or proven sourceless'.
    Static buckets come from coverage_hunt (mapping json + breadcrumbs + the
    human ledger); the evidence counters come from stored run findings."""
    c = coverage_hunt.build()
    t = c["totals"]
    rows = db.execute(
        select(LoopRun.coverage_findings).where(
            LoopRun.coverage_findings.isnot(None),
            LoopRun.deleted_at.is_(None),
        )
    ).all()
    absent_forms: set[str] = set()
    for (findings,) in rows:
        for f in findings or []:
            if (
                isinstance(f, dict)
                and (f.get("status") or "").lower() == "absent"
                and f.get("form")
            ):
                absent_forms.add(f["form"])
    return LoopCoverageSummaryOut(
        total_questions=c["total_questions"],
        mapped=t["mapped"],
        open=t["open"],
        documented_sourceless=t["documented_sourceless"],
        not_live=t["not_live"],
        label_drift=t["asik_label_drift"],
        deleted=t["deleted"],
        runs_with_findings=len(rows),
        forms_reported_absent=len(absent_forms),
        generated_at=c["generated_at"],
        ledger_updated=c["ledger_updated"],
    )


@router.post("/runs/reconcile", response_model=LoopReconcileOut)
def reconcile_runs(
    db: Session = Depends(get_db),
    admin_id: uuid.UUID = Depends(get_current_admin_id),
) -> LoopReconcileOut:
    """Poll each open needs_review PR and settle its run (merged / pr_rejected),
    deleting the merged/rejected branch. Manual twin of the nightly reconcile."""
    return LoopReconcileOut(**reconcile_needs_review(db))


@router.get("/runs/{run_id}", response_model=LoopRunOut)
def get_run(
    run_id: uuid.UUID,
    db: Session = Depends(get_db),
    admin_id: uuid.UUID = Depends(get_current_admin_id),
) -> LoopRunOut:
    obj = db.scalar(
        select(LoopRun)
        .join(LoopRun.puskesmas)
        .options(
            load_only(*_RUN_OUT_COLS),
            contains_eager(LoopRun.puskesmas).load_only(Puskesmas.name),
        )
        .where(LoopRun.id == run_id)
    )
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Loop run not found")
    return _to_out(obj, obj.puskesmas.name)


@router.post("/runs/{run_id}/open-pr", response_model=LoopRunOut)
def open_run_pr(
    run_id: uuid.UUID,
    db: Session = Depends(get_db),
    admin_id: uuid.UUID = Depends(get_current_admin_id),
) -> LoopRunOut:
    """One-click PR creation for a run whose branch is already on GitHub but
    has no PR: changes_ready (PR was off) or needs_review whose PR-create
    failed at run time. Row-locked so two concurrent clicks cannot mint two
    PRs; the loser re-reads the committed pr_url and gets a 409."""
    obj = db.scalar(
        select(LoopRun)
        .join(LoopRun.puskesmas)
        .options(
            load_only(
                LoopRun.id, LoopRun.status, LoopRun.branch_name, LoopRun.pr_url,
                LoopRun.decision, LoopRun.test_date, LoopRun.live_count,
                LoopRun.scraped_count, LoopRun.gap_summary, LoopRun.coverage_findings,
                LoopRun.review_verdict, LoopRun.review_comments,
            ),
            contains_eager(LoopRun.puskesmas).load_only(Puskesmas.name),
        )
        .where(LoopRun.id == run_id)
        .with_for_update()
    )
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Loop run not found")
    if obj.pr_url:
        raise HTTPException(status.HTTP_409_CONFLICT, "run already has a PR")
    if obj.status not in (LoopRunStatus.CHANGES_READY, LoopRunStatus.NEEDS_REVIEW):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"run is {obj.status.value} — only changes_ready (or needs_review "
            "without a PR) can open one",
        )
    puskesmas_name = obj.puskesmas.name
    try:
        pr_url = open_pr_for_run(obj, puskesmas_name)
    except RuntimeError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(e)[:500]) from e
    if not pr_url:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "GitHub returned no PR URL")
    obj.pr_url = pr_url
    obj.status = LoopRunStatus.NEEDS_REVIEW
    db.commit()
    db.refresh(obj)
    return _to_out(obj, puskesmas_name)


@router.get("/runs/{run_id}/log", response_model=LoopRunLogOut)
def get_run_log(
    run_id: uuid.UUID,
    tail: int = Query(_LOG_BACKLOG_DEFAULT, ge=1, le=_LOG_BACKLOG_MAX),
    db: Session = Depends(get_db),
    admin_id: uuid.UUID = Depends(get_current_admin_id),
) -> LoopRunLogOut:
    exists = db.scalar(select(LoopRun.id).where(LoopRun.id == run_id))
    if exists is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Loop run not found")
    lines = redis_client().lrange(f"loop:run:{run_id}:log", -tail, -1) or []
    return LoopRunLogOut(lines=lines)


@router.get("/runs/{run_id}/events", response_model=LoopRunLogOut)
def get_run_events(
    run_id: uuid.UUID,
    after_seq: int = Query(0, ge=0),
    limit: int = Query(1000, ge=1, le=5000),
    db: Session = Depends(get_db),
    admin_id: uuid.UUID = Depends(get_current_admin_id),
) -> LoopRunLogOut:
    """Durable replay from the DB (§11.3) — survives the 24h Redis TTL. Returns
    persisted event lines after `after_seq`, in order."""
    exists = db.scalar(select(LoopRun.id).where(LoopRun.id == run_id))
    if exists is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Loop run not found")
    rows = db.scalars(
        select(LoopRunEvent.text)
        .where(LoopRunEvent.loop_run_id == run_id, LoopRunEvent.seq > after_seq)
        .order_by(LoopRunEvent.seq.asc())
        .limit(limit)
    ).all()
    return LoopRunLogOut(lines=list(rows))


@router.get("/runs/{run_id}/stream")
async def stream_run(
    run_id: uuid.UUID,
    backlog: int = Query(_LOG_BACKLOG_DEFAULT, ge=0, le=_LOG_BACKLOG_MAX),
    principal: Principal = Depends(get_principal_from_query),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    if principal.typ != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin token required")
    exists = db.scalar(select(LoopRun.id).where(LoopRun.id == run_id))
    if exists is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Loop run not found")

    chan = f"loop:run:{run_id}:stream"
    log_key = f"loop:run:{run_id}:log"

    async def event_gen():
        FLUSH_S = 1.0
        KEEPALIVE_S = 15.0
        client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        try:
            if backlog > 0:
                history = await client.lrange(log_key, -backlog, -1)
                if history:
                    block = "\n".join(f"data: {line}" for line in history)
                    yield f"event: line\n{block}\n\n"
            pubsub = client.pubsub()
            await pubsub.subscribe(chan)
            try:
                buf: list[str] = []
                last_flush = time.monotonic()
                last_keepalive = last_flush
                terminal: str | None = None
                while True:
                    msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=FLUSH_S)
                    now = time.monotonic()
                    if msg is not None:
                        data = msg.get("data")
                        if isinstance(data, str):
                            if data in ("__done__", "__failed__", "__cancelled__"):
                                terminal = data
                            else:
                                buf.append(data)
                    if buf and (terminal is not None or (now - last_flush) >= FLUSH_S):
                        block = "\n".join(f"data: {line}" for line in buf)
                        yield f"event: line\n{block}\n\n"
                        buf.clear()
                        last_flush = now
                        last_keepalive = now
                    if terminal is not None:
                        yield f"event: {terminal.strip('_')}\ndata: {terminal}\n\n"
                        return
                    if not buf and (now - last_keepalive) >= KEEPALIVE_S:
                        yield ": keepalive\n\n"
                        last_keepalive = now
            finally:
                await pubsub.unsubscribe(chan)
                await pubsub.close()
        finally:
            await client.aclose()

    return StreamingResponse(event_gen(), media_type="text/event-stream")


@router.post("/runs/{run_id}/cancel", response_model=LoopRunOut)
def cancel_run(
    run_id: uuid.UUID,
    db: Session = Depends(get_db),
    admin_id: uuid.UUID = Depends(get_current_admin_id),
) -> LoopRunOut:
    obj = db.scalar(
        select(LoopRun)
        .join(LoopRun.puskesmas)
        .options(
            load_only(*_RUN_OUT_COLS),
            contains_eager(LoopRun.puskesmas).load_only(Puskesmas.name),
        )
        .where(LoopRun.id == run_id)
    )
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Loop run not found")
    if obj.status not in (LoopRunStatus.PENDING, LoopRunStatus.RUNNING):
        raise HTTPException(status.HTTP_409_CONFLICT, f"run is {obj.status.value}, cannot cancel")
    puskesmas_name = obj.puskesmas.name
    crud.mark_cancelled(db, obj)
    # Redis cancel-flag: the task polls this each tick and docker-kills the
    # container (avoids a per-tick SELECT — §8.2).
    redis_client().set(f"loop:run:{run_id}:cancel", "1", ex=86400)
    if obj.celery_task_id:
        try:
            celery_app.control.revoke(obj.celery_task_id, terminate=False)
        except Exception:
            pass
    db.refresh(obj)
    return _to_out(obj, puskesmas_name)
