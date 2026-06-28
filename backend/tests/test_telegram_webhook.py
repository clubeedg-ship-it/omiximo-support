"""Telegram webhook executes approved send_reply, denies, and is idempotent."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import func, select

from app.config import settings
from app.models.agent_action import ActionStatus, AgentAction
from app.models.marketplace_account import MarketplaceAccount
from app.models.support_thread import (
    ReplyState,
    SupportThread,
    ThreadStatus,
)
from app.services.encryption import encrypt


@pytest_asyncio.fixture
async def proposal(db) -> AgentAction:
    account = MarketplaceAccount(
        id=uuid.uuid4(), marketplace="MediaMarkt", shop_id="s", api_key_encrypted=encrypt("k"),
        base_url="https://x.mirakl.net", sla_hours=24, template_set="default", is_active=True,
    )
    thread = SupportThread(
        id=uuid.uuid4(), mirakl_thread_id="MT1", mirakl_order_id="O1",
        marketplace_account_id=account.id, customer_message="hi",
        operator_required=False, status=ThreadStatus.PENDING_REVIEW,
        reply_state=ReplyState.NEEDS_REPLY.value,
        response_deadline=datetime.now(UTC) + timedelta(hours=24),
    )
    action = AgentAction(
        id=uuid.uuid4(), thread_id=thread.id, action_type="send_reply",
        status=ActionStatus.PROPOSED.value, payload_json={"body": "Hallo, opgelost."},
        telegram_message_id=100,
    )
    db.add_all([account, thread, action])
    await db.flush()
    return action


def _callback(action_id, decision):
    return {"callback_query": {"id": "cb-1", "data": f"{decision}:{action_id}",
                               "from": {"id": 5, "username": "boss"}}}


def _command(text):
    first = text.split()[0]
    return {"message": {"text": text, "chat": {"id": -100},
                        "from": {"id": 5, "username": "boss"},
                        "entities": [{"type": "bot_command", "offset": 0, "length": len(first)}]}}


@pytest.mark.asyncio
async def test_wrong_secret_is_forbidden(unauthenticated_client, proposal, monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_WEBHOOK_SECRET", "right")
    resp = await unauthenticated_client.post(
        "/api/v1/telegram/webhook",
        json=_callback(proposal.id, "approve"),
        headers={"X-Telegram-Bot-Api-Secret-Token": "wrong"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_approve_sends_via_mirakl_and_marks_executed(unauthenticated_client, db, proposal, monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_WEBHOOK_SECRET", "")  # skip secret check
    send_mock = AsyncMock(return_value={})
    with patch("app.api.telegram.MiraklClient") as mock_cls:
        client = MagicMock()
        client.send_reply = send_mock
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=client)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=None)
        resp = await unauthenticated_client.post(
            "/api/v1/telegram/webhook", json=_callback(proposal.id, "approve"))
    assert resp.status_code == 200
    send_mock.assert_awaited_once()
    refreshed = await db.get(AgentAction, proposal.id)
    assert refreshed.status == ActionStatus.EXECUTED.value
    thread = await db.get(SupportThread, proposal.thread_id)
    assert thread.status == ThreadStatus.SENT_AUTO


@pytest.mark.asyncio
async def test_duplicate_approve_does_not_double_send(unauthenticated_client, db, proposal, monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_WEBHOOK_SECRET", "")
    send_mock = AsyncMock(return_value={})
    with patch("app.api.telegram.MiraklClient") as mock_cls:
        client = MagicMock()
        client.send_reply = send_mock
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=client)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=None)
        await unauthenticated_client.post("/api/v1/telegram/webhook", json=_callback(proposal.id, "approve"))
        await unauthenticated_client.post("/api/v1/telegram/webhook", json=_callback(proposal.id, "approve"))
    assert send_mock.await_count == 1


@pytest.mark.asyncio
async def test_help_command_sends_legend(unauthenticated_client, monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_WEBHOOK_SECRET", "")
    sent: list[str] = []
    with patch("app.api.telegram.TelegramService") as tg_cls:
        inst = tg_cls.return_value
        inst.send_activity = AsyncMock(side_effect=lambda t: sent.append(t))
        resp = await unauthenticated_client.post("/api/v1/telegram/webhook", json=_command("/help"))
    assert resp.status_code == 200
    assert sent and "commando" in sent[0].lower()


@pytest.mark.asyncio
async def test_status_command_reports_pending_and_flags(unauthenticated_client, proposal, monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_WEBHOOK_SECRET", "")
    sent: list[str] = []
    with patch("app.api.telegram.TelegramService") as tg_cls:
        inst = tg_cls.return_value
        inst.send_activity = AsyncMock(side_effect=lambda t: sent.append(t))
        # proposal fixture leaves one PENDING_REVIEW thread
        resp = await unauthenticated_client.post("/api/v1/telegram/webhook", json=_command("/status"))
    assert resp.status_code == 200
    assert sent and "Status" in sent[0]
    assert "1" in sent[0]  # one pending thread


@pytest.mark.asyncio
async def test_status_command_strips_bot_mention(unauthenticated_client, monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_WEBHOOK_SECRET", "")
    sent: list[str] = []
    with patch("app.api.telegram.TelegramService") as tg_cls:
        inst = tg_cls.return_value
        inst.send_activity = AsyncMock(side_effect=lambda t: sent.append(t))
        resp = await unauthenticated_client.post(
            "/api/v1/telegram/webhook", json=_command("/status@omiximo_support_bot"))
    assert resp.status_code == 200
    assert sent and "Status" in sent[0]


@pytest.mark.asyncio
async def test_plain_message_is_ignored(unauthenticated_client, monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_WEBHOOK_SECRET", "")
    resp = await unauthenticated_client.post(
        "/api/v1/telegram/webhook", json={"message": {"text": "hallo", "from": {"id": 1}}})
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_deny_marks_denied_and_does_not_send(unauthenticated_client, db, proposal, monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_WEBHOOK_SECRET", "")
    with patch("app.api.telegram.MiraklClient") as mock_cls:
        resp = await unauthenticated_client.post(
            "/api/v1/telegram/webhook", json=_callback(proposal.id, "deny"))
        assert resp.status_code == 200
        mock_cls.assert_not_called()
    refreshed = await db.get(AgentAction, proposal.id)
    assert refreshed.status == ActionStatus.DENIED.value
