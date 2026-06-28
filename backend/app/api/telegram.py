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

import html
import logging
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models.agent_action import ActionStatus, AgentAction
from app.models.agent_event import AgentEvent
from app.models.marketplace_account import MarketplaceAccount
from app.models.support_thread import SupportThread, ThreadStatus
from app.models.telegram_session import TelegramSession
from app.models.thread_message import ThreadMessage
from app.services.agent.cards import build_action_card, toolbar
from app.services.audit import write_audit_log
from app.services.message_insight import MessageInsightService
from app.services.mirakl_client import MiraklClient
from app.services.safety_rules import SafetyRules
from app.services.telegram import TelegramService
from app.services.text_clean import strip_html

_LANG_NAMES = {"nl": "Nederlands", "en": "English", "fr": "Français", "de": "Deutsch"}

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
        return await _handle_message(db, telegram, message)

    return {"ok": True}


# --------------------------------------------------------------------------- #
# Callback (button tap) dispatch                                               #
# --------------------------------------------------------------------------- #


async def _handle_callback(
    db: AsyncSession, telegram: TelegramService, callback: dict
) -> dict[str, bool]:
    """Route a button tap by its callback_data verb."""
    callback_id = callback.get("id") or ""
    data = str(callback.get("data") or "")
    sender = callback.get("from") or {}
    actor = sender.get("username") or str(sender.get("id") or "telegram")
    chat_id = str(((callback.get("message") or {}).get("chat") or {}).get("id") or "")

    verb, _, arg = data.partition(":")
    if verb in ("approve", "deny"):
        return await _decide(db, telegram, callback_id, verb, arg, actor)
    if verb == "edit":
        return await _start_edit(db, telegram, callback_id, arg, chat_id)
    if verb == "cancel":
        return await _cancel_edit(db, telegram, callback_id, arg)
    if verb == "tr":
        return await _start_translate(db, telegram, callback_id, arg)
    if verb == "trset":
        return await _translate(db, telegram, callback_id, arg)
    if verb == "back":
        return await _restore(db, telegram, callback_id, arg)
    await telegram.answer_callback(callback_id)
    return {"ok": True}


async def _decide(
    db: AsyncSession,
    telegram: TelegramService,
    callback_id: str,
    decision: str,
    action_id_str: str,
    decided_by: str,
) -> dict[str, bool]:
    action = await _load_proposed(db, action_id_str)
    if action is None:
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

    # Defence in depth: never let a safety-flagged reply be approved as-is.
    if (action.context_json or {}).get("safety"):
        await telegram.answer_callback(callback_id, "Bewerk eerst — veiligheidswaarschuwing")
        return {"ok": True}

    action.status = ActionStatus.APPROVED.value
    await db.flush()
    await telegram.answer_callback(callback_id, "Goedgekeurd ✅")
    await _execute_action(db, action, telegram)
    return {"ok": True}


async def _start_edit(
    db: AsyncSession, telegram: TelegramService, callback_id: str, action_id_str: str, chat_id: str
) -> dict[str, bool]:
    """Ask the operator to type a corrected reply (force-reply) and await it."""
    action = await _load_proposed(db, action_id_str)
    if action is None:
        await telegram.answer_callback(callback_id, "Niet meer beschikbaar")
        return {"ok": True}
    if action.action_type != "send_reply":
        await telegram.answer_callback(callback_id, "Alleen antwoorden zijn bewerkbaar")
        return {"ok": True}

    await telegram.answer_callback(callback_id, "Stuur de nieuwe tekst")
    prompt_id = await telegram.prompt_reply(
        "✍️ Stuur de gecorrigeerde reactie als <b>antwoord</b> op dit bericht."
    )
    if action.telegram_message_id:
        text, _ = await _render(db, action)
        await telegram.edit_card(
            message_id=action.telegram_message_id,
            text=text,
            reply_markup=toolbar(action.action_type, action.id, "editing"),
        )
    if prompt_id is not None:
        db.add(
            TelegramSession(
                id=uuid.uuid4(),
                chat_id=chat_id,
                prompt_message_id=prompt_id,
                action_id=action.id,
                kind="edit",
            )
        )
        await db.commit()
    return {"ok": True}


async def _cancel_edit(
    db: AsyncSession, telegram: TelegramService, callback_id: str, action_id_str: str
) -> dict[str, bool]:
    action = await _load_proposed(db, action_id_str)
    if action is not None:
        await db.execute(delete(TelegramSession).where(TelegramSession.action_id == action.id))
        await db.commit()
    await telegram.answer_callback(callback_id, "Geannuleerd")
    if action is not None and action.telegram_message_id:
        text, markup = await _render(db, action)
        await telegram.edit_card(
            message_id=action.telegram_message_id, text=text, reply_markup=markup
        )
    return {"ok": True}


async def _start_translate(
    db: AsyncSession, telegram: TelegramService, callback_id: str, action_id_str: str
) -> dict[str, bool]:
    """Show the language picker on a reply card."""
    action = await _load_proposed(db, action_id_str)
    if action is None or action.action_type != "send_reply":
        await telegram.answer_callback(callback_id, "Niet beschikbaar")
        return {"ok": True}
    await telegram.answer_callback(callback_id)
    if action.telegram_message_id:
        text, _ = await _render(db, action)
        await telegram.edit_card(
            message_id=action.telegram_message_id,
            text=text,
            reply_markup=toolbar(action.action_type, action.id, "picking_lang"),
        )
    return {"ok": True}


async def _translate(
    db: AsyncSession, telegram: TelegramService, callback_id: str, arg: str
) -> dict[str, bool]:
    """Render the WHOLE card (labels + conversation + reply) in the chosen language."""
    action_id_str, _, lang = arg.partition(":")
    action = await _load_proposed(db, action_id_str)
    if action is None or action.action_type != "send_reply":
        await telegram.answer_callback(callback_id, "Niet beschikbaar")
        return {"ok": True}

    await telegram.answer_callback(callback_id, "Vertalen…")
    base, _ = await _render(db, action)
    translated = await MessageInsightService().translate_html(base, lang)
    safety = (action.context_json or {}).get("safety") or None
    markup = toolbar(action.action_type, action.id, "translated", flagged=bool(safety))
    footer = f"\n\n🌐 <i>Vertaald naar {html.escape(_LANG_NAMES.get(lang, lang), quote=False)}</i>"

    if not action.telegram_message_id:
        return {"ok": True}
    if not translated:
        await telegram.edit_card(
            message_id=action.telegram_message_id,
            text=base + "\n\n🌐 <i>Vertaling niet beschikbaar</i>",
            reply_markup=markup,
        )
        return {"ok": True}

    ok = await telegram.edit_card(
        message_id=action.telegram_message_id, text=translated + footer, reply_markup=markup
    )
    if not ok:
        # The model may have mangled the HTML — retry as escaped plain text.
        safe = html.escape(strip_html(translated), quote=False)
        await telegram.edit_card(
            message_id=action.telegram_message_id, text=safe + footer, reply_markup=markup
        )
    return {"ok": True}


async def _restore(
    db: AsyncSession, telegram: TelegramService, callback_id: str, action_id_str: str
) -> dict[str, bool]:
    """Return a card to its proposed view (from a picker/translated view)."""
    action = await _load_proposed(db, action_id_str)
    await telegram.answer_callback(callback_id)
    if action is not None and action.telegram_message_id:
        text, markup = await _render(db, action)
        await telegram.edit_card(
            message_id=action.telegram_message_id, text=text, reply_markup=markup
        )
    return {"ok": True}


async def _load_proposed(db: AsyncSession, action_id_str: str) -> AgentAction | None:
    try:
        action_id = uuid.UUID(action_id_str)
    except ValueError:
        return None
    action = await db.get(AgentAction, action_id)
    if action is None or action.status != ActionStatus.PROPOSED.value:
        return None
    return action


async def _render(
    db: AsyncSession, action: AgentAction, *, state: str = "proposed"
) -> tuple[str, dict]:
    """Re-render a proposed action's card (text + toolbar) from persisted data."""
    thread = await db.get(SupportThread, action.thread_id)
    facts = (action.context_json or {}).get("facts", {})
    rows = (
        await db.execute(
            select(ThreadMessage)
            .where(ThreadMessage.thread_id == action.thread_id)
            .order_by(ThreadMessage.sequence_number)
        )
    ).scalars().all()
    payload = action.payload_json or {}
    body = payload.get("body", "") if action.action_type == "send_reply" else payload.get("reason", "")
    safety = (action.context_json or {}).get("safety") or None
    text = build_action_card(
        action_type=action.action_type,
        thread=thread,
        facts=facts,
        body=body,
        messages=list(rows),
        edited_by=payload.get("edited_by"),
        safety_violations=safety,
    )
    return text, toolbar(action.action_type, action.id, state, flagged=bool(safety))


# --------------------------------------------------------------------------- #
# Message dispatch (force-reply edits + slash commands)                        #
# --------------------------------------------------------------------------- #


async def _handle_message(
    db: AsyncSession, telegram: TelegramService, message: dict
) -> dict[str, bool]:
    """A reply to an edit prompt becomes an edit; otherwise try a slash command."""
    reply_to = message.get("reply_to_message") or {}
    prompt_id = reply_to.get("message_id")
    if prompt_id is not None:
        session = (
            await db.execute(
                select(TelegramSession).where(TelegramSession.prompt_message_id == prompt_id)
            )
        ).scalar_one_or_none()
        if session is not None:
            return await _apply_edit(
                db, telegram, session, (message.get("text") or "").strip(), message.get("from") or {}
            )
    return await _handle_command(db, telegram, message)


async def _apply_edit(
    db: AsyncSession, telegram: TelegramService, session: TelegramSession, new_text: str, sender: dict
) -> dict[str, bool]:
    editor = sender.get("username") or str(sender.get("id") or "telegram")
    action = await db.get(AgentAction, session.action_id)
    await db.execute(delete(TelegramSession).where(TelegramSession.id == session.id))

    if action is None or action.status != ActionStatus.PROPOSED.value or not new_text:
        await db.commit()
        return {"ok": True}

    payload = dict(action.payload_json or {})
    payload["body"] = new_text
    payload["edited_by"] = editor
    action.payload_json = payload
    # Re-run safety on the human-edited text so the warning/flag reflects the edit.
    thread = await db.get(SupportThread, action.thread_id)
    _, violations = SafetyRules().validate(thread, new_text)
    action.context_json = {**(action.context_json or {}), "safety": violations}
    await db.commit()

    if action.telegram_message_id:
        text, markup = await _render(db, action)
        await telegram.edit_card(
            message_id=action.telegram_message_id, text=text, reply_markup=markup
        )
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

    parts = text.split()
    cmd = parts[0].lstrip("/").split("@", 1)[0].lower()
    handler = _COMMANDS.get(cmd)
    if handler is not None:
        await handler(db, telegram, parts[1:])
    return {"ok": True}


async def _cmd_help(db: AsyncSession, telegram: TelegramService, args: list[str]) -> None:
    await telegram.send_activity(
        "🤖 <b>Omiximo Support — commando's</b>\n"
        "/pending — threads die wachten op review\n"
        "/thread &lt;order&gt; — open de kaart van een order\n"
        "/status — systeemstatus en schakelaars\n"
        "/stats — aantallen van vandaag\n"
        "/help — deze hulp\n\n"
        "<b>Op een kaart:</b>\n"
        "✅ Approve / ❌ Deny · ✏️ Edit · 🌐 Translate\n"
        "⤴️ Escalate / ❌ Dismiss — escaleer naar een mens of negeer"
    )


async def _cmd_status(db: AsyncSession, telegram: TelegramService, args: list[str]) -> None:
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


async def _cmd_pending(db: AsyncSession, telegram: TelegramService, args: list[str]) -> None:
    rows = (
        await db.execute(
            select(SupportThread)
            .where(SupportThread.status == ThreadStatus.PENDING_REVIEW)
            .order_by(SupportThread.response_deadline.asc())
            .limit(10)
        )
    ).scalars().all()
    total = (
        await db.execute(
            select(func.count())
            .select_from(SupportThread)
            .where(SupportThread.status == ThreadStatus.PENDING_REVIEW)
        )
    ).scalar_one()

    if not rows:
        await telegram.send_activity("📭 Geen threads wachten op review.")
        return

    lines = [f"📋 <b>Wachtend op review</b> — {total}"]
    for t in rows:
        risk = t.risk_level.value if t.risk_level is not None else "—"
        snippet = html.escape(strip_html(t.customer_message or "")[:60], quote=False)
        lines.append(
            f"• <code>{html.escape(str(t.mirakl_order_id), quote=False)}</code> "
            f"· {risk} {t.category or '—'} — {snippet}"
        )
    if total > len(rows):
        lines.append(f"… en {total - len(rows)} meer — open er een met /thread &lt;order&gt;.")
    await telegram.send_activity("\n".join(lines))


async def _cmd_thread(db: AsyncSession, telegram: TelegramService, args: list[str]) -> None:
    if not args:
        await telegram.send_activity("Gebruik: /thread &lt;order_id&gt;")
        return
    order_id = args[0]
    thread = (
        await db.execute(
            select(SupportThread)
            .where(SupportThread.mirakl_order_id == order_id)
            .order_by(SupportThread.response_deadline.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if thread is None:
        await telegram.send_activity(
            f"Geen thread voor order <code>{html.escape(order_id, quote=False)}</code>."
        )
        return

    action = (
        await db.execute(
            select(AgentAction)
            .where(
                AgentAction.thread_id == thread.id,
                AgentAction.status == ActionStatus.PROPOSED.value,
            )
            .order_by(AgentAction.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if action is not None:
        text, markup = await _render(db, action)
        await telegram.send_card(text, markup)
        return

    status_label = getattr(thread.status, "value", thread.status)
    risk = thread.risk_level.value if thread.risk_level is not None else "—"
    snippet = html.escape(strip_html(thread.customer_message or "")[:200], quote=False)
    await telegram.send_activity(
        f"📦 <b>Order {html.escape(order_id, quote=False)}</b> · {status_label} · {risk}\n"
        f"Geen openstaand voorstel.\n{snippet}"
    )


async def _cmd_stats(db: AsyncSession, telegram: TelegramService, args: list[str]) -> None:
    async def _count(*conds) -> int:
        q = select(func.count()).select_from(SupportThread)
        for cond in conds:
            q = q.where(cond)
        return (await db.execute(q)).scalar_one()

    start_today = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    received_today = await _count(SupportThread.created_at >= start_today)
    pending = await _count(SupportThread.status == ThreadStatus.PENDING_REVIEW)
    sent = await _count(SupportThread.status == ThreadStatus.SENT_AUTO)
    escalated = await _count(SupportThread.status == ThreadStatus.ESCALATED)
    total = await _count()

    await telegram.send_activity(
        "📊 <b>Statistieken</b>\n"
        f"• Vandaag ontvangen: <b>{received_today}</b>\n"
        f"• Wachtend op review: <b>{pending}</b>\n"
        f"• Verstuurd: <b>{sent}</b>\n"
        f"• Geëscaleerd: <b>{escalated}</b>\n"
        f"• Totaal threads: <b>{total}</b>"
    )


_COMMANDS = {
    "help": _cmd_help,
    "status": _cmd_status,
    "pending": _cmd_pending,
    "thread": _cmd_thread,
    "stats": _cmd_stats,
}


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
