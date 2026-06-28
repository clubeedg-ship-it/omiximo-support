"""TelegramService builds correct payloads and no-ops without a token."""

import pytest

from app.services.telegram import TelegramService


@pytest.mark.asyncio
async def test_noop_without_token():
    svc = TelegramService(token="", chat_id="")
    assert svc.enabled is False
    assert await svc.send_activity("hi") is None
    assert await svc.send_card("t") is None


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
async def test_send_card_posts_text_and_markup(monkeypatch):
    captured = {}

    async def fake_post(method, payload):
        captured["method"] = method
        captured["payload"] = payload
        return {"ok": True, "result": {"message_id": 42}}

    svc = TelegramService(token="t", chat_id="99")
    monkeypatch.setattr(svc, "_post", fake_post)
    markup = {"inline_keyboard": [[{"text": "✅ Approve", "callback_data": "approve:1"}]]}
    mid = await svc.send_card("Card text", markup)
    assert mid == 42
    assert captured["method"] == "sendMessage"
    assert captured["payload"]["text"] == "Card text"
    assert captured["payload"]["reply_markup"] == markup


@pytest.mark.asyncio
async def test_edit_card_posts_editmessagetext(monkeypatch):
    captured = {}

    async def fake_post(method, payload):
        captured["method"] = method
        captured["payload"] = payload
        return {"ok": True, "result": {}}

    svc = TelegramService(token="t", chat_id="99")
    monkeypatch.setattr(svc, "_post", fake_post)
    await svc.edit_card(message_id=55, text="Updated", reply_markup={"inline_keyboard": []})
    assert captured["method"] == "editMessageText"
    assert captured["payload"]["message_id"] == 55
    assert captured["payload"]["text"] == "Updated"


@pytest.mark.asyncio
async def test_prompt_reply_uses_force_reply(monkeypatch):
    captured = {}

    async def fake_post(method, payload):
        captured["method"] = method
        captured["payload"] = payload
        return {"ok": True, "result": {"message_id": 77}}

    svc = TelegramService(token="t", chat_id="99")
    monkeypatch.setattr(svc, "_post", fake_post)
    mid = await svc.prompt_reply("Reply with the new text")
    assert mid == 77
    assert captured["method"] == "sendMessage"
    assert captured["payload"]["reply_markup"] == {"force_reply": True}


@pytest.mark.asyncio
async def test_answer_callback_posts_acknowledgement(monkeypatch):
    captured = {}

    async def fake_post(method, payload):
        captured["method"] = method
        captured["payload"] = payload
        return {"ok": True, "result": True}

    svc = TelegramService(token="t", chat_id="99")
    monkeypatch.setattr(svc, "_post", fake_post)
    await svc.answer_callback("cb-123", "Goedgekeurd")
    assert captured["method"] == "answerCallbackQuery"
    assert captured["payload"]["callback_query_id"] == "cb-123"
    assert captured["payload"]["text"] == "Goedgekeurd"


@pytest.mark.asyncio
async def test_answer_callback_noop_without_token():
    svc = TelegramService(token="", chat_id="")
    assert await svc.answer_callback("x") is None
