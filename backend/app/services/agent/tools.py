"""Agent tool registry: schemas + implementations.

Two kinds of tools:

* **Read tools** (`get_order`, `get_tracking`, `get_invoice`, `search_knowledge`)
  run immediately and return facts the model uses to write its reply. They never
  raise — connectors return ``{}`` on missing data.

* **Action tools** (`send_reply`, `escalate`) do NOT act. They persist an
  ``AgentAction`` (status ``proposed``) and push a Telegram Approve/Deny card.
  The action only executes later, from the Telegram webhook, after a human
  approves. This is the permission gate.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.agent_action import ActionStatus, AgentAction
from app.models.thread_message import ThreadMessage
from app.services.agent.cards import build_action_card, toolbar
from app.services.connectors.invoice import InvoiceConnector
from app.services.connectors.mirakl import MiraklConnector
from app.services.connectors.tracking import TrackingConnector
from app.services.knowledge_service import KnowledgeService

# OpenAI/OpenRouter-compatible tool definitions.
TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "get_order",
            "description": "Fetch order details (status, items, shipping, customer) for this thread's order.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_tracking",
            "description": "Fetch carrier tracking status for this thread's order.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_invoice",
            "description": "Fetch invoice / billing information for this thread's order.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_knowledge",
            "description": "Search the company knowledge base for policies and answers.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string", "description": "What to look up."}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "send_reply",
            "description": (
                "Submit the final reply to the customer. This does not send "
                "immediately — a human approves it first. Write the complete, "
                "ready-to-send message."
            ),
            "parameters": {
                "type": "object",
                "properties": {"body": {"type": "string", "description": "The full reply text."}},
                "required": ["body"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "escalate",
            "description": "Hand off to a human when you cannot resolve the issue yourself.",
            "parameters": {
                "type": "object",
                "properties": {"reason": {"type": "string", "description": "Why it needs a human."}},
                "required": ["reason"],
            },
        },
    },
]

# Tool names that create a human-gated proposal rather than returning data.
ACTION_TOOLS = {"send_reply", "escalate"}
# Tool names that fetch facts the agent reasons over (and the card displays).
READ_TOOLS = {"get_order", "get_tracking", "get_invoice", "search_knowledge"}


@dataclass
class ToolContext:
    """Per-thread state threaded through tool execution."""

    db: AsyncSession
    thread: Any
    account: Any
    telegram: Any
    proposed_action: AgentAction | None = None
    # Latest result of each read tool, keyed by tool name. Populated as the
    # agent gathers facts so the approval card can show what it knew.
    facts: dict[str, Any] = field(default_factory=dict)


async def execute_tool(ctx: ToolContext, name: str, args: dict[str, Any]) -> dict[str, Any]:
    """Run a tool by name. Read tools return data; action tools create proposals."""
    if name in ACTION_TOOLS:
        return await _propose_action(ctx, name, args)
    if name in READ_TOOLS:
        result = await _run_read_tool(ctx, name)
        ctx.facts[name] = result
        return result
    return {"error": f"unknown tool {name}"}


async def _run_read_tool(ctx: ToolContext, name: str) -> dict[str, Any]:
    """Fetch facts for a read tool. Never raises — connectors return ``{}``."""
    order_id = ctx.thread.mirakl_order_id

    if settings.AGENT_FAKE_MIRAKL and name in ("get_order", "get_tracking", "get_invoice"):
        from app.services.agent import fake_mirakl

        return {
            "get_order": fake_mirakl.fake_order,
            "get_tracking": fake_mirakl.fake_tracking,
            "get_invoice": fake_mirakl.fake_invoice,
        }[name](order_id)

    if name == "get_order":
        return await MiraklConnector(ctx.account).fetch_context(order_id)
    if name == "get_tracking":
        return await TrackingConnector(ctx.account).fetch_context(order_id)
    if name == "get_invoice":
        return await InvoiceConnector(ctx.account).fetch_context(order_id)
    # search_knowledge
    language = (
        ctx.thread.customer_language.value
        if getattr(ctx.thread, "customer_language", None) is not None
        else None
    )
    entries = await KnowledgeService().retrieve_for_draft(
        ctx.db,
        category=ctx.thread.category or "",
        marketplace=ctx.account.marketplace,
        language=language,
    )
    return {
        "entries": [
            {"title": getattr(e, "title", ""), "content": getattr(e, "content", "")}
            for e in entries
        ]
    }


async def _thread_messages(db: AsyncSession, thread_id: Any) -> list[ThreadMessage]:
    """The thread's conversation turns, oldest first (for the card history)."""
    rows = (
        await db.execute(
            select(ThreadMessage)
            .where(ThreadMessage.thread_id == thread_id)
            .order_by(ThreadMessage.sequence_number)
        )
    ).scalars().all()
    return list(rows)


async def _propose_action(
    ctx: ToolContext, action_type: str, args: dict[str, Any]
) -> dict[str, Any]:
    """Persist a proposed action and request human approval via Telegram."""
    action = AgentAction(
        id=uuid.uuid4(),
        thread_id=ctx.thread.id,
        action_type=action_type,
        status=ActionStatus.PROPOSED.value,
        payload_json=args,
    )
    ctx.db.add(action)
    await ctx.db.flush()

    body = args.get("body", "") if action_type == "send_reply" else args.get("reason", "")
    # Snapshot the gathered facts so the card can be re-rendered later (edit/translate).
    action.context_json = {"facts": ctx.facts}
    messages = await _thread_messages(ctx.db, ctx.thread.id)
    text = build_action_card(
        action_type=action_type,
        thread=ctx.thread,
        facts=ctx.facts,
        body=body,
        messages=messages,
    )
    markup = toolbar(action_type, action.id, "proposed")
    message_id = await ctx.telegram.send_card(text, markup)
    action.telegram_message_id = message_id
    await ctx.db.flush()

    ctx.proposed_action = action
    return {"status": "awaiting_approval", "action_id": str(action.id)}
