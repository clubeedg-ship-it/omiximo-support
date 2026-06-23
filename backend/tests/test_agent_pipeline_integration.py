"""AGENT_ENABLED routes non-RED threads through the agent; collector notifies."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.config import settings
from app.models.agent_action import ActionStatus, AgentAction
from app.models.audit_log import AuditLog
from app.models.marketplace_account import MarketplaceAccount
from app.models.support_thread import (
    CustomerLanguage,
    ReplyState,
    RiskLevel,
    SupportThread,
    ThreadStatus,
)
from app.services.classifier import ClassificationResult, MessageClassifier
from app.services.draft_pipeline import DraftPipeline
from app.services.encryption import encrypt
from app.services.safety_rules import SafetyRules
from app.services.smart_draft import SmartDraftService
from app.services.template_engine import TemplateEngine


@pytest_asyncio.fixture
async def account(db) -> MarketplaceAccount:
    acc = MarketplaceAccount(
        id=uuid.uuid4(), marketplace="MediaMarkt", shop_id="shop-agent",
        api_key_encrypted=encrypt("k"), base_url="https://x.mirakl.net",
        sla_hours=24, template_set="default", is_active=True,
    )
    db.add(acc)
    await db.flush()
    return acc


@pytest_asyncio.fixture
async def thread(db, account) -> SupportThread:
    t = SupportThread(
        id=uuid.uuid4(), mirakl_thread_id="T1", mirakl_order_id="O1",
        marketplace_account_id=account.id,
        customer_message="Mijn bestelling is kapot aangekomen.",
        operator_required=False, status=ThreadStatus.PENDING_REVIEW,
        reply_state=ReplyState.NEEDS_REPLY.value,
        response_deadline=datetime.now(UTC) + timedelta(hours=24),
    )
    db.add(t)
    await db.flush()
    return t


def _pipeline_with_orange_classifier() -> DraftPipeline:
    p = DraftPipeline(
        classifier=MessageClassifier(mock_mode=True),
        template_engine=TemplateEngine(),
        safety_rules=SafetyRules(),
        smart_draft_service=SmartDraftService(mock_mode=True),
    )
    p._classifier.classify = AsyncMock(  # type: ignore[method-assign]
        return_value=ClassificationResult(
            category="complaint", risk_level=RiskLevel.ORANGE, language=CustomerLanguage.nl,
        )
    )
    return p


@pytest.mark.asyncio
async def test_agent_enabled_routes_through_agent(db, account, thread, monkeypatch):
    monkeypatch.setattr(settings, "AGENT_ENABLED", True)

    async def fake_run(self, db, *, thread, account):
        action = AgentAction(
            id=uuid.uuid4(), thread_id=thread.id, action_type="send_reply",
            status=ActionStatus.PROPOSED.value, payload_json={"body": "Hallo"},
        )
        db.add(action)
        await db.flush()
        return action

    monkeypatch.setattr("app.services.agent.runner.AgentRunner.run_for_thread", fake_run)

    pipeline = _pipeline_with_orange_classifier()
    with patch("app.services.draft_pipeline.MiraklClient") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.fetch_order = AsyncMock(return_value={})
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=None)
        await pipeline.process_new_threads(db)

    await db.refresh(thread)
    assert thread.status == ThreadStatus.PENDING_REVIEW

    actions = (await db.execute(select(AgentAction))).scalars().all()
    assert len(actions) == 1
    assert actions[0].action_type == "send_reply"

    audit_actions = set(
        (await db.execute(select(AuditLog.action))).scalars().all()
    )
    assert "agent_proposed" in audit_actions


@pytest.mark.asyncio
async def test_agent_disabled_uses_legacy_path(db, account, thread, monkeypatch):
    monkeypatch.setattr(settings, "AGENT_ENABLED", False)
    # If the agent ran, this would explode — proving the legacy path is taken.
    monkeypatch.setattr(
        "app.services.agent.runner.AgentRunner.run_for_thread",
        AsyncMock(side_effect=AssertionError("agent should not run when disabled")),
    )
    pipeline = _pipeline_with_orange_classifier()
    with patch("app.services.draft_pipeline.MiraklClient") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.fetch_order = AsyncMock(return_value={})
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=None)
        await pipeline.process_new_threads(db)

    actions = (await db.execute(select(AgentAction))).scalars().all()
    assert actions == []


@pytest.mark.asyncio
async def test_notify_new_thread_noops_without_token(db, account, thread):
    from app.services.collector import _notify_new_thread
    # No token configured -> no exception, no-op.
    await _notify_new_thread(thread, account, "Kapotte bestelling <b>x</b>")
