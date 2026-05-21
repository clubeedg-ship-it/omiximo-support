"""KnowledgeEntry ORM model.

Stores knowledge base entries (policies, FAQs, product info, marketplace rules)
that are surfaced to the LLM during draft generation. Entries are tagged by
category and marketplace for targeted retrieval.

The `retrieve_for_draft` service method selects relevant entries based on the
thread's category, marketplace, and language, providing context to the LLM.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.models.base import Base


class KnowledgeEntry(Base):
    __tablename__ = "knowledge_entries"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
    )
    entry_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
        comment="One of: policy, faq, product_info, marketplace_rule",
    )
    title: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Human-readable title for the knowledge entry",
    )
    content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Plain text content surfaced to the LLM during draft generation",
    )
    category_tags: Mapped[list[str]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        comment="Classifier categories this entry applies to; empty list = universal",
    )
    marketplace_tags: Mapped[list[str]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        comment="Marketplace names this entry applies to; empty list = universal",
    )
    language: Mapped[str | None] = mapped_column(
        String(10),
        nullable=True,
        comment="ISO 639-1 code (nl/en/fr/de); NULL = language-agnostic",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        comment="Inactive entries are excluded from retrieval",
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

    def __repr__(self) -> str:
        return (
            f"<KnowledgeEntry id={self.id} type={self.entry_type!r} "
            f"title={self.title!r} active={self.is_active}>"
        )
