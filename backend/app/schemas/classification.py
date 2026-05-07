"""Pydantic v2 schemas for classification flag endpoints (P4.4)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.support_thread import CustomerLanguage, RiskLevel


class MisclassificationFlagRequest(BaseModel):
    """Request body for flagging a thread as misclassified."""

    correct_category: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="The correct message category according to the reviewer",
    )
    correct_risk_level: RiskLevel = Field(
        ...,
        description="The correct risk level: GREEN / ORANGE / RED",
    )
    correct_language: CustomerLanguage = Field(
        ...,
        description="The correct ISO 639-1 language code: nl / en / fr / de",
    )
    reason: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="Human-readable explanation of why the classification was wrong",
    )
    actor: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="User ID or email of the person submitting the flag",
    )


class ClassificationFlagResponse(BaseModel):
    """Full representation of a classification flag."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    thread_id: uuid.UUID
    original_category: str | None
    original_risk_level: str | None
    original_language: str | None
    correct_category: str
    correct_risk_level: str
    correct_language: str
    reason: str
    actor: str
    resolution: str | None
    resolved_by: str | None
    resolved_at: datetime | None
    created_at: datetime


class ClassificationFlagListResponse(BaseModel):
    """Paginated list of classification flags."""

    items: list[ClassificationFlagResponse]
    total: int
    page: int
    page_size: int


class FlagResolveRequest(BaseModel):
    """Request body for resolving a classification flag."""

    resolution: Literal["accepted", "rejected"] = Field(
        ...,
        description="Accept or reject the proposed correction",
    )
    actor: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="User ID or email of the reviewer resolving the flag",
    )
