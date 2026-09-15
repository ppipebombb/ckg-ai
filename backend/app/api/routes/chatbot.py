"""Read-only "explainer" chatbot for the frontend-dashboard dashboards.

The single most important property: the LLM request contains ZERO patient data.
The prompt is composed exclusively of (a) our own versioned markdown knowledge
packs, (b) the user's typed question, (c) capped chat history. Even a fully
successful prompt injection can only make the bot say something wrong — there is
no classified data in context to exfiltrate. Do not weaken this.
"""
import uuid
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_dashboard_admin_id, get_db
from app.core.rate_limit import enforce_chatbot_rate_limit
from app.core.security import decrypt_json
from app.crud import llm_config as cfg_crud
from app.crud import llm_log as llm_log_crud
from app.integrations.llm_chat import chat_complete
from app.services.chatbot_knowledge import (
    ChatbotKnowledgeUnavailable,
    build_system_prompt,
)

router = APIRouter(prefix="/chatbot", tags=["chatbot"])

# Output cap — bounds cost. Headroom (1800) above a typical explainer answer so
# that with reasoning='high' the reasoning budget doesn't crowd out the visible
# answer and truncate it mid-sentence (finish=length).
_MAX_TOKENS = 1800
_PER_MILLION = Decimal("1000000")


def _calc_cost(tokens: int | None, rate: Decimal | None) -> Decimal | None:
    if tokens is None or rate is None:
        return None
    return Decimal(tokens) * rate / _PER_MILLION


class ChatHistoryItem(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=2000)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=1000)
    page: Literal[
        "dashboard",
        "dashboard-dm",
        "patients",
        "school-patients",
        "hipertensi-report",
        "gap-tatalaksana",
        "dm-report",
        "lipid-report",
        "obesitas-report",
        "bayi-kuning-ikterus",
        "bayi-kuning-ikterus-berat",
        "common",
    ]
    # max_length MUST stay in sync with the frontend's history.slice(-N) in
    # chat-widget.tsx (currently 20 = the last 10 user/assistant pairs).
    history: list[ChatHistoryItem] = Field(default_factory=list, max_length=20)


class ChatResponse(BaseModel):
    answer: str


@router.post("/messages", response_model=ChatResponse)
def post_chat_message(
    body: ChatRequest,
    db: Session = Depends(get_db),
    # get_dashboard_admin_id accepts prod AND internal admins. Using it here is
    # the DELIBERATE act of adding the chatbot to the prod-scope allowlist
    # (frontend-dashboard is default-deny on every other write/mutation endpoint).
    admin_id: uuid.UUID = Depends(get_dashboard_admin_id),
) -> ChatResponse:
    enforce_chatbot_rate_limit(admin_id)

    cfg = cfg_crud.get_active_for_chatbot(db)
    if cfg is None:
        # No config has is_active_chatbot=True — the feature is deliberately off.
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Chatbot belum dikonfigurasi"
        )

    try:
        system_prompt = build_system_prompt(body.page)
    except ChatbotKnowledgeUnavailable as exc:
        # Knowledge folder didn't ship / a pack is missing — deploy bug, fail loud.
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Basis pengetahuan chatbot tidak tersedia",
        ) from exc

    # §5.1 message assembly — the ONLY content that ever reaches the LLM.
    messages: list[dict] = [
        {"role": "system", "content": system_prompt},
        *[{"role": h.role, "content": h.content} for h in body.history[-20:]],
        {"role": "user", "content": body.message},
    ]

    api_key = decrypt_json(cfg.api_key_enc)["api_key"]
    try:
        result = chat_complete(
            provider=cfg.provider,
            base_url=cfg.base_url,
            api_key=api_key,
            model=cfg.model,
            prompt=body.message,
            messages=messages,
            max_tokens=_MAX_TOKENS,
            # gpt-oss honours reasoning_effort; DeepSeek honours thinking=True
            # (+ reasoning_effort to size its budget). Default high for a
            # factual, low-hallucination explainer; the config may override.
            reasoning_effort=cfg.reasoning_effort or "high",
            route_order=cfg.route_order,
            thinking=True,
        )
    except Exception as exc:
        # Usage logging never carries content — only the error string + metadata.
        llm_log_crud.record(
            db,
            llm_config_id=cfg.id,
            source="chatbot",
            model=cfg.model,
            success=False,
            error=str(exc)[:2000],
        )
        db.commit()
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            "Chatbot sedang tidak tersedia, coba lagi.",
        ) from exc

    prompt_cost = _calc_cost(result.input_tokens, cfg.input_price_per_1m)
    completion_cost = _calc_cost(result.output_tokens, cfg.output_price_per_1m)
    total_cost = (
        prompt_cost + completion_cost
        if prompt_cost is not None and completion_cost is not None
        else None
    )
    llm_log_crud.record(
        db,
        llm_config_id=cfg.id,
        source="chatbot",
        model=cfg.model,
        success=True,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        total_tokens=result.total_tokens,
        reasoning_tokens=result.reasoning_tokens,
        prompt_cost=prompt_cost,
        completion_cost=completion_cost,
        total_cost=total_cost,
        latency_ms=result.latency_ms,
    )
    db.commit()
    # Never hand the UI an empty answer: a blank assistant bubble renders empty
    # AND poisons the next request's history (each history item needs content
    # >= 1 char), 422-ing every follow-up. A model can occasionally return empty
    # text (e.g. budget spent on the reasoning channel, or an odd/interrupted
    # run), so fall back to a friendly line.
    answer = result.text.strip() or (
        "Maaf, saya belum bisa menjawab itu sekarang. Coba ulangi, atau tanyakan "
        "hal lain tentang dashboard atau Registri Hipertensi."
    )
    return ChatResponse(answer=answer)
