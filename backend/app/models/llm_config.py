from decimal import Decimal

from sqlalchemy import Boolean, LargeBinary, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import SoftDeleteMixin, TimestampMixin, UUIDPKMixin


class LlmConfig(UUIDPKMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "llm_configs"

    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    base_url: Mapped[str] = mapped_column(String(512), nullable=False)
    api_key_enc: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active_captcha: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active_chatbot: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Loop agent roles: the fix agent (falls back to is_active) and the PR
    # reviewer (deliberate only — no fallback; unset reviewer = review skipped).
    is_active_loop_agent: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active_loop_reviewer: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    label: Mapped[str | None] = mapped_column(String(64), nullable=True)
    input_price_per_1m: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    output_price_per_1m: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    # Free-form reasoning effort, passed through to the provider verbatim
    # (e.g. low/medium/high/xhigh for OpenAI, high/max for DeepSeek, low/medium/
    # high for gpt-oss). None/"" means omit. Capped to 16 chars; NOT allowlisted —
    # the Test-connection button is how an operator verifies a value is accepted.
    reasoning_effort: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # OpenRouter provider routing pin (comma-separated slugs, e.g. "z-ai").
    # When set, requests send provider.order + allow_fallbacks=false so the
    # upstream is hard-pinned with no fallback. Only send to endpoints that
    # accept the OpenRouter `provider` body field — verified via Test-connection.
    route_order: Mapped[str | None] = mapped_column(String(128), nullable=True)
