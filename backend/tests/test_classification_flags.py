"""Tests for P4.4: misclassification flagging endpoints.

Covers:
  POST /api/v1/threads/{id}/flag-misclassification
  GET  /api/v1/classification/flags
  PUT  /api/v1/classification/flags/{id}/resolve
"""

from __future__ import annotations

import uuid

import pytest

from app.models.classification_flag import ClassificationFlag
from app.models.support_thread import CustomerLanguage, RiskLevel, SupportThread


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _flag_payload(
    correct_category: str = "return_request",
    correct_risk_level: str = "ORANGE",
    correct_language: str = "nl",
    reason: str = "The classifier said GREEN but this is clearly an ORANGE return.",
    actor: str = "reviewer@omiximo.nl",
) -> dict:
    return {
        "correct_category": correct_category,
        "correct_risk_level": correct_risk_level,
        "correct_language": correct_language,
        "reason": reason,
        "actor": actor,
    }


# ---------------------------------------------------------------------------
# POST /api/v1/threads/{id}/flag-misclassification
# ---------------------------------------------------------------------------


class TestFlagMisclassification:

    async def test_flag_returns_201(self, client, classified_green_thread):
        resp = await client.post(
            f"/api/v1/threads/{classified_green_thread.id}/flag-misclassification",
            json=_flag_payload(),
        )
        assert resp.status_code == 201

    async def test_flag_returns_correct_fields(self, client, classified_green_thread):
        payload = _flag_payload(
            correct_category="warranty_claim",
            correct_risk_level="RED",
            correct_language="en",
            reason="Not a shipping issue — defective product.",
            actor="qa@omiximo.nl",
        )
        resp = await client.post(
            f"/api/v1/threads/{classified_green_thread.id}/flag-misclassification",
            json=payload,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["thread_id"] == str(classified_green_thread.id)
        assert data["correct_category"] == "warranty_claim"
        assert data["correct_risk_level"] == "RED"
        assert data["correct_language"] == "en"
        assert data["reason"] == "Not a shipping issue — defective product."
        assert data["actor"] == "qa@omiximo.nl"
        assert data["resolution"] is None
        assert data["resolved_by"] is None
        assert data["resolved_at"] is None

    async def test_flag_snapshots_original_classification(
        self, client, classified_green_thread
    ):
        """The flag must capture the thread's classification at the time of flagging."""
        resp = await client.post(
            f"/api/v1/threads/{classified_green_thread.id}/flag-misclassification",
            json=_flag_payload(),
        )
        assert resp.status_code == 201
        data = resp.json()
        # classified_green_thread has category=shipping_delay, risk=GREEN, lang=en
        assert data["original_category"] == "shipping_delay"
        assert data["original_risk_level"] == "GREEN"
        assert data["original_language"] == "en"

    async def test_flag_thread_without_classification(self, client, sample_thread):
        """Threads with NULL classification fields are also flaggable."""
        resp = await client.post(
            f"/api/v1/threads/{sample_thread.id}/flag-misclassification",
            json=_flag_payload(),
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["original_category"] is None
        assert data["original_risk_level"] is None
        assert data["original_language"] is None

    async def test_flag_nonexistent_thread_returns_404(self, client):
        resp = await client.post(
            f"/api/v1/threads/{uuid.uuid4()}/flag-misclassification",
            json=_flag_payload(),
        )
        assert resp.status_code == 404

    async def test_flag_writes_audit_log(self, client, db, classified_green_thread):
        from app.models.audit_log import AuditLog
        from sqlalchemy import select

        resp = await client.post(
            f"/api/v1/threads/{classified_green_thread.id}/flag-misclassification",
            json=_flag_payload(actor="auditor@omiximo.nl"),
        )
        assert resp.status_code == 201

        result = await db.execute(
            select(AuditLog).where(
                AuditLog.thread_id == classified_green_thread.id,
                AuditLog.action == "misclassification_flagged",
            )
        )
        log = result.scalar_one_or_none()
        assert log is not None
        assert log.actor == "auditor@omiximo.nl"

    async def test_flag_invalid_risk_level_returns_422(self, client, classified_green_thread):
        payload = _flag_payload(correct_risk_level="INVALID")
        resp = await client.post(
            f"/api/v1/threads/{classified_green_thread.id}/flag-misclassification",
            json=payload,
        )
        assert resp.status_code == 422

    async def test_flag_invalid_language_returns_422(self, client, classified_green_thread):
        payload = _flag_payload(correct_language="zz")
        resp = await client.post(
            f"/api/v1/threads/{classified_green_thread.id}/flag-misclassification",
            json=payload,
        )
        assert resp.status_code == 422

    async def test_flag_empty_reason_returns_422(self, client, classified_green_thread):
        payload = _flag_payload(reason="")
        resp = await client.post(
            f"/api/v1/threads/{classified_green_thread.id}/flag-misclassification",
            json=payload,
        )
        assert resp.status_code == 422

    async def test_multiple_flags_on_same_thread_allowed(
        self, client, classified_green_thread
    ):
        """Multiple flags on the same thread are allowed (different reviewers)."""
        for actor in ("reviewer1@omiximo.nl", "reviewer2@omiximo.nl"):
            resp = await client.post(
                f"/api/v1/threads/{classified_green_thread.id}/flag-misclassification",
                json=_flag_payload(actor=actor),
            )
            assert resp.status_code == 201


# ---------------------------------------------------------------------------
# GET /api/v1/classification/flags
# ---------------------------------------------------------------------------


class TestListClassificationFlags:

    async def test_list_empty_when_no_flags(self, client):
        resp = await client.get("/api/v1/classification/flags")
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert data["total"] == 0
        assert data["page"] == 1

    async def test_list_returns_created_flag(self, client, classified_green_thread):
        await client.post(
            f"/api/v1/threads/{classified_green_thread.id}/flag-misclassification",
            json=_flag_payload(),
        )
        resp = await client.get("/api/v1/classification/flags")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert len(data["items"]) == 1

    async def test_list_filter_reviewed_false_returns_unresolved_only(
        self, client, classified_green_thread
    ):
        await client.post(
            f"/api/v1/threads/{classified_green_thread.id}/flag-misclassification",
            json=_flag_payload(),
        )
        resp = await client.get("/api/v1/classification/flags?reviewed=false")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert all(item["resolution"] is None for item in data["items"])

    async def test_list_filter_reviewed_true_returns_resolved_only(
        self, client, db, classified_green_thread
    ):
        # Create a flag and resolve it directly in the DB
        flag = ClassificationFlag(
            id=uuid.uuid4(),
            thread_id=classified_green_thread.id,
            original_category="shipping_delay",
            original_risk_level="GREEN",
            original_language="en",
            correct_category="return_request",
            correct_risk_level="ORANGE",
            correct_language="en",
            reason="Wrong category.",
            actor="reviewer@omiximo.nl",
            resolution="accepted",
            resolved_by="manager@omiximo.nl",
        )
        db.add(flag)
        await db.flush()

        # Also create an unresolved one
        await client.post(
            f"/api/v1/threads/{classified_green_thread.id}/flag-misclassification",
            json=_flag_payload(),
        )

        resp = await client.get("/api/v1/classification/flags?reviewed=true")
        assert resp.status_code == 200
        data = resp.json()
        assert all(item["resolution"] is not None for item in data["items"])

    async def test_list_no_filter_returns_all(
        self, client, db, classified_green_thread
    ):
        # Resolved flag
        flag = ClassificationFlag(
            id=uuid.uuid4(),
            thread_id=classified_green_thread.id,
            original_category=None,
            original_risk_level=None,
            original_language=None,
            correct_category="return_request",
            correct_risk_level="ORANGE",
            correct_language="nl",
            reason="Wrong.",
            actor="a@omiximo.nl",
            resolution="rejected",
            resolved_by="b@omiximo.nl",
        )
        db.add(flag)
        await db.flush()

        # Unresolved flag
        await client.post(
            f"/api/v1/threads/{classified_green_thread.id}/flag-misclassification",
            json=_flag_payload(),
        )

        resp = await client.get("/api/v1/classification/flags")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2

    async def test_list_pagination(self, client, classified_green_thread):
        # Create 5 flags
        for i in range(5):
            await client.post(
                f"/api/v1/threads/{classified_green_thread.id}/flag-misclassification",
                json=_flag_payload(reason=f"Reason {i}", actor=f"actor{i}@omiximo.nl"),
            )

        resp = await client.get("/api/v1/classification/flags?page=1&page_size=2")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 5
        assert len(data["items"]) == 2
        assert data["page"] == 1
        assert data["page_size"] == 2

        resp2 = await client.get("/api/v1/classification/flags?page=3&page_size=2")
        assert resp2.status_code == 200
        data2 = resp2.json()
        assert len(data2["items"]) == 1  # last page has 1 item


# ---------------------------------------------------------------------------
# PUT /api/v1/classification/flags/{id}/resolve
# ---------------------------------------------------------------------------


class TestResolveClassificationFlag:

    async def _create_flag(self, client, thread_id: uuid.UUID) -> dict:
        resp = await client.post(
            f"/api/v1/threads/{thread_id}/flag-misclassification",
            json=_flag_payload(
                correct_category="return_request",
                correct_risk_level="ORANGE",
                correct_language="nl",
            ),
        )
        assert resp.status_code == 201
        return resp.json()

    async def test_accept_updates_thread_classification(
        self, client, db, classified_green_thread
    ):
        flag = await self._create_flag(client, classified_green_thread.id)
        flag_id = flag["id"]

        resp = await client.put(
            f"/api/v1/classification/flags/{flag_id}/resolve",
            json={"resolution": "accepted", "actor": "manager@omiximo.nl"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["resolution"] == "accepted"
        assert data["resolved_by"] == "manager@omiximo.nl"
        assert data["resolved_at"] is not None

        # Verify thread was updated
        await db.refresh(classified_green_thread)
        assert classified_green_thread.category == "return_request"
        assert classified_green_thread.risk_level == RiskLevel.ORANGE
        assert classified_green_thread.customer_language == CustomerLanguage.nl

    async def test_reject_does_not_change_thread(
        self, client, db, classified_green_thread
    ):
        original_category = classified_green_thread.category
        original_risk = classified_green_thread.risk_level

        flag = await self._create_flag(client, classified_green_thread.id)
        flag_id = flag["id"]

        resp = await client.put(
            f"/api/v1/classification/flags/{flag_id}/resolve",
            json={"resolution": "rejected", "actor": "manager@omiximo.nl"},
        )
        assert resp.status_code == 200
        assert resp.json()["resolution"] == "rejected"

        # Thread must remain unchanged
        await db.refresh(classified_green_thread)
        assert classified_green_thread.category == original_category
        assert classified_green_thread.risk_level == original_risk

    async def test_resolve_nonexistent_flag_returns_404(self, client):
        resp = await client.put(
            f"/api/v1/classification/flags/{uuid.uuid4()}/resolve",
            json={"resolution": "accepted", "actor": "manager@omiximo.nl"},
        )
        assert resp.status_code == 404

    async def test_resolve_already_resolved_flag_returns_409(
        self, client, classified_green_thread
    ):
        flag = await self._create_flag(client, classified_green_thread.id)
        flag_id = flag["id"]

        # Resolve once
        await client.put(
            f"/api/v1/classification/flags/{flag_id}/resolve",
            json={"resolution": "accepted", "actor": "manager@omiximo.nl"},
        )

        # Try to resolve again
        resp = await client.put(
            f"/api/v1/classification/flags/{flag_id}/resolve",
            json={"resolution": "rejected", "actor": "other@omiximo.nl"},
        )
        assert resp.status_code == 409
        assert "already been resolved" in resp.json()["detail"].lower()

    async def test_resolve_invalid_resolution_value_returns_422(
        self, client, classified_green_thread
    ):
        flag = await self._create_flag(client, classified_green_thread.id)
        resp = await client.put(
            f"/api/v1/classification/flags/{flag['id']}/resolve",
            json={"resolution": "maybe", "actor": "manager@omiximo.nl"},
        )
        assert resp.status_code == 422

    async def test_resolve_writes_audit_log(
        self, client, db, classified_green_thread
    ):
        from app.models.audit_log import AuditLog
        from sqlalchemy import select

        flag = await self._create_flag(client, classified_green_thread.id)

        await client.put(
            f"/api/v1/classification/flags/{flag['id']}/resolve",
            json={"resolution": "accepted", "actor": "resolver@omiximo.nl"},
        )

        result = await db.execute(
            select(AuditLog).where(
                AuditLog.thread_id == classified_green_thread.id,
                AuditLog.action == "misclassification_resolved",
            )
        )
        log = result.scalar_one_or_none()
        assert log is not None
        assert log.actor == "resolver@omiximo.nl"
        assert log.detail_json["resolution"] == "accepted"
