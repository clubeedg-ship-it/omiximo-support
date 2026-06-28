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
from app.models.telegram_session import TelegramSession
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
async def test_edit_flow_updates_draft_and_rerenders(unauthenticated_client, db, proposal, monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_WEBHOOK_SECRET", "")
    with patch("app.api.telegram.TelegramService") as tg_cls:
        inst = tg_cls.return_value
        inst.answer_callback = AsyncMock()
        inst.prompt_reply = AsyncMock(return_value=555)
        inst.edit_card = AsyncMock()

        # 1. operator taps ✏️ Edit → force-reply prompt + session recorded
        r1 = await unauthenticated_client.post(
            "/api/v1/telegram/webhook",
            json={
                "callback_query": {
                    "id": "cb-9",
                    "data": f"edit:{proposal.id}",
                    "from": {"id": 5, "username": "boss"},
                    "message": {"chat": {"id": -100}},
                }
            },
        )
        assert r1.status_code == 200
        inst.prompt_reply.assert_awaited_once()
        sessions = (await db.execute(select(TelegramSession))).scalars().all()
        assert len(sessions) == 1 and sessions[0].prompt_message_id == 555

        # 2. operator replies to the prompt with corrected text
        r2 = await unauthenticated_client.post(
            "/api/v1/telegram/webhook",
            json={
                "message": {
                    "text": "Gecorrigeerde reactie.",
                    "reply_to_message": {"message_id": 555},
                    "from": {"id": 5, "username": "boss"},
                }
            },
        )
        assert r2.status_code == 200

    refreshed = await db.get(AgentAction, proposal.id)
    assert refreshed.payload_json["body"] == "Gecorrigeerde reactie."
    assert refreshed.payload_json["edited_by"] == "boss"
    inst.edit_card.assert_awaited()
    assert (await db.execute(select(TelegramSession))).scalars().all() == []


@pytest.mark.asyncio
async def test_translate_flow_shows_picker_then_translation(unauthenticated_client, db, proposal, monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_WEBHOOK_SECRET", "")
    with patch("app.api.telegram.TelegramService") as tg_cls, patch(
        "app.api.telegram.MessageInsightService"
    ) as mi_cls:
        inst = tg_cls.return_value
        inst.answer_callback = AsyncMock()
        inst.edit_card = AsyncMock()
        mi_cls.return_value.translate_to = AsyncMock(return_value="Where is my parcel?")

        # 1. tap 🌐 Translate → language picker
        r1 = await unauthenticated_client.post(
            "/api/v1/telegram/webhook",
            json={"callback_query": {"id": "c1", "data": f"tr:{proposal.id}",
                                     "from": {"id": 5}, "message": {"chat": {"id": -1}}}},
        )
        assert r1.status_code == 200
        picker = inst.edit_card.call_args.kwargs["reply_markup"]
        picker_datas = [b["callback_data"] for row in picker["inline_keyboard"] for b in row]
        assert f"trset:{proposal.id}:en" in picker_datas

        # 2. pick English → translated view
        r2 = await unauthenticated_client.post(
            "/api/v1/telegram/webhook",
            json={"callback_query": {"id": "c2", "data": f"trset:{proposal.id}:en",
                                     "from": {"id": 5}, "message": {"chat": {"id": -1}}}},
        )
        assert r2.status_code == 200
        last = inst.edit_card.call_args
        assert "Where is my parcel?" in last.kwargs["text"]
        translated_datas = [
            b["callback_data"] for row in last.kwargs["reply_markup"]["inline_keyboard"] for b in row
        ]
        assert f"back:{proposal.id}" in translated_datas
        mi_cls.return_value.translate_to.assert_awaited_once()


@pytest.mark.asyncio
async def test_pending_command_lists_threads(unauthenticated_client, proposal, monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_WEBHOOK_SECRET", "")
    sent: list[str] = []
    with patch("app.api.telegram.TelegramService") as tg_cls:
        inst = tg_cls.return_value
        inst.send_activity = AsyncMock(side_effect=lambda t: sent.append(t))
        resp = await unauthenticated_client.post("/api/v1/telegram/webhook", json=_command("/pending"))
    assert resp.status_code == 200
    assert sent and "Wachtend op review" in sent[0]
    assert "O1" in sent[0]  # the proposal fixture's order


@pytest.mark.asyncio
async def test_thread_command_reposts_card(unauthenticated_client, proposal, monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_WEBHOOK_SECRET", "")
    cards: list[str] = []
    with patch("app.api.telegram.TelegramService") as tg_cls:
        inst = tg_cls.return_value
        inst.send_card = AsyncMock(side_effect=lambda text, markup=None: cards.append(text))
        inst.send_activity = AsyncMock()
        resp = await unauthenticated_client.post("/api/v1/telegram/webhook", json=_command("/thread O1"))
    assert resp.status_code == 200
    assert cards and "O1" in cards[0]
    assert "Hallo, opgelost." in cards[0]  # the proposed reply re-rendered


@pytest.mark.asyncio
async def test_stats_command_reports_counts(unauthenticated_client, proposal, monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_WEBHOOK_SECRET", "")
    sent: list[str] = []
    with patch("app.api.telegram.TelegramService") as tg_cls:
        inst = tg_cls.return_value
        inst.send_activity = AsyncMock(side_effect=lambda t: sent.append(t))
        resp = await unauthenticated_client.post("/api/v1/telegram/webhook", json=_command("/stats"))
    assert resp.status_code == 200
    assert sent and "Statistieken" in sent[0]
    assert "Totaal threads" in sent[0]


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
