"""Knowledge base retrieval and management service.

Provides CRUD operations on KnowledgeEntry and the critical `retrieve_for_draft`
method that selects relevant knowledge entries for a given thread context.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select, or_, and_, func, cast, String
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge_entry import KnowledgeEntry
from app.schemas.knowledge import KnowledgeEntryCreate, KnowledgeEntryUpdate


class KnowledgeService:
    """Service for managing and retrieving knowledge base entries."""

    async def create(
        self,
        db: AsyncSession,
        entry: KnowledgeEntryCreate,
    ) -> KnowledgeEntry:
        """Create a new knowledge entry."""
        knowledge_entry = KnowledgeEntry(
            id=uuid.uuid4(),
            entry_type=entry.entry_type,
            title=entry.title,
            content=entry.content,
            category_tags=entry.category_tags,
            marketplace_tags=entry.marketplace_tags,
            language=entry.language,
            is_active=entry.is_active,
        )
        db.add(knowledge_entry)
        await db.flush()
        return knowledge_entry

    async def get(
        self,
        db: AsyncSession,
        entry_id: uuid.UUID,
    ) -> KnowledgeEntry | None:
        """Get a knowledge entry by ID."""
        return await db.get(KnowledgeEntry, entry_id)

    async def list_entries(
        self,
        db: AsyncSession,
        *,
        category: str | None = None,
        marketplace: str | None = None,
        entry_type: str | None = None,
        is_active: bool | None = None,
        q: str | None = None,
    ) -> list[KnowledgeEntry]:
        """List knowledge entries with optional filters.

        Args:
            category: Filter to entries whose category_tags contain this value.
            marketplace: Filter to entries whose marketplace_tags contain this value.
            entry_type: Filter to entries of this type.
            is_active: Filter by active/inactive status.
            q: Free-text search against title and content.
        """
        stmt = select(KnowledgeEntry)

        if is_active is not None:
            stmt = stmt.where(KnowledgeEntry.is_active.is_(is_active))

        if entry_type is not None:
            stmt = stmt.where(KnowledgeEntry.entry_type == entry_type)

        if category is not None:
            # JSON column: filter entries that contain the category in their tags.
            # Uses cast to string + LIKE for cross-dialect compatibility.
            stmt = stmt.where(
                or_(
                    cast(KnowledgeEntry.category_tags, String).contains(f'"{category}"'),
                    cast(KnowledgeEntry.category_tags, String) == "[]",
                )
            )

        if marketplace is not None:
            stmt = stmt.where(
                or_(
                    cast(KnowledgeEntry.marketplace_tags, String).contains(
                        f'"{marketplace}"'
                    ),
                    cast(KnowledgeEntry.marketplace_tags, String) == "[]",
                )
            )

        if q is not None and q.strip():
            search_term = f"%{q.strip()}%"
            stmt = stmt.where(
                or_(
                    KnowledgeEntry.title.ilike(search_term),
                    KnowledgeEntry.content.ilike(search_term),
                )
            )

        stmt = stmt.order_by(
            KnowledgeEntry.entry_type.asc(),
            KnowledgeEntry.updated_at.desc(),
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def update(
        self,
        db: AsyncSession,
        entry_id: uuid.UUID,
        data: KnowledgeEntryUpdate,
    ) -> KnowledgeEntry | None:
        """Partially update a knowledge entry. Returns None if not found."""
        entry = await db.get(KnowledgeEntry, entry_id)
        if entry is None:
            return None

        if data.entry_type is not None:
            entry.entry_type = data.entry_type
        if data.title is not None:
            entry.title = data.title
        if data.content is not None:
            entry.content = data.content
        if data.category_tags is not None:
            entry.category_tags = data.category_tags
        if data.marketplace_tags is not None:
            entry.marketplace_tags = data.marketplace_tags
        # language can be explicitly set to None (to make entry language-agnostic)
        if "language" in data.model_fields_set:
            entry.language = data.language
        if data.is_active is not None:
            entry.is_active = data.is_active

        entry.updated_at = datetime.now(UTC)
        await db.flush()
        return entry

    async def delete(
        self,
        db: AsyncSession,
        entry_id: uuid.UUID,
    ) -> bool:
        """Soft-delete a knowledge entry (set is_active=False).

        Returns True if found and deactivated, False if not found.
        """
        entry = await db.get(KnowledgeEntry, entry_id)
        if entry is None:
            return False

        entry.is_active = False
        entry.updated_at = datetime.now(UTC)
        await db.flush()
        return True

    async def retrieve_for_draft(
        self,
        db: AsyncSession,
        *,
        category: str,
        marketplace: str,
        language: str | None = None,
        limit: int = 5,
    ) -> list[KnowledgeEntry]:
        """Retrieve relevant knowledge entries for draft generation.

        This is the primary retrieval method used by the draft pipeline. It
        selects active entries matching the thread's category, marketplace,
        and language context.

        Selection logic:
          - Only active entries
          - category_tags contains the category OR category_tags is empty (universal)
          - marketplace_tags contains the marketplace OR marketplace_tags is empty (universal)
          - language is NULL (language-agnostic) OR matches the given language
          - Ordered: marketplace-specific first, then by updated_at desc
          - Limited to N results
        """
        # Filter: active only
        stmt = select(KnowledgeEntry).where(KnowledgeEntry.is_active.is_(True))

        # Filter: category match or universal (empty list)
        stmt = stmt.where(
            or_(
                cast(KnowledgeEntry.category_tags, String).contains(f'"{category}"'),
                cast(KnowledgeEntry.category_tags, String) == "[]",
            )
        )

        # Filter: marketplace match or universal (empty list)
        stmt = stmt.where(
            or_(
                cast(KnowledgeEntry.marketplace_tags, String).contains(
                    f'"{marketplace}"'
                ),
                cast(KnowledgeEntry.marketplace_tags, String) == "[]",
            )
        )

        # Filter: language-agnostic or matching language
        if language is not None:
            stmt = stmt.where(
                or_(
                    KnowledgeEntry.language.is_(None),
                    KnowledgeEntry.language == language,
                )
            )
        else:
            stmt = stmt.where(KnowledgeEntry.language.is_(None))

        # Order: marketplace-specific entries first (non-empty marketplace_tags),
        # then by most recently updated
        # Entries with non-empty marketplace_tags are more specific and rank higher.
        stmt = stmt.order_by(
            # Entries with specific marketplace_tags sort first (0 before 1)
            (cast(KnowledgeEntry.marketplace_tags, String) == "[]").asc(),
            KnowledgeEntry.updated_at.desc(),
        )

        stmt = stmt.limit(limit)
        result = await db.execute(stmt)
        return list(result.scalars().all())


# Module-level singleton for use as a dependency
knowledge_service = KnowledgeService()
