"""Integration tests for the /api/v1/threads endpoints."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from app.models.audit_log import AuditLog
from app.models.support_thread import RiskLevel, SupportThread, ThreadStatus


class TestListThreads:

    async def test_protected_route_requires_auth(self, unauthenticated_client):
        resp = await unauthenticated_client.get("/api/v1/threads")
        assert resp.status_code == 401

    async def test_authenticated_user_outside_allowlist_gets_403(self, forbidden_client):
        resp = await forbidden_client.get("/api/v1/threads")
        assert resp.status_code == 403

    async def test_allowed_authenticated_user_can_access_route(self, client):
        resp = await client.get("/api/v1/threads")
        assert resp.status_code == 200

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
        assert item["marketplace_name"] == "MediaMarkt"

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

    async def test_search_by_order_id(self, client, db, sample_account):
        matching = SupportThread(
            id=uuid.uuid4(),
            mirakl_thread_id="MK-SEARCH-ORDER",
            mirakl_order_id="ORD-ABC-123",
            marketplace_account_id=sample_account.id,
            customer_message="Where is my parcel?",
            status=ThreadStatus.PENDING_REVIEW,
            operator_required=False,
            response_deadline=datetime.now(UTC) + timedelta(hours=24),
        )
        non_matching = SupportThread(
            id=uuid.uuid4(),
            mirakl_thread_id="MK-SEARCH-OTHER",
            mirakl_order_id="ORD-XYZ-999",
            marketplace_account_id=sample_account.id,
            customer_message="Invoice request",
            status=ThreadStatus.PENDING_REVIEW,
            operator_required=False,
            response_deadline=datetime.now(UTC) + timedelta(hours=24),
        )
        db.add_all([matching, non_matching])
        await db.flush()

        resp = await client.get("/api/v1/threads?search=abc-123")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["id"] == str(matching.id)

    async def test_search_by_message_fragment(self, client, db, sample_account):
        matching = SupportThread(
            id=uuid.uuid4(),
            mirakl_thread_id="MK-SEARCH-MESSAGE",
            mirakl_order_id="ORD-MESSAGE-1",
            marketplace_account_id=sample_account.id,
            customer_message="Customer says the package arrived damaged yesterday.",
            status=ThreadStatus.PENDING_REVIEW,
            operator_required=False,
            response_deadline=datetime.now(UTC) + timedelta(hours=24),
        )
        non_matching = SupportThread(
            id=uuid.uuid4(),
            mirakl_thread_id="MK-SEARCH-MESSAGE-2",
            mirakl_order_id="ORD-MESSAGE-2",
            marketplace_account_id=sample_account.id,
            customer_message="Please cancel my order.",
            status=ThreadStatus.PENDING_REVIEW,
            operator_required=False,
            response_deadline=datetime.now(UTC) + timedelta(hours=24),
        )
        db.add_all([matching, non_matching])
        await db.flush()

        resp = await client.get("/api/v1/threads?search=damaged")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["id"] == str(matching.id)


class TestGetThread:

    async def test_get_existing_thread(self, client, sample_thread):
        resp = await client.get(f"/api/v1/threads/{sample_thread.id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == str(sample_thread.id)
        assert data["mirakl_thread_id"] == sample_thread.mirakl_thread_id
        assert data["marketplace_name"] == "MediaMarkt"

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
                json={},
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
            json={},
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
            json={},
        )
        assert resp.status_code == 409

    async def test_approve_thread_without_draft_returns_422(
        self, client, sample_thread
    ):
        """Approving a thread without a drafted response returns 422."""
        resp = await client.put(
            f"/api/v1/threads/{sample_thread.id}/approve",
            json={},
        )
        assert resp.status_code == 422

    async def test_approve_audit_actor_comes_from_authenticated_user(
        self, client, db, classified_green_thread
    ):
        with patch("app.api.threads.MiraklClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.send_reply = AsyncMock(return_value={})
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            resp = await client.put(
                f"/api/v1/threads/{classified_green_thread.id}/approve",
                json={},
            )

        assert resp.status_code == 200

        result = await db.execute(
            select(AuditLog).where(
                AuditLog.thread_id == classified_green_thread.id,
                AuditLog.action == "human_approved",
            )
        )
        log = result.scalar_one_or_none()
        assert log is not None
        assert log.actor == "admin@omiximo.nl"

    async def test_failed_human_send_persists_status_and_audit(
        self, client, db, classified_green_thread
    ):
        with patch("app.api.threads.MiraklClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.send_reply = AsyncMock(side_effect=RuntimeError("mirakl down"))
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            resp = await client.put(
                f"/api/v1/threads/{classified_green_thread.id}/approve",
                json={},
            )

        assert resp.status_code == 502

        await db.refresh(classified_green_thread)
        assert classified_green_thread.status == ThreadStatus.FAILED

        result = await db.execute(
            select(AuditLog).where(
                AuditLog.thread_id == classified_green_thread.id,
                AuditLog.action == "human_send_failed",
            )
        )
        log = result.scalar_one_or_none()
        assert log is not None
        assert log.actor == "admin@omiximo.nl"
        assert log.detail_json == {"error": "mirakl down"}


class TestEscalateThread:

    async def test_escalate_pending_thread(self, client, sample_thread):
        resp = await client.put(
            f"/api/v1/threads/{sample_thread.id}/escalate",
            json={"reason": "Complex dispute requiring legal review."},
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
            json={"reason": "Already escalated."},
        )
        assert resp.status_code == 409

    async def test_escalate_nonexistent_thread_returns_404(self, client):
        resp = await client.put(
            f"/api/v1/threads/{uuid.uuid4()}/escalate",
            json={"reason": "Test."},
        )
        assert resp.status_code == 404

    async def test_escalate_requires_reason(self, client, sample_thread):
        """Missing reason field should cause a validation error."""
        resp = await client.put(
            f"/api/v1/threads/{sample_thread.id}/escalate",
            json={},
        )
        assert resp.status_code == 422


class TestTranslateDraftEndpoint:
    """Tests for POST /{thread_id}/translate-draft.

    The module-level ``_insight_service`` singleton in threads.py is not in
    mock mode. All tests that exercise the success path patch ``translate_draft``
    on the class so no real network calls are made.
    """

    @pytest.fixture(autouse=True)
    def patch_translate_draft(self, monkeypatch):
        """Replace MessageInsightService.translate_draft with a no-network stub.

        The stub behaves like the real mock: it returns a deterministic
        TranslationResult for any non-error test. Tests that want to exercise
        the failure path override this fixture locally via their own monkeypatch.
        """
        from app.services import message_insight as mi_module
        from app.services.message_insight import TranslationResult

        async def stub_translate(self_svc, english_text: str, target_language: str):
            return TranslationResult(
                translated_text=f"[Stub {target_language}]: {english_text}",
                correction_made=False,
                correction_note="",
            )

        monkeypatch.setattr(mi_module.MessageInsightService, "translate_draft", stub_translate)

    async def test_translate_draft_returns_translated_text(
        self, client, sample_thread
    ):
        """Happy path: Dutch target returns a non-empty translated_text."""
        resp = await client.post(
            f"/api/v1/threads/{sample_thread.id}/translate-draft",
            json={
                "english_text": "Dear customer, your order is on its way.",
                "target_language": "nl",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["translated_text"] is not None
        assert len(data["translated_text"]) > 0

    async def test_translate_draft_english_target_returns_400(
        self, client, sample_thread
    ):
        """Requesting English as target language must be rejected before LLM call."""
        resp = await client.post(
            f"/api/v1/threads/{sample_thread.id}/translate-draft",
            json={
                "english_text": "Dear customer, your order is on its way.",
                "target_language": "en",
            },
        )
        assert resp.status_code == 400

    async def test_translate_draft_nonexistent_thread_returns_404(self, client):
        resp = await client.post(
            f"/api/v1/threads/{uuid.uuid4()}/translate-draft",
            json={
                "english_text": "Dear customer, your order is on its way.",
                "target_language": "nl",
            },
        )
        assert resp.status_code == 404

    async def test_translate_draft_requires_auth(
        self, unauthenticated_client, sample_thread
    ):
        resp = await unauthenticated_client.post(
            f"/api/v1/threads/{sample_thread.id}/translate-draft",
            json={
                "english_text": "Dear customer, your order is on its way.",
                "target_language": "nl",
            },
        )
        assert resp.status_code == 401

    async def test_translate_draft_forbidden_user_gets_403(
        self, forbidden_client, sample_thread
    ):
        resp = await forbidden_client.post(
            f"/api/v1/threads/{sample_thread.id}/translate-draft",
            json={
                "english_text": "Dear customer, your order is on its way.",
                "target_language": "nl",
            },
        )
        assert resp.status_code == 403

    async def test_translate_draft_empty_text_returns_422(
        self, client, sample_thread
    ):
        """Empty english_text must fail Pydantic validation before reaching the handler."""
        resp = await client.post(
            f"/api/v1/threads/{sample_thread.id}/translate-draft",
            json={
                "english_text": "",
                "target_language": "nl",
            },
        )
        assert resp.status_code == 422

    async def test_translate_draft_invalid_language_returns_422(
        self, client, sample_thread
    ):
        """An unsupported language code must fail validation."""
        resp = await client.post(
            f"/api/v1/threads/{sample_thread.id}/translate-draft",
            json={
                "english_text": "Dear customer, your order is on its way.",
                "target_language": "xx",
            },
        )
        assert resp.status_code == 422

    async def test_translate_draft_response_has_expected_shape(
        self, client, sample_thread
    ):
        """Response body must contain all three defined fields."""
        resp = await client.post(
            f"/api/v1/threads/{sample_thread.id}/translate-draft",
            json={
                "english_text": "Dear customer, your order is on its way.",
                "target_language": "fr",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "translated_text" in data
        assert "correction_made" in data
        assert "correction_note" in data

    async def test_translate_draft_writes_audit_log(
        self, client, db, sample_thread
    ):
        """A successful call must persist an audit log entry with correct fields."""
        resp = await client.post(
            f"/api/v1/threads/{sample_thread.id}/translate-draft",
            json={
                "english_text": "Dear customer, your order is on its way.",
                "target_language": "de",
            },
        )
        assert resp.status_code == 200

        from sqlalchemy import select as sa_select
        from app.models.audit_log import AuditLog

        result = await db.execute(
            sa_select(AuditLog).where(
                AuditLog.thread_id == sample_thread.id,
                AuditLog.action == "draft_translation_requested",
            )
        )
        log = result.scalar_one_or_none()
        assert log is not None
        assert log.actor == "admin@omiximo.nl"
        assert log.detail_json["target_language"] == "de"
        assert log.detail_json["translation_succeeded"] is True

    async def test_translate_draft_llm_failure_returns_null_text(
        self, client, sample_thread, monkeypatch
    ):
        """When the service returns None, translated_text is null — no 500 raised."""
        from app.services import message_insight as mi_module

        # Override the autouse stub with a failing variant
        async def failing_translate(self_svc, english_text, target_language):
            return None

        monkeypatch.setattr(
            mi_module.MessageInsightService,
            "translate_draft",
            failing_translate,
        )

        resp = await client.post(
            f"/api/v1/threads/{sample_thread.id}/translate-draft",
            json={
                "english_text": "Dear customer, your order is on its way.",
                "target_language": "nl",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["translated_text"] is None

    async def test_translate_draft_llm_failure_still_writes_audit_log(
        self, client, db, sample_thread, monkeypatch
    ):
        """Even when the LLM fails, the audit log must be written."""
        from app.services import message_insight as mi_module
        from app.models.audit_log import AuditLog
        from sqlalchemy import select as sa_select

        async def failing_translate(self_svc, english_text, target_language):
            return None

        monkeypatch.setattr(
            mi_module.MessageInsightService,
            "translate_draft",
            failing_translate,
        )

        await client.post(
            f"/api/v1/threads/{sample_thread.id}/translate-draft",
            json={
                "english_text": "Dear customer, your order is on its way.",
                "target_language": "nl",
            },
        )

        result = await db.execute(
            sa_select(AuditLog).where(
                AuditLog.thread_id == sample_thread.id,
                AuditLog.action == "draft_translation_requested",
            )
        )
        log = result.scalar_one_or_none()
        assert log is not None
        assert log.detail_json["translation_succeeded"] is False

    async def test_translate_draft_stub_correction_fields_false_by_default(
        self, client, sample_thread
    ):
        """The autouse stub returns correction_made=False and an empty note."""
        resp = await client.post(
            f"/api/v1/threads/{sample_thread.id}/translate-draft",
            json={
                "english_text": "We have received your complaint.",
                "target_language": "nl",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["correction_made"] is False
        assert data["correction_note"] == ""


class TestHealthEndpoint:

    async def test_health_check_returns_ok(self, unauthenticated_client):
        resp = await unauthenticated_client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert "status" in data
        assert "timestamp" in data
        assert "database" in data
