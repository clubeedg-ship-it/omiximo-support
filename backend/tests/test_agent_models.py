"""agent_actions + agent_events models persist and round-trip."""

import uuid

import pytest

from app.models.agent_action import ActionStatus, AgentAction
from app.models.agent_event import AgentEvent


@pytest.mark.asyncio
async def test_agent_action_defaults_to_proposed(db):
    a = AgentAction(
        id=uuid.uuid4(),
        thread_id=None,
        action_type="send_reply",
        payload_json={"body": "Hallo"},
    )
    db.add(a)
    await db.flush()
    assert a.status == ActionStatus.PROPOSED.value
    assert a.payload_json["body"] == "Hallo"


@pytest.mark.asyncio
async def test_agent_event_roundtrip(db):
    e = AgentEvent(
        id=uuid.uuid4(),
        thread_id=None,
        event_type="tool_call",
        detail_json={"tool": "get_order", "args": {}},
    )
    db.add(e)
    await db.flush()
    assert e.event_type == "tool_call"
    assert e.detail_json["tool"] == "get_order"
