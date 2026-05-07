"""Pydantic v2 schemas for AuditLog endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class AuditLogResponse(BaseModel):
    """Read-only representation of an audit log entry."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    thread_id: uuid.UUID | None
    action: str
    actor: str
    detail_json: dict[str, Any] | None
    created_at: datetime
