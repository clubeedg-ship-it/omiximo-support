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
from app.models.support_thread import RiskLevel, SupportThread, ThreadStatus
from app.models.thread_message import MessageDirection, MessageAuthorType, ThreadMessage
from app.schemas.thread import (
    InsightResponse,
    ThreadApproveRequest,
    ThreadEscalateRequest,
    ThreadListResponse,
    ThreadMessageResponse,
    ThreadResponse,
    TranslateDraftRequest,
    TranslateDraftResponse,
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
    thread = await _get_thread_or_404(db, thread_id, load_messages=True)
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

    # Record the sent response as an outbound ThreadMessage
    next_seq = thread.message_count + 1
    outbound_msg = ThreadMessage(
        id=uuid.uuid4(),
        thread_id=thread.id,
        direction=MessageDirection.OUTBOUND.value,
        author_type=MessageAuthorType.SHOP_USER.value,
        body=effective_response,
        sequence_number=next_seq,
    )
    db.add(outbound_msg)
    thread.message_count = next_seq

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


@router.post("/{thread_id}/reprocess", response_model=ThreadResponse)
async def reprocess_thread(
    thread_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[CurrentUser, Depends(require_admin_user)],
) -> ThreadResponse:
    """Reprocess a failed or escalated thread.

    Resets the thread to PENDING_REVIEW with cleared classification and insight
    data, allowing it to re-enter the automation pipeline. This operation is
    idempotent: calling it multiple times on the same FAILED/ESCALATED thread
    produces the same result.

    Returns 409 if the thread has already been sent (APPROVED or SENT_AUTO),
    since those outcomes cannot be reversed.
    """
    thread = await _get_thread_or_404(db, thread_id)

    if thread.status in (ThreadStatus.APPROVED, ThreadStatus.SENT_AUTO):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Thread is in status {thread.status!r} and has already been sent. "
                "Sent threads cannot be reprocessed."
            ),
        )

    if thread.status not in (ThreadStatus.FAILED, ThreadStatus.ESCALATED):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Thread is in status {thread.status!r}. "
                "Only FAILED or ESCALATED threads can be reprocessed."
            ),
        )

    previous_status = thread.status.value

    # Reset classification and draft fields
    thread.status = ThreadStatus.PENDING_REVIEW
    thread.risk_level = None
    thread.category = None
    thread.drafted_response = None

    # Clear insight cache
    thread.message_summary = None
    thread.translated_message = None
    thread.draft_summary = None
    thread.draft_translated = None

    thread.updated_at = datetime.now(UTC)

    await write_audit_log(
        db,
        action="reprocess_initiated",
        actor=current_user.audit_actor,
        thread_id=thread.id,
        detail={"previous_status": previous_status},
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


@router.get("/{thread_id}/draft-insight", response_model=InsightResponse)
async def get_draft_insight(
    thread_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> InsightResponse:
    """Summarize and translate the drafted response for a thread.

    Caches the result in the database. The cache is invalidated when the
    drafted_response changes (e.g. via translate-draft apply). Returns
    null fields when no draft exists or the LLM is unavailable.
    """
    thread = await _get_thread_or_404(db, thread_id)

    if not thread.drafted_response:
        return InsightResponse(summary=None, translated_message=None)

    cached_summary = getattr(thread, "draft_summary", None)
    if cached_summary:
        return InsightResponse(
            summary=cached_summary,
            translated_message=getattr(thread, "draft_translated", None) or "",
        )

    detected_lang = thread.customer_language.value if thread.customer_language else "en"
    result = await _insight_service.summarize_draft(
        drafted_response=thread.drafted_response,
        detected_language=detected_lang,
    )

    if result is None:
        return InsightResponse(summary=None, translated_message=None)

    try:
        thread.draft_summary = result.summary
        thread.draft_translated = result.translated_message
        thread.updated_at = datetime.now(UTC)
        await db.commit()
    except Exception as exc:
        logger.debug("Could not cache draft insight for thread %s: %s", thread_id, exc)
        await db.rollback()

    return InsightResponse(
        summary=result.summary,
        translated_message=result.translated_message,
    )


@router.post("/{thread_id}/translate-draft", response_model=TranslateDraftResponse)
async def translate_draft(
    thread_id: uuid.UUID,
    body: TranslateDraftRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[CurrentUser, Depends(require_admin_user)],
) -> TranslateDraftResponse:
    """Translate an English draft into the customer's target language.

    Performs a two-step translate-then-verify pass so that the LLM checks
    its own output and corrects any accuracy issues before returning the
    result. The caller supplies the English source text and the desired
    target language.

    Returns null ``translated_text`` when the LLM is unavailable. Requesting
    a translation into English is rejected with 400 because back-translation
    verification is not applicable.
    """
    thread = await _get_thread_or_404(db, thread_id)

    if body.target_language.value == "en":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Back-translation verification is not applicable for English targets.",
        )

    result = await _insight_service.translate_draft(
        english_text=body.english_text,
        target_language=body.target_language.value,
    )

    await write_audit_log(
        db,
        action="draft_translation_requested",
        actor=current_user.audit_actor,
        thread_id=thread.id,
        detail={
            "target_language": body.target_language.value,
            "source_length": len(body.english_text),
            "translation_succeeded": result is not None,
        },
    )

    if result is None:
        return TranslateDraftResponse()

    try:
        thread.draft_summary = None
        thread.draft_translated = None
        await db.commit()
    except Exception:
        await db.rollback()

    return TranslateDraftResponse(
        translated_text=result.translated_text,
        correction_made=result.correction_made,
        correction_note=result.correction_note,
    )


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #


async def _get_thread_or_404(
    db: AsyncSession,
    thread_id: uuid.UUID,
    *,
    load_messages: bool = False,
) -> SupportThread:
    stmt = (
        select(SupportThread)
        .options(selectinload(SupportThread.marketplace_account))
        .where(SupportThread.id == thread_id)
    )
    if load_messages:
        stmt = stmt.options(selectinload(SupportThread.messages))
    result = await db.execute(stmt)
    thread = result.scalar_one_or_none()
    if thread is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Support thread {thread_id} not found.",
        )
    return thread


def _serialize_thread(thread: SupportThread) -> ThreadResponse:
    from sqlalchemy import inspect as sa_inspect

    marketplace_name = (
        thread.marketplace_account.marketplace
        if thread.marketplace_account is not None
        else None
    )

    # Include messages only when the relationship has been eagerly loaded.
    # Check via SQLAlchemy's instance state to avoid triggering a lazy load.
    state = sa_inspect(thread)
    messages_loaded = "messages" not in state.unloaded
    if messages_loaded:
        messages = [
            ThreadMessageResponse.model_validate(m) for m in thread.messages
        ]
    else:
        messages = []

    # Build the response bypassing Pydantic's from_attributes for the messages
    # field, which would trigger a lazy load in async context.
    return ThreadResponse(
        id=thread.id,
        mirakl_thread_id=thread.mirakl_thread_id,
        mirakl_order_id=thread.mirakl_order_id,
        marketplace_account_id=thread.marketplace_account_id,
        marketplace_name=marketplace_name,
        customer_language=thread.customer_language,
        category=thread.category,
        risk_level=thread.risk_level,
        status=thread.status,
        operator_required=thread.operator_required,
        customer_message=thread.customer_message,
        message_summary=getattr(thread, "message_summary", None),
        translated_message=getattr(thread, "translated_message", None),
        drafted_response=thread.drafted_response,
        tracking_status=thread.tracking_status,
        invoice_status=thread.invoice_status,
        response_deadline=thread.response_deadline,
        created_at=thread.created_at,
        updated_at=thread.updated_at,
        message_count=thread.message_count,
        messages=messages,
    )
