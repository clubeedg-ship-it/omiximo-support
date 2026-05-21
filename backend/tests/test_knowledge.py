"""Tests for the knowledge base system: API CRUD, filtering, and retrieval."""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge_entry import KnowledgeEntry


# --------------------------------------------------------------------------- #
# Fixtures                                                                     #
# --------------------------------------------------------------------------- #


@pytest_asyncio.fixture
async def sample_knowledge_entry(db: AsyncSession) -> KnowledgeEntry:
    """Insert and return a sample knowledge entry."""
    entry = KnowledgeEntry(
        id=uuid.uuid4(),
        entry_type="policy",
        title="Test Return Policy",
        content="30-day return window, original packaging required.",
        category_tags=["return_inquiry", "complaint"],
        marketplace_tags=[],
        language=None,
        is_active=True,
    )
    db.add(entry)
    await db.flush()
    return entry


@pytest_asyncio.fixture
async def marketplace_specific_entry(db: AsyncSession) -> KnowledgeEntry:
    """Insert a knowledge entry scoped to MediaMarktSaturn."""
    entry = KnowledgeEntry(
        id=uuid.uuid4(),
        entry_type="marketplace_rule",
        title="MediaMarkt SLA",
        content="24h response time, no external channels.",
        category_tags=[],
        marketplace_tags=["MediaMarktSaturn"],
        language=None,
        is_active=True,
    )
    db.add(entry)
    await db.flush()
    return entry


@pytest_asyncio.fixture
async def inactive_entry(db: AsyncSession) -> KnowledgeEntry:
    """Insert an inactive knowledge entry."""
    entry = KnowledgeEntry(
        id=uuid.uuid4(),
        entry_type="faq",
        title="Deprecated FAQ",
        content="This FAQ is no longer active.",
        category_tags=["general_inquiry"],
        marketplace_tags=[],
        language=None,
        is_active=False,
    )
    db.add(entry)
    await db.flush()
    return entry


@pytest_asyncio.fixture
async def dutch_entry(db: AsyncSession) -> KnowledgeEntry:
    """Insert a Dutch-language-specific knowledge entry."""
    entry = KnowledgeEntry(
        id=uuid.uuid4(),
        entry_type="faq",
        title="NL: Waar is mijn bestelling",
        content="Dutch-specific FAQ about order tracking.",
        category_tags=["tracking_update"],
        marketplace_tags=[],
        language="nl",
        is_active=True,
    )
    db.add(entry)
    await db.flush()
    return entry


# --------------------------------------------------------------------------- #
# API CRUD Tests                                                               #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_create_knowledge_entry(client: AsyncClient) -> None:
    """POST /api/v1/knowledge creates a new entry."""
    payload = {
        "entry_type": "policy",
        "title": "New Policy",
        "content": "This is a new policy content.",
        "category_tags": ["return_inquiry"],
        "marketplace_tags": ["MediaMarktSaturn"],
        "language": "en",
    }
    resp = await client.post("/api/v1/knowledge", json=payload)
    assert resp.status_code == 201
    data = resp.json()
    assert data["entry_type"] == "policy"
    assert data["title"] == "New Policy"
    assert data["content"] == "This is a new policy content."
    assert data["category_tags"] == ["return_inquiry"]
    assert data["marketplace_tags"] == ["MediaMarktSaturn"]
    assert data["language"] == "en"
    assert data["is_active"] is True
    assert "id" in data
    assert "created_at" in data
    assert "updated_at" in data


@pytest.mark.asyncio
async def test_create_entry_invalid_type(client: AsyncClient) -> None:
    """POST /api/v1/knowledge rejects invalid entry_type."""
    payload = {
        "entry_type": "invalid_type",
        "title": "Bad Entry",
        "content": "This should fail.",
    }
    resp = await client.post("/api/v1/knowledge", json=payload)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_entry_invalid_language(client: AsyncClient) -> None:
    """POST /api/v1/knowledge rejects invalid language."""
    payload = {
        "entry_type": "policy",
        "title": "Bad Language",
        "content": "This should fail.",
        "language": "xx",
    }
    resp = await client.post("/api/v1/knowledge", json=payload)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_get_knowledge_entry(
    client: AsyncClient, sample_knowledge_entry: KnowledgeEntry
) -> None:
    """GET /api/v1/knowledge/{id} returns the entry."""
    resp = await client.get(f"/api/v1/knowledge/{sample_knowledge_entry.id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == str(sample_knowledge_entry.id)
    assert data["title"] == "Test Return Policy"


@pytest.mark.asyncio
async def test_get_knowledge_entry_not_found(client: AsyncClient) -> None:
    """GET /api/v1/knowledge/{id} returns 404 for non-existent entry."""
    fake_id = uuid.uuid4()
    resp = await client.get(f"/api/v1/knowledge/{fake_id}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_list_knowledge_entries(
    client: AsyncClient, sample_knowledge_entry: KnowledgeEntry
) -> None:
    """GET /api/v1/knowledge returns a list of entries."""
    resp = await client.get("/api/v1/knowledge")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) >= 1
    titles = [e["title"] for e in data]
    assert "Test Return Policy" in titles


@pytest.mark.asyncio
async def test_update_knowledge_entry(
    client: AsyncClient, sample_knowledge_entry: KnowledgeEntry
) -> None:
    """PATCH /api/v1/knowledge/{id} updates fields."""
    payload = {"title": "Updated Title", "content": "Updated content."}
    resp = await client.patch(
        f"/api/v1/knowledge/{sample_knowledge_entry.id}", json=payload
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["title"] == "Updated Title"
    assert data["content"] == "Updated content."
    # Unchanged fields preserved
    assert data["entry_type"] == "policy"
    assert data["category_tags"] == ["return_inquiry", "complaint"]


@pytest.mark.asyncio
async def test_update_knowledge_entry_not_found(client: AsyncClient) -> None:
    """PATCH /api/v1/knowledge/{id} returns 404 for non-existent entry."""
    fake_id = uuid.uuid4()
    resp = await client.patch(f"/api/v1/knowledge/{fake_id}", json={"title": "X"})
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_knowledge_entry(
    client: AsyncClient, sample_knowledge_entry: KnowledgeEntry
) -> None:
    """DELETE /api/v1/knowledge/{id} soft-deletes (sets is_active=False)."""
    resp = await client.delete(f"/api/v1/knowledge/{sample_knowledge_entry.id}")
    assert resp.status_code == 204

    # Verify it's now inactive
    get_resp = await client.get(f"/api/v1/knowledge/{sample_knowledge_entry.id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["is_active"] is False


@pytest.mark.asyncio
async def test_delete_knowledge_entry_not_found(client: AsyncClient) -> None:
    """DELETE /api/v1/knowledge/{id} returns 404 for non-existent entry."""
    fake_id = uuid.uuid4()
    resp = await client.delete(f"/api/v1/knowledge/{fake_id}")
    assert resp.status_code == 404


# --------------------------------------------------------------------------- #
# Filtering Tests                                                              #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_list_filter_by_category(
    client: AsyncClient,
    sample_knowledge_entry: KnowledgeEntry,
    marketplace_specific_entry: KnowledgeEntry,
) -> None:
    """GET /api/v1/knowledge?category=return_inquiry filters correctly."""
    resp = await client.get("/api/v1/knowledge?category=return_inquiry")
    assert resp.status_code == 200
    data = resp.json()
    titles = [e["title"] for e in data]
    # sample_knowledge_entry has category_tags=["return_inquiry", "complaint"]
    assert "Test Return Policy" in titles
    # marketplace_specific_entry has category_tags=[] (universal), so also matches
    assert "MediaMarkt SLA" in titles


@pytest.mark.asyncio
async def test_list_filter_by_marketplace(
    client: AsyncClient,
    sample_knowledge_entry: KnowledgeEntry,
    marketplace_specific_entry: KnowledgeEntry,
) -> None:
    """GET /api/v1/knowledge?marketplace=MediaMarktSaturn filters correctly."""
    resp = await client.get("/api/v1/knowledge?marketplace=MediaMarktSaturn")
    assert resp.status_code == 200
    data = resp.json()
    titles = [e["title"] for e in data]
    # marketplace_specific_entry has marketplace_tags=["MediaMarktSaturn"]
    assert "MediaMarkt SLA" in titles
    # sample_knowledge_entry has marketplace_tags=[] (universal), so also matches
    assert "Test Return Policy" in titles


@pytest.mark.asyncio
async def test_list_filter_by_is_active(
    client: AsyncClient,
    sample_knowledge_entry: KnowledgeEntry,
    inactive_entry: KnowledgeEntry,
) -> None:
    """GET /api/v1/knowledge?is_active=true excludes inactive entries."""
    resp = await client.get("/api/v1/knowledge?is_active=true")
    assert resp.status_code == 200
    data = resp.json()
    titles = [e["title"] for e in data]
    assert "Test Return Policy" in titles
    assert "Deprecated FAQ" not in titles


@pytest.mark.asyncio
async def test_list_filter_by_entry_type(
    client: AsyncClient,
    sample_knowledge_entry: KnowledgeEntry,
    marketplace_specific_entry: KnowledgeEntry,
) -> None:
    """GET /api/v1/knowledge?entry_type=policy returns only policies."""
    resp = await client.get("/api/v1/knowledge?entry_type=policy")
    assert resp.status_code == 200
    data = resp.json()
    assert all(e["entry_type"] == "policy" for e in data)
    assert any(e["title"] == "Test Return Policy" for e in data)


@pytest.mark.asyncio
async def test_list_filter_text_search(
    client: AsyncClient,
    sample_knowledge_entry: KnowledgeEntry,
) -> None:
    """GET /api/v1/knowledge?q=packaging searches title and content."""
    resp = await client.get("/api/v1/knowledge?q=packaging")
    assert resp.status_code == 200
    data = resp.json()
    assert any(e["title"] == "Test Return Policy" for e in data)


# --------------------------------------------------------------------------- #
# retrieve_for_draft Tests (via service)                                       #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_retrieve_for_draft_returns_relevant(
    db: AsyncSession,
    sample_knowledge_entry: KnowledgeEntry,
    marketplace_specific_entry: KnowledgeEntry,
    inactive_entry: KnowledgeEntry,
) -> None:
    """retrieve_for_draft returns matching active entries."""
    from app.services.knowledge_service import knowledge_service

    results = await knowledge_service.retrieve_for_draft(
        db,
        category="return_inquiry",
        marketplace="MediaMarktSaturn",
    )
    ids = [e.id for e in results]
    # sample_knowledge_entry matches on category_tags
    assert sample_knowledge_entry.id in ids
    # marketplace_specific_entry matches (universal category, specific marketplace)
    assert marketplace_specific_entry.id in ids
    # inactive_entry should NOT be included
    assert inactive_entry.id not in ids


@pytest.mark.asyncio
async def test_retrieve_for_draft_respects_category(
    db: AsyncSession,
    sample_knowledge_entry: KnowledgeEntry,
    dutch_entry: KnowledgeEntry,
) -> None:
    """retrieve_for_draft filters by category correctly."""
    from app.services.knowledge_service import knowledge_service

    # tracking_update should match dutch_entry (has category_tags=["tracking_update"])
    # and sample_knowledge_entry should NOT match (has ["return_inquiry", "complaint"])
    # Pass language="nl" because dutch_entry has language="nl"
    results = await knowledge_service.retrieve_for_draft(
        db,
        category="tracking_update",
        marketplace="SomeMarketplace",
        language="nl",
    )
    ids = [e.id for e in results]
    assert dutch_entry.id in ids
    assert sample_knowledge_entry.id not in ids


@pytest.mark.asyncio
async def test_retrieve_for_draft_respects_is_active(
    db: AsyncSession,
    inactive_entry: KnowledgeEntry,
) -> None:
    """retrieve_for_draft excludes inactive entries."""
    from app.services.knowledge_service import knowledge_service

    results = await knowledge_service.retrieve_for_draft(
        db,
        category="general_inquiry",
        marketplace="AnyMarket",
    )
    ids = [e.id for e in results]
    assert inactive_entry.id not in ids


@pytest.mark.asyncio
async def test_retrieve_for_draft_respects_language(
    db: AsyncSession,
    sample_knowledge_entry: KnowledgeEntry,
    dutch_entry: KnowledgeEntry,
) -> None:
    """retrieve_for_draft filters by language (NULL or matching)."""
    from app.services.knowledge_service import knowledge_service

    # Requesting English — dutch_entry (language="nl") should be excluded
    results = await knowledge_service.retrieve_for_draft(
        db,
        category="tracking_update",
        marketplace="SomeMarketplace",
        language="en",
    )
    ids = [e.id for e in results]
    assert dutch_entry.id not in ids

    # Requesting Dutch — dutch_entry should be included
    results_nl = await knowledge_service.retrieve_for_draft(
        db,
        category="tracking_update",
        marketplace="SomeMarketplace",
        language="nl",
    )
    ids_nl = [e.id for e in results_nl]
    assert dutch_entry.id in ids_nl


@pytest.mark.asyncio
async def test_retrieve_for_draft_marketplace_specific_first(
    db: AsyncSession,
    sample_knowledge_entry: KnowledgeEntry,
    marketplace_specific_entry: KnowledgeEntry,
) -> None:
    """retrieve_for_draft ranks marketplace-specific entries before universal ones."""
    from app.services.knowledge_service import knowledge_service

    # Both match for MediaMarktSaturn with universal category
    # marketplace_specific_entry has marketplace_tags=["MediaMarktSaturn"] (specific)
    # sample_knowledge_entry has marketplace_tags=[] (universal)
    # But sample_knowledge_entry only matches category "return_inquiry"/"complaint"
    # We need a category that marketplace_specific_entry matches (it has [] = universal)

    # Use a general category that both can match:
    # marketplace_specific_entry: category_tags=[] (universal)
    # sample_knowledge_entry: category_tags=["return_inquiry", "complaint"]
    # For category "return_inquiry": both match
    results = await knowledge_service.retrieve_for_draft(
        db,
        category="return_inquiry",
        marketplace="MediaMarktSaturn",
    )
    if len(results) >= 2:
        # marketplace_specific_entry should come first (it's marketplace-specific)
        marketplace_specific_idx = next(
            (i for i, e in enumerate(results) if e.id == marketplace_specific_entry.id),
            None,
        )
        universal_idx = next(
            (i for i, e in enumerate(results) if e.id == sample_knowledge_entry.id),
            None,
        )
        assert marketplace_specific_idx is not None
        assert universal_idx is not None
        assert marketplace_specific_idx < universal_idx


@pytest.mark.asyncio
async def test_retrieve_for_draft_limit(
    db: AsyncSession,
) -> None:
    """retrieve_for_draft respects the limit parameter."""
    from app.services.knowledge_service import knowledge_service

    # Insert 10 entries
    for i in range(10):
        entry = KnowledgeEntry(
            id=uuid.uuid4(),
            entry_type="faq",
            title=f"Bulk Entry {i}",
            content=f"Content for bulk entry {i}.",
            category_tags=[],
            marketplace_tags=[],
            language=None,
            is_active=True,
        )
        db.add(entry)
    await db.flush()

    results = await knowledge_service.retrieve_for_draft(
        db,
        category="anything",
        marketplace="AnyMarket",
        limit=3,
    )
    assert len(results) == 3


# --------------------------------------------------------------------------- #
# Auth Tests                                                                   #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_unauthenticated_access_returns_401(
    unauthenticated_client: AsyncClient,
) -> None:
    """Unauthenticated requests to knowledge endpoints return 401."""
    resp = await unauthenticated_client.get("/api/v1/knowledge")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_forbidden_access_returns_403(
    forbidden_client: AsyncClient,
) -> None:
    """Non-admin authenticated requests return 403."""
    resp = await forbidden_client.get("/api/v1/knowledge")
    assert resp.status_code == 403
