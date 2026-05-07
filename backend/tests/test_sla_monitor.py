"""Tests for SLAMonitor and DataAlertService."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio

from app.models.marketplace_account import MarketplaceAccount
from app.models.support_thread import (
    CustomerLanguage,
    RiskLevel,
    SupportThread,
    ThreadStatus,
)
from app.services.data_alerts import DataAlertService
from app.services.encryption import encrypt
from app.services.sla_monitor import SLAMonitor


# --------------------------------------------------------------------------- #
# Fixtures                                                                     #
# --------------------------------------------------------------------------- #


@pytest_asyncio.fixture
async def sla_account(db) -> MarketplaceAccount:
    acc = MarketplaceAccount(
        id=uuid.uuid4(),
        marketplace="Boulanger",
        shop_id="shop-sla",
        api_key_encrypted=encrypt("sla-key"),
        base_url="https://marketplace.boulanger.fr",
        sla_hours=24,
        template_set="default",
        is_active=True,
    )
    db.add(acc)
    await db.flush()
    return acc


def _make_thread(account: MarketplaceAccount, deadline_offset_hours: float = 12, **kwargs) -> SupportThread:
    """Create a PENDING_REVIEW thread with a configurable deadline."""
    defaults = dict(
        id=uuid.uuid4(),
        mirakl_thread_id=f"MK-{uuid.uuid4().hex[:8]}",
        mirakl_order_id=f"ORD-{uuid.uuid4().hex[:8]}",
        marketplace_account_id=account.id,
        customer_message="Test message",
        operator_required=False,
        status=ThreadStatus.PENDING_REVIEW,
        response_deadline=datetime.now(UTC) + timedelta(hours=deadline_offset_hours),
    )
    defaults.update(kwargs)
    return SupportThread(**defaults)


# --------------------------------------------------------------------------- #
# SLAMonitor.check_approaching_deadlines                                       #
# --------------------------------------------------------------------------- #


class TestCheckApproachingDeadlines:

    async def test_returns_thread_within_one_hour(self, db, sla_account):
        """A thread 30 minutes from deadline is included."""
        thread = _make_thread(sla_account, deadline_offset_hours=0.5)
        db.add(thread)
        await db.flush()

        monitor = SLAMonitor()
        alerts = await monitor.check_approaching_deadlines(db)

        assert len(alerts) == 1
        assert alerts[0].thread_id == str(thread.id)
        assert 0 < alerts[0].hours_remaining <= 1.0

    async def test_excludes_thread_with_plenty_of_time(self, db, sla_account):
        """A thread 6 hours from deadline is not an approaching alert."""
        thread = _make_thread(sla_account, deadline_offset_hours=6)
        db.add(thread)
        await db.flush()

        monitor = SLAMonitor()
        alerts = await monitor.check_approaching_deadlines(db)
        assert len(alerts) == 0

    async def test_excludes_already_overdue(self, db, sla_account):
        """Overdue threads are not returned by check_approaching_deadlines."""
        thread = _make_thread(sla_account, deadline_offset_hours=-1)
        db.add(thread)
        await db.flush()

        monitor = SLAMonitor()
        alerts = await monitor.check_approaching_deadlines(db)
        assert len(alerts) == 0

    async def test_excludes_non_pending_threads(self, db, sla_account):
        """ESCALATED threads are not surfaced even if approaching deadline."""
        thread = _make_thread(
            sla_account,
            deadline_offset_hours=0.5,
            status=ThreadStatus.ESCALATED,
        )
        db.add(thread)
        await db.flush()

        monitor = SLAMonitor()
        alerts = await monitor.check_approaching_deadlines(db)
        assert len(alerts) == 0

    async def test_marketplace_name_resolved(self, db, sla_account):
        """Alert includes the marketplace name from the linked account."""
        thread = _make_thread(sla_account, deadline_offset_hours=0.5)
        db.add(thread)
        await db.flush()

        monitor = SLAMonitor()
        alerts = await monitor.check_approaching_deadlines(db)

        assert len(alerts) == 1
        assert alerts[0].marketplace == "Boulanger"


# --------------------------------------------------------------------------- #
# SLAMonitor.check_overdue                                                     #
# --------------------------------------------------------------------------- #


class TestCheckOverdue:

    async def test_returns_overdue_thread(self, db, sla_account):
        """A thread past its deadline is returned as overdue."""
        thread = _make_thread(sla_account, deadline_offset_hours=-2)
        db.add(thread)
        await db.flush()

        monitor = SLAMonitor()
        alerts = await monitor.check_overdue(db)

        assert len(alerts) == 1
        assert alerts[0].thread_id == str(thread.id)
        assert alerts[0].hours_remaining < 0

    async def test_excludes_future_deadline(self, db, sla_account):
        """Threads with future deadlines are not overdue."""
        thread = _make_thread(sla_account, deadline_offset_hours=1)
        db.add(thread)
        await db.flush()

        monitor = SLAMonitor()
        alerts = await monitor.check_overdue(db)
        assert len(alerts) == 0

    async def test_excludes_already_escalated(self, db, sla_account):
        """Already-escalated threads are not re-surfaced as overdue."""
        thread = _make_thread(
            sla_account,
            deadline_offset_hours=-3,
            status=ThreadStatus.ESCALATED,
        )
        db.add(thread)
        await db.flush()

        monitor = SLAMonitor()
        alerts = await monitor.check_overdue(db)
        assert len(alerts) == 0

    async def test_multiple_overdue_threads(self, db, sla_account):
        """All overdue threads are returned."""
        for i in range(4):
            db.add(_make_thread(sla_account, deadline_offset_hours=-(i + 1)))
        await db.flush()

        monitor = SLAMonitor()
        alerts = await monitor.check_overdue(db)
        assert len(alerts) == 4


# --------------------------------------------------------------------------- #
# SLAMonitor.auto_escalate_overdue                                             #
# --------------------------------------------------------------------------- #


class TestAutoEscalateOverdue:

    async def test_escalates_overdue_threads(self, db, sla_account):
        """Overdue PENDING_REVIEW threads are moved to ESCALATED."""
        thread = _make_thread(sla_account, deadline_offset_hours=-1)
        db.add(thread)
        await db.flush()

        monitor = SLAMonitor()
        count = await monitor.auto_escalate_overdue(db)

        assert count == 1
        await db.refresh(thread)
        assert thread.status == ThreadStatus.ESCALATED

    async def test_skips_non_overdue_threads(self, db, sla_account):
        """Threads with future deadlines are not escalated."""
        thread = _make_thread(sla_account, deadline_offset_hours=2)
        db.add(thread)
        await db.flush()

        monitor = SLAMonitor()
        count = await monitor.auto_escalate_overdue(db)

        assert count == 0
        await db.refresh(thread)
        assert thread.status == ThreadStatus.PENDING_REVIEW

    async def test_writes_audit_log(self, db, sla_account):
        """Each escalation writes an sla_auto_escalated audit row."""
        from app.models.audit_log import AuditLog
        from sqlalchemy import select

        thread = _make_thread(sla_account, deadline_offset_hours=-1)
        db.add(thread)
        await db.flush()

        monitor = SLAMonitor()
        await monitor.auto_escalate_overdue(db)

        stmt = select(AuditLog).where(AuditLog.action == "sla_auto_escalated")
        result = await db.execute(stmt)
        logs = result.scalars().all()

        assert len(logs) == 1
        assert logs[0].thread_id == thread.id
        assert logs[0].actor == "system"

    async def test_escalates_multiple_overdue_threads(self, db, sla_account):
        """All overdue threads in a single run are escalated."""
        threads = [_make_thread(sla_account, deadline_offset_hours=-(i + 1)) for i in range(3)]
        for t in threads:
            db.add(t)
        await db.flush()

        monitor = SLAMonitor()
        count = await monitor.auto_escalate_overdue(db)

        assert count == 3
        for t in threads:
            await db.refresh(t)
            assert t.status == ThreadStatus.ESCALATED

    async def test_does_not_re_escalate_already_escalated(self, db, sla_account):
        """Threads already in ESCALATED status are not touched again."""
        thread = _make_thread(
            sla_account,
            deadline_offset_hours=-2,
            status=ThreadStatus.ESCALATED,
        )
        db.add(thread)
        await db.flush()

        monitor = SLAMonitor()
        count = await monitor.auto_escalate_overdue(db)

        assert count == 0

    async def test_returns_zero_when_nothing_to_escalate(self, db, sla_account):
        """Empty database → return value is 0."""
        monitor = SLAMonitor()
        count = await monitor.auto_escalate_overdue(db)
        assert count == 0


# --------------------------------------------------------------------------- #
# DataAlertService                                                             #
# --------------------------------------------------------------------------- #


class TestDataAlertService:

    async def test_missing_tracking_alert(self, db, sla_account):
        """tracking_update thread with no tracking_status raises an alert."""
        thread = _make_thread(
            sla_account,
            category="tracking_update",
            tracking_status=None,
        )
        db.add(thread)
        await db.flush()

        service = DataAlertService()
        alerts = await service.check_missing_tracking(db)

        assert len(alerts) == 1
        assert alerts[0].alert_type == "missing_tracking"
        assert alerts[0].thread_id == str(thread.id)

    async def test_no_missing_tracking_when_status_set(self, db, sla_account):
        """Thread with tracking_status populated is not alerted."""
        thread = _make_thread(
            sla_account,
            category="tracking_update",
            tracking_status="IN_TRANSIT",
        )
        db.add(thread)
        await db.flush()

        service = DataAlertService()
        alerts = await service.check_missing_tracking(db)
        assert len(alerts) == 0

    async def test_missing_invoice_alert(self, db, sla_account):
        """invoice_request thread with no invoice_status raises an alert."""
        thread = _make_thread(
            sla_account,
            category="invoice_request",
            invoice_status=None,
        )
        db.add(thread)
        await db.flush()

        service = DataAlertService()
        alerts = await service.check_missing_invoice(db)

        assert len(alerts) == 1
        assert alerts[0].alert_type == "missing_invoice"

    async def test_no_missing_invoice_when_status_set(self, db, sla_account):
        """Thread with invoice_status populated is not alerted."""
        thread = _make_thread(
            sla_account,
            category="invoice_request",
            invoice_status="SENT",
        )
        db.add(thread)
        await db.flush()

        service = DataAlertService()
        alerts = await service.check_missing_invoice(db)
        assert len(alerts) == 0

    async def test_only_pending_review_threads_alerted(self, db, sla_account):
        """ESCALATED threads with missing data are not surfaced."""
        thread = _make_thread(
            sla_account,
            category="tracking_update",
            tracking_status=None,
            status=ThreadStatus.ESCALATED,
        )
        db.add(thread)
        await db.flush()

        service = DataAlertService()
        alerts = await service.check_missing_tracking(db)
        assert len(alerts) == 0

    async def test_non_tracking_category_not_alerted(self, db, sla_account):
        """Threads with unrelated categories are not included in tracking alerts."""
        thread = _make_thread(
            sla_account,
            category="return_request",
            tracking_status=None,
        )
        db.add(thread)
        await db.flush()

        service = DataAlertService()
        alerts = await service.check_missing_tracking(db)
        assert len(alerts) == 0
