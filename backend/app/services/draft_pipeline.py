"""Draft pipeline — the central orchestrator.

This single entry point ties together:
  collector      → thread_collected
  classifier     → classified
  template_engine → draft_generated (or llm_fallback_draft for ORANGE)
  safety_rules   → safety_validated / safety_blocked
  auto-send      → auto_sent (GREEN only, after safety pass)

Every step emits an audit_log row. Any unhandled exception marks the thread
FAILED and writes a pipeline_failed audit entry.

Usage (called by the background polling task):
    pipeline = DraftPipeline()
    async with AsyncSessionLocal() as db:
        await pipeline.process_new_threads(db)
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.marketplace_account import MarketplaceAccount
from app.models.support_thread import ReplyState, RiskLevel, SupportThread, ThreadStatus
from app.services.audit import write_audit_log
from app.services.classifier import ClassificationResult, MessageClassifier
from app.services.mirakl_client import MiraklClient
from app.services.safety_rules import SafetyRules
from app.services.smart_draft import SmartDraftService
from app.services.template_engine import TemplateEngine

logger = logging.getLogger(__name__)


class DraftPipeline:
    """Orchestrates the full classify → draft → validate → (auto-send) pipeline.

    Args:
        classifier:     MessageClassifier instance. Pass mock_mode=True for tests.
        template_engine: TemplateEngine instance.
        safety_rules:   SafetyRules instance.
    """

    def __init__(
        self,
        classifier: MessageClassifier | None = None,
        template_engine: TemplateEngine | None = None,
        safety_rules: SafetyRules | None = None,
        smart_draft_service: SmartDraftService | None = None,
    ) -> None:
        self._classifier = classifier or MessageClassifier()
        self._template_engine = template_engine or TemplateEngine()
        self._safety_rules = safety_rules or SafetyRules()
        self._smart_draft_service = smart_draft_service or SmartDraftService()

    async def process_new_threads(self, db: AsyncSession) -> int:
        """Process all PENDING_REVIEW threads that have not yet been classified.

        A thread is eligible for processing when:
          - status == PENDING_REVIEW
          - risk_level IS NULL (not yet classified)
          - reply_state == NEEDS_REPLY (the customer is waiting on us)

        Threads that are already handled (AWAITING_CUSTOMER / RESOLVED) are
        imported for visibility but never classified or drafted.

        Args:
            db: Database session. This method commits after each thread.

        Returns:
            Number of threads successfully processed (draft generated or escalated).
        """
        stmt = select(SupportThread).where(
            SupportThread.status == ThreadStatus.PENDING_REVIEW,
            SupportThread.risk_level.is_(None),
            SupportThread.reply_state == ReplyState.NEEDS_REPLY.value,
        )
        result = await db.execute(stmt)
        threads = list(result.scalars().all())

        processed = 0
        for thread in threads:
            try:
                await self._process_single(db, thread)
                processed += 1
            except Exception as exc:
                logger.exception(
                    "Pipeline failed for thread %s: %s",
                    thread.id,
                    exc,
                )
                thread.status = ThreadStatus.FAILED
                thread.updated_at = datetime.now(UTC)
                await write_audit_log(
                    db,
                    action="pipeline_failed",
                    actor="system",
                    thread_id=thread.id,
                    detail={"error": str(exc), "error_type": type(exc).__name__},
                )
                await db.commit()

        return processed

    async def _process_single(
        self,
        db: AsyncSession,
        thread: SupportThread,
    ) -> None:
        """Process a single thread through the full pipeline.

        Steps:
          1. Load order context from Mirakl
          2. Classify with LLM
          3. Update thread with classification result
          4. RED  → escalate immediately, no draft
             ORANGE/GREEN → generate draft via template engine
          5. Validate draft with safety rules
          6. GREEN + safe → auto-send
          7. ORANGE + safe → PENDING_REVIEW (awaits human approval)
          8. Any violation → PENDING_REVIEW with violations logged
        """
        account = await db.get(MarketplaceAccount, thread.marketplace_account_id)
        if account is None:
            raise ValueError(
                f"MarketplaceAccount {thread.marketplace_account_id} not found"
            )

        # ---------------------------------------------------------------- #
        # Step 1: Fetch order context                                       #
        # ---------------------------------------------------------------- #
        order_context: dict[str, Any] = {}
        try:
            async with MiraklClient(account) as client:
                order_context = await client.fetch_order(thread.mirakl_order_id)
        except Exception as exc:
            logger.warning(
                "Could not fetch order context for thread %s: %s — continuing without it",
                thread.id,
                exc,
            )

        # ---------------------------------------------------------------- #
        # Step 2: Classify                                                  #
        # ---------------------------------------------------------------- #
        classification: ClassificationResult = await self._classifier.classify(
            customer_message=thread.customer_message,
            order_context=order_context or None,
        )

        # ---------------------------------------------------------------- #
        # Step 3: Persist classification                                    #
        # ---------------------------------------------------------------- #
        thread.category = classification.category
        thread.risk_level = classification.risk_level
        thread.customer_language = classification.language
        thread.updated_at = datetime.now(UTC)

        await write_audit_log(
            db,
            action="classified",
            actor="system",
            thread_id=thread.id,
            detail={
                "category": classification.category,
                "risk_level": classification.risk_level.value,
                "language": classification.language.value,
            },
        )

        # ---------------------------------------------------------------- #
        # Step 4: RED threads stay in PENDING_REVIEW with no draft —       #
        # the UI shows the RED risk badge so the reviewer knows it's      #
        # high-stakes and must be handled manually.                        #
        # ---------------------------------------------------------------- #
        if classification.risk_level == RiskLevel.RED:
            thread.status = ThreadStatus.PENDING_REVIEW
            thread.updated_at = datetime.now(UTC)
            await write_audit_log(
                db,
                action="red_pending_review",
                actor="system",
                thread_id=thread.id,
                detail={"reason": "risk_level=RED — no draft, human writes reply"},
            )
            await db.commit()
            return

        # ---------------------------------------------------------------- #
        # Step 4b: Autonomous agent path (when AGENT_ENABLED)               #
        # The tool-calling agent gathers real order data and proposes a     #
        # reply gated behind Telegram Approve/Deny. The thread stays         #
        # PENDING_REVIEW until a human approves the proposed action.         #
        # ---------------------------------------------------------------- #
        from app.config import settings as _settings

        if _settings.AGENT_ENABLED:
            from app.services.agent.runner import AgentRunner

            proposed = await AgentRunner().run_for_thread(db, thread=thread, account=account)
            await write_audit_log(
                db,
                action="agent_proposed" if proposed else "agent_no_action",
                actor="system",
                thread_id=thread.id,
                detail={
                    "action_type": proposed.action_type if proposed else None,
                    "action_id": str(proposed.id) if proposed else None,
                },
            )
            thread.status = ThreadStatus.PENDING_REVIEW
            thread.updated_at = datetime.now(UTC)
            await db.commit()
            return

        # ---------------------------------------------------------------- #
        # Step 5: Generate draft                                            #
        # ---------------------------------------------------------------- #
        template_context = _build_template_context(thread, order_context, account)

        # Attempt template render (used directly for GREEN, as reference for ORANGE)
        template_rendered_ok = False
        drafted_response: str | None = None
        try:
            drafted_response = await self._template_engine.render(
                db,
                category=classification.category,
                language=classification.language,
                marketplace_account_id=thread.marketplace_account_id,
                context=template_context,
            )
            template_rendered_ok = True
        except Exception as exc:
            logger.warning(
                "Template render failed for thread %s (%s/%s): %s",
                thread.id,
                classification.category,
                classification.language.value,
                exc,
            )

        # ---------------------------------------------------------------- #
        # Step 5b: ORANGE path — smart draft with LLM augmentation         #
        # ---------------------------------------------------------------- #
        if classification.risk_level == RiskLevel.ORANGE:
            smart_result = await self._smart_draft_service.generate_draft(
                db,
                thread=thread,
                order_context=order_context,
                category=classification.category,
                language=classification.language,
                account=account,
                template_reference=drafted_response if template_rendered_ok else None,
            )

            if smart_result.drafted_response:
                thread.drafted_response = smart_result.drafted_response
            elif template_rendered_ok:
                # Smart draft failed but template succeeded — use template
                thread.drafted_response = drafted_response
            # else: no draft available — reviewer handles from scratch

            thread.updated_at = datetime.now(UTC)

            await write_audit_log(
                db,
                action="smart_draft_generated",
                actor="system",
                thread_id=thread.id,
                detail={
                    "source": smart_result.source,
                    "knowledge_entry_ids": smart_result.knowledge_entry_ids,
                    "similar_thread_count": smart_result.similar_thread_count,
                    "has_draft": thread.drafted_response is not None,
                },
            )

            # Safety validation still runs on whatever draft we have
            if thread.drafted_response:
                is_safe, violations = self._safety_rules.validate(
                    thread, thread.drafted_response,
                )
                await write_audit_log(
                    db,
                    action="safety_validated" if is_safe else "safety_blocked",
                    actor="system",
                    thread_id=thread.id,
                    detail={"is_safe": is_safe, "violations": violations},
                )
                # For ORANGE: keep the draft even if unsafe (reviewer will see violations)

            thread.status = ThreadStatus.PENDING_REVIEW
            thread.updated_at = datetime.now(UTC)
            await db.commit()
            return

        # ---------------------------------------------------------------- #
        # Step 5c: GREEN path — template-based draft (unchanged)           #
        # ---------------------------------------------------------------- #
        if not template_rendered_ok:
            # No matching template for GREEN — cannot auto-send
            thread.status = ThreadStatus.PENDING_REVIEW
            thread.updated_at = datetime.now(UTC)
            await write_audit_log(
                db,
                action="draft_template_missing",
                actor="system",
                thread_id=thread.id,
                detail={
                    "category": classification.category,
                    "language": classification.language.value,
                },
            )
            await db.commit()
            return

        thread.drafted_response = drafted_response
        thread.updated_at = datetime.now(UTC)

        await write_audit_log(
            db,
            action="draft_generated",
            actor="system",
            thread_id=thread.id,
            detail={
                "template_length": len(drafted_response) if drafted_response else 0,
                "category": classification.category,
                "language": classification.language.value,
            },
        )

        # ---------------------------------------------------------------- #
        # Step 6: Safety validation (GREEN path only)                       #
        # ---------------------------------------------------------------- #
        is_safe, violations = self._safety_rules.validate(thread, drafted_response)

        await write_audit_log(
            db,
            action="safety_validated" if is_safe else "safety_blocked",
            actor="system",
            thread_id=thread.id,
            detail={"is_safe": is_safe, "violations": violations},
        )

        if not is_safe:
            thread.status = ThreadStatus.PENDING_REVIEW
            thread.updated_at = datetime.now(UTC)
            await db.commit()
            return

        # ---------------------------------------------------------------- #
        # Step 7: Auto-send (GREEN only, gated by AUTO_SEND_ENABLED)       #
        # ---------------------------------------------------------------- #
        from app.config import settings

        if settings.AUTO_SEND_ENABLED:
            await self._auto_send(db, thread, account, drafted_response)
        else:
            # Auto-send disabled — leave draft for human approval
            thread.status = ThreadStatus.PENDING_REVIEW
            thread.updated_at = datetime.now(UTC)
            await db.commit()

    async def _auto_send(
        self,
        db: AsyncSession,
        thread: SupportThread,
        account: MarketplaceAccount,
        drafted_response: str,
    ) -> None:
        """Send the drafted response via the Mirakl API and mark the thread SENT_AUTO."""
        try:
            async with MiraklClient(account) as client:
                await client.send_reply(
                    thread_id=thread.mirakl_thread_id,
                    body=drafted_response,
                )
        except Exception as exc:
            logger.error(
                "Auto-send failed for thread %s: %s",
                thread.id,
                exc,
            )
            thread.status = ThreadStatus.FAILED
            thread.updated_at = datetime.now(UTC)
            await write_audit_log(
                db,
                action="auto_send_failed",
                actor="system",
                thread_id=thread.id,
                detail={"error": str(exc)},
            )
            await db.commit()
            return

        thread.status = ThreadStatus.SENT_AUTO
        thread.updated_at = datetime.now(UTC)
        await write_audit_log(
            db,
            action="auto_sent",
            actor="system",
            thread_id=thread.id,
            detail={"response_length": len(drafted_response)},
        )
        await db.commit()


def _build_template_context(
    thread: SupportThread,
    order_context: dict[str, Any],
    account: MarketplaceAccount,
) -> dict[str, Any]:
    """Build the Jinja2 context dict from thread and order data."""
    return {
        "order_id": thread.mirakl_order_id,
        "tracking_number": (
            order_context.get("tracking_number")
            or order_context.get("tracking", {}).get("tracking_number", "")
            if order_context else ""
        ),
        "delivery_date": (
            order_context.get("delivery_date")
            or order_context.get("shipping", {}).get("estimated_delivery_date", "")
            if order_context else ""
        ),
        "shop_name": account.marketplace,
        "marketplace": account.marketplace,
        "marketplace_name": account.marketplace,
        "customer_name": (
            order_context.get("customer", {}).get("firstname", "")
            if order_context else ""
        ),
    }
