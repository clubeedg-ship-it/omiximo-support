"""MarketplaceAccount ORM model.

Stores per-account Mirakl credentials (encrypted), configuration, and metadata.
All Mirakl API keys are stored in encrypted form; the encryption service in
app.services.encryption handles Fernet encrypt/decrypt transparently.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class MarketplaceAccount(Base):
    __tablename__ = "marketplace_accounts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
    )
    marketplace: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        comment="Human-readable marketplace name, e.g. MediaMarkt, Boulanger",
    )
    shop_id: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        comment="Seller shop ID within the marketplace",
    )
    api_key_encrypted: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
        comment="Fernet-encrypted Mirakl API key — never stored in plaintext",
    )
    base_url: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Mirakl API base URL, e.g. https://markt.mediamarkt.nl",
    )
    sla_hours: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=24,
        comment="SLA response time in hours for this marketplace",
    )
    template_set: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        default="default",
        comment="Template set identifier; maps to response_templates.template_set",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        comment="Inactive accounts are skipped during polling",
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
    support_threads: Mapped[list["SupportThread"]] = relationship(  # noqa: F821
        "SupportThread",
        back_populates="marketplace_account",
        cascade="all, delete-orphan",
    )
    response_templates: Mapped[list["ResponseTemplate"]] = relationship(  # noqa: F821
        "ResponseTemplate",
        back_populates="marketplace_account",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return (
            f"<MarketplaceAccount id={self.id} marketplace={self.marketplace!r} "
            f"shop_id={self.shop_id!r} is_active={self.is_active}>"
        )
