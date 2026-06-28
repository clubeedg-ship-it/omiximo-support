"""Telegram webhook — executes human Approve/Deny decisions.

Telegram delivers a ``callback_query`` when someone taps a button on an
approval card. ``callback_data`` is ``approve:{action_id}`` or
``deny:{action_id}``. On approve we execute the action for real (Phase 1:
``send_reply`` via Mirakl); on deny we discard it. Idempotent: a re-delivered
callback for an already-decided action is a no-op (Telegram retries).

Mounted UNPROTECTED (Telegram cannot present a Clerk token); authenticity is
verified via the ``X-Telegram-Bot-Api-Secret-Token`` header configured at
``setWebhook`` time.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models.agent_action import ActionStatus, AgentAction
from app.models.agent_event import AgentEvent
from app.models.marketplace_account import MarketplaceAccount
from app.models.support_thread import SupportThread, ThreadStatus
from app.services.audit import write_audit_log
from app.services.mirakl_client import MiraklClient
from app.services.telegram import TelegramService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/telegram", tags=["telegram"])


@router.post("/webhook")
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> dict[str, bool]:
    """Route Telegram updates: button taps (callback_query) and slash commands."""
    if (
        settings.TELEGRAM_WEBHOOK_SECRET
        and x_telegram_bot_api_secret_token != settings.TELEGRAM_WEBHOOK_SECRET
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="bad secret token")

    update = await request.json()
    telegram = TelegramService()

    callback = update.get("callback_query")
    if callback:
        return await _handle_callback(db, telegram, callback)

    message = update.get("message")
    if message:
        return await _handle_command(db, telegram, message)

    return {"ok": True}


async def _handle_callback(
    db: AsyncSession, telegram: TelegramService, callback: dict
) -> dict[str, bool]:
    """Dispatch a button tap. Only approve:/deny: are wired today."""
    callback_id = callback.get("id") or ""
    data = str(callback.get("data") or "")
    sender = callback.get("from") or {}
    decided_by = sender.get("username") or str(sender.get("id") or "telegram")

    decision, _, action_id_str = data.partition(":")
    if decision not in ("approve", "deny"):
        await telegram.answer_callback(callback_id)
        return {"ok": True}
    try:
        action_id = uuid.UUID(action_id_str)
    except ValueError:
        await telegram.answer_callback(callback_id)
        return {"ok": True}

    action = await db.get(AgentAction, action_id)
    if action is None or action.status != ActionStatus.PROPOSED.value:
        await telegram.answer_callback(callback_id, "Al verwerkt")
        return {"ok": True}  # unknown or already decided — idempotent no-op

    action.decided_by = decided_by
    action.decided_at = datetime.now(UTC)

    if decision == "deny":
        action.status = ActionStatus.DENIED.value
        await db.commit()
        await telegram.answer_callback(callback_id, "Geweigerd")
        if action.telegram_message_id:
            await telegram.resolve_message(
                message_id=action.telegram_message_id, decision="❌ Denied", footer=decided_by
            )
        return {"ok": True}

    # approve
    action.status = ActionStatus.APPROVED.value
    await db.flush()
    await telegram.answer_callback(callback_id, "Goedgekeurd ✅")
    await _execute_action(db, action, telegram)
    return {"ok": True}


async def _handle_command(
    db: AsyncSession, telegram: TelegramService, message: dict
) -> dict[str, bool]:
    """Dispatch a slash command (e.g. /help, /status). Plain messages are ignored."""
    text = (message.get("text") or "").strip()
    entities = message.get("entities") or []
    is_command = text.startswith("/") or any(
        e.get("type") == "bot_command" and e.get("offset") == 0 for e in entities
    )
    if not is_command:
        return {"ok": True}

    cmd = text.split(maxsplit=1)[0].lstrip("/").split("@", 1)[0].lower()
    handler = _COMMANDS.get(cmd)
    if handler is not None:
        await handler(db, telegram)
    return {"ok": True}


async def _cmd_help(db: AsyncSession, telegram: TelegramService) -> None:
    await telegram.send_activity(
        "🤖 <b>Omiximo Support — commando's</b>\n"
        "/status — systeemstatus en schakelaars\n"
        "/help — deze hulp\n\n"
        "<b>Op een kaart:</b>\n"
        "✅ Approve / ❌ Deny — verstuur of weiger het concept\n"
        "⤴️ Escalate / ❌ Dismiss — escaleer naar een mens of negeer"
    )


async def _cmd_status(db: AsyncSession, telegram: TelegramService) -> None:
    pending = (
        await db.execute(
            select(func.count())
            .select_from(SupportThread)
            .where(SupportThread.status == ThreadStatus.PENDING_REVIEW)
        )
    ).scalar_one()

    def _flag(value: bool) -> str:
        return "aan" if value else "uit"

    await telegram.send_activity(
        "⚙️ <b>Status</b>\n"
        f"• Wachtend op review: <b>{pending}</b>\n"
        f"• Agent: {_flag(settings.AGENT_ENABLED)} · "
        f"Fake-Mirakl: {_flag(settings.AGENT_FAKE_MIRAKL)} · "
        f"Auto-send: {_flag(settings.AUTO_SEND_ENABLED)}"
    )


_COMMANDS = {"help": _cmd_help, "status": _cmd_status}


async def _execute_action(
    db: AsyncSession, action: AgentAction, telegram: TelegramService
) -> None:
    """Carry out an approved action against the marketplace."""
    thread = await db.get(SupportThread, action.thread_id)
    if thread is None:
        action.status = ActionStatus.FAILED.value
        action.result_json = {"error": "thread not found"}
        await db.commit()
        return
    account = await db.get(MarketplaceAccount, thread.marketplace_account_id)

    if action.action_type == "send_reply":
        body = action.payload_json.get("body", "")
        try:
            if settings.AGENT_FAKE_MIRAKL:
                # Test/polish mode: simulate the send, never hit the marketplace.
                pass
            else:
                async with MiraklClient(account) as client:
                    await client.send_reply(thread_id=thread.mirakl_thread_id, body=body)
        except Exception as exc:  # noqa: BLE001
            action.status = ActionStatus.FAILED.value
            action.result_json = {"error": str(exc)}
            thread.status = ThreadStatus.FAILED
            db.add(AgentEvent(id=uuid.uuid4(), thread_id=thread.id, event_type="error",
                              detail_json={"stage": "send_reply", "error": str(exc)}))
            await db.commit()
            if action.telegram_message_id:
                await telegram.resolve_message(
                    message_id=action.telegram_message_id,
                    decision="⚠️ Send failed", footer=str(exc)[:120])
            return

        action.status = ActionStatus.EXECUTED.value
        action.result_json = {"sent": True}
        thread.status = ThreadStatus.SENT_AUTO
        thread.updated_at = datetime.now(UTC)
        await write_audit_log(
            db, action="auto_sent", actor=action.decided_by or "telegram",
            thread_id=thread.id,
            detail={"via": "telegram_approval", "action_id": str(action.id),
                    "response_length": len(body)},
        )
        db.add(AgentEvent(id=uuid.uuid4(), thread_id=thread.id, event_type="action_executed",
                          detail_json={"action_type": "send_reply", "action_id": str(action.id)}))
        await db.commit()
        if action.telegram_message_id:
            decision = "✅ Sent (simulated)" if settings.AGENT_FAKE_MIRAKL else "✅ Sent"
            await telegram.resolve_message(
                message_id=action.telegram_message_id,
                decision=decision, footer=action.decided_by or "")
        return

    if action.action_type == "escalate":
        action.status = ActionStatus.EXECUTED.value
        thread.status = ThreadStatus.ESCALATED
        thread.updated_at = datetime.now(UTC)
        await write_audit_log(
            db, action="escalated", actor=action.decided_by or "telegram",
            thread_id=thread.id, detail={"via": "telegram_approval"})
        await db.commit()
        if action.telegram_message_id:
            await telegram.resolve_message(
                message_id=action.telegram_message_id,
                decision="⤴️ Escalated", footer=action.decided_by or "")
        return

    action.status = ActionStatus.FAILED.value
    action.result_json = {"error": f"unsupported action_type {action.action_type}"}
    await db.commit()
