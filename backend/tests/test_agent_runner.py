"""Agent runner loop: uses read tools then proposes a reply; logs events."""

import pytest
from sqlalchemy import func, select

from app.models.agent_event import AgentEvent
from app.services.agent.runner import AgentRunner


class FakeTelegram:
    enabled = True

    async def send_card(self, text, reply_markup=None):
        return 5

    async def send_activity(self, text):
        return None


def _assistant_tool_call(call_id, name, arguments):
    return {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {"id": call_id, "type": "function",
                         "function": {"name": name, "arguments": arguments}}
                    ],
                }
            }
        ]
    }


@pytest.mark.asyncio
async def test_runner_uses_tool_then_proposes_reply(db, sample_account, sample_thread, monkeypatch):
    responses = iter([
        _assistant_tool_call("c1", "get_order", "{}"),
        _assistant_tool_call("c2", "send_reply", '{"body": "Hallo, opgelost."}'),
    ])

    async def fake_chat(self, messages, tools):
        return next(responses)

    async def fake_fetch(self, order_id):
        return {"order_id": order_id, "status": "DELIVERED"}

    monkeypatch.setattr(AgentRunner, "_chat", fake_chat)
    monkeypatch.setattr("app.services.agent.tools.MiraklConnector.fetch_context", fake_fetch)

    runner = AgentRunner(telegram=FakeTelegram())
    action = await runner.run_for_thread(db, thread=sample_thread, account=sample_account)

    assert action is not None
    assert action.action_type == "send_reply"
    assert action.payload_json["body"] == "Hallo, opgelost."

    # Events were logged for the tool call and the proposal.
    count = (await db.execute(select(func.count()).select_from(AgentEvent))).scalar_one()
    assert count >= 2
    types = set(
        (await db.execute(select(AgentEvent.event_type))).scalars().all()
    )
    assert "tool_call" in types
    assert "proposal_created" in types


@pytest.mark.asyncio
async def test_operator_required_thread_is_skipped_no_card(
    db, sample_account, operator_thread, monkeypatch
):
    called = {"chat": False}

    async def fake_chat(self, messages, tools):
        called["chat"] = True
        return {"choices": [{"message": {"role": "assistant", "content": "should not run"}}]}

    monkeypatch.setattr(AgentRunner, "_chat", fake_chat)
    action = await AgentRunner(telegram=FakeTelegram()).run_for_thread(
        db, thread=operator_thread, account=sample_account
    )
    assert action is None  # skipped: no draft, no escalation card — handled in the web UI
    assert called["chat"] is False


@pytest.mark.asyncio
async def test_thread_with_existing_proposed_action_is_not_redrafted(
    db, sample_account, sample_thread, monkeypatch
):
    import uuid as _uuid

    from app.models.agent_action import ActionStatus, AgentAction

    existing = AgentAction(
        id=_uuid.uuid4(), thread_id=sample_thread.id, action_type="send_reply",
        status=ActionStatus.PROPOSED.value, payload_json={"body": "earlier draft"},
    )
    db.add(existing)
    await db.flush()
    called = {"chat": False}

    async def fake_chat(self, messages, tools):
        called["chat"] = True
        return {"choices": [{"message": {"role": "assistant", "content": "dup"}}]}

    monkeypatch.setattr(AgentRunner, "_chat", fake_chat)
    action = await AgentRunner(telegram=FakeTelegram()).run_for_thread(
        db, thread=sample_thread, account=sample_account
    )
    assert action is not None and action.id == existing.id  # returns existing, no new card
    assert called["chat"] is False


@pytest.mark.asyncio
async def test_awaiting_customer_thread_is_not_drafted(db, sample_account, sample_thread, monkeypatch):
    from app.models.support_thread import ReplyState

    sample_thread.reply_state = ReplyState.AWAITING_CUSTOMER.value
    await db.flush()
    called = {"chat": False}

    async def fake_chat(self, messages, tools):
        called["chat"] = True
        return {"choices": [{"message": {"role": "assistant", "content": "nope"}}]}

    monkeypatch.setattr(AgentRunner, "_chat", fake_chat)
    action = await AgentRunner(telegram=FakeTelegram()).run_for_thread(
        db, thread=sample_thread, account=sample_account
    )
    assert action is None  # nothing to respond to — we already replied
    assert called["chat"] is False


@pytest.mark.asyncio
async def test_runner_proposes_reply_when_model_returns_plain_text(db, sample_account, sample_thread, monkeypatch):
    async def fake_chat(self, messages, tools):
        return {"choices": [{"message": {"role": "assistant", "content": "Directe oplossing."}}]}

    monkeypatch.setattr(AgentRunner, "_chat", fake_chat)
    runner = AgentRunner(telegram=FakeTelegram())
    action = await runner.run_for_thread(db, thread=sample_thread, account=sample_account)
    assert action is not None
    assert action.action_type == "send_reply"
    assert action.payload_json["body"] == "Directe oplossing."
