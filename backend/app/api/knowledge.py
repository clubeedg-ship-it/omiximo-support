"""Knowledge base CRUD endpoints."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas.knowledge import (
    KnowledgeEntryCreate,
    KnowledgeEntryResponse,
    KnowledgeEntryUpdate,
)
from app.services.knowledge_service import knowledge_service

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


@router.get("", response_model=list[KnowledgeEntryResponse])
async def list_knowledge_entries(
    db: Annotated[AsyncSession, Depends(get_db)],
    category: str | None = Query(default=None, description="Filter by category tag"),
    marketplace: str | None = Query(
        default=None, description="Filter by marketplace tag"
    ),
    entry_type: str | None = Query(default=None, description="Filter by entry type"),
    is_active: bool | None = Query(default=None, description="Filter by active status"),
    q: str | None = Query(default=None, description="Free-text search in title/content"),
) -> list[KnowledgeEntryResponse]:
    """List knowledge entries with optional filters."""
    entries = await knowledge_service.list_entries(
        db,
        category=category,
        marketplace=marketplace,
        entry_type=entry_type,
        is_active=is_active,
        q=q,
    )
    return [KnowledgeEntryResponse.model_validate(e) for e in entries]


@router.post(
    "", response_model=KnowledgeEntryResponse, status_code=status.HTTP_201_CREATED
)
async def create_knowledge_entry(
    body: KnowledgeEntryCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> KnowledgeEntryResponse:
    """Create a new knowledge base entry."""
    entry = await knowledge_service.create(db, body)
    return KnowledgeEntryResponse.model_validate(entry)


@router.get("/{entry_id}", response_model=KnowledgeEntryResponse)
async def get_knowledge_entry(
    entry_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> KnowledgeEntryResponse:
    """Fetch a single knowledge entry by UUID."""
    entry = await knowledge_service.get(db, entry_id)
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Knowledge entry {entry_id} not found.",
        )
    return KnowledgeEntryResponse.model_validate(entry)


@router.patch("/{entry_id}", response_model=KnowledgeEntryResponse)
async def update_knowledge_entry(
    entry_id: uuid.UUID,
    body: KnowledgeEntryUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> KnowledgeEntryResponse:
    """Partially update a knowledge entry."""
    entry = await knowledge_service.update(db, entry_id, body)
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Knowledge entry {entry_id} not found.",
        )
    return KnowledgeEntryResponse.model_validate(entry)


@router.delete("/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_knowledge_entry(
    entry_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    """Soft-delete a knowledge entry by setting is_active=False."""
    deleted = await knowledge_service.delete(db, entry_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Knowledge entry {entry_id} not found.",
        )
