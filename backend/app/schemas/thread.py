"""Pydantic v2 schemas for SupportThread endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.support_thread import CustomerLanguage, RiskLevel, ThreadStatus


class ThreadMessageResponse(BaseModel):
    """A single message within a thread conversation."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    direction: str
    author_type: str
    body: str
    sequence_number: int
    created_at: datetime


class ThreadResponse(BaseModel):
    """Full representation of a support thread returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    mirakl_thread_id: str
    mirakl_order_id: str
    marketplace_account_id: uuid.UUID
    marketplace_name: str | None = None
    customer_language: CustomerLanguage | None
    category: str | None
    risk_level: RiskLevel | None
    status: ThreadStatus
    operator_required: bool
    customer_message: str
    message_summary: str | None
    translated_message: str | None
    drafted_response: str | None
    tracking_status: str | None
    invoice_status: str | None
    response_deadline: datetime
    created_at: datetime
    updated_at: datetime
    message_count: int = 1
    messages: list[ThreadMessageResponse] = []


class ThreadListResponse(BaseModel):
    """Paginated list of support threads."""

    items: list[ThreadResponse]
    total: int
    page: int
    page_size: int


class InsightResponse(BaseModel):
    """AI-generated summary and translation for a thread."""

    summary: str | None = None
    translated_message: str | None = None


class ThreadApproveRequest(BaseModel):
    """Request body for the approve endpoint."""

    drafted_response_override: str | None = Field(
        default=None,
        description="If provided, replaces the system-drafted response before sending",
    )


class ThreadEscalateRequest(BaseModel):
    """Request body for the escalate endpoint."""

    reason: str = Field(
        ...,
        min_length=1,
        max_length=1000,
        description="Human-readable reason for escalation; stored in audit log",
    )


class TranslateDraftRequest(BaseModel):
    """Request body for the translate-draft endpoint."""

    english_text: str = Field(
        ...,
        min_length=1,
        max_length=10_000,
        description="English draft to be translated into the target language",
    )
    target_language: CustomerLanguage


class TranslateDraftResponse(BaseModel):
    """Response from the translate-draft endpoint."""

    translated_text: str | None = None
    correction_made: bool = False
    correction_note: str = ""
