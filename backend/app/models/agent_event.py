"""AgentEvent ORM model — the agent activity / tool-call log.

A lightweight, per-thread timeline of what the agent did: thread received,
each tool call and its result, the assistant's messages, proposals created,
and actions executed. Kept separate from ``audit_log`` (the business/compliance
trail) so high-frequency agent telemetry never bloats the audit table.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AgentEvent(Base):
    __tablename__ = "agent_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False
    )
    thread_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("support_threads.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    event_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        index=True,
        comment=(
            "thread_received | tool_call | tool_result | agent_message | "
            "proposal_created | action_executed | error"
        ),
    )
    detail_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
