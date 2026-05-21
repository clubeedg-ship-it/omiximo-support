"""Smart draft service — LLM-augmented drafting for ORANGE cases.

For ORANGE-classified threads, the template-rendered response may not be
sufficient or may not exist at all. This service enriches the drafting step by:

1. Retrieving relevant knowledge base entries (if available).
2. Fetching similar historically APPROVED threads (same category + account).
3. Building a context-rich prompt with safety constraints.
4. Calling the LLM to produce a professional, human-reviewable draft.
5. Falling back gracefully when the LLM or knowledge layer is unavailable.

Architecture notes:
- This service is non-blocking: it never raises. On any failure it returns
  a SmartDraftResult with source="template_fallback" or "unavailable".
- Safety rules still run on the final draft in the pipeline (not here).
- The knowledge service import is optional — if the other agent hasn't built
  it yet, this service degrades gracefully (empty knowledge context).
- Mock mode is provided for tests (no network calls).
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.services.text_clean import strip_html
from app.models.marketplace_account import MarketplaceAccount
from app.models.support_thread import (
    CustomerLanguage,
    SupportThread,
    ThreadStatus,
)

logger = logging.getLogger(__name__)

# Language code → full name mapping for prompt readability.
_LANGUAGE_NAMES: dict[str, str] = {
    "nl": "Dutch",
    "en": "English",
    "fr": "French",
    "de": "German",
}


@dataclass
class SmartDraftResult:
    """Structured output from the smart draft service."""

    drafted_response: str | None
    source: str  # "llm_augmented", "template_fallback", "unavailable"
    knowledge_entry_ids: list[str] = field(default_factory=list)
    similar_thread_count: int = 0


class SmartDraftService:
    """LLM-augmented draft generator for ORANGE cases.

    Uses knowledge entries + historical approved threads to produce an
    intelligent draft that will be reviewed by a human before sending.

    Args:
        mock_mode: When True, returns a deterministic mock result without
                   making any network calls.
    """

    def __init__(self, *, mock_mode: bool = False) -> None:
        self._mock_mode = mock_mode

    async def generate_draft(
        self,
        db: AsyncSession,
        *,
        thread: SupportThread,
        order_context: dict[str, Any],
        category: str,
        language: CustomerLanguage,
        account: MarketplaceAccount,
        template_reference: str | None = None,
    ) -> SmartDraftResult:
        """Generate an intelligent draft for an ORANGE case.

        Steps:
        1. Retrieve relevant knowledge entries (if knowledge_entries table exists)
        2. Retrieve similar APPROVED threads (same category, same account)
        3. Build prompt with all context
        4. Call LLM
        5. Return result (or fall back to template_reference if LLM fails)

        Never raises — returns SmartDraftResult with source="unavailable" on failure.
        """
        if self._mock_mode:
            return self._mock_draft(thread)

        try:
            # Step 1: Retrieve knowledge entries
            knowledge_entries = await self._fetch_knowledge(
                db, category, account.marketplace, language,
            )

            # Step 2: Retrieve similar historical threads
            similar_threads = await self._fetch_similar_threads(
                db, category, thread.marketplace_account_id, thread.id,
            )

            # Step 3: Build prompt
            system_prompt = self._build_system_prompt(
                shop_name=account.marketplace,
                marketplace=account.marketplace,
                language=language,
                knowledge_entries=knowledge_entries,
                similar_threads=similar_threads,
                template_reference=template_reference,
                order_context=order_context,
            )

            # Step 4: Call LLM (strip email HTML noise first)
            raw_response = await self._call_llm(
                system_prompt=system_prompt,
                user_content=strip_html(thread.customer_message),
            )

            if not raw_response or not raw_response.strip():
                # LLM returned empty — fall back
                return self._fallback_result(
                    template_reference, knowledge_entries, similar_threads,
                )

            # Extract knowledge entry IDs if available
            kb_ids = self._extract_knowledge_ids(knowledge_entries)

            return SmartDraftResult(
                drafted_response=raw_response.strip(),
                source="llm_augmented",
                knowledge_entry_ids=kb_ids,
                similar_thread_count=len(similar_threads),
            )

        except Exception as exc:
            logger.warning(
                "Smart draft generation failed for thread %s (non-blocking): %s",
                thread.id,
                exc,
            )
            return self._fallback_result(template_reference, [], [])

    # ------------------------------------------------------------------ #
    # Retrieval helpers                                                    #
    # ------------------------------------------------------------------ #

    async def _fetch_similar_threads(
        self,
        db: AsyncSession,
        category: str,
        marketplace_account_id: uuid.UUID,
        exclude_id: uuid.UUID,
    ) -> list[SupportThread]:
        """Query for up to 3 APPROVED threads with matching category and account."""
        stmt = (
            select(SupportThread)
            .where(
                SupportThread.marketplace_account_id == marketplace_account_id,
                SupportThread.category == category,
                SupportThread.status == ThreadStatus.APPROVED,
                SupportThread.drafted_response.is_not(None),
                SupportThread.id != exclude_id,
            )
            .order_by(SupportThread.updated_at.desc())
            .limit(3)
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def _fetch_knowledge(
        self,
        db: AsyncSession,
        category: str,
        marketplace: str,
        language: CustomerLanguage,
    ) -> list[Any]:
        """Attempt to retrieve knowledge entries from the knowledge service.

        If the knowledge service is not yet built or the table doesn't exist,
        gracefully returns an empty list.
        """
        try:
            from app.services.knowledge_service import KnowledgeService
            service = KnowledgeService()
            return await service.retrieve_for_draft(
                db, category=category, marketplace=marketplace, language=language,
            )
        except Exception:
            # ImportError, AttributeError, table-not-found, anything — degrade gracefully
            return []

    # ------------------------------------------------------------------ #
    # Prompt construction                                                  #
    # ------------------------------------------------------------------ #

    def _build_system_prompt(
        self,
        *,
        shop_name: str,
        marketplace: str,
        language: CustomerLanguage,
        knowledge_entries: list[Any],
        similar_threads: list[SupportThread],
        template_reference: str | None,
        order_context: dict[str, Any],
    ) -> str:
        """Construct the system prompt with all available context."""
        language_code = language.value
        language_name = _LANGUAGE_NAMES.get(language_code, language_code)

        sections: list[str] = []

        # Core identity and rules
        sections.append(
            f"You are a professional customer support agent for {shop_name}, "
            f"selling on the {marketplace} marketplace.\n\n"
            f"Write a reply to the customer message below. "
            f"This reply will be reviewed by a human before sending.\n\n"
            f"MANDATORY RULES:\n"
            f"- Write in {language_name} ({language_code}).\n"
            f"- Do NOT promise refunds, credit, or monetary compensation.\n"
            f"- Do NOT approve or authorise returns.\n"
            f"- Do NOT claim delivery without confirmed tracking status.\n"
            f"- Do NOT reject warranty or defect claims — acknowledge and say "
            f"you are investigating.\n"
            f"- Do NOT provide contact channels outside this marketplace message system.\n"
            f"- Do NOT invent information not present in the order context below.\n"
            f"- Be professional, empathetic, and concise (2-4 short paragraphs max)."
        )

        # Knowledge section
        if knowledge_entries:
            knowledge_lines = ["COMPANY KNOWLEDGE:"]
            for i, entry in enumerate(knowledge_entries, 1):
                entry_type = getattr(entry, "entry_type", "info")
                title = getattr(entry, "title", "")
                content = getattr(entry, "content", "")
                knowledge_lines.append(f"[{i}] {entry_type}: {title}\n{content}")
            sections.append("\n".join(knowledge_lines))

        # Examples section (similar approved threads)
        if similar_threads:
            example_lines = ["APPROVED RESPONSES (same category, use as style reference):"]
            for t in similar_threads:
                customer_excerpt = strip_html(t.customer_message or "")[:200]
                response_text = t.drafted_response or ""
                example_lines.append(
                    f"---\nCustomer: {customer_excerpt}\nResponse: {response_text}\n---"
                )
            sections.append("\n".join(example_lines))

        # Template reference section
        if template_reference:
            sections.append(
                f"TEMPLATE REFERENCE (style/structure guide):\n{template_reference}"
            )

        # Order context
        sections.append(
            f"ORDER CONTEXT:\n{json.dumps(order_context, indent=2, default=str)}"
        )

        # Final instruction
        sections.append("Respond with ONLY the reply text. No preamble, no labels.")

        return "\n\n".join(sections)

    # ------------------------------------------------------------------ #
    # LLM call                                                             #
    # ------------------------------------------------------------------ #

    async def _call_llm(
        self,
        *,
        system_prompt: str,
        user_content: str,
    ) -> str:
        """Make an async HTTP call to the LLM chat completions endpoint.

        Returns:
            The raw text content of the assistant message.

        Raises:
            RuntimeError: On HTTP errors, timeouts, or unexpected response shapes.
        """
        payload = {
            "model": settings.INSIGHT_LLM_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            "temperature": settings.SMART_DRAFT_TEMPERATURE,
            "max_tokens": settings.SMART_DRAFT_MAX_TOKENS,
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
                f"Smart draft LLM API returned HTTP {response.status_code}: "
                f"{response.text[:200]}"
            )

        data = response.json()
        try:
            content: str = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as exc:
            raise RuntimeError(
                f"Unexpected smart draft LLM response structure: {str(data)[:200]}"
            ) from exc

        return content

    # ------------------------------------------------------------------ #
    # Fallback and mock helpers                                            #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _fallback_result(
        template_reference: str | None,
        knowledge_entries: list[Any],
        similar_threads: list[Any],
    ) -> SmartDraftResult:
        """Produce a fallback result when LLM call fails."""
        if template_reference:
            return SmartDraftResult(
                drafted_response=template_reference,
                source="template_fallback",
                knowledge_entry_ids=SmartDraftService._extract_knowledge_ids(
                    knowledge_entries
                ),
                similar_thread_count=len(similar_threads),
            )
        return SmartDraftResult(
            drafted_response=None,
            source="unavailable",
            knowledge_entry_ids=[],
            similar_thread_count=0,
        )

    @staticmethod
    def _extract_knowledge_ids(knowledge_entries: list[Any]) -> list[str]:
        """Extract UUIDs from knowledge entries, handling various formats."""
        ids: list[str] = []
        for entry in knowledge_entries:
            entry_id = getattr(entry, "id", None)
            if entry_id is not None:
                ids.append(str(entry_id))
        return ids

    @staticmethod
    def _mock_draft(thread: SupportThread) -> SmartDraftResult:
        """Deterministic mock draft for tests and local dev.

        Returns a predictable result so that test assertions are stable
        without a live LLM API key.
        """
        return SmartDraftResult(
            drafted_response=(
                f"[MOCK DRAFT] Regarding your inquiry about order "
                f"{thread.mirakl_order_id}, we are looking into this "
                f"and will respond shortly."
            ),
            source="llm_augmented",
            knowledge_entry_ids=[],
            similar_thread_count=0,
        )
