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
from app.services.text_clean import strip_html

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

_DRAFT_SYSTEM_PROMPT = """\
You are a multilingual customer support assistant for an e-commerce seller.

Given a drafted response that will be sent to a customer, produce a JSON object \
with exactly two keys:

1. "summary": 1-2 sentences in English explaining what this response tells \
the customer — the key commitments, actions promised, and overall tone.

2. "translated_message": Full English translation of the draft. \
If the draft is already written in English, return an empty string "".

Respond with ONLY the JSON object. No prose, no markdown fences.
"""

_TRANSLATE_SYSTEM_PROMPT = """\
You are a professional multilingual translation engine for customer support communications.

You will receive:
- A source text in English (the intended reply to a customer)
- A target language code (ISO 639-1: "nl", "fr", "de", etc.)

Your task has two steps:

STEP 1 — TRANSLATE
Translate the source text into the target language. The translation must:
- Preserve all commitments, promises, and factual statements exactly
- Maintain a professional, courteous customer service tone
- Not add or remove any content

STEP 2 — VERIFY
Re-read your translation and compare it to the source. Determine whether the
translation fully and accurately represents the source intent. If any commitment,
action, or factual statement is missing, distorted, or altered in tone from
neutral/professional to negative or dismissive, produce a corrected translation.

Respond with ONLY a JSON object with exactly these keys:
{
  "translated_text": "<the final translation in the target language>",
  "correction_made": true or false,
  "correction_note": "<one sentence in English describing what was corrected, or empty string if no correction>"
}

No prose, no markdown fences, no explanation outside the JSON.
"""

_TRANSLATE_MANY_SYSTEM_PROMPT = """\
You are a professional translation engine for customer-support communications.
You receive a JSON object {"texts": ["...", "..."]}. Translate EACH string into
the requested target language, preserving meaning, commitments, and a
professional, courteous tone. Respond with ONLY {"translations": ["...", "..."]}
— the SAME number of items, in the SAME order. No prose, no markdown fences.
"""


@dataclass
class InsightResult:
    """Structured output from the message insight service."""

    summary: str
    translated_message: str


@dataclass
class TranslationResult:
    """Structured output from the back-translation verification step."""

    translated_text: str
    correction_made: bool
    correction_note: str


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

        cleaned_message = strip_html(customer_message)
        if not cleaned_message:
            return None

        try:
            user_content = self._build_user_content(cleaned_message, detected_language)
            raw_response = await self._call_llm(user_content, system_prompt=_SYSTEM_PROMPT)
            return self._parse_response(raw_response)
        except Exception as exc:
            logger.warning(
                "Message insight generation failed (non-blocking): %s",
                exc,
            )
            return None

    async def summarize_draft(
        self,
        drafted_response: str,
        detected_language: str,
    ) -> InsightResult | None:
        """Generate summary and translation for a drafted response.

        Same contract as :meth:`generate_insight` — never raises, returns
        ``None`` on failure.
        """
        if self._mock_mode:
            return self._mock_draft_insight(drafted_response, detected_language)

        try:
            user_content = (
                f"Detected language: {detected_language}\n\n"
                f"Drafted response:\n{drafted_response}"
            )
            raw_response = await self._call_llm(
                user_content, system_prompt=_DRAFT_SYSTEM_PROMPT,
            )
            return self._parse_response(raw_response)
        except Exception as exc:
            logger.warning(
                "Draft insight generation failed (non-blocking): %s", exc,
            )
            return None

    async def translate_draft(
        self,
        english_text: str,
        target_language: str,
    ) -> TranslationResult | None:
        """Translate an English draft into the target customer language.

        Performs a two-step translate-then-verify pass: the LLM translates
        the source text and immediately re-checks its own output for accuracy,
        returning a corrected translation when it detects a discrepancy.

        This method never raises — errors are logged and ``None`` is returned
        so that callers can treat the translation step as best-effort.

        Args:
            english_text: The English draft to be translated.
            target_language: ISO 639-1 code of the target language
                             (e.g. "nl", "fr", "de").

        Returns:
            A :class:`TranslationResult` on success, or ``None`` on any failure.
        """
        if self._mock_mode:
            return self._mock_translate_draft(english_text, target_language)

        try:
            user_content = (
                f"Target language: {target_language}\n\n"
                f"Source text (English):\n{english_text}"
            )
            raw_response = await self._call_llm(
                user_content, system_prompt=_TRANSLATE_SYSTEM_PROMPT,
            )
            return self._parse_translation_response(raw_response)
        except Exception as exc:
            logger.warning(
                "Draft translation failed (non-blocking): %s", exc,
            )
            return None

    async def translate_texts(
        self, texts: list[str], target_language: str
    ) -> list[str] | None:
        """Translate a list of texts into ``target_language`` in one call.

        Order- and length-preserving, source-language-agnostic, display-only.
        Used to translate a whole card (every conversation turn + the reply) at
        once. Never raises — returns ``None`` on empty input, failure, or a
        shape mismatch, so the caller can treat it as best-effort.
        """
        items = [t or "" for t in texts]
        if not any(t.strip() for t in items):
            return None
        if self._mock_mode:
            return [f"[{target_language}] {t}" for t in items]
        try:
            user_content = (
                f"Target language: {target_language}\n\n"
                + json.dumps({"texts": items}, ensure_ascii=False)
            )
            raw = await self._call_llm(
                user_content, system_prompt=_TRANSLATE_MANY_SYSTEM_PROMPT
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("translate_texts failed (non-blocking): %s", exc)
            return None
        try:
            out = json.loads(raw).get("translations")
        except (json.JSONDecodeError, AttributeError, TypeError):
            return None
        if isinstance(out, list) and len(out) == len(items):
            return [str(x) for x in out]
        return None

    # ------------------------------------------------------------------ #
    # Internals                                                            #
    # ------------------------------------------------------------------ #

    def _build_user_content(self, customer_message: str, detected_language: str) -> str:
        return (
            f"Detected language: {detected_language}\n\n"
            f"Customer message:\n{customer_message}"
        )

    async def _call_llm(
        self,
        user_content: str,
        *,
        system_prompt: str = _SYSTEM_PROMPT,
    ) -> str:
        """Make an async HTTP call to the LLM chat completions endpoint.

        Returns:
            The raw text content of the assistant message.

        Raises:
            Exception: On HTTP errors, timeouts, or unexpected response shapes.
        """
        payload = {
            "model": settings.INSIGHT_LLM_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
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

    @staticmethod
    def _mock_draft_insight(drafted_response: str, detected_language: str) -> InsightResult:
        if detected_language == "en":
            return InsightResult(
                summary="The drafted response acknowledges the customer's inquiry and provides next steps.",
                translated_message="",
            )
        return InsightResult(
            summary="The drafted response acknowledges the customer's inquiry and provides next steps.",
            translated_message=f"[Mock English translation of {detected_language} draft]: {drafted_response}",
        )

    def _parse_translation_response(self, raw: str) -> TranslationResult:
        """Parse the raw LLM JSON response into a TranslationResult.

        Raises:
            ValueError: If JSON is invalid or required fields are missing.
        """
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"Translation LLM response is not valid JSON: {raw[:200]}"
            ) from exc

        missing = [
            k for k in ("translated_text", "correction_made", "correction_note")
            if k not in data
        ]
        if missing:
            raise ValueError(
                f"Translation LLM response missing required fields: {missing}. "
                f"Raw: {raw[:200]}"
            )

        return TranslationResult(
            translated_text=str(data["translated_text"]).strip(),
            correction_made=bool(data["correction_made"]),
            correction_note=str(data["correction_note"]).strip(),
        )

    @staticmethod
    def _mock_translate_draft(english_text: str, target_language: str) -> TranslationResult:
        """Deterministic mock translation for tests and local dev.

        Returns a predictable result without any LLM calls so that test
        assertions are stable without a live API key.
        """
        return TranslationResult(
            translated_text=f"[Mock {target_language} translation]: {english_text}",
            correction_made=False,
            correction_note="",
        )
