"""ClassificationFlag ORM model.

Stores human-submitted corrections when the LLM classifier produced a wrong
category, risk_level, or language for a support thread.  Flags flow through a
two-state lifecycle:

  unresolved (resolution IS NULL)
    → accepted  – the thread's classification fields are updated to the
                  correct values and an audit row is written.
    → rejected  – the original classification is kept; the flag is closed.

Every flag and resolution action is also written to audit_log (D4).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class ClassificationFlag(Base):
    __tablename__ = "classification_flags"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
    )
    thread_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("support_threads.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="The thread whose classification is disputed",
    )

    # Snapshot of the original classification at the time of flagging
    original_category: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        comment="Category value on the thread when the flag was created",
    )
    original_risk_level: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
        comment="risk_level on the thread when the flag was created",
    )
    original_language: Mapped[str | None] = mapped_column(
        String(10),
        nullable=True,
        comment="customer_language on the thread when the flag was created",
    )

    # Proposed corrections
    correct_category: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        comment="Proposed correct category",
    )
    correct_risk_level: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="Proposed correct risk_level: GREEN / ORANGE / RED",
    )
    correct_language: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        comment="Proposed correct ISO 639-1 language code",
    )

    reason: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Human-readable explanation for why the classification is wrong",
    )
    actor: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        comment="User ID or email of the person submitting the flag",
    )

    # Resolution fields — all NULL until a reviewer accepts or rejects
    resolution: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
        index=True,
        comment="accepted | rejected | NULL (pending)",
    )
    resolved_by: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        comment="User ID or email of the reviewer who resolved the flag",
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Timestamp when the flag was resolved",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        index=True,
    )

    # Relationships
    thread: Mapped["SupportThread"] = relationship(  # noqa: F821
        "SupportThread",
        back_populates="classification_flags",
    )

    def __repr__(self) -> str:
        return (
            f"<ClassificationFlag id={self.id} thread_id={self.thread_id} "
            f"resolution={self.resolution!r}>"
        )
