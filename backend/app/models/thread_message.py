"""ThreadMessage ORM model.

Stores individual messages within a support thread conversation. Enables
multi-message support: customer follow-ups, outbound replies, and operator
messages are each stored as separate rows ordered by sequence_number.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class MessageDirection(str, enum.Enum):
    """Direction of a message relative to the shop."""

    INBOUND = "INBOUND"
    OUTBOUND = "OUTBOUND"


class MessageAuthorType(str, enum.Enum):
    """Who authored the message."""

    CUSTOMER = "CUSTOMER"
    SHOP_USER = "SHOP_USER"
    OPERATOR = "OPERATOR"
    SYSTEM = "SYSTEM"


class ThreadMessage(Base):
    __tablename__ = "thread_messages"
    __table_args__ = (
        UniqueConstraint(
            "thread_id",
            "sequence_number",
            name="uq_thread_message_sequence",
        ),
    )

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
    )
    direction: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="INBOUND or OUTBOUND",
    )
    author_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="CUSTOMER, SHOP_USER, OPERATOR, or SYSTEM",
    )
    body: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Full message body text",
    )
    mirakl_message_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        index=True,
        comment="Stable Mirakl message identifier; enables idempotent sync/backfill",
    )
    author_name: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        comment="Display name of the message sender (who replied)",
    )
    sequence_number: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="1-based position of this message within the thread",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    # Relationship back to thread
    thread: Mapped["SupportThread"] = relationship(  # noqa: F821
        "SupportThread",
        back_populates="messages",
    )

    def __repr__(self) -> str:
        return (
            f"<ThreadMessage id={self.id} thread_id={self.thread_id} "
            f"seq={self.sequence_number} direction={self.direction}>"
        )
