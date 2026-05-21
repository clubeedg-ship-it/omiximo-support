"""Pydantic v2 schemas for KnowledgeEntry endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

ALLOWED_ENTRY_TYPES = ("policy", "faq", "product_info", "marketplace_rule")

EntryType = Literal["policy", "faq", "product_info", "marketplace_rule"]


class KnowledgeEntryCreate(BaseModel):
    """Request body for creating a new knowledge entry."""

    entry_type: EntryType = Field(
        ...,
        description="Type of knowledge entry",
    )
    title: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Human-readable title",
    )
    content: str = Field(
        ...,
        min_length=1,
        description="Plain text content surfaced to the LLM",
    )
    category_tags: list[str] = Field(
        default_factory=list,
        description="Classifier categories this applies to; empty = universal",
    )
    marketplace_tags: list[str] = Field(
        default_factory=list,
        description="Marketplace names this applies to; empty = universal",
    )
    language: str | None = Field(
        default=None,
        description="ISO 639-1 code (nl/en/fr/de); NULL = language-agnostic",
    )
    is_active: bool = True

    @field_validator("language")
    @classmethod
    def validate_language(cls, v: str | None) -> str | None:
        if v is not None and v not in ("nl", "en", "fr", "de"):
            msg = "language must be one of: nl, en, fr, de"
            raise ValueError(msg)
        return v


class KnowledgeEntryUpdate(BaseModel):
    """Partial update schema for knowledge entries."""

    entry_type: EntryType | None = None
    title: str | None = Field(default=None, min_length=1, max_length=255)
    content: str | None = Field(default=None, min_length=1)
    category_tags: list[str] | None = None
    marketplace_tags: list[str] | None = None
    language: str | None = None
    is_active: bool | None = None

    @field_validator("language")
    @classmethod
    def validate_language(cls, v: str | None) -> str | None:
        if v is not None and v not in ("nl", "en", "fr", "de"):
            msg = "language must be one of: nl, en, fr, de"
            raise ValueError(msg)
        return v


class KnowledgeEntryResponse(BaseModel):
    """Full representation of a knowledge entry returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    entry_type: str
    title: str
    content: str
    category_tags: list[str]
    marketplace_tags: list[str]
    language: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime
