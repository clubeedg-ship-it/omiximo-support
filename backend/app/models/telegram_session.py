"""TelegramSession ORM model — transient "awaiting typed input" state.

When an operator taps ✏️ Edit on an approval card, the bot sends a force-reply
prompt and records a row here keyed by the prompt's message id. The operator's
reply (a normal Telegram message whose ``reply_to_message`` is that prompt) is
matched back to the awaiting action, the action is updated, and the row deleted.

Persisting this (rather than keeping it in memory) means an awaiting edit
survives an API restart — and the API runs as a single process anyway (D-016).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class TelegramSession(Base):
    __tablename__ = "telegram_sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False
    )
    chat_id: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_message_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False, index=True,
        comment="message_id of the bot's force-reply prompt the user replies to",
    )
    action_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_actions.id", ondelete="CASCADE"),
        nullable=False,
    )
    kind: Mapped[str] = mapped_column(
        String(16), nullable=False, comment="What input is awaited, e.g. 'edit'"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
