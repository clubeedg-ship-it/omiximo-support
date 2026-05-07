"""Missing data alert service (Phase 3).

DataAlertService surfaces threads where connector data (tracking, invoice)
is expected but has not been populated.  These are informational alerts that
help operators identify threads where Phase-2 connector data is absent.

Rules:
  - category == "tracking_update"  AND tracking_status IS NULL  → missing tracking
  - category == "invoice_request"  AND invoice_status  IS NULL  → missing invoice

Only PENDING_REVIEW threads are surfaced; terminal threads (SENT_AUTO,
APPROVED, ESCALATED, FAILED) are excluded because the data may be irrelevant
once a thread is resolved.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.support_thread import SupportThread, ThreadStatus

logger = logging.getLogger(__name__)

# Categories that require tracking / invoice data
_TRACKING_CATEGORIES: frozenset[str] = frozenset(
    {"tracking_update", "shipping_inquiry", "delivery_status"}
)
_INVOICE_CATEGORIES: frozenset[str] = frozenset(
    {"invoice_request", "invoice_inquiry", "billing_issue"}
)


@dataclass
class DataAlert:
    """Alert describing a thread with missing connector data."""

    thread_id: str
    alert_type: str  # "missing_tracking" | "missing_invoice"
    message: str
    created_at: datetime


class DataAlertService:
    """Checks for threads where required connector data is absent."""

    async def check_missing_tracking(
        self,
        db: AsyncSession,
    ) -> list[DataAlert]:
        """Return alerts for tracking_update threads with no tracking_status.

        Args:
            db: Async database session (read-only).

        Returns:
            List of DataAlert for each affected PENDING_REVIEW thread.
        """
        stmt = (
            select(SupportThread)
            .where(
                SupportThread.status == ThreadStatus.PENDING_REVIEW,
                SupportThread.category.in_(list(_TRACKING_CATEGORIES)),
                SupportThread.tracking_status.is_(None),
            )
            .order_by(SupportThread.created_at.asc())
        )
        result = await db.execute(stmt)
        threads = list(result.scalars().all())

        alerts: list[DataAlert] = []
        for thread in threads:
            alerts.append(
                DataAlert(
                    thread_id=str(thread.id),
                    alert_type="missing_tracking",
                    message=(
                        f"Thread {thread.mirakl_thread_id} (order "
                        f"{thread.mirakl_order_id}) has category "
                        f"{thread.category!r} but tracking_status is not set. "
                        "Connect the carrier tracking API to populate this field."
                    ),
                    created_at=thread.created_at,
                )
            )
        return alerts

    async def check_missing_invoice(
        self,
        db: AsyncSession,
    ) -> list[DataAlert]:
        """Return alerts for invoice_request threads with no invoice_status.

        Args:
            db: Async database session (read-only).

        Returns:
            List of DataAlert for each affected PENDING_REVIEW thread.
        """
        stmt = (
            select(SupportThread)
            .where(
                SupportThread.status == ThreadStatus.PENDING_REVIEW,
                SupportThread.category.in_(list(_INVOICE_CATEGORIES)),
                SupportThread.invoice_status.is_(None),
            )
            .order_by(SupportThread.created_at.asc())
        )
        result = await db.execute(stmt)
        threads = list(result.scalars().all())

        alerts: list[DataAlert] = []
        for thread in threads:
            alerts.append(
                DataAlert(
                    thread_id=str(thread.id),
                    alert_type="missing_invoice",
                    message=(
                        f"Thread {thread.mirakl_thread_id} (order "
                        f"{thread.mirakl_order_id}) has category "
                        f"{thread.category!r} but invoice_status is not set. "
                        "Connect the invoice API to populate this field."
                    ),
                    created_at=thread.created_at,
                )
            )
        return alerts
