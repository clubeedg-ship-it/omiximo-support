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
async def test_runner_proposes_reply_when_model_returns_plain_text(db, sample_account, sample_thread, monkeypatch):
    async def fake_chat(self, messages, tools):
        return {"choices": [{"message": {"role": "assistant", "content": "Directe oplossing."}}]}

    monkeypatch.setattr(AgentRunner, "_chat", fake_chat)
    runner = AgentRunner(telegram=FakeTelegram())
    action = await runner.run_for_thread(db, thread=sample_thread, account=sample_account)
    assert action is not None
    assert action.action_type == "send_reply"
    assert action.payload_json["body"] == "Directe oplossing."
