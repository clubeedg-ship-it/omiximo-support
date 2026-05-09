"""Message insight service.

Produces a concise English summary and an English translation of the raw
customer message. Both fields are generated in a single LLM call so we
minimise latency and API cost.

Architecture note (D1): The insight service does NOT classify or generate
response drafts. It is a read-only enrichment step that runs after
classification and writes two nullable columns on the thread record:
  - message_summary     — 1-2 sentence English description of what the
                          customer wants and their tone/urgency.
  - translated_message  — Full English translation of the customer message.
                          Empty string when the message is already in English.

Errors are logged and swallowed; the insight step must never block the
classify → draft → safety → send pipeline.

A mock_mode is provided for tests (no network calls).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are a multilingual customer support assistant for an e-commerce seller.

Given a raw customer message and the detected language, produce a JSON object \
with exactly two keys:

1. "summary": 1-2 sentences in English describing what the customer wants and \
their tone or urgency (e.g. frustrated, polite, urgent).

2. "translated_message": Full English translation of the customer message. \
If the message is already written in English, return an empty string "".

Respond with ONLY the JSON object. No prose, no markdown fences.
"""


@dataclass
class InsightResult:
    """Structured output from the message insight service."""

    summary: str
    translated_message: str


class MessageInsightService:
    """Enriches a customer message with a summary and English translation.

    Args:
        mock_mode: When True, returns a deterministic mock result without
                   making any network calls. Useful for unit tests and local
                   development without an LLM API key.
    """

    def __init__(self, *, mock_mode: bool = False) -> None:
        self._mock_mode = mock_mode

    async def generate_insight(
        self,
        customer_message: str,
        detected_language: str,
    ) -> InsightResult | None:
        """Generate summary and translation for a customer message.

        This method never raises — errors are logged and ``None`` is returned
        so that callers can treat the insight step as best-effort enrichment.

        Args:
            customer_message: Raw message text as collected from Mirakl.
            detected_language: ISO 639-1 code of the detected language
                               (e.g. "nl", "en", "fr", "de").

        Returns:
            An :class:`InsightResult` on success, or ``None`` on any failure.
        """
        if self._mock_mode:
            return self._mock_insight(customer_message, detected_language)

        try:
            user_content = self._build_user_content(customer_message, detected_language)
            raw_response = await self._call_llm(user_content)
            return self._parse_response(raw_response)
        except Exception as exc:
            logger.warning(
                "Message insight generation failed (non-blocking): %s",
                exc,
            )
            return None

    # ------------------------------------------------------------------ #
    # Internals                                                            #
    # ------------------------------------------------------------------ #

    def _build_user_content(self, customer_message: str, detected_language: str) -> str:
        return (
            f"Detected language: {detected_language}\n\n"
            f"Customer message:\n{customer_message}"
        )

    async def _call_llm(self, user_content: str) -> str:
        """Make an async HTTP call to the LLM chat completions endpoint.

        Returns:
            The raw text content of the assistant message.

        Raises:
            Exception: On HTTP errors, timeouts, or unexpected response shapes.
        """
        payload = {
            "model": settings.INSIGHT_LLM_MODEL,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            "temperature": 0.0,
            "max_tokens": 1000,
            "response_format": {"type": "json_object"},
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{settings.LLM_API_BASE_URL}/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.LLM_API_KEY}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )

        if response.is_error:
            raise RuntimeError(
                f"Insight LLM API returned HTTP {response.status_code}: "
                f"{response.text[:200]}"
            )

        data = response.json()
        try:
            content: str = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as exc:
            raise RuntimeError(
                f"Unexpected insight LLM response structure: {str(data)[:200]}"
            ) from exc

        return content

    def _parse_response(self, raw: str) -> InsightResult:
        """Parse the raw LLM JSON response into an InsightResult.

        Raises:
            ValueError: If JSON is invalid or required fields are missing.
        """
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"Insight LLM response is not valid JSON: {raw[:200]}"
            ) from exc

        missing = [k for k in ("summary", "translated_message") if k not in data]
        if missing:
            raise ValueError(
                f"Insight LLM response missing required fields: {missing}. "
                f"Raw: {raw[:200]}"
            )

        return InsightResult(
            summary=str(data["summary"]).strip(),
            translated_message=str(data["translated_message"]).strip(),
        )

    @staticmethod
    def _mock_insight(customer_message: str, detected_language: str) -> InsightResult:
        """Deterministic mock insight for tests and local dev.

        Returns a predictable result based on message content and language so
        that test assertions are stable without a live LLM API key.
        """
        message_lower = customer_message.lower()

        # Build a simple summary heuristic
        if any(word in message_lower for word in ["refund", "terugbetaling", "remboursement", "rückerstattung"]):
            summary = "The customer is requesting a refund and appears frustrated."
        elif any(word in message_lower for word in ["return", "retour", "rücksendung", "terugsturen"]):
            summary = "The customer wants to return their order."
        elif any(word in message_lower for word in ["where", "tracking", "waar", "livraison", "lieferung", "bestelling"]):
            summary = "The customer is asking about the status or location of their order."
        elif any(word in message_lower for word in ["broken", "defect", "kapot", "garantie", "warranty"]):
            summary = "The customer is reporting a defective product and may want a repair or replacement."
        else:
            summary = "The customer has a general inquiry."

        # Only produce a translation when the message is not English
        if detected_language == "en":
            translated_message = ""
        else:
            translated_message = f"[Mock English translation of {detected_language} message]: {customer_message}"

        return InsightResult(
            summary=summary,
            translated_message=translated_message,
        )
