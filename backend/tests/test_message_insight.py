"""Tests for the MessageInsightService using mock mode and parse helpers."""

from __future__ import annotations

import json

import pytest

from app.services.message_insight import InsightResult, MessageInsightService, TranslationResult


@pytest.fixture
def mock_insight_service() -> MessageInsightService:
    """MessageInsightService in mock mode (no LLM calls)."""
    return MessageInsightService(mock_mode=True)


class TestMockInsightService:
    """Verify the deterministic mock heuristics produce stable results."""

    async def test_returns_insight_result(self, mock_insight_service):
        result = await mock_insight_service.generate_insight(
            customer_message="Where is my order?",
            detected_language="en",
        )
        assert isinstance(result, InsightResult)
        assert isinstance(result.summary, str)
        assert isinstance(result.translated_message, str)

    async def test_english_message_has_empty_translation(self, mock_insight_service):
        result = await mock_insight_service.generate_insight(
            customer_message="Where is my order? I have been waiting for a week.",
            detected_language="en",
        )
        assert result is not None
        assert result.translated_message == ""

    async def test_non_english_message_has_translation(self, mock_insight_service):
        result = await mock_insight_service.generate_insight(
            customer_message="Waar is mijn pakket?",
            detected_language="nl",
        )
        assert result is not None
        assert result.translated_message != ""
        assert "nl" in result.translated_message.lower() or "waar" in result.translated_message.lower()

    async def test_refund_message_summary(self, mock_insight_service):
        result = await mock_insight_service.generate_insight(
            customer_message="I want a full refund for my order.",
            detected_language="en",
        )
        assert result is not None
        assert "refund" in result.summary.lower()

    async def test_return_message_summary(self, mock_insight_service):
        result = await mock_insight_service.generate_insight(
            customer_message="I would like to return this product.",
            detected_language="en",
        )
        assert result is not None
        assert "return" in result.summary.lower()

    async def test_tracking_message_summary(self, mock_insight_service):
        result = await mock_insight_service.generate_insight(
            customer_message="Where is my tracking information?",
            detected_language="en",
        )
        assert result is not None
        assert result.summary != ""

    async def test_defect_message_summary(self, mock_insight_service):
        result = await mock_insight_service.generate_insight(
            customer_message="The product is broken and has a defect.",
            detected_language="en",
        )
        assert result is not None
        assert "defect" in result.summary.lower() or "broken" in result.summary.lower()

    async def test_generic_message_has_summary(self, mock_insight_service):
        result = await mock_insight_service.generate_insight(
            customer_message="Hello, I have a question.",
            detected_language="en",
        )
        assert result is not None
        assert len(result.summary) > 0

    async def test_french_message_translated(self, mock_insight_service):
        result = await mock_insight_service.generate_insight(
            customer_message="Où est ma commande?",
            detected_language="fr",
        )
        assert result is not None
        assert result.translated_message != ""

    async def test_german_message_translated(self, mock_insight_service):
        result = await mock_insight_service.generate_insight(
            customer_message="Wo ist meine Bestellung?",
            detected_language="de",
        )
        assert result is not None
        assert result.translated_message != ""

    async def test_dutch_refund_message_summary(self, mock_insight_service):
        result = await mock_insight_service.generate_insight(
            customer_message="Ik wil een terugbetaling voor mijn bestelling.",
            detected_language="nl",
        )
        assert result is not None
        assert "refund" in result.summary.lower()


class TestParseResponse:
    """Test _parse_response with various JSON shapes."""

    def setup_method(self):
        self.service = MessageInsightService(mock_mode=False)

    def test_valid_response_parses(self):
        raw = json.dumps({
            "summary": "The customer is asking about their order status.",
            "translated_message": "",
        })
        result = self.service._parse_response(raw)
        assert result.summary == "The customer is asking about their order status."
        assert result.translated_message == ""

    def test_translation_preserved(self):
        raw = json.dumps({
            "summary": "Customer wants to know where their package is.",
            "translated_message": "Where is my package? I have been waiting for a week.",
        })
        result = self.service._parse_response(raw)
        assert "package" in result.translated_message

    def test_whitespace_stripped_from_fields(self):
        raw = json.dumps({
            "summary": "  Customer is frustrated.  ",
            "translated_message": "  Where is my order?  ",
        })
        result = self.service._parse_response(raw)
        assert result.summary == "Customer is frustrated."
        assert result.translated_message == "Where is my order?"

    def test_invalid_json_raises_value_error(self):
        with pytest.raises(ValueError, match="not valid JSON"):
            self.service._parse_response("not json at all {")

    def test_missing_summary_raises_value_error(self):
        raw = json.dumps({"translated_message": ""})
        with pytest.raises(ValueError, match="missing required fields"):
            self.service._parse_response(raw)

    def test_missing_translated_message_raises_value_error(self):
        raw = json.dumps({"summary": "The customer has a question."})
        with pytest.raises(ValueError, match="missing required fields"):
            self.service._parse_response(raw)

    def test_empty_json_object_raises_value_error(self):
        raw = json.dumps({})
        with pytest.raises(ValueError, match="missing required fields"):
            self.service._parse_response(raw)


class TestInsightServiceErrorHandling:
    """Verify that errors in the live path are swallowed and None is returned."""

    async def test_network_error_returns_none(self, monkeypatch):
        """A network failure must not propagate — None is returned instead."""
        import httpx

        service = MessageInsightService(mock_mode=False)

        async def raise_network_error(*args, **kwargs):
            raise httpx.ConnectError("Connection refused")

        monkeypatch.setattr(
            "httpx.AsyncClient.post",
            raise_network_error,
        )

        result = await service.generate_insight(
            customer_message="Test message",
            detected_language="en",
        )
        assert result is None

    async def test_bad_json_from_llm_returns_none(self, monkeypatch):
        """An unparseable LLM response must not propagate."""
        service = MessageInsightService(mock_mode=False)

        # Patch _call_llm to return bad JSON
        async def return_bad_json(user_content: str) -> str:
            return "not valid json {"

        monkeypatch.setattr(service, "_call_llm", return_bad_json)

        result = await service.generate_insight(
            customer_message="Test message",
            detected_language="en",
        )
        assert result is None


class TestMockTranslateDraft:
    """Verify the deterministic mock for translate_draft returns stable results."""

    async def test_returns_translation_result(self, mock_insight_service):
        result = await mock_insight_service.translate_draft(
            english_text="Dear customer, your order is on its way.",
            target_language="nl",
        )
        assert isinstance(result, TranslationResult)

    async def test_translated_text_contains_source(self, mock_insight_service):
        source = "Dear customer, your order is on its way."
        result = await mock_insight_service.translate_draft(
            english_text=source,
            target_language="nl",
        )
        assert result is not None
        assert source in result.translated_text

    async def test_translated_text_contains_target_language(self, mock_insight_service):
        result = await mock_insight_service.translate_draft(
            english_text="Thank you for your message.",
            target_language="fr",
        )
        assert result is not None
        assert "fr" in result.translated_text

    async def test_mock_returns_no_correction(self, mock_insight_service):
        result = await mock_insight_service.translate_draft(
            english_text="We apologise for the inconvenience.",
            target_language="de",
        )
        assert result is not None
        assert result.correction_made is False
        assert result.correction_note == ""

    async def test_different_target_languages_differ(self, mock_insight_service):
        source = "Your order has shipped."
        result_nl = await mock_insight_service.translate_draft(source, "nl")
        result_fr = await mock_insight_service.translate_draft(source, "fr")
        assert result_nl is not None
        assert result_fr is not None
        assert result_nl.translated_text != result_fr.translated_text


class TestParseTranslationResponse:
    """Test _parse_translation_response with various JSON shapes."""

    def setup_method(self):
        self.service = MessageInsightService(mock_mode=False)

    def test_valid_response_parses(self):
        raw = json.dumps({
            "translated_text": "Bedankt voor uw bericht.",
            "correction_made": False,
            "correction_note": "",
        })
        result = self.service._parse_translation_response(raw)
        assert result.translated_text == "Bedankt voor uw bericht."
        assert result.correction_made is False
        assert result.correction_note == ""

    def test_correction_fields_preserved(self):
        raw = json.dumps({
            "translated_text": "Merci pour votre message.",
            "correction_made": True,
            "correction_note": "Original omitted the delivery promise.",
        })
        result = self.service._parse_translation_response(raw)
        assert result.correction_made is True
        assert "delivery" in result.correction_note

    def test_whitespace_stripped_from_text_fields(self):
        raw = json.dumps({
            "translated_text": "  Vielen Dank.  ",
            "correction_made": False,
            "correction_note": "  ",
        })
        result = self.service._parse_translation_response(raw)
        assert result.translated_text == "Vielen Dank."
        assert result.correction_note == ""

    def test_invalid_json_raises_value_error(self):
        with pytest.raises(ValueError, match="not valid JSON"):
            self.service._parse_translation_response("not json {")

    def test_missing_translated_text_raises_value_error(self):
        raw = json.dumps({"correction_made": False, "correction_note": ""})
        with pytest.raises(ValueError, match="missing required fields"):
            self.service._parse_translation_response(raw)

    def test_missing_correction_made_raises_value_error(self):
        raw = json.dumps({"translated_text": "Hallo.", "correction_note": ""})
        with pytest.raises(ValueError, match="missing required fields"):
            self.service._parse_translation_response(raw)

    def test_missing_correction_note_raises_value_error(self):
        raw = json.dumps({"translated_text": "Hallo.", "correction_made": False})
        with pytest.raises(ValueError, match="missing required fields"):
            self.service._parse_translation_response(raw)

    def test_empty_object_raises_value_error(self):
        with pytest.raises(ValueError, match="missing required fields"):
            self.service._parse_translation_response("{}")


class TestTranslateDraftErrorHandling:
    """Verify that errors in the live translate_draft path are swallowed."""

    async def test_network_error_returns_none(self, monkeypatch):
        import httpx

        service = MessageInsightService(mock_mode=False)

        async def raise_network_error(*args, **kwargs):
            raise httpx.ConnectError("Connection refused")

        monkeypatch.setattr("httpx.AsyncClient.post", raise_network_error)

        result = await service.translate_draft(
            english_text="Your order is on its way.",
            target_language="nl",
        )
        assert result is None

    async def test_bad_json_from_llm_returns_none(self, monkeypatch):
        service = MessageInsightService(mock_mode=False)

        async def return_bad_json(user_content: str, *, system_prompt: str) -> str:
            return "not valid json {"

        monkeypatch.setattr(service, "_call_llm", return_bad_json)

        result = await service.translate_draft(
            english_text="Your order is on its way.",
            target_language="nl",
        )
        assert result is None

    async def test_missing_fields_from_llm_returns_none(self, monkeypatch):
        service = MessageInsightService(mock_mode=False)

        async def return_incomplete_json(user_content: str, *, system_prompt: str) -> str:
            return json.dumps({"translated_text": "Uw bestelling is onderweg."})

        monkeypatch.setattr(service, "_call_llm", return_incomplete_json)

        result = await service.translate_draft(
            english_text="Your order is on its way.",
            target_language="nl",
        )
        assert result is None


class TestTranslateHtml:
    """translate_html renders a whole HTML card in the target language, tags intact."""

    @pytest.mark.asyncio
    async def test_extracts_translated_html_from_json(self, monkeypatch):
        svc = MessageInsightService()

        async def fake_call(user_content, *, system_prompt):
            return '{"translated": "<b>Order</b>\\n<blockquote>Where is my parcel?</blockquote>"}'

        monkeypatch.setattr(svc, "_call_llm", fake_call)
        out = await svc.translate_html(
            "<b>Bestelling</b>\n<blockquote>Waar is mijn pakket?</blockquote>", "en"
        )
        assert out == "<b>Order</b>\n<blockquote>Where is my parcel?</blockquote>"

    @pytest.mark.asyncio
    async def test_mock_mode_prefixes(self):
        out = await MessageInsightService(mock_mode=True).translate_html("<b>hi</b>", "en")
        assert out == "[en] <b>hi</b>"

    @pytest.mark.asyncio
    async def test_empty_returns_none(self):
        assert await MessageInsightService().translate_html("   ", "en") is None
