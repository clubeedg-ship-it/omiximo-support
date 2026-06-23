"""Agent tool execution: read tools return data; action tools gate via Telegram."""

import pytest

from app.models.agent_action import ActionStatus
from app.services.agent import tools as tools_mod
from app.services.agent.tools import ToolContext, execute_tool


class FakeTelegram:
    enabled = True

    def __init__(self):
        self.requests = []

    async def send_approval_request(self, *, action_id, title, body):
        self.requests.append({"action_id": action_id, "title": title, "body": body})
        return 7


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
    assert len(tg.requests) == 1
    assert "Hallo" in tg.requests[0]["body"]


@pytest.mark.asyncio
async def test_unknown_tool_returns_error(db, sample_account, sample_thread):
    ctx = ToolContext(db=db, thread=sample_thread, account=sample_account, telegram=FakeTelegram())
    out = await execute_tool(ctx, "nonexistent", {})
    assert "error" in out
