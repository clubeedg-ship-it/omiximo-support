"""Response template CRUD endpoints."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.marketplace_account import MarketplaceAccount
from app.models.response_template import ResponseTemplate
from app.schemas.template import (
    TemplateCreate,
    TemplateOverrideCreate,
    TemplateOverrideResponse,
    TemplateResponse,
    TemplateUpdate,
)

router = APIRouter(prefix="/templates", tags=["templates"])


@router.get("", response_model=list[TemplateResponse])
async def list_templates(
    db: Annotated[AsyncSession, Depends(get_db)],
    marketplace_account_id: uuid.UUID | None = Query(default=None),
    category: str | None = Query(default=None),
    language: str | None = Query(default=None),
    active_only: bool = Query(default=True),
) -> list[TemplateResponse]:
    """List response templates with optional filters."""
    stmt = select(ResponseTemplate)

    if marketplace_account_id is not None:
        stmt = stmt.where(
            ResponseTemplate.marketplace_account_id == marketplace_account_id
        )
    if category is not None:
        stmt = stmt.where(ResponseTemplate.category == category)
    if language is not None:
        stmt = stmt.where(ResponseTemplate.language == language)
    if active_only:
        stmt = stmt.where(ResponseTemplate.is_active.is_(True))

    stmt = stmt.order_by(
        ResponseTemplate.category.asc(),
        ResponseTemplate.language.asc(),
    )
    result = await db.execute(stmt)
    templates = result.scalars().all()
    return [TemplateResponse.model_validate(t) for t in templates]


@router.get("/{template_id}", response_model=TemplateResponse)
async def get_template(
    template_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TemplateResponse:
    """Fetch a single response template by UUID."""
    template = await _get_template_or_404(db, template_id)
    return TemplateResponse.model_validate(template)


@router.post("", response_model=TemplateResponse, status_code=status.HTTP_201_CREATED)
async def create_template(
    body: TemplateCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TemplateResponse:
    """Create a new response template.

    Templates with ``marketplace_account_id=None`` are global fallbacks
    used when no account-scoped template matches.
    """
    template = ResponseTemplate(
        id=uuid.uuid4(),
        marketplace_account_id=body.marketplace_account_id,
        category=body.category,
        language=body.language.value,
        template_body=body.template_body,
        is_active=body.is_active,
    )
    db.add(template)
    await db.flush()

    return TemplateResponse.model_validate(template)


@router.patch("/{template_id}", response_model=TemplateResponse)
async def update_template(
    template_id: uuid.UUID,
    body: TemplateUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TemplateResponse:
    """Partially update a response template.

    Updating template_body takes effect immediately for the next pipeline run.
    """
    template = await _get_template_or_404(db, template_id)

    if body.category is not None:
        template.category = body.category
    if body.language is not None:
        template.language = body.language.value
    if body.template_body is not None:
        template.template_body = body.template_body
    if body.is_active is not None:
        template.is_active = body.is_active

    template.updated_at = datetime.now(UTC)
    await db.flush()

    return TemplateResponse.model_validate(template)


@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_template(
    template_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    """Soft-delete a template by setting is_active=False.

    Hard deletes are not supported to preserve audit traceability.
    """
    template = await _get_template_or_404(db, template_id)
    template.is_active = False
    template.updated_at = datetime.now(UTC)


# --------------------------------------------------------------------------- #
# P4.3: Marketplace-specific template override endpoints                       #
# --------------------------------------------------------------------------- #


@router.post(
    "/override",
    response_model=TemplateOverrideResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a marketplace-specific template override",
)
async def create_template_override(
    body: TemplateOverrideCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TemplateOverrideResponse:
    """Create an account-scoped template override for a category + language combo.

    Validates that the marketplace account exists and that no active override
    already exists for the same (account, category, language) triple.
    """
    # Validate that the marketplace account exists
    account = await db.get(MarketplaceAccount, body.marketplace_account_id)
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Marketplace account {body.marketplace_account_id} not found.",
        )

    # Check for duplicate active override
    duplicate_stmt = select(ResponseTemplate).where(
        and_(
            ResponseTemplate.marketplace_account_id == body.marketplace_account_id,
            ResponseTemplate.category == body.category,
            ResponseTemplate.language == body.language.value,
            ResponseTemplate.is_active.is_(True),
        )
    )
    result = await db.execute(duplicate_stmt)
    existing = result.scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"An active override already exists for account "
                f"{body.marketplace_account_id}, category={body.category!r}, "
                f"language={body.language.value!r}. "
                f"Update or delete the existing override (id={existing.id}) first."
            ),
        )

    override = ResponseTemplate(
        id=uuid.uuid4(),
        marketplace_account_id=body.marketplace_account_id,
        category=body.category,
        language=body.language.value,
        template_body=body.template_body,
        is_active=True,
    )
    db.add(override)
    await db.flush()

    return TemplateOverrideResponse.model_validate(override)


@router.get(
    "/overrides/{marketplace_account_id}",
    response_model=list[TemplateOverrideResponse],
    summary="List all template overrides for a marketplace account",
)
async def list_template_overrides(
    marketplace_account_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[TemplateOverrideResponse]:
    """Return all active and inactive overrides for the given marketplace account.

    Returns an empty list (not 404) when the account has no overrides.
    """
    account = await db.get(MarketplaceAccount, marketplace_account_id)
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Marketplace account {marketplace_account_id} not found.",
        )

    stmt = (
        select(ResponseTemplate)
        .where(ResponseTemplate.marketplace_account_id == marketplace_account_id)
        .order_by(ResponseTemplate.category.asc(), ResponseTemplate.language.asc())
    )
    result = await db.execute(stmt)
    overrides = result.scalars().all()
    return [TemplateOverrideResponse.model_validate(o) for o in overrides]


@router.delete(
    "/overrides/{template_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a marketplace-specific template override",
)
async def delete_template_override(
    template_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    """Hard-delete an account-scoped template override.

    After deletion the template engine falls back to the matching global
    template (marketplace_account_id IS NULL) for the same category + language.

    Raises 404 if the template does not exist.
    Raises 400 if the template is a global template (not an account-scoped override).
    """
    override = await _get_template_or_404(db, template_id)

    if override.marketplace_account_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Template {template_id} is a global template, not an account-scoped "
                "override. Use DELETE /templates/{id} to soft-delete global templates."
            ),
        )

    await db.delete(override)
    await db.flush()


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #


async def _get_template_or_404(
    db: AsyncSession,
    template_id: uuid.UUID,
) -> ResponseTemplate:
    template = await db.get(ResponseTemplate, template_id)
    if template is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Response template {template_id} not found.",
        )
    return template
