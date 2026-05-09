"""Message classifier service.

Architecture decision D1: the LLM determines category, risk_level, and
language. It does NOT generate the response text.

The classifier sends the customer message and any available order context to
the configured LLM and parses a structured JSON response. A mock mode is
available for testing without a live LLM API.

Expected LLM JSON response schema:
{
  "category": "<string>",
  "risk_level": "GREEN" | "ORANGE" | "RED",
  "language": "nl" | "en" | "fr" | "de"
}
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

import httpx

from app.config import settings
from app.core.exceptions import ClassificationError
from app.models.support_thread import CustomerLanguage, RiskLevel

logger = logging.getLogger(__name__)

CLASSIFIER_CATEGORIES: tuple[str, ...] = (
    "tracking_update",
    "invoice_request",
    "return_inquiry",
    "complaint",
    "defect_report",
    "delivery_confirmation",
    "general_inquiry",
)
_WELL_KNOWN_CATEGORIES = ", ".join(CLASSIFIER_CATEGORIES)


@dataclass
class ClassificationResult:
    """Structured output from the LLM classifier."""

    category: str
    risk_level: RiskLevel
    language: CustomerLanguage


_SYSTEM_PROMPT = """\
You are a customer support classifier for an e-commerce seller on multiple Mirakl marketplaces.

Analyse the customer message and available order context, then respond with a JSON object \
containing exactly three keys:

1. "category": MUST be exactly one of these values: {well_known_categories}. \
Pick the closest match. Use "general_inquiry" if none fit well.

2. "risk_level": One of "GREEN", "ORANGE", or "RED" based on automation safety:
   - GREEN  = Standard query answerable by template; safe for auto-send after safety checks.
   - ORANGE = Ambiguous or sensitive; a draft should be prepared but human approval is required.
   - RED    = High risk, complex, legal/financial exposure, or operator involvement; no automation.

3. "language": The ISO 639-1 code of the customer message. Must be one of: "nl", "en", "fr", "de".

Respond with ONLY the JSON object. No prose, no markdown fences.
""".format(well_known_categories=_WELL_KNOWN_CATEGORIES)


class MessageClassifier:
    """Classifies a customer message using the configured LLM.

    Args:
        mock_mode: When True, the classifier returns a deterministic mock
                   response without making any network calls. Useful for
                   unit tests and local development without an LLM API key.
    """

    def __init__(self, *, mock_mode: bool = False) -> None:
        self._mock_mode = mock_mode

    async def classify(
        self,
        customer_message: str,
        order_context: dict[str, Any] | None = None,
    ) -> ClassificationResult:
        """Classify a customer message.

        Args:
            customer_message: Raw text from the customer as collected from Mirakl.
            order_context:    Optional dict of order data from the connector layer.
                              Included in the LLM prompt to improve classification accuracy.

        Returns:
            A :class:`ClassificationResult` with category, risk_level, and language.

        Raises:
            ClassificationError: If the LLM response cannot be parsed or contains
                                  invalid enum values.
        """
        if self._mock_mode:
            return self._mock_classify(customer_message)

        user_content = self._build_user_content(customer_message, order_context)
        raw_response = await self._call_llm(user_content)
        return self._parse_response(raw_response)

    # ------------------------------------------------------------------ #
    # Internals                                                            #
    # ------------------------------------------------------------------ #

    def _build_user_content(
        self,
        customer_message: str,
        order_context: dict[str, Any] | None,
    ) -> str:
        parts = [f"Customer message:\n{customer_message}"]
        if order_context:
            parts.append(f"\nOrder context:\n{json.dumps(order_context, indent=2)}")
        return "\n".join(parts)

    async def _call_llm(self, user_content: str) -> str:
        """Make an async HTTP call to the LLM chat completions endpoint.

        Returns:
            The raw text content of the assistant message.

        Raises:
            ClassificationError: On HTTP errors or timeout.
        """
        payload = {
            "model": settings.LLM_MODEL,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            "temperature": 0.0,  # deterministic classification
            "max_tokens": 200,
            "response_format": {"type": "json_object"},
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{settings.LLM_API_BASE_URL}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {settings.LLM_API_KEY}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
        except httpx.RequestError as exc:
            raise ClassificationError(
                f"LLM API network error: {exc}",
                detail=str(exc),
            ) from exc

        if response.is_error:
            raise ClassificationError(
                f"LLM API returned HTTP {response.status_code}",
                raw_response=response.text[:500],
                detail=f"status={response.status_code}",
            )

        data = response.json()
        try:
            content: str = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as exc:
            raise ClassificationError(
                "Unexpected LLM response structure",
                raw_response=str(data)[:500],
                detail=str(exc),
            ) from exc

        return content

    def _parse_response(self, raw: str) -> ClassificationResult:
        """Parse the raw LLM JSON response into a ClassificationResult.

        Raises:
            ClassificationError: If JSON is invalid or required fields are missing
                                  or contain invalid enum values.
        """
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ClassificationError(
                "LLM response is not valid JSON",
                raw_response=raw[:500],
                detail=str(exc),
            ) from exc

        missing = [k for k in ("category", "risk_level", "language") if k not in data]
        if missing:
            raise ClassificationError(
                f"LLM response missing required fields: {missing}",
                raw_response=raw[:500],
            )

        try:
            risk_level = RiskLevel(data["risk_level"])
        except ValueError as exc:
            raise ClassificationError(
                f"Invalid risk_level value: {data['risk_level']!r}. "
                f"Must be one of {[e.value for e in RiskLevel]}.",
                raw_response=raw[:500],
                detail=str(exc),
            ) from exc

        try:
            language = CustomerLanguage(data["language"])
        except ValueError as exc:
            raise ClassificationError(
                f"Invalid language value: {data['language']!r}. "
                f"Must be one of {[e.value for e in CustomerLanguage]}.",
                raw_response=raw[:500],
                detail=str(exc),
            ) from exc

        category = str(data["category"]).strip().lower().replace(" ", "_")
        if not category:
            raise ClassificationError(
                "LLM response 'category' field is empty",
                raw_response=raw[:500],
            )

        return ClassificationResult(
            category=category,
            risk_level=risk_level,
            language=language,
        )

    @staticmethod
    def _mock_classify(customer_message: str) -> ClassificationResult:
        """Deterministic mock classification for tests and local dev.

        Applies simple keyword heuristics so that test assertions are
        predictable without needing a real LLM API key.
        """
        message_lower = customer_message.lower()

        # Determine language by keyword presence
        if any(word in message_lower for word in ["waar", "pakket", "bestelling", "bezorgd"]):
            language = CustomerLanguage.nl
        elif any(word in message_lower for word in ["où", "commande", "livraison"]):
            language = CustomerLanguage.fr
        elif any(word in message_lower for word in ["wo", "bestellung", "lieferung"]):
            language = CustomerLanguage.de
        else:
            language = CustomerLanguage.en

        # Determine category and risk_level
        if any(word in message_lower for word in ["refund", "money back", "terugbetaling"]):
            return ClassificationResult(
                category="refund_request",
                risk_level=RiskLevel.RED,
                language=language,
            )
        if any(word in message_lower for word in ["return", "retour", "rücksendung", "terugsturen"]):
            return ClassificationResult(
                category="return_request",
                risk_level=RiskLevel.ORANGE,
                language=language,
            )
        if any(word in message_lower for word in ["warranty", "defect", "broken", "garantie", "kapot"]):
            return ClassificationResult(
                category="warranty_claim",
                risk_level=RiskLevel.ORANGE,
                language=language,
            )
        if any(word in message_lower for word in ["where", "tracking", "delivered", "waar", "levering"]):
            return ClassificationResult(
                category="shipping_delay",
                risk_level=RiskLevel.GREEN,
                language=language,
            )

        # Default
        return ClassificationResult(
            category="general_inquiry",
            risk_level=RiskLevel.GREEN,
            language=language,
        )
