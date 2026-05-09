"""Support thread endpoints.

Provides list/detail/approve/escalate operations on SupportThread resources.
All mutating endpoints write to audit_log before returning.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import CurrentUser, require_admin_user
from app.database import get_db
from app.models.marketplace_account import MarketplaceAccount
from app.models.support_thread import RiskLevel, SupportThread, ThreadStatus
from app.schemas.thread import (
    InsightResponse,
    ThreadApproveRequest,
    ThreadEscalateRequest,
    ThreadListResponse,
    ThreadResponse,
)
from app.services.audit import write_audit_log
from app.services.message_insight import MessageInsightService
from app.services.mirakl_client import MiraklClient

logger = logging.getLogger(__name__)

_insight_service = MessageInsightService()

router = APIRouter(prefix="/threads", tags=["threads"])


@router.get("", response_model=ThreadListResponse)
async def list_threads(
    db: Annotated[AsyncSession, Depends(get_db)],
    risk_level: RiskLevel | None = Query(default=None),
    thread_status: ThreadStatus | None = Query(default=None, alias="status"),
    marketplace_account_id: uuid.UUID | None = Query(default=None),
    search: str | None = Query(default=None, min_length=1),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> ThreadListResponse:
    """List support threads with optional filtering and pagination.

    Filters:
      - risk_level: GREEN | ORANGE | RED
      - status: PENDING_REVIEW | APPROVED | SENT_AUTO | ESCALATED | FAILED
      - marketplace_account_id: UUID of the marketplace account
    """
    filtered_stmt = select(SupportThread)

    if risk_level is not None:
        filtered_stmt = filtered_stmt.where(SupportThread.risk_level == risk_level)
    if thread_status is not None:
        filtered_stmt = filtered_stmt.where(SupportThread.status == thread_status)
    if marketplace_account_id is not None:
        filtered_stmt = filtered_stmt.where(
            SupportThread.marketplace_account_id == marketplace_account_id
        )
    if search is not None and search.strip():
        search_term = f"%{search.strip()}%"
        filtered_stmt = filtered_stmt.where(
            or_(
                SupportThread.mirakl_order_id.ilike(search_term),
                SupportThread.mirakl_thread_id.ilike(search_term),
                SupportThread.customer_message.ilike(search_term),
            )
        )

    # Count total matching rows
    count_stmt = select(func.count()).select_from(filtered_stmt.subquery())
    total: int = (await db.execute(count_stmt)).scalar_one()

    # Fetch page
    offset = (page - 1) * page_size
    data_stmt = (
        filtered_stmt
        .options(selectinload(SupportThread.marketplace_account))
        .order_by(SupportThread.response_deadline.asc())
        .offset(offset)
        .limit(page_size)
    )
    rows = list((await db.execute(data_stmt)).scalars().all())

    return ThreadListResponse(
        items=[_serialize_thread(r) for r in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{thread_id}", response_model=ThreadResponse)
async def get_thread(
    thread_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ThreadResponse:
    """Fetch a single support thread by its internal UUID."""
    thread = await _get_thread_or_404(db, thread_id)
    return _serialize_thread(thread)


@router.put("/{thread_id}/approve", response_model=ThreadResponse)
async def approve_thread(
    thread_id: uuid.UUID,
    body: ThreadApproveRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[CurrentUser, Depends(require_admin_user)],
) -> ThreadResponse:
    """Approve a drafted response for sending.

    The human reviewer may optionally supply a corrected response via
    ``drafted_response_override``. After approval the drafted response is
    sent to the customer via the Mirakl API and the thread status becomes APPROVED.

    The actual send happens synchronously within this request so that the
    response contains the final state.
    """
    thread = await _get_thread_or_404(db, thread_id)

    if thread.status not in (ThreadStatus.PENDING_REVIEW,):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Thread is in status {thread.status!r} and cannot be approved. "
                "Only PENDING_REVIEW threads can be approved."
            ),
        )

    if not thread.drafted_response and not body.drafted_response_override:
        raise HTTPException(
            status_code=422,
            detail="Thread has no drafted response. Generate a draft before approving.",
        )

    # Apply override if provided
    if body.drafted_response_override:
        thread.drafted_response = body.drafted_response_override

    effective_response = thread.drafted_response
    assert effective_response  # guarded above

    # Load the associated account to send via Mirakl
    account = thread.marketplace_account
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Marketplace account not found for this thread.",
        )

    # Send via Mirakl
    try:
        async with MiraklClient(account) as client:
            await client.send_reply(
                thread_id=thread.mirakl_thread_id,
                body=effective_response,
            )
    except Exception as exc:
        thread.status = ThreadStatus.FAILED
        thread.updated_at = datetime.now(UTC)
        await write_audit_log(
            db,
            action="human_send_failed",
            actor=current_user.audit_actor,
            thread_id=thread.id,
            detail={"error": str(exc)},
        )
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Mirakl send failed: {exc}",
        ) from exc

    thread.status = ThreadStatus.APPROVED
    thread.updated_at = datetime.now(UTC)

    await write_audit_log(
        db,
        action="human_approved",
        actor=current_user.audit_actor,
        thread_id=thread.id,
        detail={
            "override_applied": body.drafted_response_override is not None,
            "response_length": len(effective_response),
        },
    )

    return _serialize_thread(thread)


@router.put("/{thread_id}/escalate", response_model=ThreadResponse)
async def escalate_thread(
    thread_id: uuid.UUID,
    body: ThreadEscalateRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[CurrentUser, Depends(require_admin_user)],
) -> ThreadResponse:
    """Escalate a thread for manual handling.

    Sets status to ESCALATED and writes an audit entry with the provided reason.
    Once escalated, the thread is removed from the automation pipeline.
    """
    thread = await _get_thread_or_404(db, thread_id)

    if thread.status == ThreadStatus.ESCALATED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Thread is already escalated.",
        )

    if thread.status in (ThreadStatus.SENT_AUTO, ThreadStatus.APPROVED):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Thread is in status {thread.status!r} and has already been sent. "
                "Escalation is not applicable."
            ),
        )

    thread.status = ThreadStatus.ESCALATED
    thread.updated_at = datetime.now(UTC)

    await write_audit_log(
        db,
        action="escalated_manual",
        actor=current_user.audit_actor,
        thread_id=thread.id,
        detail={"reason": body.reason},
    )

    return _serialize_thread(thread)


@router.get("/{thread_id}/insight", response_model=InsightResponse)
async def get_thread_insight(
    thread_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> InsightResponse:
    """Generate or return cached AI insight (summary + translation) for a thread.

    On first call, generates via the configured insight LLM and caches the
    result in the database.  Subsequent calls return the cached result.

    This endpoint never raises 500 — it returns null fields when the LLM is
    unavailable or the insight columns have not been migrated yet.
    """
    thread = await _get_thread_or_404(db, thread_id)

    cached_summary = getattr(thread, "message_summary", None)
    if cached_summary:
        return InsightResponse(
            summary=cached_summary,
            translated_message=getattr(thread, "translated_message", None) or "",
        )

    detected_lang = thread.customer_language.value if thread.customer_language else "en"
    result = await _insight_service.generate_insight(
        customer_message=thread.customer_message,
        detected_language=detected_lang,
    )

    if result is None:
        return InsightResponse(summary=None, translated_message=None)

    try:
        thread.message_summary = result.summary
        thread.translated_message = result.translated_message
        thread.updated_at = datetime.now(UTC)
        await db.commit()
    except Exception as exc:
        logger.debug("Could not cache insight for thread %s: %s", thread_id, exc)
        await db.rollback()

    return InsightResponse(
        summary=result.summary,
        translated_message=result.translated_message,
    )


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #


async def _get_thread_or_404(
    db: AsyncSession,
    thread_id: uuid.UUID,
) -> SupportThread:
    stmt = (
        select(SupportThread)
        .options(selectinload(SupportThread.marketplace_account))
        .where(SupportThread.id == thread_id)
    )
    result = await db.execute(stmt)
    thread = result.scalar_one_or_none()
    if thread is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Support thread {thread_id} not found.",
        )
    return thread


def _serialize_thread(thread: SupportThread) -> ThreadResponse:
    marketplace_name = (
        thread.marketplace_account.marketplace
        if thread.marketplace_account is not None
        else None
    )
    extras: dict[str, str | None] = {"marketplace_name": marketplace_name}
    extras["message_summary"] = getattr(thread, "message_summary", None)
    extras["translated_message"] = getattr(thread, "translated_message", None)
    return ThreadResponse.model_validate(thread).model_copy(update=extras)
