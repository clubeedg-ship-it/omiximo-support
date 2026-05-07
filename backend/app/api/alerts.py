"""Alerts API endpoint (Phase 3).

GET /api/v1/alerts

Returns a combined view of:
  - SLA approaching deadlines (within 1 hour)
  - SLA overdue threads
  - Missing tracking data
  - Missing invoice data

All alert sources are queried in parallel for efficiency.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services.data_alerts import DataAlertService
from app.services.sla_monitor import SLAAlert, SLAMonitor

router = APIRouter(prefix="/alerts", tags=["alerts"])


# --------------------------------------------------------------------------- #
# Response schemas                                                             #
# --------------------------------------------------------------------------- #


class SLAAlertResponse(BaseModel):
    """Serialisable representation of an SLAAlert."""

    thread_id: str
    deadline: datetime
    hours_remaining: float
    marketplace: str

    model_config = {"from_attributes": True}


class DataAlertResponse(BaseModel):
    """Serialisable representation of a DataAlert."""

    thread_id: str
    alert_type: str
    message: str
    created_at: datetime

    model_config = {"from_attributes": True}


class AlertsResponse(BaseModel):
    """Combined alerts response body."""

    sla_approaching: list[SLAAlertResponse] = Field(
        default_factory=list,
        description="Threads whose deadline is within 1 hour",
    )
    sla_overdue: list[SLAAlertResponse] = Field(
        default_factory=list,
        description="Threads past their response deadline",
    )
    missing_data: list[DataAlertResponse] = Field(
        default_factory=list,
        description="Threads missing required connector data (tracking/invoice)",
    )
    total_count: int = Field(
        ...,
        description="Sum of all alert counts across all categories",
    )


# --------------------------------------------------------------------------- #
# Endpoint                                                                     #
# --------------------------------------------------------------------------- #


@router.get(
    "",
    response_model=AlertsResponse,
    summary="Get combined system alerts",
    description=(
        "Returns SLA approaching/overdue alerts and missing connector-data "
        "alerts in a single response."
    ),
)
async def get_alerts(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AlertsResponse:
    """Fetch all active system alerts.

    Queries SLA and data-alert services concurrently and merges the results.
    """
    import asyncio

    monitor = SLAMonitor()
    data_service = DataAlertService()

    (
        sla_approaching,
        sla_overdue,
        missing_tracking,
        missing_invoice,
    ) = await asyncio.gather(
        monitor.check_approaching_deadlines(db),
        monitor.check_overdue(db),
        data_service.check_missing_tracking(db),
        data_service.check_missing_invoice(db),
    )

    missing_data = missing_tracking + missing_invoice

    sla_approaching_resp = [
        SLAAlertResponse(
            thread_id=a.thread_id,
            deadline=a.deadline,
            hours_remaining=a.hours_remaining,
            marketplace=a.marketplace,
        )
        for a in sla_approaching
    ]
    sla_overdue_resp = [
        SLAAlertResponse(
            thread_id=a.thread_id,
            deadline=a.deadline,
            hours_remaining=a.hours_remaining,
            marketplace=a.marketplace,
        )
        for a in sla_overdue
    ]
    missing_data_resp = [
        DataAlertResponse(
            thread_id=a.thread_id,
            alert_type=a.alert_type,
            message=a.message,
            created_at=a.created_at,
        )
        for a in missing_data
    ]

    total_count = len(sla_approaching_resp) + len(sla_overdue_resp) + len(missing_data_resp)

    return AlertsResponse(
        sla_approaching=sla_approaching_resp,
        sla_overdue=sla_overdue_resp,
        missing_data=missing_data_resp,
        total_count=total_count,
    )
