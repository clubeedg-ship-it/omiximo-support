"""TelegramService builds correct payloads and no-ops without a token."""

import uuid

import pytest

from app.services.telegram import TelegramService


@pytest.mark.asyncio
async def test_noop_without_token():
    svc = TelegramService(token="", chat_id="")
    assert svc.enabled is False
    assert await svc.send_activity("hi") is None
    assert await svc.send_approval_request(action_id=uuid.uuid4(), title="t", body="b") is None


@pytest.mark.asyncio
async def test_send_activity_posts_text(monkeypatch):
    captured = {}

    async def fake_post(method, payload):
        captured["method"] = method
        captured["payload"] = payload
        return {"ok": True, "result": {"message_id": 11}}

    svc = TelegramService(token="t", chat_id="99")
    monkeypatch.setattr(svc, "_post", fake_post)
    mid = await svc.send_activity("new thread")
    assert mid == 11
    assert captured["method"] == "sendMessage"
    assert captured["payload"]["chat_id"] == "99"
    assert captured["payload"]["text"] == "new thread"


@pytest.mark.asyncio
async def test_approval_request_builds_inline_keyboard(monkeypatch):
    captured = {}

    async def fake_post(method, payload):
        captured["payload"] = payload
        return {"ok": True, "result": {"message_id": 42}}

    svc = TelegramService(token="t", chat_id="99")
    monkeypatch.setattr(svc, "_post", fake_post)
    aid = uuid.uuid4()
    mid = await svc.send_approval_request(action_id=aid, title="Reply ready", body="Hallo")
    assert mid == 42
    row = captured["payload"]["reply_markup"]["inline_keyboard"][0]
    assert row[0]["callback_data"] == f"approve:{aid}"
    assert row[1]["callback_data"] == f"deny:{aid}"
    assert "Hallo" in captured["payload"]["text"]
