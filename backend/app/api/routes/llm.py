import uuid
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, aliased, load_only

from app.api.deps import get_current_admin_id, get_db
from app.api.pagination import Page, PageParams, page_params, paginate
from app.celery_app import celery_app
from app.core.rate_limit import enforce_llm_test_rate_limit
from app.core.security import decrypt_json
from app.crud import llm_config as cfg_crud
from app.crud import merge_job as merge_crud
from app.integrations.llm_chat import chat_complete
from app.models.llm_config import LlmConfig
from app.models.llm_log import LlmLog
from app.models.patient import Patient
from app.models.scrape_job import TriggererType
from app.schemas.llm import (
    LlmConfigCreate,
    LlmConfigOut,
    LlmConfigReveal,
    LlmConfigTestIn,
    LlmConfigTestOut,
    LlmConfigUpdate,
    LlmLogOut,
    LlmLogRetryMergeIn,
    LlmLogRetryMergeOut,
    LlmUsageBucket,
)

router = APIRouter(tags=["llm"])

# Test-connection prompt + budget. max_tokens is deliberately generous:
# reasoning models (o-series / gpt-oss with high effort) spend hidden tokens
# before emitting visible content, so a tiny cap yields empty content and a
# false failure.
_TEST_PROMPT = "Reply with exactly the word: OK"
_TEST_MAX_TOKENS = 512

_CFG_OUT_COLS = (
    LlmConfig.id, LlmConfig.provider, LlmConfig.model, LlmConfig.base_url,
    LlmConfig.is_active, LlmConfig.is_active_captcha, LlmConfig.is_active_chatbot,
    LlmConfig.is_active_loop_agent, LlmConfig.is_active_loop_reviewer,
    LlmConfig.label, LlmConfig.reasoning_effort,
    LlmConfig.input_price_per_1m, LlmConfig.output_price_per_1m,
    LlmConfig.created_at, LlmConfig.updated_at,
)
_LOG_OUT_COLS = (
    LlmLog.id, LlmLog.llm_config_id, LlmLog.scrape_job_id,
    LlmLog.merge_job_id, LlmLog.patient_id, LlmLog.puskesmas_id,
    LlmLog.source,
    LlmLog.model, LlmLog.input_tokens, LlmLog.output_tokens, LlmLog.reasoning_tokens,
    LlmLog.total_tokens, LlmLog.prompt_cost, LlmLog.completion_cost, LlmLog.total_cost,
    LlmLog.latency_ms, LlmLog.success, LlmLog.error, LlmLog.created_at,
)


# ── llm-configs ───────────────────────────────────────────────────────────────

@router.post("/llm-configs", response_model=LlmConfigOut, status_code=status.HTTP_201_CREATED)
def create_llm_config(
    data: LlmConfigCreate,
    db: Session = Depends(get_db),
    _: uuid.UUID = Depends(get_current_admin_id),
) -> LlmConfigOut:
    return LlmConfigOut.model_validate(cfg_crud.create(db, data))


@router.get("/llm-configs", response_model=Page[LlmConfigOut])
def list_llm_configs(
    params: PageParams = Depends(page_params),
    label: str | None = Query(default=None),
    db: Session = Depends(get_db),
    _: uuid.UUID = Depends(get_current_admin_id),
) -> Page[LlmConfigOut]:
    stmt = (
        select(LlmConfig)
        .options(load_only(*_CFG_OUT_COLS))
        .order_by(LlmConfig.created_at.desc())
    )
    if label:
        stmt = stmt.where(LlmConfig.label.ilike(f"%{label}%"))
    items, total, pages = paginate(db, stmt, params)
    return Page[LlmConfigOut](
        items=[LlmConfigOut.model_validate(i) for i in items],
        total=total, page=params.page, size=params.size, pages=pages,
    )


@router.get("/llm-configs/{id}", response_model=LlmConfigOut)
def get_llm_config(
    id: uuid.UUID,
    db: Session = Depends(get_db),
    _: uuid.UUID = Depends(get_current_admin_id),
) -> LlmConfigOut:
    obj = db.scalar(
        select(LlmConfig).options(load_only(*_CFG_OUT_COLS)).where(LlmConfig.id == id)
    )
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "LlmConfig not found")
    return LlmConfigOut.model_validate(obj)


@router.patch("/llm-configs/{id}", response_model=LlmConfigOut)
def update_llm_config(
    id: uuid.UUID,
    data: LlmConfigUpdate,
    db: Session = Depends(get_db),
    _: uuid.UUID = Depends(get_current_admin_id),
) -> LlmConfigOut:
    obj = db.scalar(
        select(LlmConfig).options(load_only(*_CFG_OUT_COLS)).where(LlmConfig.id == id)
    )
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "LlmConfig not found")
    return LlmConfigOut.model_validate(cfg_crud.update_config(db, obj, data))


@router.delete("/llm-configs/{id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_llm_config(
    id: uuid.UUID,
    db: Session = Depends(get_db),
    _: uuid.UUID = Depends(get_current_admin_id),
) -> None:
    obj = db.scalar(
        select(LlmConfig)
        .options(load_only(
            LlmConfig.id, LlmConfig.is_active,
            LlmConfig.is_active_captcha, LlmConfig.is_active_chatbot,
            LlmConfig.is_active_loop_agent, LlmConfig.is_active_loop_reviewer,
        ))
        .where(LlmConfig.id == id)
    )
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "LlmConfig not found")
    cfg_crud.soft_delete(db, obj)


@router.post("/llm-configs/{id}/activate", response_model=LlmConfigOut)
def activate_llm_config(
    id: uuid.UUID,
    db: Session = Depends(get_db),
    _: uuid.UUID = Depends(get_current_admin_id),
) -> LlmConfigOut:
    return LlmConfigOut.model_validate(cfg_crud.set_active(db, id))


@router.post("/llm-configs/{id}/activate-captcha", response_model=LlmConfigOut)
def activate_llm_config_captcha(
    id: uuid.UUID,
    db: Session = Depends(get_db),
    _: uuid.UUID = Depends(get_current_admin_id),
) -> LlmConfigOut:
    return LlmConfigOut.model_validate(cfg_crud.set_active_captcha(db, id))


@router.post("/llm-configs/{id}/activate-chatbot", response_model=LlmConfigOut)
def activate_llm_config_chatbot(
    id: uuid.UUID,
    db: Session = Depends(get_db),
    _: uuid.UUID = Depends(get_current_admin_id),
) -> LlmConfigOut:
    return LlmConfigOut.model_validate(cfg_crud.set_active_chatbot(db, id))


@router.post("/llm-configs/{id}/activate-loop-agent", response_model=LlmConfigOut)
def activate_llm_config_loop_agent(
    id: uuid.UUID,
    db: Session = Depends(get_db),
    _: uuid.UUID = Depends(get_current_admin_id),
) -> LlmConfigOut:
    return LlmConfigOut.model_validate(cfg_crud.set_active_loop_agent(db, id))


@router.post("/llm-configs/{id}/activate-loop-reviewer", response_model=LlmConfigOut)
def activate_llm_config_loop_reviewer(
    id: uuid.UUID,
    db: Session = Depends(get_db),
    _: uuid.UUID = Depends(get_current_admin_id),
) -> LlmConfigOut:
    return LlmConfigOut.model_validate(cfg_crud.set_active_loop_reviewer(db, id))


@router.get("/llm-configs/{id}/reveal", response_model=LlmConfigReveal)
def reveal_llm_config(
    id: uuid.UUID,
    db: Session = Depends(get_db),
    admin_id: uuid.UUID = Depends(get_current_admin_id),
) -> LlmConfigReveal:
    return LlmConfigReveal(api_key=cfg_crud.reveal(db, admin_id, id))


@router.post("/llm-configs/test", response_model=LlmConfigTestOut)
def test_llm_connection(
    data: LlmConfigTestIn,
    db: Session = Depends(get_db),
    admin_id: uuid.UUID = Depends(get_current_admin_id),
) -> LlmConfigTestOut:
    """Send a minimal prompt through the given config and report success/failure.

    Returns HTTP 200 for BOTH outcomes: a reachable-but-misconfigured endpoint
    is a diagnostic *result* (ok=false + error), not an API error — the UI
    renders both inline. Non-2xx is reserved for misuse (unknown config_id).
    Does not write a billed llm_log row.
    """
    enforce_llm_test_rate_limit(admin_id)

    # Resolve the api key + routing pin: typed-in wins; else the stored row.
    api_key = (data.api_key or "").strip()
    route_order = (data.route_order or "").strip() or None
    if not api_key or route_order is None:
        obj = db.scalar(
            select(LlmConfig)
            .options(load_only(LlmConfig.id, LlmConfig.api_key_enc, LlmConfig.route_order))
            .where(LlmConfig.id == data.config_id)
        )
        if obj is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "LlmConfig not found")
        if not api_key:
            try:
                api_key = decrypt_json(obj.api_key_enc)["api_key"]
            except Exception:
                return LlmConfigTestOut(
                    ok=False, model=data.model,
                    error="stored api_key could not be decrypted",
                )
            if route_order is None:
                route_order = obj.route_order

    try:
        result = chat_complete(
            provider=data.provider,
            base_url=data.base_url,
            api_key=api_key,
            model=data.model,
            route_order=route_order,
            prompt=_TEST_PROMPT,
            max_tokens=_TEST_MAX_TOKENS,
            reasoning_effort=data.reasoning_effort,
        )
    except Exception as exc:
        return LlmConfigTestOut(ok=False, model=data.model, error=str(exc)[:1000])

    reply = (result.text or "").strip()
    if not reply:
        return LlmConfigTestOut(
            ok=False, model=data.model, latency_ms=result.latency_ms,
            error="empty response (model returned no content)",
        )
    return LlmConfigTestOut(
        ok=True, model=data.model, latency_ms=result.latency_ms, reply=reply[:500],
    )


# ── llm-logs ──────────────────────────────────────────────────────────────────

@router.get("/llm-logs", response_model=Page[LlmLogOut])
def list_llm_logs(
    params: PageParams = Depends(page_params),
    source: str | None = Query(default=None),
    success: bool | None = Query(default=None),
    # retry_status splits the "fail" bucket: "retried_ok" = a later merge log
    # for the same patient succeeded; "not_retried" = no later success exists.
    # When set, results are implicitly constrained to failed merge_patient_data
    # rows since those are the only rows for which "retried_ok" is defined.
    retry_status: Literal["retried_ok", "not_retried"] | None = Query(default=None),
    llm_config_id: uuid.UUID | None = Query(default=None),
    puskesmas_id: uuid.UUID | None = Query(default=None),
    since: datetime | None = Query(default=None),
    db: Session = Depends(get_db),
    _: uuid.UUID = Depends(get_current_admin_id),
) -> Page[LlmLogOut]:
    stmt = (
        select(LlmLog)
        .options(load_only(*_LOG_OUT_COLS))
        .order_by(LlmLog.created_at.desc())
    )
    if source is not None:
        stmt = stmt.where(LlmLog.source == source)
    if success is not None:
        stmt = stmt.where(LlmLog.success == success)
    if llm_config_id is not None:
        stmt = stmt.where(LlmLog.llm_config_id == llm_config_id)
    if puskesmas_id is not None:
        stmt = stmt.where(LlmLog.puskesmas_id == puskesmas_id)
    if since is not None:
        stmt = stmt.where(LlmLog.created_at >= since)
    if retry_status is not None:
        # Correlated EXISTS: is there a LATER same-patient merge_patient_data
        # log with success=True? Aliased to disambiguate from the outer LlmLog
        # selection. Implicit narrow to failed merge rows so the flag is
        # actually meaningful (success rows + non-merge rows can't be "retried").
        later = aliased(LlmLog)
        later_success_exists = (
            select(1)
            .where(
                later.patient_id == LlmLog.patient_id,
                later.source == "merge_patient_data",
                later.success.is_(True),
                later.created_at > LlmLog.created_at,
            )
            .exists()
        )
        stmt = stmt.where(
            LlmLog.source == "merge_patient_data",
            LlmLog.success.is_(False),
            LlmLog.patient_id.is_not(None),
        )
        if retry_status == "retried_ok":
            stmt = stmt.where(later_success_exists)
        else:  # "not_retried"
            stmt = stmt.where(~later_success_exists)
    items, total, pages = paginate(db, stmt, params)

    # Mark failed merge_patient_data logs that have a later successful retry for the same patient.
    # One batched GROUP BY: returns at most one row per distinct patient on this page, regardless
    # of how many successful retries exist. Comparison vs the failed row's timestamp happens in
    # Python — keeps the SQL plan small and index-friendly.
    failed_merge_rows = [
        i for i in items
        if i.source == "merge_patient_data" and not i.success and i.patient_id is not None
    ]
    superseded_ids: set[uuid.UUID] = set()
    if failed_merge_rows:
        patient_ids = {r.patient_id for r in failed_merge_rows}
        latest_rows = db.execute(
            select(LlmLog.patient_id, func.max(LlmLog.created_at))
            .where(
                LlmLog.patient_id.in_(patient_ids),
                LlmLog.source == "merge_patient_data",
                LlmLog.success.is_(True),
            )
            .group_by(LlmLog.patient_id)
        ).all()
        latest_success_by_patient: dict[uuid.UUID, datetime] = {
            pid: ts for pid, ts in latest_rows
        }
        for r in failed_merge_rows:
            ts = latest_success_by_patient.get(r.patient_id)
            if ts is not None and ts > r.created_at:
                superseded_ids.add(r.id)

    out_items: list[LlmLogOut] = []
    for i in items:
        m = LlmLogOut.model_validate(i)
        if i.id in superseded_ids:
            m.superseded_by_success = True
        out_items.append(m)
    return Page[LlmLogOut](
        items=out_items,
        total=total, page=params.page, size=params.size, pages=pages,
    )


@router.get("/llm-logs/usage", response_model=list[LlmUsageBucket])
def llm_usage(
    group_by: Literal["day", "month"] = Query(default="day"),
    since: datetime | None = Query(default=None),
    until: datetime | None = Query(default=None),
    source: str | None = Query(default=None),
    llm_config_id: uuid.UUID | None = Query(default=None),
    db: Session = Depends(get_db),
    _: uuid.UUID = Depends(get_current_admin_id),
) -> list[LlmUsageBucket]:
    bucket_col = func.date_trunc(group_by, LlmLog.created_at).label("bucket")
    stmt = (
        select(
            bucket_col,
            func.count().label("calls"),
            func.coalesce(func.sum(LlmLog.input_tokens), 0).label("input_tokens"),
            func.coalesce(func.sum(LlmLog.output_tokens), 0).label("output_tokens"),
            func.sum(LlmLog.prompt_cost).label("prompt_cost"),
            func.sum(LlmLog.completion_cost).label("completion_cost"),
            func.sum(LlmLog.total_cost).label("total_cost"),
        )
        .group_by(bucket_col)
        .order_by(bucket_col.desc())
    )
    if since is not None:
        stmt = stmt.where(LlmLog.created_at >= since)
    if until is not None:
        # inclusive — symmetric with `since >=` for closed range semantics
        stmt = stmt.where(LlmLog.created_at <= until)
    if source is not None:
        stmt = stmt.where(LlmLog.source == source)
    if llm_config_id is not None:
        stmt = stmt.where(LlmLog.llm_config_id == llm_config_id)
    rows = db.execute(stmt).all()
    return [LlmUsageBucket(**row._mapping) for row in rows]


_RETRY_BULK_MAX = 200


@router.post("/llm-logs/retry-merge-bulk", response_model=LlmLogRetryMergeOut)
def retry_merge_bulk(
    body: LlmLogRetryMergeIn,
    db: Session = Depends(get_db),
    admin_id: uuid.UUID = Depends(get_current_admin_id),
) -> LlmLogRetryMergeOut:
    if not body.log_ids:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "log_ids is empty")
    if len(body.log_ids) > _RETRY_BULK_MAX:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"too many log_ids (max {_RETRY_BULK_MAX})",
        )

    log_rows = db.execute(
        select(LlmLog.id, LlmLog.source, LlmLog.success, LlmLog.patient_id)
        .where(LlmLog.id.in_(body.log_ids))
    ).all()

    triggered = 0
    skipped = 0
    skipped_reasons: list[str] = []
    job_ids: list[uuid.UUID] = []
    seen_patient_ids: set[uuid.UUID] = set()

    for log_id, src, ok, patient_id in log_rows:
        if src != "merge_patient_data":
            skipped += 1
            skipped_reasons.append(f"{log_id}: source is '{src}', not retryable")
            continue
        if ok:
            skipped += 1
            skipped_reasons.append(f"{log_id}: log is successful, nothing to retry")
            continue
        if patient_id is None:
            skipped += 1
            skipped_reasons.append(f"{log_id}: no patient_id on log")
            continue
        if patient_id in seen_patient_ids:
            skipped += 1
            skipped_reasons.append(f"{log_id}: patient {patient_id} already queued")
            continue
        seen_patient_ids.add(patient_id)

        prow = db.execute(
            select(
                Patient.id,
                Patient.puskesmas_id,
                Patient.scraped_asik_data.isnot(None).label("has_asik"),
                Patient.scraped_epus_data.isnot(None).label("has_epus"),
            ).where(Patient.id == patient_id)
        ).one_or_none()
        if prow is None:
            skipped += 1
            skipped_reasons.append(f"{log_id}: patient {patient_id} not found")
            continue
        _, p_pus_id, has_asik, has_epus = prow
        if not (has_asik and has_epus):
            skipped += 1
            skipped_reasons.append(
                f"{log_id}: patient {patient_id} missing scrape on one side"
            )
            continue

        try:
            job = merge_crud.create(
                db,
                puskesmas_id=p_pus_id,
                date_filter=None,
                triggered_by_id=admin_id,
                triggered_by_type=TriggererType.ADMIN,
                force_remerge=True,
                patient_id=patient_id,
            )
        except IntegrityError:
            db.rollback()
            skipped += 1
            skipped_reasons.append(
                f"{log_id}: merge already in progress for patient {patient_id}"
            )
            continue

        try:
            celery_app.send_task("merge.run", args=[str(job.id)])
        except Exception as e:
            merge_crud.mark_failed(db, job, f"broker unreachable: {e}"[:2000], datetime.now(UTC))
            skipped += 1
            skipped_reasons.append(f"{log_id}: broker unavailable")
            continue

        triggered += 1
        job_ids.append(job.id)

    return LlmLogRetryMergeOut(
        triggered=triggered,
        skipped=skipped,
        skipped_reasons=skipped_reasons,
        job_ids=job_ids,
    )


@router.get("/llm-logs/{id}", response_model=LlmLogOut)
def get_llm_log(
    id: uuid.UUID,
    db: Session = Depends(get_db),
    _: uuid.UUID = Depends(get_current_admin_id),
) -> LlmLogOut:
    obj = db.scalar(
        select(LlmLog).options(load_only(*_LOG_OUT_COLS)).where(LlmLog.id == id)
    )
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "LlmLog not found")
    return LlmLogOut.model_validate(obj)
