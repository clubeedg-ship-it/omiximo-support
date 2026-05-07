"""Tests for template resolution and Jinja2 rendering."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio

from app.core.exceptions import TemplateNotFoundError, TemplateRenderError
from app.models.marketplace_account import MarketplaceAccount
from app.models.response_template import ResponseTemplate
from app.models.support_thread import CustomerLanguage
from app.services.encryption import encrypt
from app.services.template_engine import TemplateEngine


@pytest_asyncio.fixture
async def engine_instance():
    return TemplateEngine()


class TestTemplateResolution:

    async def test_global_template_found(
        self, db, sample_template, engine_instance
    ):
        """Global template (account_id=None) is found when category+language match."""
        rendered = await engine_instance.render(
            db,
            category="shipping_delay",
            language=CustomerLanguage.en,
            marketplace_account_id=uuid.uuid4(),  # Any account
            context={"order_id": "ORD-123", "shop_name": "TestShop"},
        )
        assert "ORD-123" in rendered
        assert "TestShop" in rendered

    async def test_account_scoped_template_preferred_over_global(
        self, db, sample_account, sample_template, nl_template, engine_instance
    ):
        """Account-scoped template takes priority over global when both match."""
        rendered = await engine_instance.render(
            db,
            category="shipping_delay",
            language=CustomerLanguage.nl,
            marketplace_account_id=sample_account.id,
            context={"order_id": "ORD-NL-001", "shop_name": "MediaMarkt"},
        )
        assert "ORD-NL-001" in rendered
        # Dutch template uses "Beste" greeting
        assert "Beste" in rendered

    async def test_template_not_found_raises(self, db, engine_instance):
        """TemplateNotFoundError raised when no matching template exists."""
        with pytest.raises(TemplateNotFoundError) as exc_info:
            await engine_instance.render(
                db,
                category="nonexistent_category_xyz",
                language=CustomerLanguage.en,
                marketplace_account_id=uuid.uuid4(),
                context={},
            )
        assert "nonexistent_category_xyz" in exc_info.value.message

    async def test_inactive_template_not_returned(self, db, engine_instance, sample_account):
        """Inactive templates are excluded from resolution."""
        # Create an inactive template
        inactive = ResponseTemplate(
            id=uuid.uuid4(),
            marketplace_account_id=None,
            category="invoice_request",
            language="en",
            template_body="This is an inactive template.",
            is_active=False,
        )
        db.add(inactive)
        await db.flush()

        with pytest.raises(TemplateNotFoundError):
            await engine_instance.render(
                db,
                category="invoice_request",
                language=CustomerLanguage.en,
                marketplace_account_id=sample_account.id,
                context={},
            )


class TestJinja2Rendering:

    async def test_slots_rendered_correctly(self, db, sample_template, engine_instance):
        """All standard slots are replaced in the rendered output."""
        rendered = await engine_instance.render(
            db,
            category="shipping_delay",
            language=CustomerLanguage.en,
            marketplace_account_id=uuid.uuid4(),
            context={
                "order_id": "ORD-999",
                "tracking_number": "TRACK-XYZ",
                "customer_name": "Jan",
                "shop_name": "BestShop",
            },
        )
        assert "ORD-999" in rendered
        assert "TRACK-XYZ" in rendered
        assert "Jan" in rendered
        assert "BestShop" in rendered

    async def test_missing_optional_slot_uses_default(
        self, db, sample_template, engine_instance
    ):
        """Template uses 'or' fallback for optional slots like tracking_number."""
        rendered = await engine_instance.render(
            db,
            category="shipping_delay",
            language=CustomerLanguage.en,
            marketplace_account_id=uuid.uuid4(),
            context={"order_id": "ORD-111", "shop_name": "Shop"},
            # No tracking_number provided
        )
        # The template body uses {{ tracking_number or 'not yet available' }}
        assert "not yet available" in rendered

    async def test_syntax_error_in_template_raises_render_error(
        self, db, engine_instance, sample_account
    ):
        """A Jinja2 syntax error in the template body raises TemplateRenderError."""
        broken = ResponseTemplate(
            id=uuid.uuid4(),
            marketplace_account_id=None,
            category="broken_template",
            language="en",
            template_body="{{ unclosed_tag",
            is_active=True,
        )
        db.add(broken)
        await db.flush()

        with pytest.raises(TemplateRenderError):
            await engine_instance.render(
                db,
                category="broken_template",
                language=CustomerLanguage.en,
                marketplace_account_id=sample_account.id,
                context={},
            )

    async def test_multiline_template_renders(self, db, engine_instance, sample_account):
        """Multi-line templates render without collapsing newlines."""
        template = ResponseTemplate(
            id=uuid.uuid4(),
            marketplace_account_id=None,
            category="general_inquiry",
            language="en",
            template_body="Line 1\nLine 2\nLine 3",
            is_active=True,
        )
        db.add(template)
        await db.flush()

        rendered = await engine_instance.render(
            db,
            category="general_inquiry",
            language=CustomerLanguage.en,
            marketplace_account_id=sample_account.id,
            context={},
        )
        assert "Line 1" in rendered
        assert "Line 2" in rendered
        assert "Line 3" in rendered

    async def test_context_overrides_defaults(
        self, db, sample_template, engine_instance
    ):
        """Caller-supplied context values override the empty-string defaults."""
        rendered = await engine_instance.render(
            db,
            category="shipping_delay",
            language=CustomerLanguage.en,
            marketplace_account_id=uuid.uuid4(),
            context={
                "order_id": "CUSTOM-ORDER",
                "tracking_number": "CUSTOM-TRACKING",
                "shop_name": "Custom Shop",
                "customer_name": "Alice",
                "delivery_date": "2026-05-15",
            },
        )
        assert "CUSTOM-ORDER" in rendered
        assert "CUSTOM-TRACKING" in rendered
        assert "Custom Shop" in rendered
