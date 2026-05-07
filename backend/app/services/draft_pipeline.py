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
from app.models.support_thread import RiskLevel, SupportThread, ThreadStatus
from app.services.audit import write_audit_log
from app.services.classifier import ClassificationResult, MessageClassifier
from app.services.mirakl_client import MiraklClient
from app.services.safety_rules import SafetyRules
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
    ) -> None:
        self._classifier = classifier or MessageClassifier()
        self._template_engine = template_engine or TemplateEngine()
        self._safety_rules = safety_rules or SafetyRules()

    async def process_new_threads(self, db: AsyncSession) -> int:
        """Process all PENDING_REVIEW threads that have not yet been classified.

        A thread is eligible for processing when:
          - status == PENDING_REVIEW
          - risk_level IS NULL (not yet classified)

        Args:
            db: Database session. This method commits after each thread.

        Returns:
            Number of threads successfully processed (draft generated or escalated).
        """
        stmt = select(SupportThread).where(
            SupportThread.status == ThreadStatus.PENDING_REVIEW,
            SupportThread.risk_level.is_(None),
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
        # Step 4: Route by risk level                                       #
        # ---------------------------------------------------------------- #
        if classification.risk_level == RiskLevel.RED:
            thread.status = ThreadStatus.ESCALATED
            thread.updated_at = datetime.now(UTC)
            await write_audit_log(
                db,
                action="escalated_auto_red",
                actor="system",
                thread_id=thread.id,
                detail={"reason": "risk_level=RED — manual handling required"},
            )
            await db.commit()
            return

        # ---------------------------------------------------------------- #
        # Step 5: Generate draft                                            #
        # ---------------------------------------------------------------- #
        template_context = _build_template_context(thread, order_context, account)

        try:
            drafted_response = await self._template_engine.render(
                db,
                category=classification.category,
                language=classification.language,
                marketplace_account_id=thread.marketplace_account_id,
                context=template_context,
            )
        except Exception as exc:
            # No matching template — for ORANGE this is acceptable (human handles it);
            # for GREEN we cannot auto-send, so we escalate to PENDING_REVIEW.
            logger.warning(
                "Template render failed for thread %s (%s/%s): %s",
                thread.id,
                classification.category,
                classification.language.value,
                exc,
            )
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
                    "error": str(exc),
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
                "template_length": len(drafted_response),
                "category": classification.category,
                "language": classification.language.value,
            },
        )

        # ---------------------------------------------------------------- #
        # Step 6: Safety validation                                         #
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
        # Step 7: Auto-send (GREEN only) or hand to human (ORANGE)        #
        # ---------------------------------------------------------------- #
        if classification.risk_level == RiskLevel.GREEN:
            await self._auto_send(db, thread, account, drafted_response)
        else:
            # ORANGE: draft ready, awaiting human approval
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
        "customer_name": (
            order_context.get("customer", {}).get("firstname", "")
            if order_context else ""
        ),
    }
