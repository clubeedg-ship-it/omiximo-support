"""Pydantic v2 schemas for ResponseTemplate endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.support_thread import CustomerLanguage


class TemplateCreate(BaseModel):
    """Request body for creating a new response template."""

    marketplace_account_id: uuid.UUID | None = Field(
        default=None,
        description="Scope this template to a specific account; NULL means global",
    )
    category: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Message category, e.g. shipping_delay, return_request",
    )
    language: CustomerLanguage
    template_body: str = Field(
        ...,
        min_length=1,
        description=(
            "Jinja2 template body. Available context slots: "
            "{{ order_id }}, {{ tracking_number }}, {{ delivery_date }}, "
            "{{ shop_name }}, {{ customer_name }}"
        ),
    )
    is_active: bool = True


class TemplateUpdate(BaseModel):
    """Partial update schema for response templates."""

    category: str | None = Field(default=None, min_length=1, max_length=100)
    language: CustomerLanguage | None = None
    template_body: str | None = Field(default=None, min_length=1)
    is_active: bool | None = None


class TemplateResponse(BaseModel):
    """Full representation of a response template."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    marketplace_account_id: uuid.UUID | None
    category: str
    language: str
    template_body: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# P4.3: Marketplace-specific template override schemas
# ---------------------------------------------------------------------------


class TemplateOverrideCreate(BaseModel):
    """Request body for creating a marketplace-specific template override.

    An override is a ResponseTemplate scoped to a specific marketplace_account_id.
    Only one active override per (account, category, language) tuple is allowed.
    """

    marketplace_account_id: uuid.UUID = Field(
        ...,
        description="The marketplace account this override applies to",
    )
    category: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Message category, e.g. shipping_delay, return_request",
    )
    language: CustomerLanguage = Field(
        ...,
        description="ISO 639-1 language code: nl, en, fr, de",
    )
    template_body: str = Field(
        ...,
        min_length=1,
        description=(
            "Jinja2 template body. Available context slots: "
            "{{ order_id }}, {{ tracking_number }}, {{ delivery_date }}, "
            "{{ shop_name }}, {{ customer_name }}"
        ),
    )


class TemplateOverrideResponse(BaseModel):
    """Full representation of a marketplace-specific template override.

    Re-uses the same underlying ResponseTemplate table; this schema makes the
    override semantics explicit in the API surface.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    marketplace_account_id: uuid.UUID
    category: str
    language: str
    template_body: str
    is_active: bool
    created_at: datetime
    updated_at: datetime
