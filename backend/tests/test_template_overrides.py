"""Tests for P4.3: marketplace-specific template override endpoints.

Covers:
  POST   /api/v1/templates/override
  GET    /api/v1/templates/overrides/{marketplace_account_id}
  DELETE /api/v1/templates/overrides/{id}
"""

from __future__ import annotations

import uuid

import pytest

from app.models.response_template import ResponseTemplate


# ---------------------------------------------------------------------------
# POST /api/v1/templates/override
# ---------------------------------------------------------------------------


class TestCreateTemplateOverride:

    async def test_create_override_returns_201(self, client, sample_account):
        payload = {
            "marketplace_account_id": str(sample_account.id),
            "category": "shipping_delay",
            "language": "en",
            "template_body": "Hi {{ customer_name }}, your order {{ order_id }} is on its way.",
        }
        resp = await client.post("/api/v1/templates/override", json=payload)
        assert resp.status_code == 201

    async def test_create_override_returns_correct_fields(self, client, sample_account):
        payload = {
            "marketplace_account_id": str(sample_account.id),
            "category": "return_request",
            "language": "nl",
            "template_body": "Beste klant, uw retour is ontvangen.",
        }
        resp = await client.post("/api/v1/templates/override", json=payload)
        assert resp.status_code == 201
        data = resp.json()
        assert data["marketplace_account_id"] == str(sample_account.id)
        assert data["category"] == "return_request"
        assert data["language"] == "nl"
        assert data["template_body"] == "Beste klant, uw retour is ontvangen."
        assert data["is_active"] is True
        assert "id" in data
        assert "created_at" in data
        assert "updated_at" in data

    async def test_create_override_nonexistent_account_returns_404(self, client):
        payload = {
            "marketplace_account_id": str(uuid.uuid4()),
            "category": "shipping_delay",
            "language": "en",
            "template_body": "Your order is on the way.",
        }
        resp = await client.post("/api/v1/templates/override", json=payload)
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()

    async def test_create_duplicate_override_returns_409(self, client, sample_account):
        payload = {
            "marketplace_account_id": str(sample_account.id),
            "category": "shipping_delay",
            "language": "fr",
            "template_body": "Votre commande est en route.",
        }
        first = await client.post("/api/v1/templates/override", json=payload)
        assert first.status_code == 201

        # Same account + category + language — should be rejected
        payload["template_body"] = "Un autre texte."
        second = await client.post("/api/v1/templates/override", json=payload)
        assert second.status_code == 409
        assert "already exists" in second.json()["detail"].lower()

    async def test_create_override_different_language_allowed(self, client, sample_account):
        """Same account+category but different language is a distinct override."""
        base = {
            "marketplace_account_id": str(sample_account.id),
            "category": "warranty_claim",
            "template_body": "Template body.",
        }
        r1 = await client.post("/api/v1/templates/override", json={**base, "language": "en"})
        r2 = await client.post("/api/v1/templates/override", json={**base, "language": "de"})
        assert r1.status_code == 201
        assert r2.status_code == 201

    async def test_create_override_different_category_allowed(self, client, sample_account):
        """Same account+language but different category is a distinct override."""
        base = {
            "marketplace_account_id": str(sample_account.id),
            "language": "en",
            "template_body": "Template body.",
        }
        r1 = await client.post("/api/v1/templates/override", json={**base, "category": "shipping_delay"})
        r2 = await client.post("/api/v1/templates/override", json={**base, "category": "return_request"})
        assert r1.status_code == 201
        assert r2.status_code == 201

    async def test_create_override_invalid_language_returns_422(self, client, sample_account):
        payload = {
            "marketplace_account_id": str(sample_account.id),
            "category": "shipping_delay",
            "language": "xx",  # unsupported
            "template_body": "Template body.",
        }
        resp = await client.post("/api/v1/templates/override", json=payload)
        assert resp.status_code == 422

    async def test_create_override_empty_body_returns_422(self, client, sample_account):
        payload = {
            "marketplace_account_id": str(sample_account.id),
            "category": "shipping_delay",
            "language": "en",
            "template_body": "",  # violates min_length=1
        }
        resp = await client.post("/api/v1/templates/override", json=payload)
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# GET /api/v1/templates/overrides/{marketplace_account_id}
# ---------------------------------------------------------------------------


class TestListTemplateOverrides:

    async def test_list_returns_empty_for_account_with_no_overrides(
        self, client, sample_account
    ):
        resp = await client.get(f"/api/v1/templates/overrides/{sample_account.id}")
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_list_returns_nonexistent_account_404(self, client):
        resp = await client.get(f"/api/v1/templates/overrides/{uuid.uuid4()}")
        assert resp.status_code == 404

    async def test_list_returns_created_overrides(self, client, sample_account):
        # Create two overrides for this account
        for lang in ("en", "nl"):
            payload = {
                "marketplace_account_id": str(sample_account.id),
                "category": "invoice_request",
                "language": lang,
                "template_body": f"Invoice template ({lang}).",
            }
            r = await client.post("/api/v1/templates/override", json=payload)
            assert r.status_code == 201

        resp = await client.get(f"/api/v1/templates/overrides/{sample_account.id}")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        languages = {item["language"] for item in data}
        assert languages == {"en", "nl"}

    async def test_list_does_not_return_global_templates(
        self, client, sample_account, sample_template
    ):
        """Global templates (marketplace_account_id=NULL) must not appear in overrides list."""
        resp = await client.get(f"/api/v1/templates/overrides/{sample_account.id}")
        assert resp.status_code == 200
        for item in resp.json():
            assert item["marketplace_account_id"] == str(sample_account.id)

    async def test_list_includes_inactive_overrides(self, client, sample_account, db):
        """Listing overrides returns both active and inactive records."""
        override = ResponseTemplate(
            id=uuid.uuid4(),
            marketplace_account_id=sample_account.id,
            category="shipping_delay",
            language="de",
            template_body="Ihr Paket ist unterwegs.",
            is_active=False,  # explicitly inactive
        )
        db.add(override)
        await db.flush()

        resp = await client.get(f"/api/v1/templates/overrides/{sample_account.id}")
        assert resp.status_code == 200
        ids = [item["id"] for item in resp.json()]
        assert str(override.id) in ids


# ---------------------------------------------------------------------------
# DELETE /api/v1/templates/overrides/{id}
# ---------------------------------------------------------------------------


class TestDeleteTemplateOverride:

    async def _create_override(self, client, sample_account, category="shipping_delay", language="en"):
        payload = {
            "marketplace_account_id": str(sample_account.id),
            "category": category,
            "language": language,
            "template_body": "Override body.",
        }
        r = await client.post("/api/v1/templates/override", json=payload)
        assert r.status_code == 201
        return r.json()

    async def test_delete_removes_override(self, client, sample_account, db):
        override = await self._create_override(client, sample_account)
        override_id = override["id"]

        resp = await client.delete(f"/api/v1/templates/overrides/{override_id}")
        assert resp.status_code == 204

        # Verify the record is gone from the database
        record = await db.get(ResponseTemplate, uuid.UUID(override_id))
        assert record is None

    async def test_delete_nonexistent_returns_404(self, client):
        resp = await client.delete(f"/api/v1/templates/overrides/{uuid.uuid4()}")
        assert resp.status_code == 404

    async def test_delete_global_template_returns_400(
        self, client, sample_template
    ):
        """Cannot delete a global template through the override endpoint."""
        resp = await client.delete(f"/api/v1/templates/overrides/{sample_template.id}")
        assert resp.status_code == 400
        assert "global" in resp.json()["detail"].lower()

    async def test_delete_allows_recreating_same_override(self, client, sample_account):
        """After deletion a new override for the same combo can be created."""
        override = await self._create_override(client, sample_account, category="return_request", language="fr")
        override_id = override["id"]

        del_resp = await client.delete(f"/api/v1/templates/overrides/{override_id}")
        assert del_resp.status_code == 204

        new_payload = {
            "marketplace_account_id": str(sample_account.id),
            "category": "return_request",
            "language": "fr",
            "template_body": "Nouvelle réponse retour.",
        }
        recreate_resp = await client.post("/api/v1/templates/override", json=new_payload)
        assert recreate_resp.status_code == 201
