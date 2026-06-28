"""Agent runner — the tool-calling loop.

Drives one thread to a proposed action:

1. Build messages = system prompt + THIS thread's conversation history only
   (scoped memory — no other threads, no global state).
2. Call the LLM with the tool schemas.
3. Execute any read tools the model asks for, feed results back, repeat.
4. Stop when the model calls ``send_reply``/``escalate`` (an AgentAction is
   proposed and a Telegram Approve/Deny card is sent) or steps are exhausted.

Every step is recorded as an ``AgentEvent`` row. The loop never raises into the
pipeline — on any failure it logs an ``error`` event and returns ``None``.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.agent_action import AgentAction
from app.models.agent_event import AgentEvent
from app.models.thread_message import MessageAuthorType, ThreadMessage
from app.services.agent.tools import TOOL_SCHEMAS, ToolContext, execute_tool
from app.services.telegram import TelegramService
from app.services.text_clean import strip_html

logger = logging.getLogger(__name__)

_LANGUAGE_NAMES = {"nl": "Dutch", "en": "English", "fr": "French", "de": "German"}


class AgentRunner:
    def __init__(self, telegram: TelegramService | None = None) -> None:
        self._telegram = telegram or TelegramService()

    async def run_for_thread(
        self, db: AsyncSession, *, thread: Any, account: Any
    ) -> AgentAction | None:
        """Run the agent loop for one thread; return the proposed AgentAction."""
        ctx = ToolContext(db=db, thread=thread, account=account, telegram=self._telegram)

        # Operator/marketplace messages are never auto-replied (D-003 / R3).
        # Escalate immediately instead of drafting a customer reply that would
        # only be safety-blocked — a clear escalation card, no wasted LLM call.
        if getattr(thread, "operator_required", False):
            await execute_tool(
                ctx,
                "escalate",
                {"reason": "Operator-/marktplaatsbericht — handmatige afhandeling vereist."},
            )
            if ctx.proposed_action is not None:
                await self._log(
                    db, thread, "proposal_created",
                    {"action_type": "escalate", "action_id": str(ctx.proposed_action.id)},
                )
            return ctx.proposed_action

        try:
            messages = await self._build_messages(db, thread, account)
        except Exception as exc:  # noqa: BLE001
            await self._log(db, thread, "error", {"stage": "build_messages", "error": str(exc)})
            return None

        for _step in range(settings.AGENT_MAX_STEPS):
            try:
                response = await self._chat(messages, TOOL_SCHEMAS)
            except Exception as exc:  # noqa: BLE001
                await self._log(db, thread, "error", {"stage": "llm", "error": str(exc)})
                return None

            message = response["choices"][0]["message"]
            tool_calls = message.get("tool_calls") or []

            # Model produced a final answer without using send_reply: treat the
            # text as the reply and propose it (robustness against models that
            # skip the tool call).
            if not tool_calls:
                content = (message.get("content") or "").strip()
                if not content:
                    await self._log(db, thread, "error", {"stage": "empty_response"})
                    return None
                await execute_tool(ctx, "send_reply", {"body": content})
                if ctx.proposed_action is not None:
                    await self._log(
                        db, thread, "proposal_created",
                        {"action_type": "send_reply", "action_id": str(ctx.proposed_action.id)},
                    )
                return ctx.proposed_action

            # Append the assistant turn, then execute each requested tool.
            messages.append(message)
            for call in tool_calls:
                name = call["function"]["name"]
                try:
                    args = json.loads(call["function"].get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {}
                await self._log(db, thread, "tool_call", {"tool": name, "args": args})

                result = await execute_tool(ctx, name, args)
                await self._log(db, thread, "tool_result", {"tool": name, "result": result})
                if name not in ("send_reply", "escalate"):
                    await self._narrate(_format_tool_result(name, result))

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.get("id", name),
                        "content": json.dumps(result, default=str),
                    }
                )

                if ctx.proposed_action is not None:
                    await self._log(
                        db, thread, "proposal_created",
                        {"action_type": name, "action_id": str(ctx.proposed_action.id)},
                    )
                    return ctx.proposed_action

        await self._log(db, thread, "error", {"stage": "max_steps_exhausted"})
        return None

    async def _build_messages(
        self, db: AsyncSession, thread: Any, account: Any
    ) -> list[dict[str, Any]]:
        """System prompt + the thread's own conversation (scoped memory)."""
        language_code = (
            thread.customer_language.value
            if getattr(thread, "customer_language", None) is not None
            else "nl"
        )
        language_name = _LANGUAGE_NAMES.get(language_code, language_code)
        system = (
            f"You ARE the customer-support representative for {account.marketplace} "
            f"on the {account.marketplace} marketplace. Resolve the customer's issue "
            f"yourself.\n\n"
            f"First use the read tools (get_order, get_tracking, get_invoice, "
            f"search_knowledge) to gather facts — never guess order facts. Then write a "
            f"genuinely helpful, complete reply in {language_name} ({language_code}) and "
            f"submit it with send_reply. Your reply is shown to a human for one-tap "
            f"approval before it is sent, so make it ready-to-send.\n\n"
            f"If you truly cannot resolve it (needs a human decision or data you cannot "
            f"obtain), call escalate with a reason. Do not invent tracking numbers, "
            f"refunds, or promises you cannot support from tool data. Use ONLY this "
            f"conversation as context."
        )
        messages: list[dict[str, Any]] = [{"role": "system", "content": system}]

        rows = (
            await db.execute(
                select(ThreadMessage)
                .where(ThreadMessage.thread_id == thread.id)
                .order_by(ThreadMessage.sequence_number)
            )
        ).scalars().all()

        if rows:
            for m in rows:
                role = "user" if m.author_type == MessageAuthorType.CUSTOMER.value else "assistant"
                body = strip_html(m.body or "")
                if body:
                    messages.append({"role": role, "content": body})
        else:
            # Fallback to the denormalised latest customer message.
            messages.append(
                {"role": "user", "content": strip_html(thread.customer_message or "")}
            )
        return messages

    async def _chat(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """One OpenRouter chat-completions call with tools enabled."""
        payload = {
            "model": settings.AGENT_MODEL,
            "messages": messages,
            "tools": tools,
            "tool_choice": "auto",
            "temperature": 0.3,
        }
        async with httpx.AsyncClient(timeout=45.0) as client:
            response = await client.post(
                f"{settings.LLM_API_BASE_URL}/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.LLM_API_KEY}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
        if response.is_error:
            raise RuntimeError(f"Agent LLM HTTP {response.status_code}: {response.text[:200]}")
        return response.json()

    async def _log(
        self, db: AsyncSession, thread: Any, event_type: str, detail: dict[str, Any]
    ) -> None:
        db.add(
            AgentEvent(
                id=uuid.uuid4(),
                thread_id=getattr(thread, "id", None),
                event_type=event_type,
                detail_json=detail,
            )
        )
        await db.flush()

    async def _narrate(self, text: str) -> None:
        """Post a step line to the Telegram activity channel (best-effort)."""
        if settings.AGENT_TELEGRAM_VERBOSE:
            await self._telegram.send_activity(text)


def _format_tool_result(name: str, result: dict[str, Any]) -> str:
    """One concise activity line summarising a read-tool result."""
    if not isinstance(result, dict):
        return f"🔧 {name}"
    if name == "get_order":
        oid = result.get("order_id", "?")
        status = result.get("status") or "?"
        item = result.get("item")
        tail = f" — {item}" if item else ""
        return f"🔎 <b>Order {oid}</b>: {status}{tail}"
    if name == "get_tracking":
        if not result:
            return "📦 Tracking: geen gegevens"
        return (
            f"📦 Tracking {result.get('tracking_number', '?')} "
            f"({result.get('carrier', '?')}): {result.get('status', '?')} — "
            f"{result.get('last_event', '')}"
        )
    if name == "get_invoice":
        if not result:
            return "🧾 Factuur: geen gegevens"
        return f"🧾 Factuur {result.get('invoice_number', '?')}: {result.get('status', '?')}"
    if name == "search_knowledge":
        n = len(result.get("entries", []))
        return f"📚 Kennisbank: {n} resultaat(en)"
    return f"🔧 {name}"
