"""SLA monitoring service (Phase 3).

SLAMonitor provides three operations:

  check_approaching_deadlines(db) → list[SLAAlert]
      Threads whose response_deadline is within the next hour and are still
      PENDING_REVIEW.

  check_overdue(db) → list[SLAAlert]
      Threads past their response_deadline still in PENDING_REVIEW.

  auto_escalate_overdue(db) → int
      Moves overdue PENDING_REVIEW threads to ESCALATED, writes an audit row
      for each, and returns the count.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.support_thread import SupportThread, ThreadStatus
from app.services.audit import write_audit_log

logger = logging.getLogger(__name__)

# Approaching-deadline window: alert when deadline is within this many seconds.
_APPROACHING_WINDOW_SECONDS = 3600  # 1 hour


@dataclass
class SLAAlert:
    """Alert describing a thread that is approaching or past its SLA deadline."""

    thread_id: str
    deadline: datetime
    hours_remaining: float
    marketplace: str


class SLAMonitor:
    """Checks SLA deadlines and auto-escalates overdue threads.

    All methods are safe to call multiple times; they are read-only except for
    auto_escalate_overdue which commits its changes.
    """

    async def check_approaching_deadlines(
        self,
        db: AsyncSession,
    ) -> list[SLAAlert]:
        """Return alerts for threads whose deadline is within the next hour.

        Only threads with status PENDING_REVIEW are included; threads that are
        already escalated / sent / failed do not need an SLA alert.

        Args:
            db: Async database session (read-only).

        Returns:
            List of SLAAlert, sorted by deadline ascending (most urgent first).
        """
        now = datetime.now(UTC)
        window_end = now + timedelta(seconds=_APPROACHING_WINDOW_SECONDS)

        stmt = (
            select(SupportThread)
            .where(
                SupportThread.status == ThreadStatus.PENDING_REVIEW,
                SupportThread.response_deadline > now,
                SupportThread.response_deadline <= window_end,
            )
            .order_by(SupportThread.response_deadline.asc())
        )
        result = await db.execute(stmt)
        threads = list(result.scalars().all())

        alerts: list[SLAAlert] = []
        for thread in threads:
            deadline = _ensure_utc(thread.response_deadline)
            hours_remaining = (deadline - now).total_seconds() / 3600
            marketplace = await _resolve_marketplace(db, thread)
            alerts.append(
                SLAAlert(
                    thread_id=str(thread.id),
                    deadline=deadline,
                    hours_remaining=round(hours_remaining, 2),
                    marketplace=marketplace,
                )
            )
        return alerts

    async def check_overdue(
        self,
        db: AsyncSession,
    ) -> list[SLAAlert]:
        """Return alerts for threads that are past their SLA deadline.

        Only PENDING_REVIEW threads are returned; already-escalated threads
        are excluded to avoid duplicate alerts.

        Args:
            db: Async database session (read-only).

        Returns:
            List of SLAAlert with negative hours_remaining, sorted by deadline
            ascending (overdue the longest first).
        """
        now = datetime.now(UTC)

        stmt = (
            select(SupportThread)
            .where(
                SupportThread.status == ThreadStatus.PENDING_REVIEW,
                SupportThread.response_deadline <= now,
            )
            .order_by(SupportThread.response_deadline.asc())
        )
        result = await db.execute(stmt)
        threads = list(result.scalars().all())

        alerts: list[SLAAlert] = []
        for thread in threads:
            deadline = _ensure_utc(thread.response_deadline)
            hours_remaining = (deadline - now).total_seconds() / 3600
            marketplace = await _resolve_marketplace(db, thread)
            alerts.append(
                SLAAlert(
                    thread_id=str(thread.id),
                    deadline=deadline,
                    hours_remaining=round(hours_remaining, 2),
                    marketplace=marketplace,
                )
            )
        return alerts

    async def auto_escalate_overdue(
        self,
        db: AsyncSession,
    ) -> int:
        """Escalate all overdue PENDING_REVIEW threads.

        Threads past their response_deadline that are still PENDING_REVIEW are
        moved to ESCALATED.  A "sla_auto_escalated" audit row is written for
        each one before committing.

        Args:
            db: Async database session.  Changes are committed per-thread to
                limit blast radius of individual failures.

        Returns:
            Number of threads escalated.
        """
        now = datetime.now(UTC)

        stmt = (
            select(SupportThread)
            .where(
                SupportThread.status == ThreadStatus.PENDING_REVIEW,
                SupportThread.response_deadline <= now,
            )
        )
        result = await db.execute(stmt)
        threads = list(result.scalars().all())

        escalated_count = 0
        for thread in threads:
            try:
                deadline = _ensure_utc(thread.response_deadline)
                hours_overdue = (now - deadline).total_seconds() / 3600

                thread.status = ThreadStatus.ESCALATED
                thread.updated_at = now

                await write_audit_log(
                    db,
                    action="sla_auto_escalated",
                    actor="system",
                    thread_id=thread.id,
                    detail={
                        "deadline": deadline.isoformat(),
                        "hours_overdue": round(hours_overdue, 2),
                        "previous_status": ThreadStatus.PENDING_REVIEW.value,
                    },
                )
                await db.commit()
                escalated_count += 1
                logger.info(
                    "SLA auto-escalated thread %s (%.1f hours overdue)",
                    thread.id,
                    hours_overdue,
                )
            except Exception as exc:
                logger.exception(
                    "Failed to auto-escalate thread %s: %s",
                    thread.id,
                    exc,
                )

        return escalated_count


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #


def _ensure_utc(dt: datetime) -> datetime:
    """Return *dt* with UTC timezone; if naive, assume UTC."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


async def _resolve_marketplace(db: AsyncSession, thread: SupportThread) -> str:
    """Look up the marketplace name for the thread's account."""
    from app.models.marketplace_account import MarketplaceAccount

    account = await db.get(MarketplaceAccount, thread.marketplace_account_id)
    if account is not None:
        return account.marketplace
    return str(thread.marketplace_account_id)
