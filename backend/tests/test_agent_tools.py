"""Agent tool execution: read tools return data; action tools gate via Telegram."""

import uuid
from datetime import UTC, datetime

import pytest

from app.models.agent_action import ActionStatus
from app.models.thread_message import ThreadMessage
from app.services.agent import tools as tools_mod
from app.services.agent.tools import ToolContext, execute_tool


class FakeTelegram:
    enabled = True

    def __init__(self):
        self.cards = []

    async def send_card(self, text, reply_markup=None):
        self.cards.append({"text": text, "reply_markup": reply_markup})
        return 7


def _button_datas(reply_markup):
    return [b["callback_data"] for row in reply_markup["inline_keyboard"] for b in row]


def _button_texts(reply_markup):
    return [b["text"] for row in reply_markup["inline_keyboard"] for b in row]


@pytest.mark.asyncio
async def test_get_order_delegates_to_connector(db, sample_account, sample_thread, monkeypatch):
    async def fake_fetch(self, order_id):
        return {"order_id": order_id, "status": "SHIPPED"}

    monkeypatch.setattr(tools_mod.MiraklConnector, "fetch_context", fake_fetch)
    ctx = ToolContext(db=db, thread=sample_thread, account=sample_account, telegram=FakeTelegram())
    out = await execute_tool(ctx, "get_order", {})
    assert out["status"] == "SHIPPED"
    assert out["order_id"] == sample_thread.mirakl_order_id


@pytest.mark.asyncio
async def test_send_reply_creates_proposal_and_requests_approval(db, sample_account, sample_thread):
    tg = FakeTelegram()
    ctx = ToolContext(db=db, thread=sample_thread, account=sample_account, telegram=tg)
    out = await execute_tool(ctx, "send_reply", {"body": "Hallo, hier is uw oplossing."})
    assert out["status"] == "awaiting_approval"
    assert ctx.proposed_action is not None
    assert ctx.proposed_action.action_type == "send_reply"
    assert ctx.proposed_action.status == ActionStatus.PROPOSED.value
    assert ctx.proposed_action.payload_json["body"] == "Hallo, hier is uw oplossing."
    assert ctx.proposed_action.telegram_message_id == 7
    assert len(tg.cards) == 1
    assert "Hallo" in tg.cards[0]["text"]
    datas = _button_datas(tg.cards[0]["reply_markup"])
    assert f"approve:{ctx.proposed_action.id}" in datas
    assert f"edit:{ctx.proposed_action.id}" in datas
    # facts snapshot persisted for later re-render
    assert ctx.proposed_action.context_json == {"facts": ctx.facts}


@pytest.mark.asyncio
async def test_send_reply_card_folds_in_gathered_facts_and_classification(
    db, sample_account, classified_green_thread, monkeypatch
):
    async def fake_fetch(self, order_id):
        return {
            "order_id": order_id,
            "status": "DELIVERED",
            "item": "Sony WH-1000XM5",
            "amount": "379.00 EUR",
            "customer_name": "Lisa",
            "shop_name": "MediaMarktSaturn",
        }

    monkeypatch.setattr(tools_mod.MiraklConnector, "fetch_context", fake_fetch)
    tg = FakeTelegram()
    ctx = ToolContext(
        db=db, thread=classified_green_thread, account=sample_account, telegram=tg
    )
    # The agent gathers a fact, then proposes a reply on the same context.
    await execute_tool(ctx, "get_order", {})
    await execute_tool(ctx, "send_reply", {"body": "Beste Lisa, het spijt ons."})

    text = tg.cards[0]["text"]
    assert "GREEN" in text  # classification folded into the card
    assert "DELIVERED" in text
    assert "Sony WH-1000XM5" in text
    assert "€379,00" in text
    assert "Beste Lisa, het spijt ons." in text


@pytest.mark.asyncio
async def test_send_reply_card_includes_full_conversation_when_multi_message(
    db, sample_account, sample_thread
):
    turns = [
        ("CUSTOMER", "INBOUND", "Waar blijft mijn pakket?"),
        ("OPERATOR", "OUTBOUND", "We zoeken het direct uit."),
        ("CUSTOMER", "INBOUND", "Nog steeds niks ontvangen."),
    ]
    for i, (atype, direction, text) in enumerate(turns):
        db.add(
            ThreadMessage(
                id=uuid.uuid4(),
                thread_id=sample_thread.id,
                direction=direction,
                author_type=atype,
                body=text,
                sequence_number=i,
                created_at=datetime(2026, 6, 22 + i, 10, 0, tzinfo=UTC),
            )
        )
    await db.flush()

    tg = FakeTelegram()
    ctx = ToolContext(db=db, thread=sample_thread, account=sample_account, telegram=tg)
    await execute_tool(ctx, "send_reply", {"body": "Bedankt voor uw geduld."})

    text = tg.cards[0]["text"]
    assert "Gesprek" in text
    assert "3 berichten" in text
    assert "Nog steeds niks ontvangen." in text
    assert "Bedankt voor uw geduld." in text  # proposed reply shown separately


@pytest.mark.asyncio
async def test_escalate_uses_escalation_card_and_buttons(db, sample_account, sample_thread):
    tg = FakeTelegram()
    ctx = ToolContext(db=db, thread=sample_thread, account=sample_account, telegram=tg)
    out = await execute_tool(ctx, "escalate", {"reason": "Vereist een menselijk besluit."})
    assert out["status"] == "awaiting_approval"
    assert ctx.proposed_action.action_type == "escalate"
    text = tg.cards[0]["text"]
    assert "Escalatie" in text
    assert "Vereist een menselijk besluit." in text
    assert "Voorgestelde reactie" not in text
    texts = _button_texts(tg.cards[0]["reply_markup"])
    assert any("Escalate" in t for t in texts)
    assert any("Dismiss" in t for t in texts)


@pytest.mark.asyncio
async def test_unknown_tool_returns_error(db, sample_account, sample_thread):
    ctx = ToolContext(db=db, thread=sample_thread, account=sample_account, telegram=FakeTelegram())
    out = await execute_tool(ctx, "nonexistent", {})
    assert "error" in out
