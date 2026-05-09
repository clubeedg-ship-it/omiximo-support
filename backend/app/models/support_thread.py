"""SupportThread ORM model.

Central entity: one row per Mirakl message thread. Tracks the full lifecycle
from collection through classification, drafting, human review, and dispatch.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class CustomerLanguage(str, enum.Enum):
    """ISO 639-1 language codes supported by the template engine."""

    nl = "nl"
    en = "en"
    fr = "fr"
    de = "de"


class RiskLevel(str, enum.Enum):
    """
    Classification output from the LLM classifier.

    GREEN  – Safe for auto-send after safety_rules pass.
    ORANGE – Requires human approval before sending.
    RED    – Manual handling only; system must not draft a response.
    """

    GREEN = "GREEN"
    ORANGE = "ORANGE"
    RED = "RED"


class ThreadStatus(str, enum.Enum):
    """
    Lifecycle status of a support thread.

    PENDING_REVIEW – Newly collected or just classified; awaiting action.
    APPROVED       – Human has approved the drafted response.
    SENT_AUTO      – Green-path: response was sent automatically.
    ESCALATED      – Manually escalated; removed from automation pipeline.
    FAILED         – A pipeline step failed; requires investigation.
    """

    PENDING_REVIEW = "PENDING_REVIEW"
    APPROVED = "APPROVED"
    SENT_AUTO = "SENT_AUTO"
    ESCALATED = "ESCALATED"
    FAILED = "FAILED"


class SupportThread(Base):
    __tablename__ = "support_threads"
    __table_args__ = (
        UniqueConstraint(
            "mirakl_thread_id",
            "marketplace_account_id",
            name="uq_thread_account",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
    )
    mirakl_thread_id: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
        comment="Mirakl-assigned thread identifier",
    )
    mirakl_order_id: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
        comment="Mirakl-assigned order identifier associated with this thread",
    )
    marketplace_account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("marketplace_accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    customer_language: Mapped[CustomerLanguage | None] = mapped_column(
        Enum(CustomerLanguage, name="customer_language_enum"),
        nullable=True,
        comment="Detected customer language; populated after classification",
    )
    category: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        index=True,
        comment="Message category returned by the LLM classifier",
    )
    risk_level: Mapped[RiskLevel | None] = mapped_column(
        Enum(RiskLevel, name="risk_level_enum"),
        nullable=True,
        index=True,
        comment="Risk classification: GREEN / ORANGE / RED",
    )
    status: Mapped[ThreadStatus] = mapped_column(
        Enum(ThreadStatus, name="thread_status_enum"),
        nullable=False,
        default=ThreadStatus.PENDING_REVIEW,
        index=True,
        comment="Lifecycle status of this thread",
    )
    operator_required: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        comment="True when the message originates from the marketplace operator; "
        "auto-reply is permanently blocked for these threads",
    )
    customer_message: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Raw customer message text as received from Mirakl",
    )
    message_summary: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="1-2 sentence English summary of the customer message; populated by insight service",
    )
    translated_message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Full English translation of the customer message; NULL or empty when already English",
    )
    draft_summary: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="1-2 sentence English summary of the drafted response; populated by insight service",
    )
    draft_translated: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Full English translation of the drafted response; NULL or empty when already English",
    )
    drafted_response: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Template-rendered response; NULL until classification + drafting completes",
    )
    tracking_status: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        comment="Latest carrier tracking status (Phase 2)",
    )
    invoice_status: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        comment="Invoice status from billing system (Phase 2)",
    )
    response_deadline: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="SLA deadline; computed as created_at + marketplace_account.sla_hours",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    # Relationships
    marketplace_account: Mapped["MarketplaceAccount"] = relationship(  # noqa: F821
        "MarketplaceAccount",
        back_populates="support_threads",
    )
    audit_logs: Mapped[list["AuditLog"]] = relationship(  # noqa: F821
        "AuditLog",
        back_populates="thread",
        cascade="all, delete-orphan",
    )
    classification_flags: Mapped[list["ClassificationFlag"]] = relationship(  # noqa: F821
        "ClassificationFlag",
        back_populates="thread",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return (
            f"<SupportThread id={self.id} mirakl_thread_id={self.mirakl_thread_id!r} "
            f"status={self.status} risk_level={self.risk_level}>"
        )
