"""ResponseTemplate ORM model.

Stores Jinja2 template bodies for each combination of category + language.
Templates can be scoped to a specific marketplace_account or left global
(marketplace_account_id IS NULL), which acts as a fallback.

Resolution order used by the template engine:
  1. account-scoped template matching category + language
  2. global template (marketplace_account_id IS NULL) matching category + language
  3. TemplateNotFoundError
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.support_thread import CustomerLanguage


class ResponseTemplate(Base):
    __tablename__ = "response_templates"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
    )
    marketplace_account_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("marketplace_accounts.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
        comment="NULL means this template is available to all marketplace accounts",
    )
    category: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
        comment="Message category this template handles, e.g. shipping_delay, return_request",
    )
    language: Mapped[CustomerLanguage] = mapped_column(
        String(10),
        nullable=False,
        index=True,
        comment="ISO 639-1 language code: nl, en, fr, de",
    )
    template_body: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment=(
            "Jinja2 template. Available slots: {{ order_id }}, {{ tracking_number }}, "
            "{{ delivery_date }}, {{ shop_name }}, {{ customer_name }}"
        ),
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        comment="Inactive templates are skipped during resolution",
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
    marketplace_account: Mapped["MarketplaceAccount | None"] = relationship(  # noqa: F821
        "MarketplaceAccount",
        back_populates="response_templates",
    )

    def __repr__(self) -> str:
        return (
            f"<ResponseTemplate id={self.id} category={self.category!r} "
            f"language={self.language!r} account_id={self.marketplace_account_id}>"
        )
