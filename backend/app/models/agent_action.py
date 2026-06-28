"""AgentAction ORM model — the human approval gate.

Every action the autonomous agent wants to take in the outside world
(send a reply, escalate, and — in later phases — approve a return or issue a
refund) is first persisted here with status ``proposed`` and surfaced to a
human via Telegram. Nothing is executed until a human taps Approve, which
flips the row to ``approved`` and then ``executed`` (or ``failed``).
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ActionStatus(str, enum.Enum):
    """Lifecycle of a proposed agent action."""

    PROPOSED = "proposed"
    APPROVED = "approved"
    DENIED = "denied"
    EXECUTED = "executed"
    FAILED = "failed"


class AgentAction(Base):
    __tablename__ = "agent_actions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False
    )
    thread_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("support_threads.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    action_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        comment="send_reply | escalate | (future: approve_return, issue_refund)",
    )
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=ActionStatus.PROPOSED.value,
        index=True,
    )
    payload_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict,
        comment="Action parameters, e.g. {'body': '...'} for send_reply",
    )
    telegram_message_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    decided_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    result_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    context_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True,
        comment="Snapshot of the read-tool facts the card was built from, "
        "so the card can be re-rendered (edit/translate) after the run.",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
