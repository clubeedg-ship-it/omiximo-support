"""Pydantic v2 schemas for MarketplaceAccount endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class MarketplaceAccountCreate(BaseModel):
    """Request body for creating a new marketplace account.

    ``api_key`` is optional when Mirakl Connect OAuth2 is used — in that case
    authentication is handled centrally and no per-shop key is required.
    When provided, the plaintext key is encrypted by the service layer before
    persistence and is never returned in responses.
    """

    marketplace: str = Field(..., min_length=1, max_length=100)
    shop_id: str = Field(..., min_length=1, max_length=100)
    api_key: str | None = Field(
        default=None,
        description=(
            "Plaintext Mirakl API key — will be encrypted before storage. "
            "Optional when Mirakl Connect OAuth2 credentials are configured."
        ),
    )
    base_url: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Mirakl API base URL, e.g. https://markt.mediamarkt.nl",
    )
    sla_hours: int = Field(default=24, ge=1, le=168)
    template_set: str = Field(default="default", min_length=1, max_length=100)
    is_active: bool = True


class MarketplaceAccountUpdate(BaseModel):
    """Partial update schema; all fields are optional."""

    marketplace: str | None = Field(default=None, min_length=1, max_length=100)
    shop_id: str | None = Field(default=None, min_length=1, max_length=100)
    api_key: str | None = Field(
        default=None,
        description="If provided, replaces the stored encrypted key",
    )
    base_url: str | None = Field(default=None, min_length=1, max_length=255)
    sla_hours: int | None = Field(default=None, ge=1, le=168)
    template_set: str | None = Field(default=None, min_length=1, max_length=100)
    is_active: bool | None = None


class MarketplaceAccountResponse(BaseModel):
    """Public representation of a marketplace account.

    NOTE: api_key_encrypted is intentionally excluded — callers never receive
    the encrypted key material via the API.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    marketplace: str
    shop_id: str
    base_url: str
    sla_hours: int
    template_set: str
    is_active: bool
    created_at: datetime
    updated_at: datetime
