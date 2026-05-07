"""Integration tests for the /api/v1/threads endpoints."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from app.models.support_thread import RiskLevel, SupportThread, ThreadStatus


class TestListThreads:

    async def test_list_returns_empty_when_no_threads(self, client, db):
        resp = await client.get("/api/v1/threads")
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert data["total"] == 0
        assert data["page"] == 1

    async def test_list_returns_created_thread(self, client, sample_thread):
        resp = await client.get("/api/v1/threads")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        item = data["items"][0]
        assert item["mirakl_thread_id"] == sample_thread.mirakl_thread_id
        assert item["status"] == "PENDING_REVIEW"

    async def test_filter_by_risk_level(self, client, db, sample_account):
        """Only threads matching the requested risk_level are returned."""
        # Create a GREEN thread
        from app.models.support_thread import CustomerLanguage
        green_thread = SupportThread(
            id=uuid.uuid4(),
            mirakl_thread_id="MK-GREEN",
            mirakl_order_id="ORD-GREEN",
            marketplace_account_id=sample_account.id,
            customer_message="Where is my order?",
            risk_level=RiskLevel.GREEN,
            status=ThreadStatus.PENDING_REVIEW,
            operator_required=False,
            response_deadline=datetime.now(UTC) + timedelta(hours=24),
        )
        # Create a RED thread
        red_thread = SupportThread(
            id=uuid.uuid4(),
            mirakl_thread_id="MK-RED",
            mirakl_order_id="ORD-RED",
            marketplace_account_id=sample_account.id,
            customer_message="I want a refund!",
            risk_level=RiskLevel.RED,
            status=ThreadStatus.ESCALATED,
            operator_required=False,
            response_deadline=datetime.now(UTC) + timedelta(hours=24),
        )
        db.add(green_thread)
        db.add(red_thread)
        await db.flush()

        resp = await client.get("/api/v1/threads?risk_level=GREEN")
        assert resp.status_code == 200
        data = resp.json()
        assert all(t["risk_level"] == "GREEN" for t in data["items"])

    async def test_filter_by_status(self, client, db, sample_account):
        thread = SupportThread(
            id=uuid.uuid4(),
            mirakl_thread_id="MK-ESCALATED",
            mirakl_order_id="ORD-ESCALATED",
            marketplace_account_id=sample_account.id,
            customer_message="Issue",
            status=ThreadStatus.ESCALATED,
            operator_required=False,
            response_deadline=datetime.now(UTC) + timedelta(hours=24),
        )
        db.add(thread)
        await db.flush()

        resp = await client.get("/api/v1/threads?status=ESCALATED")
        assert resp.status_code == 200
        data = resp.json()
        assert all(t["status"] == "ESCALATED" for t in data["items"])

    async def test_filter_by_marketplace_account_id(
        self, client, db, sample_account, sample_thread
    ):
        resp = await client.get(
            f"/api/v1/threads?marketplace_account_id={sample_account.id}"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert all(
            t["marketplace_account_id"] == str(sample_account.id)
            for t in data["items"]
        )

    async def test_pagination(self, client, db, sample_account):
        """page_size=1 returns only one item per page."""
        for i in range(3):
            t = SupportThread(
                id=uuid.uuid4(),
                mirakl_thread_id=f"MK-PAGE-{i}",
                mirakl_order_id=f"ORD-PAGE-{i}",
                marketplace_account_id=sample_account.id,
                customer_message="test",
                status=ThreadStatus.PENDING_REVIEW,
                operator_required=False,
                response_deadline=datetime.now(UTC) + timedelta(hours=24),
            )
            db.add(t)
        await db.flush()

        resp = await client.get("/api/v1/threads?page=1&page_size=1")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) == 1
        assert data["page"] == 1
        assert data["page_size"] == 1


class TestGetThread:

    async def test_get_existing_thread(self, client, sample_thread):
        resp = await client.get(f"/api/v1/threads/{sample_thread.id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == str(sample_thread.id)
        assert data["mirakl_thread_id"] == sample_thread.mirakl_thread_id

    async def test_get_nonexistent_thread_returns_404(self, client):
        resp = await client.get(f"/api/v1/threads/{uuid.uuid4()}")
        assert resp.status_code == 404


class TestApproveThread:

    async def test_approve_thread_with_drafted_response(
        self, client, classified_green_thread, sample_account
    ):
        """Approving a thread with a draft sends the reply and sets status=APPROVED."""
        with patch(
            "app.api.threads.MiraklClient",
        ) as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.send_reply = AsyncMock(return_value={"status": "sent"})
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            resp = await client.put(
                f"/api/v1/threads/{classified_green_thread.id}/approve",
                json={"actor": "admin@omiximo.nl"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "APPROVED"

    async def test_approve_thread_with_override(
        self, client, classified_green_thread
    ):
        """A drafted_response_override replaces the system draft."""
        with patch("app.api.threads.MiraklClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.send_reply = AsyncMock(return_value={})
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            override = "Custom response by human reviewer."
            resp = await client.put(
                f"/api/v1/threads/{classified_green_thread.id}/approve",
                json={
                    "actor": "admin@omiximo.nl",
                    "drafted_response_override": override,
                },
            )

        assert resp.status_code == 200
        # The send_reply should have been called with the override text
        mock_client.send_reply.assert_called_once()
        call_kwargs = mock_client.send_reply.call_args
        assert override in str(call_kwargs)

    async def test_approve_nonexistent_thread_returns_404(self, client):
        resp = await client.put(
            f"/api/v1/threads/{uuid.uuid4()}/approve",
            json={"actor": "user@example.com"},
        )
        assert resp.status_code == 404

    async def test_approve_already_sent_thread_returns_409(
        self, client, db, sample_account
    ):
        """Cannot re-approve an already sent thread."""
        sent_thread = SupportThread(
            id=uuid.uuid4(),
            mirakl_thread_id="MK-SENT",
            mirakl_order_id="ORD-SENT",
            marketplace_account_id=sample_account.id,
            customer_message="test",
            status=ThreadStatus.SENT_AUTO,
            operator_required=False,
            response_deadline=datetime.now(UTC) + timedelta(hours=24),
        )
        db.add(sent_thread)
        await db.flush()

        resp = await client.put(
            f"/api/v1/threads/{sent_thread.id}/approve",
            json={"actor": "user@example.com"},
        )
        assert resp.status_code == 409

    async def test_approve_thread_without_draft_returns_422(
        self, client, sample_thread
    ):
        """Approving a thread without a drafted response returns 422."""
        resp = await client.put(
            f"/api/v1/threads/{sample_thread.id}/approve",
            json={"actor": "user@example.com"},
        )
        assert resp.status_code == 422


class TestEscalateThread:

    async def test_escalate_pending_thread(self, client, sample_thread):
        resp = await client.put(
            f"/api/v1/threads/{sample_thread.id}/escalate",
            json={"actor": "agent@omiximo.nl", "reason": "Complex dispute requiring legal review."},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ESCALATED"

    async def test_escalate_already_escalated_returns_409(
        self, client, db, sample_account
    ):
        escalated = SupportThread(
            id=uuid.uuid4(),
            mirakl_thread_id="MK-ESC2",
            mirakl_order_id="ORD-ESC2",
            marketplace_account_id=sample_account.id,
            customer_message="test",
            status=ThreadStatus.ESCALATED,
            operator_required=False,
            response_deadline=datetime.now(UTC) + timedelta(hours=24),
        )
        db.add(escalated)
        await db.flush()

        resp = await client.put(
            f"/api/v1/threads/{escalated.id}/escalate",
            json={"actor": "user@example.com", "reason": "Already escalated."},
        )
        assert resp.status_code == 409

    async def test_escalate_nonexistent_thread_returns_404(self, client):
        resp = await client.put(
            f"/api/v1/threads/{uuid.uuid4()}/escalate",
            json={"actor": "user@example.com", "reason": "Test."},
        )
        assert resp.status_code == 404

    async def test_escalate_requires_reason(self, client, sample_thread):
        """Missing reason field should cause a validation error."""
        resp = await client.put(
            f"/api/v1/threads/{sample_thread.id}/escalate",
            json={"actor": "user@example.com"},
        )
        assert resp.status_code == 422


class TestHealthEndpoint:

    async def test_health_check_returns_ok(self, client):
        resp = await client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert "status" in data
        assert "timestamp" in data
        assert "database" in data
