"""Tests for the MessageInsightService using mock mode and parse helpers."""

from __future__ import annotations

import json

import pytest

from app.services.message_insight import InsightResult, MessageInsightService


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
