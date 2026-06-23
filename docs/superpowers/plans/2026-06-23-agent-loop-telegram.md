# Autonomous Support Agent — Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the template-first, human-writes-everything draft step with a native LLM tool-calling agent that pulls real Mirakl order data, resolves the customer's issue as the rep, and proposes its reply through a Telegram **Approve/Deny** gate — while logging every new thread and every tool call to the same Telegram channel.

**Architecture:** A per-thread agent loop calls the OpenRouter chat-completions API with tool definitions. *Read* tools (order/tracking/invoice/knowledge) execute immediately and feed facts back to the model. The single *action* tool in Phase 1 (`send_reply`) does **not** send — it persists an `agent_actions` proposal and posts a rich Telegram message with inline Approve/Deny buttons. A Telegram webhook executes the Mirakl send only after a human taps Approve. Every step is recorded in an `agent_events` table and mirrored to a Telegram "activity channel". The agent's memory is strictly the thread's own conversation history — no cross-thread or global state.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2 (async), asyncpg, Alembic, httpx (already a dependency — no new packages), OpenRouter (OpenAI-compatible tool calling), Telegram Bot API.

## Global Constraints

- No new runtime dependencies — use `httpx` (already present) for both OpenRouter and Telegram. (Verbatim repo invariant: keep the dependency set minimal.)
- The API process is **single-replica** (`replicas: 1`, `Recreate`) because `app.main:app` runs in-process background loops. Do not add a second replica. (From `k8s/README.md`.)
- **No outbound customer message, return, or refund is ever executed without a human Approve.** Phase 1 only gates `send_reply`; the gate mechanism must be generic enough for later action types.
- Agent memory = the thread's own `thread_messages` only. No global memory, no cross-thread retrieval of other customers' content. (Knowledge-base lookup of company info is allowed; other customers' threads are not injected as memory in Phase 1.)
- All customer-facing copy stays in the customer's language (`thread.customer_language`).
- Secrets (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_WEBHOOK_SECRET`) live in the `omiximo-env` k8s Secret, never in git.
- Alembic head before this work: `010`. New migration is `011`.
- Reuse existing primitives: `MiraklClient(account).send_reply(thread_id, body)`, the `connectors/` (`MiraklConnector`, `TrackingConnector`, `InvoiceConnector`) each exposing `async fetch_context(order_id) -> dict`, `KnowledgeService.retrieve_for_draft(...)`, `write_audit_log(...)`, `strip_html(...)`.

---

## File Structure

**New files**
- `backend/app/services/telegram.py` — Telegram Bot API client (send activity, send approval request, edit message on decision).
- `backend/app/models/agent_action.py` — `agent_actions` table (the permission-gate proposals).
- `backend/app/models/agent_event.py` — `agent_events` table (agent activity / tool-call log).
- `backend/app/services/agent/__init__.py`
- `backend/app/services/agent/tools.py` — tool registry: JSON schemas + Python implementations (read tools + `send_reply`/`escalate`).
- `backend/app/services/agent/runner.py` — the LLM tool-calling loop (`AgentRunner.run_for_thread`).
- `backend/app/api/telegram.py` — `POST /api/v1/telegram/webhook` (button callbacks → execute approved action).
- `backend/alembic/versions/011_agent_actions_events.py` — migration for both new tables.
- Tests: `backend/tests/test_telegram_service.py`, `test_agent_tools.py`, `test_agent_runner.py`, `test_agent_actions_model.py`, `test_telegram_webhook.py`, `test_agent_pipeline_integration.py`.

**Modified files**
- `backend/app/config.py` — add Telegram + agent settings.
- `backend/app/models/__init__.py` — export new models.
- `backend/app/services/draft_pipeline.py` — route ORANGE/GREEN drafting through `AgentRunner`; keep classification + RED-escalate.
- `backend/app/services/collector.py` — post a Telegram activity line when a new thread is collected.
- `backend/app/api/router.py` — mount the (unprotected) telegram webhook router.

---

## Task 0: Config + settings

**Files:**
- Modify: `backend/app/config.py`
- Test: `backend/tests/test_config_agent.py`

**Interfaces:**
- Produces settings: `TELEGRAM_BOT_TOKEN: str`, `TELEGRAM_CHAT_ID: str`, `TELEGRAM_WEBHOOK_SECRET: str`, `AGENT_ENABLED: bool`, `AGENT_MODEL: str`, `AGENT_MAX_STEPS: int`, `PUBLIC_BASE_URL: str`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_config_agent.py
from app.config import Settings

def test_agent_settings_have_safe_defaults():
    s = Settings(_env_file=None)
    assert s.AGENT_ENABLED is False            # off until explicitly enabled
    assert s.AGENT_MODEL                        # non-empty default
    assert s.AGENT_MAX_STEPS >= 1
    assert s.TELEGRAM_BOT_TOKEN == ""           # secret, empty by default
```

- [ ] **Step 2: Run test, expect failure** — `pytest tests/test_config_agent.py -v` → FAIL (attrs missing).

- [ ] **Step 3: Add settings** to the `Settings` class in `config.py`:

```python
    # --- Telegram activity channel + approval gate ---
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_CHAT_ID: str = ""           # chat/group the bot posts to
    TELEGRAM_WEBHOOK_SECRET: str = ""    # X-Telegram-Bot-Api-Secret-Token value

    # --- Autonomous agent ---
    AGENT_ENABLED: bool = False
    AGENT_MODEL: str = "google/gemini-2.5-flash"   # tool-calling capable on OpenRouter
    AGENT_MAX_STEPS: int = 6                        # max tool-call iterations per thread
    PUBLIC_BASE_URL: str = "https://api-support.abbamarkt.nl"  # for setWebhook
```

- [ ] **Step 4: Run test, expect pass.**

- [ ] **Step 5: Commit** — `git commit -am "feat(agent): add telegram + agent settings"`

---

## Task 1: `agent_actions` and `agent_events` models + migration

**Files:**
- Create: `backend/app/models/agent_action.py`, `backend/app/models/agent_event.py`
- Modify: `backend/app/models/__init__.py`
- Create: `backend/alembic/versions/011_agent_actions_events.py`
- Test: `backend/tests/test_agent_actions_model.py`

**Interfaces:**
- Produces `AgentAction` with columns: `id: uuid`, `thread_id: uuid (FK support_threads.id)`, `action_type: str` (`"send_reply"`/`"escalate"`), `status: str` (`"proposed"|"approved"|"denied"|"executed"|"failed"`), `payload_json: JSON` (e.g. `{"body": "..."}`), `telegram_message_id: int|None`, `decided_by: str|None`, `result_json: JSON|None`, `created_at`, `decided_at: datetime|None`.
- Produces `AgentEvent`: `id`, `thread_id`, `event_type: str` (`"thread_received"|"tool_call"|"tool_result"|"agent_message"|"proposal_created"|"action_executed"|"error"`), `detail_json: JSON`, `created_at`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_agent_actions_model.py
import uuid
import pytest
from app.models.agent_action import AgentAction, ActionStatus
from app.models.agent_event import AgentEvent

@pytest.mark.asyncio
async def test_agent_action_roundtrip(db_session):
    a = AgentAction(
        id=uuid.uuid4(), thread_id=None, action_type="send_reply",
        status=ActionStatus.PROPOSED.value, payload_json={"body": "Hallo"},
    )
    db_session.add(a); await db_session.flush()
    assert a.status == "proposed"

@pytest.mark.asyncio
async def test_agent_event_roundtrip(db_session):
    e = AgentEvent(id=uuid.uuid4(), thread_id=None,
                   event_type="tool_call", detail_json={"tool": "get_order"})
    db_session.add(e); await db_session.flush()
    assert e.event_type == "tool_call"
```

- [ ] **Step 2: Run, expect FAIL** (modules missing).

- [ ] **Step 3: Implement models.**

```python
# backend/app/models/agent_action.py
from __future__ import annotations
import enum, uuid
from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base

class ActionStatus(str, enum.Enum):
    PROPOSED = "proposed"
    APPROVED = "approved"
    DENIED = "denied"
    EXECUTED = "executed"
    FAILED = "failed"

class AgentAction(Base):
    __tablename__ = "agent_actions"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    thread_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("support_threads.id", ondelete="CASCADE"), nullable=True, index=True)
    action_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=ActionStatus.PROPOSED.value, index=True)
    payload_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    telegram_message_id: Mapped[int | None] = mapped_column(nullable=True)
    decided_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    result_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
```

```python
# backend/app/models/agent_event.py
from __future__ import annotations
import uuid
from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base

class AgentEvent(Base):
    __tablename__ = "agent_events"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    thread_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("support_threads.id", ondelete="CASCADE"), nullable=True, index=True)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    detail_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
```

Add to `backend/app/models/__init__.py`:

```python
from app.models.agent_action import AgentAction, ActionStatus  # noqa: F401
from app.models.agent_event import AgentEvent  # noqa: F401
```

- [ ] **Step 4: Write the migration** `011_agent_actions_events.py` (`down_revision = "010"`), creating both tables with the columns above + indexes on `thread_id`, `status`, `created_at`.

- [ ] **Step 5: Run tests + `alembic upgrade head` against a scratch DB, expect PASS / clean upgrade.**

- [ ] **Step 6: Commit** — `git commit -am "feat(agent): agent_actions + agent_events models and migration 011"`

---

## Task 2: Telegram service

**Files:**
- Create: `backend/app/services/telegram.py`
- Test: `backend/tests/test_telegram_service.py`

**Interfaces:**
- Produces `TelegramService` with:
  - `async send_activity(text: str) -> int | None` — posts plain text to `TELEGRAM_CHAT_ID`, returns message_id.
  - `async send_approval_request(*, action_id: uuid.UUID, title: str, body: str) -> int | None` — posts a message with inline keyboard `[[✅ Approve | ❌ Deny]]`, callback_data `approve:{action_id}` / `deny:{action_id}`. Returns message_id.
  - `async resolve_message(*, message_id: int, decision: str, footer: str) -> None` — edits the message (removes buttons, appends decision footer).
  - No-ops gracefully (returns `None`) when `TELEGRAM_BOT_TOKEN` is empty, so the system runs without Telegram configured.

- [ ] **Step 1: Write the failing test** (mock httpx with `respx` or monkeypatch `_post`):

```python
# backend/tests/test_telegram_service.py
import uuid, pytest
from app.services.telegram import TelegramService

@pytest.mark.asyncio
async def test_send_activity_noop_without_token(monkeypatch):
    svc = TelegramService(token="", chat_id="")
    assert await svc.send_activity("hi") is None

@pytest.mark.asyncio
async def test_send_approval_request_builds_inline_keyboard(monkeypatch):
    captured = {}
    async def fake_post(method, payload):
        captured["method"] = method; captured["payload"] = payload
        return {"ok": True, "result": {"message_id": 42}}
    svc = TelegramService(token="t", chat_id="99")
    monkeypatch.setattr(svc, "_post", fake_post)
    aid = uuid.uuid4()
    mid = await svc.send_approval_request(action_id=aid, title="Reply ready", body="Hallo")
    assert mid == 42
    kb = captured["payload"]["reply_markup"]["inline_keyboard"][0]
    assert kb[0]["callback_data"] == f"approve:{aid}"
    assert kb[1]["callback_data"] == f"deny:{aid}"
```

- [ ] **Step 2: Run, expect FAIL.**

- [ ] **Step 3: Implement.**

```python
# backend/app/services/telegram.py
from __future__ import annotations
import logging, uuid
from typing import Any
import httpx
from app.config import settings

logger = logging.getLogger(__name__)

class TelegramService:
    def __init__(self, token: str | None = None, chat_id: str | None = None) -> None:
        self._token = token if token is not None else settings.TELEGRAM_BOT_TOKEN
        self._chat_id = chat_id if chat_id is not None else settings.TELEGRAM_CHAT_ID

    @property
    def enabled(self) -> bool:
        return bool(self._token and self._chat_id)

    async def _post(self, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"https://api.telegram.org/bot{self._token}/{method}"
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(url, json=payload)
        data = resp.json()
        if not data.get("ok"):
            raise RuntimeError(f"Telegram {method} failed: {str(data)[:200]}")
        return data

    async def send_activity(self, text: str) -> int | None:
        if not self.enabled:
            return None
        try:
            data = await self._post("sendMessage", {
                "chat_id": self._chat_id, "text": text,
                "parse_mode": "HTML", "disable_web_page_preview": True,
            })
            return data["result"]["message_id"]
        except Exception as exc:
            logger.warning("Telegram send_activity failed: %s", exc)
            return None

    async def send_approval_request(self, *, action_id: uuid.UUID, title: str, body: str) -> int | None:
        if not self.enabled:
            return None
        text = f"<b>{title}</b>\n\n{body}"
        markup = {"inline_keyboard": [[
            {"text": "✅ Approve", "callback_data": f"approve:{action_id}"},
            {"text": "❌ Deny", "callback_data": f"deny:{action_id}"},
        ]]}
        try:
            data = await self._post("sendMessage", {
                "chat_id": self._chat_id, "text": text,
                "parse_mode": "HTML", "reply_markup": markup,
                "disable_web_page_preview": True,
            })
            return data["result"]["message_id"]
        except Exception as exc:
            logger.warning("Telegram send_approval_request failed: %s", exc)
            return None

    async def resolve_message(self, *, message_id: int, decision: str, footer: str) -> None:
        if not self.enabled:
            return
        try:
            await self._post("editMessageReplyMarkup", {
                "chat_id": self._chat_id, "message_id": message_id,
                "reply_markup": {"inline_keyboard": []},
            })
            await self._post("sendMessage", {
                "chat_id": self._chat_id, "text": f"{decision} — {footer}",
                "reply_to_message_id": message_id, "parse_mode": "HTML",
            })
        except Exception as exc:
            logger.warning("Telegram resolve_message failed: %s", exc)
```

- [ ] **Step 4: Run tests, expect PASS.**

- [ ] **Step 5: Commit** — `git commit -am "feat(agent): Telegram service (activity + approval gate)"`

---

## Task 3: Tool layer

**Files:**
- Create: `backend/app/services/agent/__init__.py`, `backend/app/services/agent/tools.py`
- Test: `backend/tests/test_agent_tools.py`

**Interfaces:**
- Produces `TOOL_SCHEMAS: list[dict]` — OpenAI/OpenRouter tool definitions for: `get_order`, `get_tracking`, `get_invoice`, `search_knowledge`, `send_reply`, `escalate`.
- Produces `class ToolContext` holding `db`, `thread`, `account`, `telegram`, and accumulating `proposed_action: AgentAction | None`.
- Produces `async execute_tool(ctx: ToolContext, name: str, args: dict) -> dict` — runs a read tool and returns data, or for `send_reply`/`escalate` creates an `AgentAction` (status `proposed`) + Telegram approval and returns `{"status": "awaiting_approval"}`. Read tools never raise (connectors return `{}` on missing data).

- [ ] **Step 1: Write failing tests** for (a) `get_order` calls the Mirakl connector and returns its dict, (b) `send_reply` creates a proposed `AgentAction` and calls `telegram.send_approval_request`, and (c) unknown tool name returns an error dict. Use a fake connector + fake telegram.

```python
# backend/tests/test_agent_tools.py (excerpt)
@pytest.mark.asyncio
async def test_send_reply_creates_proposal_and_requests_approval(db_session, fake_thread, fake_account):
    sent = {}
    class FakeTg:
        enabled = True
        async def send_approval_request(self, **kw): sent.update(kw); return 7
    ctx = ToolContext(db=db_session, thread=fake_thread, account=fake_account, telegram=FakeTg())
    out = await execute_tool(ctx, "send_reply", {"body": "Hallo, ..."})
    assert out["status"] == "awaiting_approval"
    assert ctx.proposed_action is not None
    assert ctx.proposed_action.payload_json["body"] == "Hallo, ..."
    assert ctx.proposed_action.telegram_message_id == 7
    assert "Hallo" in sent["body"]
```

- [ ] **Step 2: Run, expect FAIL.**

- [ ] **Step 3: Implement `tools.py`.** Read tools delegate to connectors:

```python
# backend/app/services/agent/tools.py (core)
from __future__ import annotations
import uuid
from dataclasses import dataclass, field
from typing import Any
from app.models.agent_action import AgentAction, ActionStatus
from app.services.connectors.mirakl import MiraklConnector
from app.services.connectors.tracking import TrackingConnector
from app.services.connectors.invoice import InvoiceConnector
from app.services.knowledge_service import KnowledgeService

TOOL_SCHEMAS: list[dict] = [
    {"type": "function", "function": {"name": "get_order",
     "description": "Fetch order details (status, items, customer) for the thread's order.",
     "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {"name": "get_tracking",
     "description": "Fetch carrier tracking status for the thread's order.",
     "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {"name": "get_invoice",
     "description": "Fetch invoice/billing info for the thread's order.",
     "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {"name": "search_knowledge",
     "description": "Search company knowledge base for policies/answers.",
     "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}},
    {"type": "function", "function": {"name": "send_reply",
     "description": "Propose the final reply to the customer. Requires human approval before it is sent.",
     "parameters": {"type": "object", "properties": {"body": {"type": "string"}}, "required": ["body"]}}},
    {"type": "function", "function": {"name": "escalate",
     "description": "Escalate to a human when you cannot resolve the issue.",
     "parameters": {"type": "object", "properties": {"reason": {"type": "string"}}, "required": ["reason"]}}},
]

@dataclass
class ToolContext:
    db: Any
    thread: Any
    account: Any
    telegram: Any
    proposed_action: AgentAction | None = None
    events: list[dict] = field(default_factory=list)

async def execute_tool(ctx: ToolContext, name: str, args: dict) -> dict:
    order_id = ctx.thread.mirakl_order_id
    if name == "get_order":
        return await MiraklConnector(ctx.account).fetch_context(order_id)
    if name == "get_tracking":
        return await TrackingConnector(ctx.account).fetch_context(order_id)
    if name == "get_invoice":
        return await InvoiceConnector(ctx.account).fetch_context(order_id)
    if name == "search_knowledge":
        svc = KnowledgeService()
        entries = await svc.retrieve_for_draft(
            ctx.db, category=ctx.thread.category or "", marketplace=ctx.account.marketplace,
            language=ctx.thread.customer_language)
        return {"entries": [getattr(e, "content", "") for e in entries]}
    if name in ("send_reply", "escalate"):
        return await _propose_action(ctx, name, args)
    return {"error": f"unknown tool {name}"}

async def _propose_action(ctx: ToolContext, action_type: str, args: dict) -> dict:
    action = AgentAction(
        id=uuid.uuid4(), thread_id=ctx.thread.id, action_type=action_type,
        status=ActionStatus.PROPOSED.value, payload_json=args)
    ctx.db.add(action); await ctx.db.flush()
    if action_type == "send_reply":
        title = f"Reply ready — order {ctx.thread.mirakl_order_id}"
        body = args.get("body", "")
    else:
        title = f"Escalation — order {ctx.thread.mirakl_order_id}"
        body = args.get("reason", "")
    mid = await ctx.telegram.send_approval_request(action_id=action.id, title=title, body=body)
    action.telegram_message_id = mid
    await ctx.db.flush()
    ctx.proposed_action = action
    return {"status": "awaiting_approval", "action_id": str(action.id)}
```

- [ ] **Step 4: Run tests, expect PASS.**

- [ ] **Step 5: Commit** — `git commit -am "feat(agent): tool layer (read tools + approval-gated send_reply)"`

---

## Task 4: Agent runner (LLM tool-calling loop)

**Files:**
- Create: `backend/app/services/agent/runner.py`
- Test: `backend/tests/test_agent_runner.py`

**Interfaces:**
- Produces `class AgentRunner` with `async run_for_thread(db, *, thread, account) -> AgentAction | None`.
- Consumes `TOOL_SCHEMAS`, `ToolContext`, `execute_tool` (Task 3); `TelegramService` (Task 2); `AgentEvent` (Task 1).
- Behaviour: builds messages = `[system_prompt] + thread conversation history (scoped memory)`. Loops up to `AGENT_MAX_STEPS`: POST to `{LLM_API_BASE_URL}/chat/completions` with `model=AGENT_MODEL`, `tools=TOOL_SCHEMAS`. If the model returns `tool_calls`, execute each via `execute_tool`, append results as `role:"tool"` messages, log an `AgentEvent("tool_call")`. Stop when a `send_reply`/`escalate` proposal is created (returns the `AgentAction`) or steps exhausted (logs `error`, returns `None`). Each LLM call is wrapped so the loop never crashes the pipeline.

- [ ] **Step 1: Write the failing test** with a fake LLM transport that first asks for `get_order`, then calls `send_reply`:

```python
# backend/tests/test_agent_runner.py (excerpt)
@pytest.mark.asyncio
async def test_runner_uses_tools_then_proposes_reply(db_session, fake_thread, fake_account, monkeypatch):
    calls = iter([
        {"choices": [{"message": {"role": "assistant", "tool_calls": [
            {"id": "c1", "type": "function", "function": {"name": "get_order", "arguments": "{}"}}]}}]},
        {"choices": [{"message": {"role": "assistant", "tool_calls": [
            {"id": "c2", "type": "function", "function": {"name": "send_reply", "arguments": "{\"body\": \"Hallo\"}"}}]}}]},
    ])
    async def fake_chat(self, messages, tools): return next(calls)
    monkeypatch.setattr(AgentRunner, "_chat", fake_chat)
    runner = AgentRunner(telegram=FakeTelegram())
    action = await runner.run_for_thread(db_session, thread=fake_thread, account=fake_account)
    assert action is not None and action.action_type == "send_reply"
    assert action.payload_json["body"] == "Hallo"
```

- [ ] **Step 2: Run, expect FAIL.**

- [ ] **Step 3: Implement `runner.py`** — `_chat()` does the httpx POST (mirrors `smart_draft._call_llm` but adds `tools`); `run_for_thread()` builds the scoped-memory message list and runs the loop, writing `AgentEvent` rows and returning the proposed `AgentAction`. System prompt (verbatim intent):

```
You ARE the customer-support representative for {shop} on the {marketplace} marketplace.
Resolve the customer's issue yourself. First use the read tools (get_order, get_tracking,
get_invoice, search_knowledge) to gather facts — never guess order facts. Then write a
genuinely helpful reply in {language} and submit it with send_reply. Your reply will be
shown to a human for one-tap approval before it is sent, so be concrete and complete.
If you truly cannot resolve it (needs a human decision/data you can't get), call escalate.
Use ONLY this thread's conversation as context. Do not invent tracking numbers, refunds,
or promises you cannot support from tool data.
```

Conversation memory is built from `thread_messages` ordered by `sequence_number` (customer = `role:"user"`, shop/operator = `role:"assistant"`).

- [ ] **Step 4: Run tests, expect PASS.**

- [ ] **Step 5: Commit** — `git commit -am "feat(agent): tool-calling agent runner with thread-scoped memory"`

---

## Task 5: Pipeline + collector integration

**Files:**
- Modify: `backend/app/services/draft_pipeline.py` (ORANGE/GREEN branches → `AgentRunner.run_for_thread`)
- Modify: `backend/app/services/collector.py` (Telegram activity on `thread_collected`)
- Test: `backend/tests/test_agent_pipeline_integration.py`

**Interfaces:**
- Consumes `AgentRunner`, `TelegramService`.
- When `AGENT_ENABLED` is true: after classification, for non-RED threads call `AgentRunner.run_for_thread`; the produced `AgentAction` (proposed, awaiting approval) leaves the thread `PENDING_REVIEW`. RED still escalates with no draft. When `AGENT_ENABLED` is false, the existing template/smart_draft path runs unchanged (safe rollback).
- On new thread collected, post `🆕 New thread — order {order} ({marketplace}) — "{first 120 chars}"` to the activity channel.

- [ ] **Step 1: Write failing test** asserting that with `AGENT_ENABLED=True` a collected+classified ORANGE thread yields a `proposed` `AgentAction` and a `proposal_created` `AgentEvent`, and that the legacy path is used when disabled.

- [ ] **Step 2: Run, expect FAIL.**

- [ ] **Step 3: Implement** the branch in `_process_single` (guard on `settings.AGENT_ENABLED`) and the `telegram.send_activity(...)` call in the collector's new-thread path (after the `thread_collected` audit write). Keep all existing audit_log writes.

- [ ] **Step 4: Run tests, expect PASS.**

- [ ] **Step 5: Commit** — `git commit -am "feat(agent): route drafting through agent loop + new-thread activity feed"`

---

## Task 6: Telegram webhook — execute approved actions

**Files:**
- Create: `backend/app/api/telegram.py`
- Modify: `backend/app/api/router.py` (mount unprotected, like `webhooks_router`)
- Test: `backend/tests/test_telegram_webhook.py`

**Interfaces:**
- `POST /api/v1/telegram/webhook` — validates header `X-Telegram-Bot-Api-Secret-Token == TELEGRAM_WEBHOOK_SECRET`; parses `callback_query.data` = `approve:{id}` / `deny:{id}`; loads the `AgentAction`.
  - **deny** → status `denied`, `decided_at`, edit Telegram message → "❌ Denied".
  - **approve** → for `send_reply`: load thread+account, `MiraklClient(account).send_reply(thread.mirakl_thread_id, payload["body"])`, set thread `status=SENT_AUTO`, action `executed` (or `failed` on Mirakl error), write `auto_sent` audit + `action_executed` AgentEvent, edit Telegram message → "✅ Sent".
- Idempotent: a callback for an already-decided action returns 200 and does nothing (Telegram retries).

- [ ] **Step 1: Write failing tests:** (a) wrong secret → 403; (b) `approve:{id}` on a `send_reply` proposal calls Mirakl send once and marks `executed`; (c) re-delivery of the same callback does not double-send.

- [ ] **Step 2: Run, expect FAIL.**

- [ ] **Step 3: Implement** the endpoint + router mount. Use a fake/injected MiraklClient in tests.

- [ ] **Step 4: Run tests, expect PASS.**

- [ ] **Step 5: Commit** — `git commit -am "feat(agent): telegram webhook executes approved send_reply"`

---

## Task 7: Wire-up, rollout, and live smoke test

**Files:** none new (ops + docs).

- [ ] **Step 1:** Add `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `TELEGRAM_WEBHOOK_SECRET`, `AGENT_ENABLED=false` to the `omiximo-env` secret (`kubectl create secret ... --dry-run -o yaml | kubectl apply`). Keep `AGENT_ENABLED=false` initially.
- [ ] **Step 2:** Build + import the new API image (`docker build -t omiximo-api:prod backend` → `k3s ctr images import`), `kubectl rollout restart deploy/api` (migration `011` runs in the init container).
- [ ] **Step 3:** Register the Telegram webhook: `setWebhook` to `https://api-support.abbamarkt.nl/api/v1/telegram/webhook` with `secret_token=$TELEGRAM_WEBHOOK_SECRET`. Confirm host nginx routes `/api/v1/telegram/webhook` to NodePort 30800 (add a `location` if the conf only proxies specific paths).
- [ ] **Step 4:** Smoke test with Telegram still gating but agent **off**: send a test activity message via the bot to confirm token/chat/webhook all work end-to-end.
- [ ] **Step 5:** Enable for one thread: set `AGENT_ENABLED=true`, watch the activity channel show 🆕 new-thread + tool calls, receive an Approve/Deny card, tap Approve, confirm the reply lands in Mirakl and the thread flips to `SENT_AUTO`. Then decide on broader rollout.
- [ ] **Step 6:** Update `k8s/README.md` + `PROJECT.md` with the agent flow, the `AGENT_ENABLED` kill-switch, and the webhook registration step. Commit.

---

## Self-Review

- **Spec coverage:** agent loop (Tasks 3–5) ✓; real Mirakl data (Task 3 read tools via existing connectors) ✓; Telegram Approve/Deny on send_reply (Tasks 2, 6) ✓; logging of actions/tool-calls (`agent_events`, Task 1; written in Tasks 4–6) ✓; new-thread activity channel (Task 5) ✓; permissions gate (Tasks 3 + 6, no execution without Approve) ✓; thread-scoped memory (Task 4 system prompt + message build) ✓.
- **Kill switch:** `AGENT_ENABLED=false` restores the exact current behaviour — safe rollback at every step.
- **No new dependencies:** OpenRouter + Telegram both over `httpx`.
- **Out of Phase 1 (documented, not built):** `approve_return` / `issue_refund` Mirakl actions, Hermes self-improvement loop, vector/cross-thread memory. The gate (`AgentAction.action_type`) and the webhook dispatch are written generically so these slot in as new `action_type`s later.
