"""Telegram Bot API client.

Two jobs:
1. Activity channel — post new-thread notices and agent tool-call telemetry.
2. Approval gate — send a rich Approve/Deny card for each proposed agent
   action, and edit it once a decision is made.

Degrades gracefully: with no bot token configured, every method is a no-op
returning ``None`` so the rest of the system runs unaffected. All network
failures are caught and logged (never raised) — Telegram being down must not
break thread processing.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_API_BASE = "https://api.telegram.org"


class TelegramService:
    def __init__(self, token: str | None = None, chat_id: str | None = None) -> None:
        self._token = token if token is not None else settings.TELEGRAM_BOT_TOKEN
        self._chat_id = chat_id if chat_id is not None else settings.TELEGRAM_CHAT_ID

    @property
    def enabled(self) -> bool:
        return bool(self._token and self._chat_id)

    async def _post(self, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        """POST to the Bot API. Raises RuntimeError on a non-ok response."""
        url = f"{_API_BASE}/bot{self._token}/{method}"
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(url, json=payload)
        data = resp.json()
        if not data.get("ok"):
            raise RuntimeError(f"Telegram {method} failed: {str(data)[:200]}")
        return data

    async def send_activity(self, text: str) -> int | None:
        """Post a plain activity message. Returns the message_id, or None."""
        if not self.enabled:
            return None
        try:
            data = await self._post(
                "sendMessage",
                {
                    "chat_id": self._chat_id,
                    "text": text,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                },
            )
            return data["result"]["message_id"]
        except Exception as exc:  # noqa: BLE001 — Telegram must never break the pipeline
            logger.warning("Telegram send_activity failed: %s", exc)
            return None

    async def send_approval_request(
        self, *, action_id: uuid.UUID, title: str, body: str
    ) -> int | None:
        """Post an Approve/Deny card. callback_data carries the action id."""
        if not self.enabled:
            return None
        text = f"<b>{title}</b>\n\n{body}"
        markup = {
            "inline_keyboard": [
                [
                    {"text": "✅ Approve", "callback_data": f"approve:{action_id}"},
                    {"text": "❌ Deny", "callback_data": f"deny:{action_id}"},
                ]
            ]
        }
        try:
            data = await self._post(
                "sendMessage",
                {
                    "chat_id": self._chat_id,
                    "text": text,
                    "parse_mode": "HTML",
                    "reply_markup": markup,
                    "disable_web_page_preview": True,
                },
            )
            return data["result"]["message_id"]
        except Exception as exc:  # noqa: BLE001
            logger.warning("Telegram send_approval_request failed: %s", exc)
            return None

    async def resolve_message(
        self, *, message_id: int, decision: str, footer: str
    ) -> None:
        """Strip the buttons from a decided card and post a decision note."""
        if not self.enabled:
            return
        try:
            await self._post(
                "editMessageReplyMarkup",
                {
                    "chat_id": self._chat_id,
                    "message_id": message_id,
                    "reply_markup": {"inline_keyboard": []},
                },
            )
            await self._post(
                "sendMessage",
                {
                    "chat_id": self._chat_id,
                    "text": f"{decision} — {footer}",
                    "reply_to_message_id": message_id,
                    "parse_mode": "HTML",
                },
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Telegram resolve_message failed: %s", exc)
