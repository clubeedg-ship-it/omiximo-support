"""Tests for the SmartDraftService."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from app.models.marketplace_account import MarketplaceAccount
from app.models.support_thread import (
    CustomerLanguage,
    RiskLevel,
    SupportThread,
    ThreadStatus,
)
from app.services.encryption import encrypt
from app.services.smart_draft import SmartDraftResult, SmartDraftService


# --------------------------------------------------------------------------- #
# Fixtures                                                                     #
# --------------------------------------------------------------------------- #


@pytest_asyncio.fixture
async def smart_draft_account(db) -> MarketplaceAccount:
    """Account fixture for smart draft tests."""
    account = MarketplaceAccount(
        id=uuid.uuid4(),
        marketplace="MediaMarkt",
        shop_id="shop-smart-draft",
        api_key_encrypted=encrypt("smart-draft-api-key"),
        base_url="https://markt.mediamarkt.nl",
        sla_hours=24,
        template_set="default",
        is_active=True,
    )
    db.add(account)
    await db.flush()
    return account


@pytest_asyncio.fixture
async def orange_thread(db, smart_draft_account) -> SupportThread:
    """An ORANGE thread for smart draft generation."""
    thread = SupportThread(
        id=uuid.uuid4(),
        mirakl_thread_id="MK-SMART-001",
        mirakl_order_id="ORD-SMART-001",
        marketplace_account_id=smart_draft_account.id,
        customer_message="I want to return the item because it does not fit.",
        customer_language=CustomerLanguage.en,
        category="return_request",
        risk_level=RiskLevel.ORANGE,
        operator_required=False,
        status=ThreadStatus.PENDING_REVIEW,
        response_deadline=datetime.now(UTC) + timedelta(hours=24),
    )
    db.add(thread)
    await db.flush()
    return thread


@pytest_asyncio.fixture
async def approved_threads(db, smart_draft_account) -> list[SupportThread]:
    """Create some APPROVED historical threads with same category."""
    threads = []
    for i in range(3):
        t = SupportThread(
            id=uuid.uuid4(),
            mirakl_thread_id=f"MK-HIST-{i:03d}",
            mirakl_order_id=f"ORD-HIST-{i:03d}",
            marketplace_account_id=smart_draft_account.id,
            customer_message=f"I want to return item {i}.",
            customer_language=CustomerLanguage.en,
            category="return_request",
            risk_level=RiskLevel.ORANGE,
            operator_required=False,
            status=ThreadStatus.APPROVED,
            drafted_response=f"We have noted your return request for item {i}. Our team is reviewing.",
            response_deadline=datetime.now(UTC) + timedelta(hours=24),
        )
        db.add(t)
        threads.append(t)
    await db.flush()
    return threads


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #


def _make_httpx_mock(response_content: str):
    """Build a patch context manager and mock client for httpx.AsyncClient.

    The httpx.AsyncClient is used as ``async with httpx.AsyncClient(...) as client:``.
    We need to mock the constructor to return an async context manager, which
    yields a mock client whose `.post()` is async and returns a MagicMock
    response (since httpx Response methods like .json() and .is_error are sync).
    """
    # The response object: .is_error is a property (sync), .json() is sync
    mock_response = MagicMock()
    mock_response.is_error = False
    mock_response.status_code = 200
    mock_response.text = ""
    mock_response.json.return_value = {
        "choices": [{"message": {"content": response_content}}]
    }

    # The client: .post() is async
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)

    # The context manager returned by httpx.AsyncClient(...)
    mock_cm = AsyncMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_client)
    mock_cm.__aexit__ = AsyncMock(return_value=False)

    patcher = patch(
        "app.services.smart_draft.httpx.AsyncClient",
        return_value=mock_cm,
    )
    return patcher, mock_client


def _make_failing_httpx_mock():
    """Build a patch where the .post() call raises RuntimeError."""
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(side_effect=RuntimeError("LLM unavailable"))

    mock_cm = AsyncMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_client)
    mock_cm.__aexit__ = AsyncMock(return_value=False)

    patcher = patch(
        "app.services.smart_draft.httpx.AsyncClient",
        return_value=mock_cm,
    )
    return patcher


# --------------------------------------------------------------------------- #
# Tests: Mock mode                                                             #
# --------------------------------------------------------------------------- #


class TestMockMode:

    async def test_mock_mode_returns_draft(self, db, orange_thread, smart_draft_account):
        """Mock mode produces a non-empty draft."""
        service = SmartDraftService(mock_mode=True)
        result = await service.generate_draft(
            db,
            thread=orange_thread,
            order_context={"id": "ORD-SMART-001"},
            category="return_request",
            language=CustomerLanguage.en,
            account=smart_draft_account,
        )
        assert result.drafted_response is not None
        assert len(result.drafted_response) > 0
        assert "ORD-SMART-001" in result.drafted_response

    async def test_mock_mode_source_is_llm_augmented(
        self, db, orange_thread, smart_draft_account,
    ):
        """Mock mode source field is 'llm_augmented'."""
        service = SmartDraftService(mock_mode=True)
        result = await service.generate_draft(
            db,
            thread=orange_thread,
            order_context={},
            category="return_request",
            language=CustomerLanguage.en,
            account=smart_draft_account,
        )
        assert result.source == "llm_augmented"


# --------------------------------------------------------------------------- #
# Tests: Draft generation with LLM                                             #
# --------------------------------------------------------------------------- #


class TestDraftGeneration:

    async def test_generate_draft_with_no_knowledge_no_history(
        self, db, orange_thread, smart_draft_account,
    ):
        """Works with empty retrieval (no KB entries, no similar threads)."""
        service = SmartDraftService()
        patcher, mock_client = _make_httpx_mock(
            "Thank you for reaching out. We are looking into your return request."
        )

        with patcher:
            result = await service.generate_draft(
                db,
                thread=orange_thread,
                order_context={"id": "ORD-SMART-001"},
                category="return_request",
                language=CustomerLanguage.en,
                account=smart_draft_account,
            )

        assert result.drafted_response is not None
        assert "looking into your return request" in result.drafted_response
        assert result.source == "llm_augmented"
        assert result.similar_thread_count == 0

    async def test_generate_draft_fetches_similar_threads(
        self, db, orange_thread, smart_draft_account, approved_threads,
    ):
        """Verify the SQL query returns APPROVED threads with matching criteria."""
        service = SmartDraftService()
        patcher, mock_client = _make_httpx_mock(
            "We acknowledge your return request and are reviewing it."
        )

        with patcher:
            result = await service.generate_draft(
                db,
                thread=orange_thread,
                order_context={},
                category="return_request",
                language=CustomerLanguage.en,
                account=smart_draft_account,
            )

        assert result.similar_thread_count == 3
        assert result.source == "llm_augmented"

    async def test_generate_draft_excludes_current_thread(
        self, db, smart_draft_account,
    ):
        """The current thread is excluded from similar thread results."""
        # Create a thread that is APPROVED with same category
        thread = SupportThread(
            id=uuid.uuid4(),
            mirakl_thread_id="MK-SELF-001",
            mirakl_order_id="ORD-SELF-001",
            marketplace_account_id=smart_draft_account.id,
            customer_message="I want to return item.",
            customer_language=CustomerLanguage.en,
            category="return_request",
            risk_level=RiskLevel.ORANGE,
            operator_required=False,
            status=ThreadStatus.APPROVED,
            drafted_response="Some draft",
            response_deadline=datetime.now(UTC) + timedelta(hours=24),
        )
        db.add(thread)
        await db.flush()

        service = SmartDraftService()

        # Directly test the internal method
        similar = await service._fetch_similar_threads(
            db,
            category="return_request",
            marketplace_account_id=smart_draft_account.id,
            exclude_id=thread.id,
        )

        # The thread itself should NOT appear in results
        similar_ids = [t.id for t in similar]
        assert thread.id not in similar_ids


# --------------------------------------------------------------------------- #
# Tests: Fallback behavior                                                     #
# --------------------------------------------------------------------------- #


class TestFallback:

    async def test_llm_failure_returns_template_fallback(
        self, db, orange_thread, smart_draft_account,
    ):
        """When LLM fails, falls back to template_reference."""
        service = SmartDraftService()
        patcher = _make_failing_httpx_mock()

        with patcher:
            result = await service.generate_draft(
                db,
                thread=orange_thread,
                order_context={},
                category="return_request",
                language=CustomerLanguage.en,
                account=smart_draft_account,
                template_reference="We received your return request for order {{ order_id }}.",
            )

        assert result.source == "template_fallback"
        assert result.drafted_response == "We received your return request for order {{ order_id }}."

    async def test_llm_failure_with_no_template_returns_unavailable(
        self, db, orange_thread, smart_draft_account,
    ):
        """When both LLM and template fail, source is 'unavailable'."""
        service = SmartDraftService()
        patcher = _make_failing_httpx_mock()

        with patcher:
            result = await service.generate_draft(
                db,
                thread=orange_thread,
                order_context={},
                category="return_request",
                language=CustomerLanguage.en,
                account=smart_draft_account,
                template_reference=None,
            )

        assert result.source == "unavailable"
        assert result.drafted_response is None


# --------------------------------------------------------------------------- #
# Tests: Prompt construction                                                   #
# --------------------------------------------------------------------------- #


class TestPromptConstruction:

    async def test_prompt_includes_customer_message(
        self, db, orange_thread, smart_draft_account,
    ):
        """Verify customer message is passed as user content to LLM."""
        service = SmartDraftService()
        patcher, mock_client = _make_httpx_mock("Draft reply.")

        with patcher:
            await service.generate_draft(
                db,
                thread=orange_thread,
                order_context={},
                category="return_request",
                language=CustomerLanguage.en,
                account=smart_draft_account,
            )

        # Extract the payload from the post call
        call_args = mock_client.post.call_args
        payload = call_args.kwargs.get("json", {})
        messages = payload.get("messages", [])
        user_messages = [m for m in messages if m["role"] == "user"]
        assert len(user_messages) == 1
        assert orange_thread.customer_message in user_messages[0]["content"]

    async def test_prompt_includes_knowledge_entries(
        self, db, orange_thread, smart_draft_account,
    ):
        """Verify KB content appears in the system prompt."""
        service = SmartDraftService()

        # Mock a knowledge entry
        mock_kb_entry = MagicMock()
        mock_kb_entry.id = uuid.uuid4()
        mock_kb_entry.entry_type = "policy"
        mock_kb_entry.title = "Return Policy"
        mock_kb_entry.content = "Items can be returned within 30 days."

        # Monkey-patch the _fetch_knowledge method
        async def mock_fetch_knowledge(db, category, marketplace, language):
            return [mock_kb_entry]

        service._fetch_knowledge = mock_fetch_knowledge  # type: ignore[method-assign]

        patcher, mock_client = _make_httpx_mock("Draft reply.")

        with patcher:
            result = await service.generate_draft(
                db,
                thread=orange_thread,
                order_context={},
                category="return_request",
                language=CustomerLanguage.en,
                account=smart_draft_account,
            )

        # Extract the payload from the post call
        call_args = mock_client.post.call_args
        payload = call_args.kwargs.get("json", {})
        messages = payload.get("messages", [])
        system_messages = [m for m in messages if m["role"] == "system"]
        assert len(system_messages) == 1
        system_content = system_messages[0]["content"]
        assert "COMPANY KNOWLEDGE:" in system_content
        assert "Return Policy" in system_content
        assert "Items can be returned within 30 days." in system_content

        # Result should contain the KB entry ID
        assert len(result.knowledge_entry_ids) == 1
        assert str(mock_kb_entry.id) in result.knowledge_entry_ids

    async def test_prompt_includes_order_context(
        self, db, orange_thread, smart_draft_account,
    ):
        """Verify order data appears in the system prompt."""
        service = SmartDraftService()

        order_ctx = {
            "id": "ORD-SMART-001",
            "customer": {"firstname": "Jan"},
            "total_price": "49.99",
        }

        patcher, mock_client = _make_httpx_mock("Draft reply.")

        with patcher:
            await service.generate_draft(
                db,
                thread=orange_thread,
                order_context=order_ctx,
                category="return_request",
                language=CustomerLanguage.en,
                account=smart_draft_account,
            )

        # Extract the payload from the post call
        call_args = mock_client.post.call_args
        payload = call_args.kwargs.get("json", {})
        messages = payload.get("messages", [])
        system_messages = [m for m in messages if m["role"] == "system"]
        assert len(system_messages) == 1
        system_content = system_messages[0]["content"]
        assert "ORDER CONTEXT:" in system_content
        assert "ORD-SMART-001" in system_content
        assert "Jan" in system_content
