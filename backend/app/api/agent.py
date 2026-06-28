"""Agent test-run endpoint — fire a synthetic thread through the full agent loop.

Test/polish tool. Active ONLY when ``settings.AGENT_FAKE_MIRAKL`` is True, so it
cannot be used against the real marketplace. It injects a synthetic thread with
fake Mirakl order data, runs the tool-calling agent, and posts the whole
workflow (classification → tool lookups → drafted reply → Approve/Deny card) to
the Telegram activity channel — without enabling the agent on real customer
threads.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models.marketplace_account import MarketplaceAccount
from app.models.support_thread import (
    CustomerLanguage,
    ReplyState,
    RiskLevel,
    SupportThread,
    ThreadStatus,
)
from app.services.agent.fake_mirakl import DEFAULT_SCENARIO, SCENARIOS
from app.services.agent.runner import AgentRunner
from app.services.telegram import TelegramService

router = APIRouter(prefix="/agent", tags=["agent"])


class TestRunRequest(BaseModel):
    scenario: str | None = None          # key in fake_mirakl.SCENARIOS
    customer_message: str | None = None  # override the scenario's message


class TestRunResponse(BaseModel):
    thread_id: str
    action_id: str | None
    scenario: str


@router.post("/test-run", response_model=TestRunResponse)
async def agent_test_run(
    payload: TestRunRequest, db: AsyncSession = Depends(get_db)
) -> TestRunResponse:
    if not settings.AGENT_FAKE_MIRAKL:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="test-run is only available when AGENT_FAKE_MIRAKL is enabled",
        )

    scenario = payload.scenario if payload.scenario in SCENARIOS else DEFAULT_SCENARIO
    sc = SCENARIOS[scenario]
    order = sc["order"]
    customer_message = payload.customer_message or sc["customer_message"]

    account = (
        await db.execute(
            select(MarketplaceAccount).where(MarketplaceAccount.is_active.is_(True)).limit(1)
        )
    ).scalar_one_or_none()
    if account is None:
        raise HTTPException(status_code=400, detail="no active marketplace account")

    thread = SupportThread(
        id=uuid.uuid4(),
        mirakl_thread_id=f"TEST-{uuid.uuid4().hex[:8]}",
        mirakl_order_id=order["order_id"],
        marketplace_account_id=account.id,
        customer_message=customer_message,
        operator_required=False,
        status=ThreadStatus.PENDING_REVIEW,
        reply_state=ReplyState.NEEDS_REPLY.value,
        response_deadline=datetime.now(UTC) + timedelta(hours=24),
        category="complaint",
        risk_level=RiskLevel.ORANGE,
        customer_language=CustomerLanguage.nl,
    )
    db.add(thread)
    await db.flush()

    telegram = TelegramService()
    await telegram.send_activity(
        f"🧪 <b>Test thread</b> — order {order['order_id']} ({account.marketplace})\n{customer_message}"
    )
    # Classification + order facts are now folded into the approval card itself
    # (app.services.agent.cards), so no separate narration line for them here.

    action = await AgentRunner(telegram=telegram).run_for_thread(
        db, thread=thread, account=account
    )
    await db.commit()

    return TestRunResponse(
        thread_id=str(thread.id),
        action_id=str(action.id) if action else None,
        scenario=scenario,
    )
