"""Auto-send validation and execution service (Phase 2).

Two classes compose the auto-send pipeline:

AutoSendValidator
    Stateless eligibility checker.  Given a SupportThread it returns a
    (eligible: bool, reasons: list[str]) tuple.  Every hard criterion from
    the spec is checked here so that nothing in AutoSendExecutor needs to
    duplicate that logic.

AutoSendExecutor
    Queries all eligible threads in a single run, sends each one via
    MiraklClient, and returns an AutoSendReport summarising what happened.

    The executor uses SELECT FOR UPDATE SKIP LOCKED so that multiple workers
    can run concurrently without double-sending the same thread.  Because
    SQLite (used in tests) does not support SKIP LOCKED the statement falls
    back gracefully; tests patch MiraklClient so no real HTTP call is made.

Architecture notes
    - Only GREEN threads are auto-sent.
    - A thread overdue past response_deadline is NOT auto-sent; it is
      escalated (SLA auto-escalation is the responsibility of SLAMonitor, but
      the executor must not send overdue threads either).
    - All outcomes write to audit_log before committing.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.marketplace_account import MarketplaceAccount
from app.models.support_thread import RiskLevel, SupportThread, ThreadStatus
from app.services.audit import write_audit_log
from app.services.mirakl_client import MiraklClient
from app.services.safety_rules import SafetyRules

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Data structures                                                              #
# --------------------------------------------------------------------------- #


@dataclass
class SendDetail:
    """Per-thread outcome from a single auto-send execution run."""

    thread_id: str
    mirakl_thread_id: str
    outcome: str  # "sent" | "failed" | "skipped"
    reasons: list[str] = field(default_factory=list)
    error: str | None = None


@dataclass
class AutoSendReport:
    """Aggregate result returned by AutoSendExecutor.execute_auto_sends()."""

    sent: int = 0
    failed: int = 0
    skipped: int = 0
    details: list[SendDetail] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# AutoSendValidator                                                            #
# --------------------------------------------------------------------------- #


class AutoSendValidator:
    """Stateless eligibility checker for auto-send.

    All criteria for whether a thread may be auto-sent live here.  The
    executor delegates to this class before touching the Mirakl API.
    """

    def __init__(self, safety_rules: SafetyRules | None = None) -> None:
        self._safety = safety_rules or SafetyRules()

    def is_eligible(
        self,
        thread: SupportThread,
    ) -> tuple[bool, list[str]]:
        """Check all auto-send eligibility criteria for *thread*.

        Checks (in order):
          1. risk_level == GREEN
          2. status == PENDING_REVIEW  (not already processed)
          3. drafted_response is not None
          4. operator_required == False
          5. response_deadline is not past (overdue → escalate, not send)
          6. safety_rules.validate() passes

        Args:
            thread: The SupportThread to evaluate.

        Returns:
            ``(eligible, reasons)`` where *eligible* is True only when all
            criteria pass.  *reasons* is a list of human-readable explanations
            for any failing criterion; empty when eligible is True.
        """
        reasons: list[str] = []

        # 1. Risk level must be GREEN
        if thread.risk_level != RiskLevel.GREEN:
            reasons.append(
                f"risk_level is {thread.risk_level!r}, expected GREEN"
            )

        # 2. Status must be PENDING_REVIEW
        if thread.status != ThreadStatus.PENDING_REVIEW:
            reasons.append(
                f"status is {thread.status!r}, expected PENDING_REVIEW"
            )

        # 3. Draft must exist
        if not thread.drafted_response:
            reasons.append("drafted_response is None — no draft to send")

        # 4. Operator messages must never be auto-sent
        if thread.operator_required:
            reasons.append(
                "operator_required=True — auto-reply to operator messages is blocked"
            )

        # 5. Do not auto-send overdue threads
        now = datetime.now(UTC)
        deadline = thread.response_deadline
        # Ensure deadline is timezone-aware for comparison
        if deadline.tzinfo is None:
            from datetime import timezone
            deadline = deadline.replace(tzinfo=timezone.utc)
        if now > deadline:
            reasons.append(
                f"response_deadline {deadline.isoformat()} is past "
                "— overdue threads must be escalated, not auto-sent"
            )

        # Return early if structural checks already failed; safety_rules need
        # a valid drafted_response so we must not call them without one.
        if reasons:
            return False, reasons

        # 6. Safety rules
        assert thread.drafted_response is not None  # guarded above
        is_safe, violations = self._safety.validate(thread, thread.drafted_response)
        if not is_safe:
            reasons.extend(violations)

        return (len(reasons) == 0, reasons)


# --------------------------------------------------------------------------- #
# AutoSendExecutor                                                             #
# --------------------------------------------------------------------------- #


class AutoSendExecutor:
    """Queries candidate threads and executes auto-send for eligible ones.

    Designed to be run periodically by the background task scheduler.
    The SELECT FOR UPDATE SKIP LOCKED pattern ensures two concurrent
    executor runs do not process the same thread twice.
    """

    def __init__(self, validator: AutoSendValidator | None = None) -> None:
        self._validator = validator or AutoSendValidator()

    async def execute_auto_sends(self, db: AsyncSession) -> AutoSendReport:
        """Find and execute all eligible auto-send threads.

        For each eligible thread:
          - Calls MiraklClient.send_reply()
          - On success: status → SENT_AUTO, audit_log "auto_send_success"
          - On failure: status → FAILED,    audit_log "auto_send_failed"

        Ineligible threads are counted as skipped.

        Args:
            db: Async database session.  Each thread is committed individually
                so a failure on one does not roll back the others.

        Returns:
            AutoSendReport with sent/failed/skipped counts and per-thread
            details.
        """
        report = AutoSendReport()

        # Fetch candidates: GREEN PENDING_REVIEW threads with a draft.
        # SELECT FOR UPDATE SKIP LOCKED prevents concurrent double-sends.
        stmt = (
            select(SupportThread)
            .where(
                SupportThread.risk_level == RiskLevel.GREEN,
                SupportThread.status == ThreadStatus.PENDING_REVIEW,
                SupportThread.drafted_response.is_not(None),
                SupportThread.operator_required.is_(False),
            )
        )
        # SKIP LOCKED is only available on PostgreSQL; wrap in try/except so
        # the SQLite test environment still works.
        try:
            from sqlalchemy.dialects.postgresql import insert as pg_insert  # noqa: F401
            stmt = stmt.with_for_update(skip_locked=True)
        except Exception:
            pass  # SQLite — skip_locked not supported; safe in tests

        result = await db.execute(stmt)
        candidates: list[SupportThread] = list(result.scalars().all())

        for thread in candidates:
            detail = await self._process_candidate(db, thread)
            report.details.append(detail)
            if detail.outcome == "sent":
                report.sent += 1
            elif detail.outcome == "failed":
                report.failed += 1
            else:
                report.skipped += 1

        return report

    async def _process_candidate(
        self,
        db: AsyncSession,
        thread: SupportThread,
    ) -> SendDetail:
        """Validate eligibility and, if eligible, send the drafted response.

        Returns a SendDetail describing the outcome.
        """
        eligible, reasons = self._validator.is_eligible(thread)

        if not eligible:
            logger.debug(
                "Thread %s skipped (ineligible): %s",
                thread.id,
                "; ".join(reasons),
            )
            return SendDetail(
                thread_id=str(thread.id),
                mirakl_thread_id=thread.mirakl_thread_id,
                outcome="skipped",
                reasons=reasons,
            )

        # Load the marketplace account (needed for MiraklClient)
        account: MarketplaceAccount | None = await db.get(
            MarketplaceAccount, thread.marketplace_account_id
        )
        if account is None:
            error_msg = (
                f"MarketplaceAccount {thread.marketplace_account_id} not found"
            )
            logger.error("Auto-send skipped for thread %s: %s", thread.id, error_msg)
            return SendDetail(
                thread_id=str(thread.id),
                mirakl_thread_id=thread.mirakl_thread_id,
                outcome="skipped",
                reasons=[error_msg],
            )

        drafted = thread.drafted_response
        assert drafted is not None  # guarded by validator

        return await self._send(db, thread, account, drafted)

    async def _send(
        self,
        db: AsyncSession,
        thread: SupportThread,
        account: MarketplaceAccount,
        drafted_response: str,
    ) -> SendDetail:
        """Execute the Mirakl API call and persist the outcome."""
        try:
            async with MiraklClient(account) as client:
                await client.send_reply(
                    thread_id=thread.mirakl_thread_id,
                    body=drafted_response,
                )
        except Exception as exc:
            logger.error(
                "Auto-send FAILED for thread %s: %s",
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
                detail={"error": str(exc), "error_type": type(exc).__name__},
            )
            await db.commit()
            return SendDetail(
                thread_id=str(thread.id),
                mirakl_thread_id=thread.mirakl_thread_id,
                outcome="failed",
                error=str(exc),
            )

        thread.status = ThreadStatus.SENT_AUTO
        thread.updated_at = datetime.now(UTC)
        await write_audit_log(
            db,
            action="auto_send_success",
            actor="system",
            thread_id=thread.id,
            detail={"response_length": len(drafted_response)},
        )
        await db.commit()
        logger.info("Auto-sent thread %s (%s)", thread.id, thread.mirakl_thread_id)
        return SendDetail(
            thread_id=str(thread.id),
            mirakl_thread_id=thread.mirakl_thread_id,
            outcome="sent",
        )
