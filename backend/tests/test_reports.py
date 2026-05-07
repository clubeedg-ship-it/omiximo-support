"""Tests for /api/v1/reports/summary and /api/v1/reports/timeline endpoints."""

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
from app.services.encryption import encrypt


# --------------------------------------------------------------------------- #
# Fixtures                                                                     #
# --------------------------------------------------------------------------- #


@pytest_asyncio.fixture
async def rpt_account(db) -> MarketplaceAccount:
    acc = MarketplaceAccount(
        id=uuid.uuid4(),
        marketplace="Carrefour",
        shop_id="shop-carrefour",
        api_key_encrypted=encrypt("rpt-key"),
        base_url="https://marketplace.carrefour.fr",
        sla_hours=24,
        template_set="default",
        is_active=True,
    )
    db.add(acc)
    await db.flush()
    return acc


@pytest_asyncio.fixture
async def rpt_account2(db) -> MarketplaceAccount:
    acc = MarketplaceAccount(
        id=uuid.uuid4(),
        marketplace="Pixmania",
        shop_id="shop-pixmania",
        api_key_encrypted=encrypt("rpt-key-2"),
        base_url="https://marketplace.pixmania.com",
        sla_hours=48,
        template_set="default",
        is_active=True,
    )
    db.add(acc)
    await db.flush()
    return acc


def _thread(account: MarketplaceAccount, **kwargs) -> SupportThread:
    defaults = dict(
        id=uuid.uuid4(),
        mirakl_thread_id=f"MK-{uuid.uuid4().hex[:8]}",
        mirakl_order_id=f"ORD-{uuid.uuid4().hex[:8]}",
        marketplace_account_id=account.id,
        customer_message="Test",
        operator_required=False,
        status=ThreadStatus.PENDING_REVIEW,
        response_deadline=datetime.now(UTC) + timedelta(hours=24),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    defaults.update(kwargs)
    return SupportThread(**defaults)


# --------------------------------------------------------------------------- #
# Summary report                                                               #
# --------------------------------------------------------------------------- #


class TestSummaryReport:

    async def test_empty_database_returns_zeros(self, client):
        """No threads → all counts are 0 and rates are sensible defaults."""
        resp = await client.get("/api/v1/reports/summary")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_threads"] == 0
        assert data["auto_reply_rate"] == 0.0

    async def test_counts_threads_by_risk_level(self, client, db, rpt_account):
        """by_risk_level contains correct counts for GREEN / ORANGE / RED."""
        db.add(_thread(rpt_account, risk_level=RiskLevel.GREEN))
        db.add(_thread(rpt_account, risk_level=RiskLevel.GREEN))
        db.add(_thread(rpt_account, risk_level=RiskLevel.ORANGE))
        db.add(_thread(rpt_account, risk_level=RiskLevel.RED, status=ThreadStatus.ESCALATED))
        await db.flush()

        resp = await client.get("/api/v1/reports/summary")
        assert resp.status_code == 200
        data = resp.json()
        assert data["by_risk_level"]["green"] == 2
        assert data["by_risk_level"]["orange"] == 1
        assert data["by_risk_level"]["red"] == 1

    async def test_counts_threads_by_status(self, client, db, rpt_account):
        """by_status reflects exact status distribution."""
        db.add(_thread(rpt_account, status=ThreadStatus.PENDING_REVIEW))
        db.add(_thread(rpt_account, status=ThreadStatus.SENT_AUTO))
        db.add(_thread(rpt_account, status=ThreadStatus.ESCALATED))
        db.add(_thread(rpt_account, status=ThreadStatus.FAILED))
        await db.flush()

        resp = await client.get("/api/v1/reports/summary")
        data = resp.json()
        assert data["by_status"]["pending"] == 1
        assert data["by_status"]["sent_auto"] == 1
        assert data["by_status"]["escalated"] == 1
        assert data["by_status"]["failed"] == 1

    async def test_auto_reply_rate_calculation(self, client, db, rpt_account):
        """auto_reply_rate = sent_auto / total terminal threads."""
        # 2 sent_auto, 1 escalated → terminal = 3, rate = 2/3
        db.add(_thread(rpt_account, status=ThreadStatus.SENT_AUTO))
        db.add(_thread(rpt_account, status=ThreadStatus.SENT_AUTO))
        db.add(_thread(rpt_account, status=ThreadStatus.ESCALATED))
        await db.flush()

        resp = await client.get("/api/v1/reports/summary")
        data = resp.json()
        assert abs(data["auto_reply_rate"] - 2 / 3) < 0.01

    async def test_by_category_counts(self, client, db, rpt_account):
        """by_category contains correct per-category counts."""
        db.add(_thread(rpt_account, category="shipping_delay"))
        db.add(_thread(rpt_account, category="shipping_delay"))
        db.add(_thread(rpt_account, category="return_request"))
        await db.flush()

        resp = await client.get("/api/v1/reports/summary")
        data = resp.json()
        assert data["by_category"]["shipping_delay"] == 2
        assert data["by_category"]["return_request"] == 1

    async def test_by_marketplace_counts(self, client, db, rpt_account, rpt_account2):
        """by_marketplace groups threads by marketplace name."""
        db.add(_thread(rpt_account))
        db.add(_thread(rpt_account))
        db.add(_thread(rpt_account2))
        await db.flush()

        resp = await client.get("/api/v1/reports/summary")
        data = resp.json()
        assert data["by_marketplace"]["Carrefour"] == 2
        assert data["by_marketplace"]["Pixmania"] == 1

    async def test_filter_by_marketplace_account_id(self, client, db, rpt_account, rpt_account2):
        """Filtering by marketplace_account_id restricts results."""
        db.add(_thread(rpt_account))
        db.add(_thread(rpt_account))
        db.add(_thread(rpt_account2))
        await db.flush()

        resp = await client.get(
            f"/api/v1/reports/summary?marketplace_account_id={rpt_account.id}"
        )
        data = resp.json()
        assert data["total_threads"] == 2

    async def test_days_filter_excludes_old_threads(self, client, db, rpt_account):
        """Threads older than 'days' are excluded from the report."""
        old_thread = _thread(
            rpt_account,
            created_at=datetime.now(UTC) - timedelta(days=30),
            updated_at=datetime.now(UTC) - timedelta(days=30),
        )
        recent_thread = _thread(rpt_account)
        db.add(old_thread)
        db.add(recent_thread)
        await db.flush()

        resp = await client.get("/api/v1/reports/summary?days=7")
        data = resp.json()
        assert data["total_threads"] == 1

    async def test_unclassified_threads_counted(self, client, db, rpt_account):
        """Threads with no risk_level appear under 'unclassified'."""
        db.add(_thread(rpt_account, risk_level=None))
        await db.flush()

        resp = await client.get("/api/v1/reports/summary")
        data = resp.json()
        assert data["by_risk_level"]["unclassified"] == 1

    async def test_sla_compliance_rate_all_on_time(self, client, db, rpt_account):
        """All threads resolved before deadline → sla_compliance_rate == 1.0."""
        t = _thread(
            rpt_account,
            status=ThreadStatus.SENT_AUTO,
            response_deadline=datetime.now(UTC) + timedelta(hours=10),
            updated_at=datetime.now(UTC),
        )
        db.add(t)
        await db.flush()

        resp = await client.get("/api/v1/reports/summary")
        data = resp.json()
        assert data["sla_compliance_rate"] == 1.0

    async def test_sla_compliance_rate_none_on_time(self, client, db, rpt_account):
        """Thread resolved after deadline → sla_compliance_rate == 0.0."""
        t = _thread(
            rpt_account,
            status=ThreadStatus.ESCALATED,
            response_deadline=datetime.now(UTC) - timedelta(hours=2),
            updated_at=datetime.now(UTC),  # resolved NOW, but deadline was 2h ago
        )
        db.add(t)
        await db.flush()

        resp = await client.get("/api/v1/reports/summary")
        data = resp.json()
        assert data["sla_compliance_rate"] == 0.0

    async def test_total_threads_is_correct(self, client, db, rpt_account):
        """total_threads equals the number of threads in the window."""
        for _ in range(5):
            db.add(_thread(rpt_account))
        await db.flush()

        resp = await client.get("/api/v1/reports/summary")
        data = resp.json()
        assert data["total_threads"] == 5


# --------------------------------------------------------------------------- #
# Timeline report                                                              #
# --------------------------------------------------------------------------- #


class TestTimelineReport:

    async def test_timeline_returns_points(self, client, db, rpt_account):
        """Timeline with threads populates the expected bucket structure."""
        db.add(_thread(rpt_account))
        await db.flush()

        resp = await client.get("/api/v1/reports/timeline?days=7&granularity=day")
        assert resp.status_code == 200
        data = resp.json()
        assert data["granularity"] == "day"
        assert len(data["points"]) > 0

        for point in data["points"]:
            assert "date" in point
            assert "new_threads" in point
            assert "resolved" in point
            assert "auto_sent" in point
            assert "escalated" in point

    async def test_timeline_new_thread_counted_in_correct_bucket(
        self, client, db, rpt_account
    ):
        """A thread created today appears in today's bucket."""
        db.add(_thread(rpt_account, created_at=datetime.now(UTC)))
        await db.flush()

        resp = await client.get("/api/v1/reports/timeline?days=2&granularity=day")
        data = resp.json()

        today = datetime.now(UTC).strftime("%Y-%m-%d")
        today_bucket = next((p for p in data["points"] if p["date"] == today), None)
        assert today_bucket is not None
        assert today_bucket["new_threads"] == 1

    async def test_timeline_hour_granularity(self, client, db, rpt_account):
        """Hour granularity returns more granular buckets."""
        db.add(_thread(rpt_account))
        await db.flush()

        resp = await client.get("/api/v1/reports/timeline?days=1&granularity=hour")
        data = resp.json()
        assert data["granularity"] == "hour"
        # 1-day hour granularity should have ~24+ buckets
        assert len(data["points"]) >= 24

    async def test_timeline_invalid_granularity_returns_422(self, client):
        """An invalid granularity parameter returns 422."""
        resp = await client.get("/api/v1/reports/timeline?granularity=month")
        assert resp.status_code == 422

    async def test_timeline_auto_sent_counted(self, client, db, rpt_account):
        """SENT_AUTO threads increment auto_sent in the correct bucket."""
        db.add(
            _thread(
                rpt_account,
                status=ThreadStatus.SENT_AUTO,
                updated_at=datetime.now(UTC),
            )
        )
        await db.flush()

        resp = await client.get("/api/v1/reports/timeline?days=2&granularity=day")
        data = resp.json()
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        today_bucket = next((p for p in data["points"] if p["date"] == today), None)
        assert today_bucket is not None
        assert today_bucket["auto_sent"] == 1

    async def test_timeline_escalated_counted(self, client, db, rpt_account):
        """ESCALATED threads increment escalated in the correct bucket."""
        db.add(
            _thread(
                rpt_account,
                status=ThreadStatus.ESCALATED,
                updated_at=datetime.now(UTC),
            )
        )
        await db.flush()

        resp = await client.get("/api/v1/reports/timeline?days=2&granularity=day")
        data = resp.json()
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        today_bucket = next((p for p in data["points"] if p["date"] == today), None)
        assert today_bucket is not None
        assert today_bucket["escalated"] == 1

    async def test_timeline_empty_database_returns_continuous_buckets(self, client):
        """Empty DB → all buckets present with zeros."""
        resp = await client.get("/api/v1/reports/timeline?days=3&granularity=day")
        data = resp.json()
        # Should have 3-4 day buckets (since + now boundary)
        assert len(data["points"]) >= 3
        for point in data["points"]:
            assert point["new_threads"] == 0
            assert point["resolved"] == 0

    async def test_timeline_filter_by_marketplace_account_id(
        self, client, db, rpt_account, rpt_account2
    ):
        """Filtering by marketplace_account_id restricts timeline data."""
        db.add(_thread(rpt_account, created_at=datetime.now(UTC)))
        db.add(_thread(rpt_account2, created_at=datetime.now(UTC)))
        await db.flush()

        resp = await client.get(
            f"/api/v1/reports/timeline?days=1&marketplace_account_id={rpt_account.id}"
        )
        data = resp.json()
        total_new = sum(p["new_threads"] for p in data["points"])
        assert total_new == 1
