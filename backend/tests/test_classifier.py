"""Tests for the MessageClassifier service using mock mode."""

from __future__ import annotations

import json

import pytest
import pytest_asyncio

from app.core.exceptions import ClassificationError
from app.models.support_thread import CustomerLanguage, RiskLevel
from app.services.classifier import ClassificationResult, MessageClassifier


@pytest_asyncio.fixture
def mock_classifier():
    """MessageClassifier in mock mode (no LLM calls)."""
    return MessageClassifier(mock_mode=True)


class TestMockClassifier:
    """Test the deterministic mock classification heuristics."""

    async def test_shipping_delay_classified_green(self, mock_classifier):
        result = await mock_classifier.classify(
            "Where is my order? I have been waiting for a week."
        )
        assert result.risk_level == RiskLevel.GREEN
        assert result.category == "shipping_delay"
        assert result.language == CustomerLanguage.en

    async def test_return_request_classified_orange(self, mock_classifier):
        result = await mock_classifier.classify(
            "I want to return the product I received."
        )
        assert result.risk_level == RiskLevel.ORANGE
        assert result.category == "return_request"

    async def test_refund_request_classified_red(self, mock_classifier):
        result = await mock_classifier.classify(
            "I demand a full refund for this purchase."
        )
        assert result.risk_level == RiskLevel.RED
        assert result.category == "refund_request"

    async def test_warranty_classified_orange(self, mock_classifier):
        result = await mock_classifier.classify(
            "The product is broken and I need warranty service."
        )
        assert result.risk_level == RiskLevel.ORANGE
        assert result.category == "warranty_claim"

    async def test_dutch_language_detected(self, mock_classifier):
        result = await mock_classifier.classify(
            "Waar is mijn pakket? Ik heb niets ontvangen."
        )
        assert result.language == CustomerLanguage.nl

    async def test_french_language_detected(self, mock_classifier):
        result = await mock_classifier.classify(
            "Où est ma commande? La livraison est en retard."
        )
        assert result.language == CustomerLanguage.fr

    async def test_german_language_detected(self, mock_classifier):
        result = await mock_classifier.classify(
            "Wo ist meine Bestellung? Die Lieferung ist überfällig."
        )
        assert result.language == CustomerLanguage.de

    async def test_general_inquiry_default(self, mock_classifier):
        result = await mock_classifier.classify("Hello, I have a question about my account.")
        assert result.category == "general_inquiry"
        assert result.risk_level == RiskLevel.GREEN

    async def test_with_order_context(self, mock_classifier):
        """Order context is accepted without error in mock mode."""
        context = {"id": "ORD-001", "status": "SHIPPED"}
        result = await mock_classifier.classify(
            "Where is my order?",
            order_context=context,
        )
        assert isinstance(result, ClassificationResult)

    async def test_returns_classification_result(self, mock_classifier):
        result = await mock_classifier.classify("test message")
        assert isinstance(result, ClassificationResult)
        assert isinstance(result.category, str)
        assert isinstance(result.risk_level, RiskLevel)
        assert isinstance(result.language, CustomerLanguage)


class TestParseResponse:
    """Test _parse_response with various JSON shapes."""

    def setup_method(self):
        self.classifier = MessageClassifier(mock_mode=False)

    def test_valid_response_parses(self):
        raw = json.dumps({
            "category": "shipping_delay",
            "risk_level": "GREEN",
            "language": "en",
        })
        result = self.classifier._parse_response(raw)
        assert result.category == "shipping_delay"
        assert result.risk_level == RiskLevel.GREEN
        assert result.language == CustomerLanguage.en

    def test_category_normalised_to_snake_case(self):
        raw = json.dumps({
            "category": "Shipping Delay",
            "risk_level": "GREEN",
            "language": "nl",
        })
        result = self.classifier._parse_response(raw)
        assert result.category == "shipping_delay"

    def test_invalid_json_raises(self):
        with pytest.raises(ClassificationError, match="not valid JSON"):
            self.classifier._parse_response("not json at all")

    def test_missing_risk_level_raises(self):
        raw = json.dumps({"category": "general_inquiry", "language": "en"})
        with pytest.raises(ClassificationError, match="missing required fields"):
            self.classifier._parse_response(raw)

    def test_missing_language_raises(self):
        raw = json.dumps({"category": "general_inquiry", "risk_level": "GREEN"})
        with pytest.raises(ClassificationError, match="missing required fields"):
            self.classifier._parse_response(raw)

    def test_missing_category_raises(self):
        raw = json.dumps({"risk_level": "GREEN", "language": "en"})
        with pytest.raises(ClassificationError, match="missing required fields"):
            self.classifier._parse_response(raw)

    def test_invalid_risk_level_raises(self):
        raw = json.dumps({
            "category": "general_inquiry",
            "risk_level": "YELLOW",
            "language": "en",
        })
        with pytest.raises(ClassificationError, match="Invalid risk_level"):
            self.classifier._parse_response(raw)

    def test_invalid_language_raises(self):
        raw = json.dumps({
            "category": "general_inquiry",
            "risk_level": "GREEN",
            "language": "es",  # Not in supported list
        })
        with pytest.raises(ClassificationError, match="Invalid language"):
            self.classifier._parse_response(raw)

    def test_empty_category_raises(self):
        raw = json.dumps({
            "category": "",
            "risk_level": "GREEN",
            "language": "en",
        })
        with pytest.raises(ClassificationError, match="empty"):
            self.classifier._parse_response(raw)

    def test_all_risk_levels_accepted(self):
        for level in ("GREEN", "ORANGE", "RED"):
            raw = json.dumps({
                "category": "test_category",
                "risk_level": level,
                "language": "en",
            })
            result = self.classifier._parse_response(raw)
            assert result.risk_level.value == level

    def test_all_languages_accepted(self):
        for lang in ("nl", "en", "fr", "de"):
            raw = json.dumps({
                "category": "general_inquiry",
                "risk_level": "GREEN",
                "language": lang,
            })
            result = self.classifier._parse_response(raw)
            assert result.language.value == lang
