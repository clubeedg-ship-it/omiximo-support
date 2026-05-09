"""Marketplace account CRUD endpoints."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.marketplace_account import MarketplaceAccount
from app.schemas.marketplace import (
    MarketplaceAccountCreate,
    MarketplaceAccountResponse,
    MarketplaceAccountUpdate,
)
from app.services.encryption import encrypt

router = APIRouter(prefix="/marketplace-accounts", tags=["marketplace-accounts"])


@router.get("", response_model=list[MarketplaceAccountResponse])
async def list_accounts(
    db: Annotated[AsyncSession, Depends(get_db)],
    active_only: bool = True,
) -> list[MarketplaceAccountResponse]:
    """List marketplace accounts, optionally filtered to active only."""
    stmt = select(MarketplaceAccount)
    if active_only:
        stmt = stmt.where(MarketplaceAccount.is_active.is_(True))
    stmt = stmt.order_by(MarketplaceAccount.marketplace.asc())
    result = await db.execute(stmt)
    accounts = result.scalars().all()
    return [MarketplaceAccountResponse.model_validate(a) for a in accounts]


@router.get("/{account_id}", response_model=MarketplaceAccountResponse)
async def get_account(
    account_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> MarketplaceAccountResponse:
    """Fetch a single marketplace account by UUID."""
    account = await _get_account_or_404(db, account_id)
    return MarketplaceAccountResponse.model_validate(account)


@router.post("", response_model=MarketplaceAccountResponse, status_code=status.HTTP_201_CREATED)
async def create_account(
    body: MarketplaceAccountCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> MarketplaceAccountResponse:
    """Create a new marketplace account.

    If ``api_key`` is provided it is encrypted with Fernet before storage.
    When Mirakl Connect OAuth2 is used, ``api_key`` may be omitted entirely —
    authentication is handled centrally and no per-shop key is required.
    """
    encrypted_key = encrypt(body.api_key) if body.api_key else None

    account = MarketplaceAccount(
        id=uuid.uuid4(),
        marketplace=body.marketplace,
        shop_id=body.shop_id,
        api_key_encrypted=encrypted_key,
        base_url=body.base_url,
        sla_hours=body.sla_hours,
        template_set=body.template_set,
        is_active=body.is_active,
    )
    db.add(account)
    await db.flush()

    return MarketplaceAccountResponse.model_validate(account)


@router.patch("/{account_id}", response_model=MarketplaceAccountResponse)
async def update_account(
    account_id: uuid.UUID,
    body: MarketplaceAccountUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> MarketplaceAccountResponse:
    """Partially update a marketplace account.

    Only fields explicitly provided in the request body are updated.
    If ``api_key`` is included, it is re-encrypted before storage.
    """
    account = await _get_account_or_404(db, account_id)

    if body.marketplace is not None:
        account.marketplace = body.marketplace
    if body.shop_id is not None:
        account.shop_id = body.shop_id
    if body.api_key is not None:
        account.api_key_encrypted = encrypt(body.api_key)
    if body.base_url is not None:
        account.base_url = body.base_url
    if body.sla_hours is not None:
        account.sla_hours = body.sla_hours
    if body.template_set is not None:
        account.template_set = body.template_set
    if body.is_active is not None:
        account.is_active = body.is_active

    account.updated_at = datetime.now(UTC)
    await db.flush()

    return MarketplaceAccountResponse.model_validate(account)


@router.delete("/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_account(
    account_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    """Soft-delete a marketplace account by setting is_active=False.

    Hard deletes are not supported — accounts may have associated thread history.
    """
    account = await _get_account_or_404(db, account_id)
    account.is_active = False
    account.updated_at = datetime.now(UTC)


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #


async def _get_account_or_404(
    db: AsyncSession,
    account_id: uuid.UUID,
) -> MarketplaceAccount:
    account = await db.get(MarketplaceAccount, account_id)
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Marketplace account {account_id} not found.",
        )
    return account
