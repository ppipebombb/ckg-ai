import uuid
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models.llm_log import LlmLog


def record(
    db: Session,
    *,
    llm_config_id: uuid.UUID,
    source: str,
    model: str,
    success: bool,
    scrape_job_id: uuid.UUID | None = None,
    merge_job_id: uuid.UUID | None = None,
    patient_id: uuid.UUID | None = None,
    puskesmas_id: uuid.UUID | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    total_tokens: int | None = None,
    reasoning_tokens: int | None = None,
    prompt_cost: Decimal | None = None,
    completion_cost: Decimal | None = None,
    total_cost: Decimal | None = None,
    latency_ms: int | None = None,
    error: str | None = None,
) -> LlmLog:
    row = LlmLog(
        llm_config_id=llm_config_id,
        scrape_job_id=scrape_job_id,
        merge_job_id=merge_job_id,
        patient_id=patient_id,
        puskesmas_id=puskesmas_id,
        source=source,
        model=model,
        success=success,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        reasoning_tokens=reasoning_tokens,
        prompt_cost=prompt_cost,
        completion_cost=completion_cost,
        total_cost=total_cost,
        latency_ms=latency_ms,
        error=error,
    )
    db.add(row)
    db.flush()
    return row
