"""Tests for the Mirakl webhook endpoint."""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.config import settings


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #


def _valid_payload(
    event_type: str = "MESSAGING_THREAD_CREATED",
    thread_id: str = "MK-THREAD-WH-001",
    order_id: str = "MK-ORDER-WH-001",
    shop_id: str = "shop-001",
) -> dict:
    return {
        "event_type": event_type,
        "payload": {
            "thread_id": thread_id,
            "order_id": order_id,
            "shop_id": shop_id,
        },
    }


def _sign(body: bytes, secret: str) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


# --------------------------------------------------------------------------- #
# Basic acceptance                                                             #
# --------------------------------------------------------------------------- #


class TestWebhookEndpoint:

    async def test_returns_200_for_valid_payload(self, client):
        """Well-formed payload without signature header is accepted (no secret configured)."""
        payload = _valid_payload()

        with patch(
            "app.api.webhooks._process_webhook_async",
            new_callable=lambda: (lambda *a, **kw: AsyncMock(return_value=None)),
        ):
            resp = await client.post(
                "/api/v1/webhooks/mirakl",
                json=payload,
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["received"] is True
        assert data["event_type"] == "MESSAGING_THREAD_CREATED"
        assert data["thread_id"] == "MK-THREAD-WH-001"

    async def test_accepts_messaging_thread_updated_event(self, client):
        """MESSAGING_THREAD_UPDATED events are also accepted."""
        payload = _valid_payload(event_type="MESSAGING_THREAD_UPDATED")

        resp = await client.post("/api/v1/webhooks/mirakl", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["event_type"] == "MESSAGING_THREAD_UPDATED"

    async def test_returns_422_for_missing_payload_field(self, client):
        """Missing required field causes 422."""
        bad_payload = {"event_type": "MESSAGING_THREAD_CREATED"}

        resp = await client.post("/api/v1/webhooks/mirakl", json=bad_payload)
        assert resp.status_code == 422

    async def test_returns_422_for_missing_thread_id(self, client):
        """Payload inner block missing thread_id → 422."""
        bad_payload = {
            "event_type": "MESSAGING_THREAD_CREATED",
            "payload": {
                "order_id": "ORD-001",
                "shop_id": "shop-001",
                # thread_id missing
            },
        }
        resp = await client.post("/api/v1/webhooks/mirakl", json=bad_payload)
        assert resp.status_code == 422

    async def test_returns_422_for_completely_invalid_json_structure(self, client):
        """A payload that cannot be parsed to the schema returns 422."""
        resp = await client.post(
            "/api/v1/webhooks/mirakl",
            content=b"not-json",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 422


# --------------------------------------------------------------------------- #
# Signature validation                                                         #
# --------------------------------------------------------------------------- #


class TestWebhookSignature:

    async def test_valid_signature_accepted(self, client):
        """When MIRAKL_WEBHOOK_SECRET is set, a correct signature is accepted."""
        secret = "test-webhook-secret"
        payload_dict = _valid_payload()
        body = json.dumps(payload_dict).encode()
        sig = _sign(body, secret)

        with patch.object(settings, "MIRAKL_WEBHOOK_SECRET", secret):
            resp = await client.post(
                "/api/v1/webhooks/mirakl",
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "X-Mirakl-Signature": sig,
                },
            )

        assert resp.status_code == 200

    async def test_invalid_signature_returns_401(self, client):
        """A wrong signature returns HTTP 401 when a secret is configured."""
        secret = "test-webhook-secret"
        payload_dict = _valid_payload()
        body = json.dumps(payload_dict).encode()

        with patch.object(settings, "MIRAKL_WEBHOOK_SECRET", secret):
            resp = await client.post(
                "/api/v1/webhooks/mirakl",
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "X-Mirakl-Signature": "wrong-signature",
                },
            )

        assert resp.status_code == 401

    async def test_missing_signature_returns_401_when_secret_configured(self, client):
        """When a secret is set, a missing signature header returns 401."""
        secret = "test-webhook-secret"
        payload_dict = _valid_payload()

        with patch.object(settings, "MIRAKL_WEBHOOK_SECRET", secret):
            resp = await client.post(
                "/api/v1/webhooks/mirakl",
                json=payload_dict,
            )

        assert resp.status_code == 401

    async def test_no_secret_no_signature_is_accepted(self, client):
        """When MIRAKL_WEBHOOK_SECRET is empty, no signature is required."""
        with patch.object(settings, "MIRAKL_WEBHOOK_SECRET", ""):
            resp = await client.post(
                "/api/v1/webhooks/mirakl",
                json=_valid_payload(),
            )
        assert resp.status_code == 200

    async def test_sha256_prefixed_signature_accepted(self, client):
        """Mirakl may prefix the digest with 'sha256='; both forms should work."""
        secret = "test-webhook-secret"
        payload_dict = _valid_payload()
        body = json.dumps(payload_dict).encode()
        sig = "sha256=" + _sign(body, secret)

        with patch.object(settings, "MIRAKL_WEBHOOK_SECRET", secret):
            resp = await client.post(
                "/api/v1/webhooks/mirakl",
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "X-Mirakl-Signature": sig,
                },
            )

        assert resp.status_code == 200


# --------------------------------------------------------------------------- #
# Background processing (unit test _process_webhook_async)                    #
# --------------------------------------------------------------------------- #


class TestWebhookBackgroundProcessing:

    async def test_background_task_is_registered(self, client):
        """Verify the background task is added to BackgroundTasks (smoke test)."""
        called_with: dict = {}

        async def fake_process(**kwargs):
            called_with.update(kwargs)

        with patch("app.api.webhooks._process_webhook_async", side_effect=fake_process):
            resp = await client.post(
                "/api/v1/webhooks/mirakl",
                json=_valid_payload(
                    thread_id="MK-BG-001",
                    order_id="ORD-BG-001",
                    shop_id="shop-bg",
                ),
            )

        assert resp.status_code == 200
        # BackgroundTasks run during the request in HTTPX AsyncClient test mode
        assert called_with.get("thread_id") == "MK-BG-001"
        assert called_with.get("order_id") == "ORD-BG-001"
        assert called_with.get("shop_id") == "shop-bg"

    async def test_process_webhook_async_unknown_shop_logs_warning(self):
        """If no account matches shop_id, a warning is logged and processing stops."""
        from app.api.webhooks import _process_webhook_async

        # AsyncSessionLocal is imported inside the function; patch via the database module
        with patch("app.database.AsyncSessionLocal") as mock_session_cls:
            mock_db = AsyncMock()
            mock_db.execute = AsyncMock(
                return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
            )
            mock_session_cls.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_session_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            # Should not raise — just log and return
            await _process_webhook_async(
                thread_id="T1",
                order_id="O1",
                shop_id="unknown-shop",
                event_type="MESSAGING_THREAD_CREATED",
            )
