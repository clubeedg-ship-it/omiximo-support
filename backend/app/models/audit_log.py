"""AuditLog ORM model.

Every automated decision, draft generation, approval, send, and failure
produces exactly one audit row (D4 architecture decision). The audit log
is append-only; rows are never updated or deleted.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
    )
    thread_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("support_threads.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="FK to the associated support thread; NULL for account-level events",
    )
    action: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
        comment=(
            "Action identifier, e.g. thread_collected, classified, draft_generated, "
            "safety_validated, auto_sent, human_approved, escalated, pipeline_failed"
        ),
    )
    actor: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        comment="Who or what triggered this action: 'system' or a user identifier",
    )
    detail_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSON,
        nullable=True,
        comment="Arbitrary structured context for this audit event",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        index=True,
    )

    # Relationships
    thread: Mapped["SupportThread | None"] = relationship(  # noqa: F821
        "SupportThread",
        back_populates="audit_logs",
    )

    def __repr__(self) -> str:
        return (
            f"<AuditLog id={self.id} action={self.action!r} "
            f"actor={self.actor!r} thread_id={self.thread_id}>"
        )
