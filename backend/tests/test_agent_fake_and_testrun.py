"""Fake-Mirakl tools + /agent/test-run endpoint."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio

from app.config import settings
from app.models.agent_action import AgentAction
from app.models.marketplace_account import MarketplaceAccount
from app.models.support_thread import (
    ReplyState,
    SupportThread,
    ThreadStatus,
)
from app.services.agent.runner import AgentRunner
from app.services.agent.tools import ToolContext, execute_tool
from app.services.encryption import encrypt


@pytest_asyncio.fixture
async def active_account(db) -> MarketplaceAccount:
    acc = MarketplaceAccount(
        id=uuid.uuid4(), marketplace="MediaMarktSaturn", shop_id="3102",
        api_key_encrypted=encrypt("k"), base_url="https://x.mirakl.net",
        sla_hours=24, template_set="default", is_active=True,
    )
    db.add(acc)
    await db.flush()
    return acc


@pytest.mark.asyncio
async def test_fake_get_order_returns_fixture(db, active_account, monkeypatch):
    monkeypatch.setattr(settings, "AGENT_FAKE_MIRAKL", True)
    thread = SupportThread(
        id=uuid.uuid4(), mirakl_thread_id="T", mirakl_order_id="FAKE-1002",
        marketplace_account_id=active_account.id, customer_message="kapot",
        operator_required=False, status=ThreadStatus.PENDING_REVIEW,
        reply_state=ReplyState.NEEDS_REPLY.value,
        response_deadline=datetime.now(UTC) + timedelta(hours=24),
    )
    db.add(thread)
    await db.flush()

    class Tg:
        enabled = False

    out = await execute_tool(
        ToolContext(db=db, thread=thread, account=active_account, telegram=Tg()),
        "get_order", {},
    )
    assert out["order_id"] == "FAKE-1002"
    assert out["status"] == "DELIVERED"


@pytest.mark.asyncio
async def test_test_run_forbidden_when_fake_disabled(unauthenticated_client, monkeypatch):
    monkeypatch.setattr(settings, "AGENT_FAKE_MIRAKL", False)
    resp = await unauthenticated_client.post("/api/v1/agent/test-run", json={})
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_test_run_creates_thread_and_proposal(unauthenticated_client, db, active_account, monkeypatch):
    monkeypatch.setattr(settings, "AGENT_FAKE_MIRAKL", True)

    async def fake_chat(self, messages, tools):
        return {"choices": [{"message": {"role": "assistant",
                                         "content": "Hallo, wij lossen dit voor u op."}}]}

    monkeypatch.setattr(AgentRunner, "_chat", fake_chat)

    resp = await unauthenticated_client.post(
        "/api/v1/agent/test-run", json={"scenario": "broken_item"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["scenario"] == "broken_item"
    assert body["action_id"] is not None

    action = await db.get(AgentAction, uuid.UUID(body["action_id"]))
    assert action is not None
    assert action.action_type == "send_reply"
