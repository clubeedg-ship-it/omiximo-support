"""Classification flag endpoints (P4.4).

Allows human reviewers to flag threads where the LLM classifier produced
wrong results, track those flags, and resolve them — optionally applying the
correction back to the original thread.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.classification_flag import ClassificationFlag
from app.models.support_thread import CustomerLanguage, RiskLevel, SupportThread
from app.schemas.classification import (
    ClassificationFlagListResponse,
    ClassificationFlagResponse,
    FlagResolveRequest,
    MisclassificationFlagRequest,
)
from app.services.audit import write_audit_log

router = APIRouter(tags=["classification"])


# --------------------------------------------------------------------------- #
# Flag a thread as misclassified                                               #
# --------------------------------------------------------------------------- #


@router.post(
    "/threads/{thread_id}/flag-misclassification",
    response_model=ClassificationFlagResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Flag a thread as misclassified",
)
async def flag_misclassification(
    thread_id: uuid.UUID,
    body: MisclassificationFlagRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ClassificationFlagResponse:
    """Submit a misclassification flag for a support thread.

    Records the current (wrong) classification and the proposed corrections.
    Also writes an audit_log row with action "misclassification_flagged".
    """
    thread = await db.get(SupportThread, thread_id)
    if thread is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Support thread {thread_id} not found.",
        )

    flag = ClassificationFlag(
        id=uuid.uuid4(),
        thread_id=thread_id,
        # Snapshot the current (disputed) classification
        original_category=thread.category,
        original_risk_level=thread.risk_level.value if thread.risk_level else None,
        original_language=thread.customer_language.value if thread.customer_language else None,
        # Proposed corrections
        correct_category=body.correct_category,
        correct_risk_level=body.correct_risk_level.value,
        correct_language=body.correct_language.value,
        reason=body.reason,
        actor=body.actor,
    )
    db.add(flag)
    await db.flush()

    await write_audit_log(
        db,
        action="misclassification_flagged",
        actor=body.actor,
        thread_id=thread_id,
        detail={
            "flag_id": str(flag.id),
            "original_category": flag.original_category,
            "original_risk_level": flag.original_risk_level,
            "original_language": flag.original_language,
            "correct_category": flag.correct_category,
            "correct_risk_level": flag.correct_risk_level,
            "correct_language": flag.correct_language,
            "reason": body.reason,
        },
    )

    return ClassificationFlagResponse.model_validate(flag)


# --------------------------------------------------------------------------- #
# List flags                                                                   #
# --------------------------------------------------------------------------- #


@router.get(
    "/classification/flags",
    response_model=ClassificationFlagListResponse,
    summary="List misclassification flags",
)
async def list_classification_flags(
    db: Annotated[AsyncSession, Depends(get_db)],
    reviewed: bool | None = Query(
        default=None,
        description=(
            "Filter by review state. "
            "true = only resolved flags; false = only pending flags; "
            "omit to return all."
        ),
    ),
    page: int = Query(default=1, ge=1, description="1-based page number"),
    page_size: int = Query(default=20, ge=1, le=100, description="Items per page"),
) -> ClassificationFlagListResponse:
    """Return a paginated list of classification flags.

    Use the ``reviewed`` query parameter to filter by resolution state:
    - ``reviewed=false`` — only unresolved flags (resolution IS NULL)
    - ``reviewed=true``  — only resolved flags (resolution IS NOT NULL)
    - omit              — return all flags regardless of state
    """
    stmt = select(ClassificationFlag)
    count_stmt = select(func.count()).select_from(ClassificationFlag)

    if reviewed is False:
        stmt = stmt.where(ClassificationFlag.resolution.is_(None))
        count_stmt = count_stmt.where(ClassificationFlag.resolution.is_(None))
    elif reviewed is True:
        stmt = stmt.where(ClassificationFlag.resolution.is_not(None))
        count_stmt = count_stmt.where(ClassificationFlag.resolution.is_not(None))

    total_result = await db.execute(count_stmt)
    total = total_result.scalar_one()

    offset = (page - 1) * page_size
    stmt = (
        stmt
        .order_by(ClassificationFlag.created_at.desc())
        .offset(offset)
        .limit(page_size)
    )

    result = await db.execute(stmt)
    flags = result.scalars().all()

    return ClassificationFlagListResponse(
        items=[ClassificationFlagResponse.model_validate(f) for f in flags],
        total=total,
        page=page,
        page_size=page_size,
    )


# --------------------------------------------------------------------------- #
# Resolve a flag                                                               #
# --------------------------------------------------------------------------- #


@router.put(
    "/classification/flags/{flag_id}/resolve",
    response_model=ClassificationFlagResponse,
    summary="Resolve a misclassification flag",
)
async def resolve_classification_flag(
    flag_id: uuid.UUID,
    body: FlagResolveRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ClassificationFlagResponse:
    """Accept or reject a misclassification flag.

    When **accepted**, the original thread's category, risk_level, and
    customer_language are updated to the proposed correct values.

    When **rejected**, the original thread is left unchanged.

    In both cases an audit_log row with action "misclassification_resolved"
    is written.
    """
    flag = await db.get(ClassificationFlag, flag_id)
    if flag is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Classification flag {flag_id} not found.",
        )

    if flag.resolution is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Flag {flag_id} has already been resolved "
                f"(resolution={flag.resolution!r})."
            ),
        )

    now = datetime.now(UTC)
    flag.resolution = body.resolution
    flag.resolved_by = body.actor
    flag.resolved_at = now

    if body.resolution == "accepted":
        thread = await db.get(SupportThread, flag.thread_id)
        if thread is not None:
            thread.category = flag.correct_category
            thread.risk_level = RiskLevel(flag.correct_risk_level)
            thread.customer_language = CustomerLanguage(flag.correct_language)
            thread.updated_at = now

    await db.flush()

    await write_audit_log(
        db,
        action="misclassification_resolved",
        actor=body.actor,
        thread_id=flag.thread_id,
        detail={
            "flag_id": str(flag_id),
            "resolution": body.resolution,
            "correct_category": flag.correct_category,
            "correct_risk_level": flag.correct_risk_level,
            "correct_language": flag.correct_language,
        },
    )

    return ClassificationFlagResponse.model_validate(flag)
