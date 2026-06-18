"""Reporting endpoints (Phase 4).

GET /api/v1/reports/summary
    Aggregated metrics for a configurable time window.

GET /api/v1/reports/timeline
    Time-bucketed counts of thread events (new, resolved, auto-sent, escalated).

All queries are performed directly against the support_threads and audit_log
tables.  No materialised views or separate reporting schema are required at
this scale.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import case, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

import uuid as _uuid

from app.database import get_db
from app.models.marketplace_account import MarketplaceAccount
from app.models.support_thread import SupportThread, ThreadStatus

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/reports", tags=["reports"])


# --------------------------------------------------------------------------- #
# Response schemas                                                             #
# --------------------------------------------------------------------------- #


class SummaryReport(BaseModel):
    """Aggregated summary metrics for the requested window."""

    total_threads: int = Field(..., description="Total threads created in the window")
    by_risk_level: dict[str, int] = Field(
        ...,
        description="Thread counts keyed by risk level (green/orange/red/unclassified)",
    )
    by_status: dict[str, int] = Field(
        ...,
        description="Thread counts keyed by status",
    )
    avg_response_time_hours: float = Field(
        ...,
        description=(
            "Mean time in hours from thread creation to first status change "
            "away from PENDING_REVIEW"
        ),
    )
    auto_reply_rate: float = Field(
        ...,
        description=(
            "Fraction of terminal threads that were auto-sent "
            "(sent_auto / total terminal)"
        ),
    )
    sla_compliance_rate: float = Field(
        ...,
        description=(
            "Fraction of resolved threads that were resolved before their deadline"
        ),
    )
    by_category: dict[str, int] = Field(
        ...,
        description="Thread counts keyed by category label",
    )
    by_marketplace: dict[str, int] = Field(
        ...,
        description="Thread counts keyed by marketplace name",
    )


class TimelinePoint(BaseModel):
    """A single time bucket in the timeline report."""

    date: str = Field(..., description="ISO 8601 bucket label (date or datetime)")
    new_threads: int
    resolved: int
    auto_sent: int
    escalated: int


class TimelineReport(BaseModel):
    """Timeline of thread events bucketed by day or hour."""

    granularity: str
    points: list[TimelinePoint]


# --------------------------------------------------------------------------- #
# Endpoints                                                                    #
# --------------------------------------------------------------------------- #


@router.get(
    "/summary",
    response_model=SummaryReport,
    summary="Thread summary report",
)
async def get_summary_report(
    db: Annotated[AsyncSession, Depends(get_db)],
    marketplace_account_id: _uuid.UUID | None = Query(
        default=None,
        description="Restrict to a single marketplace account",
    ),
    days: int = Query(
        default=0,
        ge=0,
        le=3650,
        description="Lookback window in days. 0 means all time (default 0)",
    ),
) -> SummaryReport:
    """Return aggregated metrics for threads created in the last *days* days."""
    base_filter: list = []
    if days > 0:
        since = datetime.now(UTC) - timedelta(days=days)
        base_filter.append(SupportThread.created_at >= since)
    if marketplace_account_id is not None:
        base_filter.append(
            SupportThread.marketplace_account_id == marketplace_account_id
        )

    # ------------------------------------------------------------------ #
    # Fetch all matching threads                                           #
    # ------------------------------------------------------------------ #
    stmt = select(SupportThread).where(*base_filter) if base_filter else select(SupportThread)
    result = await db.execute(stmt)
    threads = list(result.scalars().all())

    total_threads = len(threads)

    # ------------------------------------------------------------------ #
    # By-risk-level                                                        #
    # ------------------------------------------------------------------ #
    by_risk: dict[str, int] = {"green": 0, "orange": 0, "red": 0, "unclassified": 0}
    for t in threads:
        if t.risk_level is None:
            by_risk["unclassified"] += 1
        else:
            by_risk[t.risk_level.value.lower()] += 1

    # ------------------------------------------------------------------ #
    # By-status                                                            #
    # ------------------------------------------------------------------ #
    by_status: dict[str, int] = {
        "pending": 0,
        "approved": 0,
        "sent_auto": 0,
        "escalated": 0,
        "failed": 0,
    }
    status_map = {
        ThreadStatus.PENDING_REVIEW: "pending",
        ThreadStatus.APPROVED: "approved",
        ThreadStatus.SENT_AUTO: "sent_auto",
        ThreadStatus.ESCALATED: "escalated",
        ThreadStatus.FAILED: "failed",
    }
    for t in threads:
        key = status_map.get(t.status, "pending")
        by_status[key] += 1

    # ------------------------------------------------------------------ #
    # By-category                                                          #
    # ------------------------------------------------------------------ #
    by_category: dict[str, int] = {}
    for t in threads:
        cat = t.category or "uncategorized"
        by_category[cat] = by_category.get(cat, 0) + 1

    # ------------------------------------------------------------------ #
    # By-marketplace                                                       #
    # ------------------------------------------------------------------ #
    by_marketplace: dict[str, int] = {}
    for t in threads:
        marketplace_name = await _get_marketplace_name(db, t.marketplace_account_id)
        by_marketplace[marketplace_name] = by_marketplace.get(marketplace_name, 0) + 1

    # ------------------------------------------------------------------ #
    # Terminal threads for rate calculations                               #
    # ------------------------------------------------------------------ #
    terminal_statuses = {
        ThreadStatus.APPROVED,
        ThreadStatus.SENT_AUTO,
        ThreadStatus.ESCALATED,
        ThreadStatus.FAILED,
    }
    terminal_threads = [t for t in threads if t.status in terminal_statuses]
    total_terminal = len(terminal_threads)

    # Auto-reply rate: sent_auto / total terminal
    sent_auto_count = by_status["sent_auto"]
    auto_reply_rate = (sent_auto_count / total_terminal) if total_terminal > 0 else 0.0

    # SLA compliance: resolved before deadline / total resolved
    # "resolved" = not PENDING_REVIEW and not FAILED
    resolved_threads = [
        t for t in threads
        if t.status in {ThreadStatus.APPROVED, ThreadStatus.SENT_AUTO, ThreadStatus.ESCALATED}
    ]
    if resolved_threads:
        on_time = sum(
            1 for t in resolved_threads
            if _is_before_deadline(t.updated_at, t.response_deadline)
        )
        sla_compliance_rate = on_time / len(resolved_threads)
    else:
        sla_compliance_rate = 1.0  # vacuously compliant

    # Average response time: created_at → updated_at for terminal threads
    if terminal_threads:
        response_times_hours = [
            (
                _ensure_utc(t.updated_at) - _ensure_utc(t.created_at)
            ).total_seconds() / 3600
            for t in terminal_threads
        ]
        avg_response_time_hours = sum(response_times_hours) / len(response_times_hours)
    else:
        avg_response_time_hours = 0.0

    return SummaryReport(
        total_threads=total_threads,
        by_risk_level=by_risk,
        by_status=by_status,
        avg_response_time_hours=round(avg_response_time_hours, 2),
        auto_reply_rate=round(auto_reply_rate, 4),
        sla_compliance_rate=round(sla_compliance_rate, 4),
        by_category=by_category,
        by_marketplace=by_marketplace,
    )


@router.get(
    "/timeline",
    response_model=TimelineReport,
    summary="Thread timeline report",
)
async def get_timeline_report(
    db: Annotated[AsyncSession, Depends(get_db)],
    marketplace_account_id: _uuid.UUID | None = Query(
        default=None,
        description="Restrict to a single marketplace account",
    ),
    days: int = Query(
        default=0,
        ge=0,
        le=3650,
        description="Lookback window in days. 0 means all time (default 0)",
    ),
    granularity: str = Query(
        default="day",
        pattern="^(day|hour)$",
        description="Bucket size: 'day' or 'hour'",
    ),
) -> TimelineReport:
    """Return thread counts bucketed by *granularity* over the last *days* days."""
    now = datetime.now(UTC)

    base_filter: list = []
    if days > 0:
        since = datetime.now(UTC) - timedelta(days=days)
        base_filter.append(SupportThread.created_at >= since)
    if marketplace_account_id is not None:
        base_filter.append(
            SupportThread.marketplace_account_id == marketplace_account_id
        )

    stmt = select(SupportThread).where(*base_filter) if base_filter else select(SupportThread)
    result = await db.execute(stmt)
    threads = list(result.scalars().all())

    # For all-time, derive start from earliest thread
    if days == 0:
        if threads:
            since = min(_ensure_utc(t.created_at) for t in threads)
        else:
            since = now - timedelta(days=365)
    else:
        since = now - timedelta(days=days)

    # ------------------------------------------------------------------ #
    # Build buckets                                                        #
    # ------------------------------------------------------------------ #
    buckets: dict[str, dict[str, int]] = {}

    # Pre-populate all expected buckets with zeros so the timeline is
    # continuous even for periods with no activity.
    current = since
    while current <= now:
        key = _bucket_key(current, granularity)
        buckets[key] = {
            "new_threads": 0,
            "resolved": 0,
            "auto_sent": 0,
            "escalated": 0,
        }
        if granularity == "day":
            current += timedelta(days=1)
        else:
            current += timedelta(hours=1)

    # Fill buckets from thread data
    for t in threads:
        created_key = _bucket_key(_ensure_utc(t.created_at), granularity)
        if created_key in buckets:
            buckets[created_key]["new_threads"] += 1

        if t.status in {
            ThreadStatus.APPROVED,
            ThreadStatus.SENT_AUTO,
            ThreadStatus.ESCALATED,
            ThreadStatus.FAILED,
        }:
            updated_key = _bucket_key(_ensure_utc(t.updated_at), granularity)
            if updated_key in buckets:
                buckets[updated_key]["resolved"] += 1

        if t.status == ThreadStatus.SENT_AUTO:
            updated_key = _bucket_key(_ensure_utc(t.updated_at), granularity)
            if updated_key in buckets:
                buckets[updated_key]["auto_sent"] += 1

        if t.status == ThreadStatus.ESCALATED:
            updated_key = _bucket_key(_ensure_utc(t.updated_at), granularity)
            if updated_key in buckets:
                buckets[updated_key]["escalated"] += 1

    points = [
        TimelinePoint(
            date=key,
            new_threads=vals["new_threads"],
            resolved=vals["resolved"],
            auto_sent=vals["auto_sent"],
            escalated=vals["escalated"],
        )
        for key, vals in sorted(buckets.items())
    ]

    return TimelineReport(granularity=granularity, points=points)


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #

_marketplace_cache: dict[str, str] = {}


async def _get_marketplace_name(
    db: AsyncSession,
    account_id: _uuid.UUID,
) -> str:
    """Resolve marketplace name from account_id, with an in-request cache."""
    key = str(account_id)
    if key in _marketplace_cache:
        return _marketplace_cache[key]
    account = await db.get(MarketplaceAccount, account_id)
    name = account.marketplace if account else key
    _marketplace_cache[key] = name
    return name


def _bucket_key(dt: datetime, granularity: str) -> str:
    """Return an ISO bucket label for *dt* at *granularity* (day or hour)."""
    if granularity == "hour":
        return dt.strftime("%Y-%m-%dT%H:00:00")
    return dt.strftime("%Y-%m-%d")


def _ensure_utc(dt: datetime) -> datetime:
    """Return *dt* with UTC timezone; naive datetimes are assumed UTC."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


def _is_before_deadline(updated_at: datetime, response_deadline: datetime) -> bool:
    """Return True if *updated_at* precedes *response_deadline*."""
    return _ensure_utc(updated_at) <= _ensure_utc(response_deadline)
