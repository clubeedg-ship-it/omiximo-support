"""Integration tests for DraftPipeline with mocked external dependencies."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from app.models.marketplace_account import MarketplaceAccount
from app.models.response_template import ResponseTemplate
from app.models.support_thread import (
    CustomerLanguage,
    RiskLevel,
    SupportThread,
    ThreadStatus,
)
from app.services.classifier import ClassificationResult, MessageClassifier
from app.services.draft_pipeline import DraftPipeline
from app.services.encryption import encrypt
from app.services.safety_rules import SafetyRules
from app.services.template_engine import TemplateEngine


def make_pipeline(mock_llm: bool = True) -> DraftPipeline:
    """Create a DraftPipeline with mocked classifier (no LLM calls)."""
    return DraftPipeline(
        classifier=MessageClassifier(mock_mode=mock_llm),
        template_engine=TemplateEngine(),
        safety_rules=SafetyRules(),
    )


@pytest_asyncio.fixture
async def pipeline_account(db) -> MarketplaceAccount:
    """Account fixture for pipeline tests."""
    account = MarketplaceAccount(
        id=uuid.uuid4(),
        marketplace="Boulanger",
        shop_id="shop-pipeline",
        api_key_encrypted=encrypt("pipeline-api-key"),
        base_url="https://marketplace.boulanger.fr",
        sla_hours=48,
        template_set="default",
        is_active=True,
    )
    db.add(account)
    await db.flush()
    return account


@pytest_asyncio.fixture
async def pending_thread(db, pipeline_account) -> SupportThread:
    """Unclassified PENDING_REVIEW thread for pipeline processing."""
    thread = SupportThread(
        id=uuid.uuid4(),
        mirakl_thread_id="MK-PIPELINE-001",
        mirakl_order_id="ORD-PIPELINE-001",
        marketplace_account_id=pipeline_account.id,
        customer_message="Where is my order? Tracking shows nothing.",
        operator_required=False,
        status=ThreadStatus.PENDING_REVIEW,
        response_deadline=datetime.now(UTC) + timedelta(hours=48),
    )
    db.add(thread)
    await db.flush()
    return thread


@pytest_asyncio.fixture
async def shipping_template(db) -> ResponseTemplate:
    """Global English template for tracking_update (resolved from shipping_delay)."""
    template = ResponseTemplate(
        id=uuid.uuid4(),
        marketplace_account_id=None,
        category="tracking_update",
        language="en",
        template_body=(
            "Dear {{ customer_name or 'customer' }},\n"
            "Your order {{ order_id }} is in transit. "
            "Tracking: {{ tracking_number or 'pending' }}.\n"
            "Best regards, {{ shop_name }}"
        ),
        is_active=True,
    )
    db.add(template)
    await db.flush()
    return template


class TestPipelineGreenPath:

    async def test_green_thread_gets_draft_and_sent(
        self, db, pending_thread, shipping_template, pipeline_account
    ):
        """GREEN thread with matching template gets drafted and auto-sent."""
        pipeline = make_pipeline()

        with patch(
            "app.services.draft_pipeline.MiraklClient"
        ) as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.fetch_order = AsyncMock(return_value={
                "id": "ORD-PIPELINE-001",
                "customer": {"firstname": "Marie"},
                "shipping": {"estimated_delivery_date": "2026-05-15"},
            })
            mock_client.send_reply = AsyncMock(return_value={"status": "sent"})
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            processed = await pipeline.process_new_threads(db)

        assert processed == 1
        await db.refresh(pending_thread)
        assert pending_thread.status == ThreadStatus.SENT_AUTO
        assert pending_thread.drafted_response is not None
        assert pending_thread.risk_level == RiskLevel.GREEN
        assert pending_thread.category == "shipping_delay"

    async def test_auto_send_failure_marks_thread_failed(
        self, db, pending_thread, shipping_template
    ):
        """When Mirakl send_reply raises, the thread status becomes FAILED."""
        from app.core.exceptions import MiraklAPIError
        pipeline = make_pipeline()

        with patch("app.services.draft_pipeline.MiraklClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.fetch_order = AsyncMock(return_value={})
            mock_client.send_reply = AsyncMock(
                side_effect=MiraklAPIError("Network error", status_code=503)
            )
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            await pipeline.process_new_threads(db)

        await db.refresh(pending_thread)
        assert pending_thread.status == ThreadStatus.FAILED


class TestPipelineRedPath:

    async def test_red_thread_is_escalated(self, db, pipeline_account):
        """RED classification → thread is immediately escalated, no draft."""
        thread = SupportThread(
            id=uuid.uuid4(),
            mirakl_thread_id="MK-RED-001",
            mirakl_order_id="ORD-RED-001",
            marketplace_account_id=pipeline_account.id,
            customer_message="I demand a full refund and will sue your company.",
            operator_required=False,
            status=ThreadStatus.PENDING_REVIEW,
            response_deadline=datetime.now(UTC) + timedelta(hours=24),
        )
        db.add(thread)
        await db.flush()

        pipeline = make_pipeline()

        with patch("app.services.draft_pipeline.MiraklClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.fetch_order = AsyncMock(return_value={})
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            await pipeline.process_new_threads(db)

        await db.refresh(thread)
        assert thread.status == ThreadStatus.ESCALATED
        assert thread.drafted_response is None


class TestPipelineOrangePath:

    async def test_orange_thread_stays_pending_with_draft(
        self, db, pipeline_account
    ):
        """ORANGE threads get a draft but remain PENDING_REVIEW for human approval."""
        # Create a return_request (maps to ORANGE in mock classifier)
        thread = SupportThread(
            id=uuid.uuid4(),
            mirakl_thread_id="MK-ORANGE-001",
            mirakl_order_id="ORD-ORANGE-001",
            marketplace_account_id=pipeline_account.id,
            customer_message="I want to return the item I ordered.",
            operator_required=False,
            status=ThreadStatus.PENDING_REVIEW,
            response_deadline=datetime.now(UTC) + timedelta(hours=24),
        )
        db.add(thread)

        # Create a return_inquiry template (resolved from return_request)
        return_template = ResponseTemplate(
            id=uuid.uuid4(),
            marketplace_account_id=None,
            category="return_inquiry",
            language="en",
            template_body="We have received your return request for order {{ order_id }}.",
            is_active=True,
        )
        db.add(return_template)
        await db.flush()

        pipeline = make_pipeline()

        with patch("app.services.draft_pipeline.MiraklClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.fetch_order = AsyncMock(return_value={})
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            await pipeline.process_new_threads(db)

        await db.refresh(thread)
        assert thread.status == ThreadStatus.PENDING_REVIEW
        assert thread.risk_level == RiskLevel.ORANGE
        # Draft should exist (template matched)
        assert thread.drafted_response is not None


class TestPipelineSafetyBlock:

    async def test_safety_violation_blocks_auto_send(
        self, db, pipeline_account
    ):
        """When safety rules fire, GREEN thread stays PENDING_REVIEW (not sent)."""
        thread = SupportThread(
            id=uuid.uuid4(),
            mirakl_thread_id="MK-SAFETY-001",
            mirakl_order_id="ORD-SAFETY-001",
            marketplace_account_id=pipeline_account.id,
            customer_message="Where is my order?",
            operator_required=False,
            status=ThreadStatus.PENDING_REVIEW,
            response_deadline=datetime.now(UTC) + timedelta(hours=24),
        )
        db.add(thread)

        # Template that contains a refund promise (triggers R1)
        unsafe_template = ResponseTemplate(
            id=uuid.uuid4(),
            marketplace_account_id=None,
            category="tracking_update",
            language="en",
            template_body=(
                "Your order {{ order_id }} is on its way. "
                "If not arrived in 3 days, we will refund you in full."
            ),
            is_active=True,
        )
        db.add(unsafe_template)
        await db.flush()

        pipeline = make_pipeline()

        with patch("app.services.draft_pipeline.MiraklClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.fetch_order = AsyncMock(return_value={})
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            await pipeline.process_new_threads(db)

        await db.refresh(thread)
        # Must NOT have been auto-sent due to safety violation
        assert thread.status == ThreadStatus.PENDING_REVIEW
        assert thread.risk_level == RiskLevel.GREEN


class TestPipelineTemplateMissing:

    async def test_no_matching_template_stays_pending(
        self, db, pipeline_account
    ):
        """When no template is found, thread stays PENDING_REVIEW."""
        thread = SupportThread(
            id=uuid.uuid4(),
            mirakl_thread_id="MK-NOTEMPL-001",
            mirakl_order_id="ORD-NOTEMPL-001",
            marketplace_account_id=pipeline_account.id,
            customer_message="Where is my order?",
            operator_required=False,
            status=ThreadStatus.PENDING_REVIEW,
            response_deadline=datetime.now(UTC) + timedelta(hours=24),
        )
        db.add(thread)
        await db.flush()

        pipeline = make_pipeline()

        # No templates in DB for shipping_delay/en → TemplateNotFoundError
        with patch("app.services.draft_pipeline.MiraklClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.fetch_order = AsyncMock(return_value={})
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            await pipeline.process_new_threads(db)

        await db.refresh(thread)
        assert thread.status == ThreadStatus.PENDING_REVIEW
        # Classification did happen but no draft was generated
        assert thread.risk_level is not None


class TestPipelineAlreadyClassified:

    async def test_already_classified_thread_is_skipped(
        self, db, pipeline_account, shipping_template
    ):
        """Threads with risk_level already set are not reprocessed."""
        thread = SupportThread(
            id=uuid.uuid4(),
            mirakl_thread_id="MK-DONE-001",
            mirakl_order_id="ORD-DONE-001",
            marketplace_account_id=pipeline_account.id,
            customer_message="test",
            risk_level=RiskLevel.GREEN,  # Already classified
            status=ThreadStatus.PENDING_REVIEW,
            operator_required=False,
            response_deadline=datetime.now(UTC) + timedelta(hours=24),
        )
        db.add(thread)
        await db.flush()

        pipeline = make_pipeline()
        processed = await pipeline.process_new_threads(db)
        assert processed == 0
