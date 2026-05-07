"""Tests for AutoSendValidator and AutoSendExecutor."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio

from app.models.marketplace_account import MarketplaceAccount
from app.models.support_thread import (
    CustomerLanguage,
    RiskLevel,
    SupportThread,
    ThreadStatus,
)
from app.services.auto_send import AutoSendExecutor, AutoSendReport, AutoSendValidator
from app.services.encryption import encrypt


# --------------------------------------------------------------------------- #
# Fixtures                                                                     #
# --------------------------------------------------------------------------- #


@pytest_asyncio.fixture
async def account(db) -> MarketplaceAccount:
    acc = MarketplaceAccount(
        id=uuid.uuid4(),
        marketplace="MediaMarkt",
        shop_id="shop-autosend",
        api_key_encrypted=encrypt("test-key"),
        base_url="https://markt.mediamarkt.nl",
        sla_hours=24,
        template_set="default",
        is_active=True,
    )
    db.add(acc)
    await db.flush()
    return acc


def _make_green_thread(account: MarketplaceAccount, **kwargs) -> SupportThread:
    """Helper to create a minimal eligible GREEN thread."""
    defaults = dict(
        id=uuid.uuid4(),
        mirakl_thread_id=f"MK-{uuid.uuid4().hex[:8]}",
        mirakl_order_id=f"ORD-{uuid.uuid4().hex[:8]}",
        marketplace_account_id=account.id,
        customer_message="Where is my order?",
        customer_language=CustomerLanguage.en,
        category="shipping_delay",
        risk_level=RiskLevel.GREEN,
        operator_required=False,
        status=ThreadStatus.PENDING_REVIEW,
        drafted_response="Your order is on its way. Best regards, MediaMarkt",
        response_deadline=datetime.now(UTC) + timedelta(hours=12),
    )
    defaults.update(kwargs)
    return SupportThread(**defaults)


# --------------------------------------------------------------------------- #
# AutoSendValidator                                                            #
# --------------------------------------------------------------------------- #


class TestAutoSendValidator:

    def test_eligible_green_thread(self, sample_account):
        """A fully-eligible GREEN thread returns (True, [])."""
        thread = _make_green_thread(sample_account)
        validator = AutoSendValidator()
        eligible, reasons = validator.is_eligible(thread)
        assert eligible is True
        assert reasons == []

    def test_ineligible_orange_risk(self, sample_account):
        """ORANGE risk_level is not eligible for auto-send."""
        thread = _make_green_thread(sample_account, risk_level=RiskLevel.ORANGE)
        validator = AutoSendValidator()
        eligible, reasons = validator.is_eligible(thread)
        assert eligible is False
        assert any("ORANGE" in r for r in reasons)

    def test_ineligible_red_risk(self, sample_account):
        """RED risk_level is not eligible for auto-send."""
        thread = _make_green_thread(sample_account, risk_level=RiskLevel.RED)
        validator = AutoSendValidator()
        eligible, reasons = validator.is_eligible(thread)
        assert eligible is False
        assert any("RED" in r for r in reasons)

    def test_ineligible_non_pending_status(self, sample_account):
        """A thread in SENT_AUTO status is not eligible."""
        thread = _make_green_thread(sample_account, status=ThreadStatus.SENT_AUTO)
        validator = AutoSendValidator()
        eligible, reasons = validator.is_eligible(thread)
        assert eligible is False
        assert any("SENT_AUTO" in r for r in reasons)

    def test_ineligible_no_draft(self, sample_account):
        """A thread without a drafted_response is not eligible."""
        thread = _make_green_thread(sample_account, drafted_response=None)
        validator = AutoSendValidator()
        eligible, reasons = validator.is_eligible(thread)
        assert eligible is False
        assert any("drafted_response" in r for r in reasons)

    def test_ineligible_operator_required(self, sample_account):
        """An operator_required=True thread must never be auto-sent."""
        thread = _make_green_thread(sample_account, operator_required=True)
        validator = AutoSendValidator()
        eligible, reasons = validator.is_eligible(thread)
        assert eligible is False
        assert any("operator_required" in r for r in reasons)

    def test_ineligible_overdue(self, sample_account):
        """A thread past its response_deadline is not eligible."""
        thread = _make_green_thread(
            sample_account,
            response_deadline=datetime.now(UTC) - timedelta(hours=1),
        )
        validator = AutoSendValidator()
        eligible, reasons = validator.is_eligible(thread)
        assert eligible is False
        assert any("deadline" in r.lower() or "overdue" in r.lower() for r in reasons)

    def test_ineligible_safety_violation(self, sample_account):
        """A thread whose draft contains a refund promise is blocked by safety rules."""
        thread = _make_green_thread(
            sample_account,
            drafted_response="We will refund you in full within 3 business days.",
        )
        validator = AutoSendValidator()
        eligible, reasons = validator.is_eligible(thread)
        assert eligible is False
        assert any("R1" in r or "refund" in r.lower() for r in reasons)

    def test_multiple_failures_accumulate(self, sample_account):
        """All failing criteria are returned, not just the first one."""
        thread = _make_green_thread(
            sample_account,
            risk_level=RiskLevel.ORANGE,
            status=ThreadStatus.ESCALATED,
        )
        validator = AutoSendValidator()
        eligible, reasons = validator.is_eligible(thread)
        assert eligible is False
        # Both risk_level and status failures should appear
        assert len(reasons) >= 2


# --------------------------------------------------------------------------- #
# AutoSendExecutor                                                             #
# --------------------------------------------------------------------------- #


class TestAutoSendExecutor:

    async def test_sends_eligible_thread(self, db, account):
        """Eligible GREEN thread is sent and status becomes SENT_AUTO."""
        thread = _make_green_thread(account)
        db.add(thread)
        await db.flush()

        with patch("app.services.auto_send.MiraklClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.send_reply = AsyncMock(return_value={"status": "sent"})
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            executor = AutoSendExecutor()
            report = await executor.execute_auto_sends(db)

        assert report.sent == 1
        assert report.failed == 0
        await db.refresh(thread)
        assert thread.status == ThreadStatus.SENT_AUTO

    async def test_skips_orange_thread(self, db, account):
        """ORANGE thread is skipped without attempting a send."""
        thread = _make_green_thread(account, risk_level=RiskLevel.ORANGE)
        db.add(thread)
        await db.flush()

        with patch("app.services.auto_send.MiraklClient") as mock_cls:
            mock_client = AsyncMock()
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            executor = AutoSendExecutor()
            report = await executor.execute_auto_sends(db)

        assert report.sent == 0
        # ORANGE thread is not fetched by the query at all (filter is on GREEN)
        # so it never reaches the validator and is not in the report
        assert report.skipped == 0

    async def test_marks_failed_on_mirakl_error(self, db, account):
        """A Mirakl API error marks the thread FAILED and logs the error."""
        from app.core.exceptions import MiraklAPIError

        thread = _make_green_thread(account)
        db.add(thread)
        await db.flush()

        with patch("app.services.auto_send.MiraklClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.send_reply = AsyncMock(
                side_effect=MiraklAPIError("Connection refused", status_code=503)
            )
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            executor = AutoSendExecutor()
            report = await executor.execute_auto_sends(db)

        assert report.failed == 1
        assert report.sent == 0
        await db.refresh(thread)
        assert thread.status == ThreadStatus.FAILED
        assert report.details[0].error is not None

    async def test_skips_overdue_thread(self, db, account):
        """Overdue threads are not sent — they should be escalated by SLAMonitor."""
        thread = _make_green_thread(
            account,
            response_deadline=datetime.now(UTC) - timedelta(hours=2),
        )
        db.add(thread)
        await db.flush()

        with patch("app.services.auto_send.MiraklClient") as mock_cls:
            mock_client = AsyncMock()
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            executor = AutoSendExecutor()
            report = await executor.execute_auto_sends(db)

        # Thread appears as a candidate (deadline filter is not in the SQL query,
        # the validator handles it) and is skipped by the validator.
        assert report.sent == 0
        assert report.skipped == 1

    async def test_processes_multiple_threads(self, db, account):
        """Multiple eligible threads are all processed in one run."""
        threads = [_make_green_thread(account) for _ in range(3)]
        for t in threads:
            db.add(t)
        await db.flush()

        with patch("app.services.auto_send.MiraklClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.send_reply = AsyncMock(return_value={"status": "sent"})
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            executor = AutoSendExecutor()
            report = await executor.execute_auto_sends(db)

        assert report.sent == 3
        assert report.failed == 0

    async def test_returns_empty_report_when_no_candidates(self, db, account):
        """No threads in DB → AutoSendReport with all zeros."""
        executor = AutoSendExecutor()
        report = await executor.execute_auto_sends(db)
        assert report.sent == 0
        assert report.failed == 0
        assert report.skipped == 0
        assert report.details == []

    async def test_does_not_double_send_already_sent(self, db, account):
        """SENT_AUTO threads are excluded from the candidate query."""
        thread = _make_green_thread(account, status=ThreadStatus.SENT_AUTO)
        db.add(thread)
        await db.flush()

        with patch("app.services.auto_send.MiraklClient") as mock_cls:
            mock_client = AsyncMock()
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            executor = AutoSendExecutor()
            report = await executor.execute_auto_sends(db)

        assert report.sent == 0
        mock_client.send_reply.assert_not_called()
