import uuid
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, load_only

from app.core.rate_limit import enforce_decrypt_rate_limit
from app.core.security import decrypt_json, encrypt_json
from app.models.llm_config import LlmConfig
from app.schemas.llm import LlmConfigCreate, LlmConfigUpdate

_OUT_COLS = (
    LlmConfig.id, LlmConfig.provider, LlmConfig.model, LlmConfig.base_url,
    LlmConfig.is_active, LlmConfig.is_active_captcha, LlmConfig.is_active_chatbot,
    LlmConfig.is_active_loop_agent, LlmConfig.is_active_loop_reviewer,
    LlmConfig.label, LlmConfig.reasoning_effort, LlmConfig.route_order,
    LlmConfig.input_price_per_1m, LlmConfig.output_price_per_1m,
    LlmConfig.created_at, LlmConfig.updated_at,
)


def get_active(db: Session) -> LlmConfig | None:
    return db.scalar(
        select(LlmConfig)
        .options(load_only(
            LlmConfig.id, LlmConfig.provider, LlmConfig.model,
            LlmConfig.base_url, LlmConfig.api_key_enc, LlmConfig.route_order, LlmConfig.is_active,
            LlmConfig.reasoning_effort,
            LlmConfig.input_price_per_1m, LlmConfig.output_price_per_1m,
        ))
        .where(LlmConfig.is_active.is_(True))
    )


def get_active_for_captcha(db: Session) -> LlmConfig | None:
    obj = db.scalar(
        select(LlmConfig)
        .options(load_only(
            LlmConfig.id, LlmConfig.provider, LlmConfig.model,
            LlmConfig.base_url, LlmConfig.api_key_enc, LlmConfig.route_order, LlmConfig.is_active_captcha,
            LlmConfig.reasoning_effort,
            LlmConfig.input_price_per_1m, LlmConfig.output_price_per_1m,
        ))
        .where(LlmConfig.is_active_captcha.is_(True))
    )
    if obj is not None:
        return obj
    return get_active(db)


def get_active_for_chatbot(db: Session) -> LlmConfig | None:
    # No fallback to get_active() (unlike captcha): the explainer chatbot must
    # be deliberately enabled. If no config has is_active_chatbot=True the
    # feature is off and the route returns 503 — we never silently route public
    # chat traffic to the (possibly expensive) merge config.
    return db.scalar(
        select(LlmConfig)
        .options(load_only(
            LlmConfig.id, LlmConfig.provider, LlmConfig.model,
            LlmConfig.base_url, LlmConfig.api_key_enc, LlmConfig.route_order, LlmConfig.is_active_chatbot,
            LlmConfig.reasoning_effort,
            LlmConfig.input_price_per_1m, LlmConfig.output_price_per_1m,
        ))
        .where(LlmConfig.is_active_chatbot.is_(True))
    )


def get_active_for_loop_agent(db: Session) -> LlmConfig | None:
    # Falls back to get_active() (same as captcha): the loop agent can ride the
    # general-purpose merge config until a dedicated one is set.
    obj = db.scalar(
        select(LlmConfig)
        .options(load_only(
            LlmConfig.id, LlmConfig.provider, LlmConfig.model,
            LlmConfig.base_url, LlmConfig.api_key_enc, LlmConfig.route_order, LlmConfig.is_active_loop_agent,
            LlmConfig.reasoning_effort,
            LlmConfig.input_price_per_1m, LlmConfig.output_price_per_1m,
        ))
        .where(LlmConfig.is_active_loop_agent.is_(True))
    )
    if obj is not None:
        return obj
    return get_active(db)


def get_active_for_loop_reviewer(db: Session) -> LlmConfig | None:
    # NO fallback (same reasoning as chatbot): reviewing the agent's diff must be
    # deliberate — a wrong "cheap default" here silently gates every fix. If unset,
    # the run skips the review step and lands in needs_review with a note.
    return db.scalar(
        select(LlmConfig)
        .options(load_only(
            LlmConfig.id, LlmConfig.provider, LlmConfig.model,
            LlmConfig.base_url, LlmConfig.api_key_enc, LlmConfig.route_order, LlmConfig.is_active_loop_reviewer,
            LlmConfig.reasoning_effort,
            LlmConfig.input_price_per_1m, LlmConfig.output_price_per_1m,
        ))
        .where(LlmConfig.is_active_loop_reviewer.is_(True))
    )


def create(db: Session, data: LlmConfigCreate) -> LlmConfig:
    enc = encrypt_json({"api_key": data.api_key})
    obj = LlmConfig(
        provider=data.provider,
        model=data.model,
        base_url=data.base_url,
        api_key_enc=enc,
        is_active=False,
        label=data.label,
        reasoning_effort=data.reasoning_effort,
        route_order=data.route_order,
        input_price_per_1m=data.input_price_per_1m,
        output_price_per_1m=data.output_price_per_1m,
    )
    db.add(obj)
    db.flush()
    if data.is_active:
        try:
            _set_active_in_txn(db, obj.id)
        except IntegrityError:
            db.rollback()
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Could not activate; another active config exists",
            )
    if data.is_active_captcha:
        try:
            _set_active_captcha_in_txn(db, obj.id)
        except IntegrityError:
            db.rollback()
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Could not activate for captcha; another captcha-active config exists",
            )
    if data.is_active_chatbot:
        try:
            _set_active_chatbot_in_txn(db, obj.id)
        except IntegrityError:
            db.rollback()
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Could not activate for chatbot; another chatbot-active config exists",
            )
    if data.is_active_loop_agent:
        try:
            _set_active_loop_agent_in_txn(db, obj.id)
        except IntegrityError:
            db.rollback()
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Could not activate for loop agent; another loop-agent-active config exists",
            )
    if data.is_active_loop_reviewer:
        try:
            _set_active_loop_reviewer_in_txn(db, obj.id)
        except IntegrityError:
            db.rollback()
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Could not activate for loop reviewer; another loop-reviewer-active config exists",
            )
    db.commit()
    db.refresh(obj)
    return obj


def update_config(db: Session, obj: LlmConfig, data: LlmConfigUpdate) -> LlmConfig:
    fields = data.model_dump(exclude_unset=True)
    api_key = fields.pop("api_key", None)
    for field, value in fields.items():
        setattr(obj, field, value)
    if api_key is not None:
        obj.api_key_enc = encrypt_json({"api_key": api_key})
    db.commit()
    db.refresh(obj)
    return obj


def set_active(db: Session, target_id: uuid.UUID) -> LlmConfig:
    obj = db.scalar(
        select(LlmConfig)
        .options(load_only(*_OUT_COLS))
        .where(LlmConfig.id == target_id)
    )
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "LlmConfig not found")
    try:
        _set_active_in_txn(db, target_id)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Could not activate; constraint violation")
    db.refresh(obj)
    return obj


def set_active_captcha(db: Session, target_id: uuid.UUID) -> LlmConfig:
    obj = db.scalar(
        select(LlmConfig)
        .options(load_only(*_OUT_COLS))
        .where(LlmConfig.id == target_id)
    )
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "LlmConfig not found")
    try:
        _set_active_captcha_in_txn(db, target_id)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Could not activate for captcha; constraint violation")
    db.refresh(obj)
    return obj


def set_active_chatbot(db: Session, target_id: uuid.UUID) -> LlmConfig:
    obj = db.scalar(
        select(LlmConfig)
        .options(load_only(*_OUT_COLS))
        .where(LlmConfig.id == target_id)
    )
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "LlmConfig not found")
    try:
        _set_active_chatbot_in_txn(db, target_id)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Could not activate for chatbot; constraint violation")
    db.refresh(obj)
    return obj


def set_active_loop_agent(db: Session, target_id: uuid.UUID) -> LlmConfig:
    obj = db.scalar(
        select(LlmConfig)
        .options(load_only(*_OUT_COLS))
        .where(LlmConfig.id == target_id)
    )
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "LlmConfig not found")
    try:
        _set_active_loop_agent_in_txn(db, target_id)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Could not activate for loop agent; constraint violation")
    db.refresh(obj)
    return obj


def set_active_loop_reviewer(db: Session, target_id: uuid.UUID) -> LlmConfig:
    obj = db.scalar(
        select(LlmConfig)
        .options(load_only(*_OUT_COLS))
        .where(LlmConfig.id == target_id)
    )
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "LlmConfig not found")
    try:
        _set_active_loop_reviewer_in_txn(db, target_id)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Could not activate for loop reviewer; constraint violation")
    db.refresh(obj)
    return obj


def _set_active_in_txn(db: Session, target_id: uuid.UUID) -> None:
    db.execute(
        update(LlmConfig)
        .where(LlmConfig.is_active.is_(True), LlmConfig.id != target_id)
        .values(is_active=False)
    )
    db.execute(
        update(LlmConfig)
        .where(LlmConfig.id == target_id, LlmConfig.deleted_at.is_(None))
        .values(is_active=True)
    )


def _set_active_captcha_in_txn(db: Session, target_id: uuid.UUID) -> None:
    db.execute(
        update(LlmConfig)
        .where(LlmConfig.is_active_captcha.is_(True), LlmConfig.id != target_id)
        .values(is_active_captcha=False)
    )
    db.execute(
        update(LlmConfig)
        .where(LlmConfig.id == target_id, LlmConfig.deleted_at.is_(None))
        .values(is_active_captcha=True)
    )


def _set_active_chatbot_in_txn(db: Session, target_id: uuid.UUID) -> None:
    db.execute(
        update(LlmConfig)
        .where(LlmConfig.is_active_chatbot.is_(True), LlmConfig.id != target_id)
        .values(is_active_chatbot=False)
    )
    db.execute(
        update(LlmConfig)
        .where(LlmConfig.id == target_id, LlmConfig.deleted_at.is_(None))
        .values(is_active_chatbot=True)
    )


def _set_active_loop_agent_in_txn(db: Session, target_id: uuid.UUID) -> None:
    db.execute(
        update(LlmConfig)
        .where(LlmConfig.is_active_loop_agent.is_(True), LlmConfig.id != target_id)
        .values(is_active_loop_agent=False)
    )
    db.execute(
        update(LlmConfig)
        .where(LlmConfig.id == target_id, LlmConfig.deleted_at.is_(None))
        .values(is_active_loop_agent=True)
    )


def _set_active_loop_reviewer_in_txn(db: Session, target_id: uuid.UUID) -> None:
    db.execute(
        update(LlmConfig)
        .where(LlmConfig.is_active_loop_reviewer.is_(True), LlmConfig.id != target_id)
        .values(is_active_loop_reviewer=False)
    )
    db.execute(
        update(LlmConfig)
        .where(LlmConfig.id == target_id, LlmConfig.deleted_at.is_(None))
        .values(is_active_loop_reviewer=True)
    )


def soft_delete(db: Session, obj: LlmConfig) -> None:
    if obj.is_active:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Cannot delete the active llm_config; activate another config first",
        )
    if obj.is_active_captcha:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Cannot delete the captcha-active llm_config; activate another config first",
        )
    if obj.is_active_chatbot:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Cannot delete the chatbot-active llm_config; activate another config first",
        )
    if obj.is_active_loop_agent:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Cannot delete the loop-agent-active llm_config; activate another config first",
        )
    if obj.is_active_loop_reviewer:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Cannot delete the loop-reviewer-active llm_config; activate another config first",
        )
    obj.deleted_at = datetime.now(UTC)
    db.commit()


def reveal(db: Session, admin_id: uuid.UUID, config_id: uuid.UUID) -> str:
    enforce_decrypt_rate_limit(admin_id, config_id)
    obj = db.scalar(
        select(LlmConfig)
        .options(load_only(LlmConfig.id, LlmConfig.api_key_enc))
        .where(LlmConfig.id == config_id)
    )
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "LlmConfig not found")
    return decrypt_json(obj.api_key_enc)["api_key"]
