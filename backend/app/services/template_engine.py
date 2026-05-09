"""Template engine service.

Architecture decision D1: LLM classifies — templates generate the response.
LLM freeform drafting is ONLY allowed for ORANGE cases as a fallback when no
matching template exists.

This service:
1. Resolves the best matching ResponseTemplate for (category, language, account).
2. Renders it with Jinja2 using the supplied order data context dict.
3. Raises TemplateNotFoundError when no active template is found.

Template resolution order:
  1. Account-scoped template (marketplace_account_id = account_id) — exact match
  2. Global template (marketplace_account_id IS NULL) — fallback
  3. TemplateNotFoundError

Available Jinja2 slots (always passed in context):
  {{ order_id }}          – Mirakl order identifier
  {{ tracking_number }}   – Carrier tracking number (may be empty string)
  {{ delivery_date }}     – Expected or actual delivery date (may be empty string)
  {{ shop_name }}         – Marketplace display name
  {{ customer_name }}     – Customer first name (may be empty string)
  {{ marketplace }}       – Marketplace brand name
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from jinja2 import Environment, StrictUndefined, TemplateSyntaxError, UndefinedError
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import TemplateNotFoundError, TemplateRenderError
from app.models.response_template import ResponseTemplate
from app.models.support_thread import CustomerLanguage

logger = logging.getLogger(__name__)

_CATEGORY_ALIASES: dict[str, str] = {
    "shipping_delay": "tracking_update",
    "missing_parcel": "tracking_update",
    "return_request": "return_inquiry",
    "warranty_claim": "defect_report",
    "damaged_item": "defect_report",
    "wrong_item": "complaint",
    "order_cancellation": "complaint",
}

# Jinja2 environment with StrictUndefined so missing slots surface as errors
# rather than silently rendering as empty strings.
_jinja_env = Environment(
    undefined=StrictUndefined,
    autoescape=False,  # Plain-text responses; no HTML escaping needed
    trim_blocks=True,
    lstrip_blocks=True,
)


class TemplateEngine:
    """Resolves and renders response templates.

    This class is stateless and can be instantiated once and reused.
    The database session is passed per-call to support both request-scoped
    and background-task usage patterns.
    """

    async def render(
        self,
        db: AsyncSession,
        *,
        category: str,
        language: CustomerLanguage,
        marketplace_account_id: uuid.UUID,
        context: dict[str, Any],
    ) -> str:
        """Resolve the best matching template and render it with Jinja2.

        Args:
            db:                      Async database session.
            category:                Message category from the classifier.
            language:                Customer language code.
            marketplace_account_id:  Used for account-scoped template lookup.
            context:                 Dict of slot values passed to Jinja2.

        Returns:
            Rendered response string ready for sending.

        Raises:
            TemplateNotFoundError:  No active template found for the given criteria.
            TemplateRenderError:    Jinja2 rendering failed (e.g. missing slot).
        """
        resolved_category = _CATEGORY_ALIASES.get(category, category)
        template_record = await self._resolve_template(
            db,
            category=resolved_category,
            language=language,
            marketplace_account_id=marketplace_account_id,
        )

        return self._render_body(template_record, context)

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    async def _resolve_template(
        self,
        db: AsyncSession,
        *,
        category: str,
        language: CustomerLanguage,
        marketplace_account_id: uuid.UUID,
    ) -> ResponseTemplate:
        """Query for the best matching active template.

        Priority: account-scoped > global.  Within each tier, the most
        recently updated template wins (so updating a template takes effect
        immediately without a restart).
        """
        stmt = (
            select(ResponseTemplate)
            .where(
                and_(
                    ResponseTemplate.category == category,
                    ResponseTemplate.language == language.value,
                    ResponseTemplate.is_active.is_(True),
                    or_(
                        ResponseTemplate.marketplace_account_id == marketplace_account_id,
                        ResponseTemplate.marketplace_account_id.is_(None),
                    ),
                )
            )
            .order_by(
                # Account-scoped rows sort before global rows (NULLs last)
                ResponseTemplate.marketplace_account_id.is_(None).asc(),
                ResponseTemplate.updated_at.desc(),
            )
            .limit(1)
        )

        result = await db.execute(stmt)
        template = result.scalar_one_or_none()

        if template is None:
            raise TemplateNotFoundError(
                f"No active template found for category={category!r}, "
                f"language={language!r}, account_id={marketplace_account_id}",
                category=category,
                language=language.value,
                account_id=str(marketplace_account_id),
            )

        return template

    @staticmethod
    def _render_body(template: ResponseTemplate, context: dict[str, Any]) -> str:
        """Compile and render the Jinja2 template body.

        Raises:
            TemplateRenderError: On syntax errors or undefined slot references.
        """
        # Ensure all standard slots exist in context with safe defaults so
        # templates don't fail on optional fields.
        safe_context: dict[str, Any] = {
            "order_id": "",
            "tracking_number": "",
            "delivery_date": "",
            "shop_name": "",
            "customer_name": "",
            "marketplace": "",
        }
        safe_context.update(context)

        try:
            jinja_template = _jinja_env.from_string(template.template_body)
            return jinja_template.render(**safe_context)
        except TemplateSyntaxError as exc:
            raise TemplateRenderError(
                f"Jinja2 syntax error in template id={template.id}: {exc}",
                detail=str(exc),
            ) from exc
        except UndefinedError as exc:
            raise TemplateRenderError(
                f"Jinja2 undefined variable in template id={template.id}: {exc}",
                detail=str(exc),
            ) from exc
        except Exception as exc:
            raise TemplateRenderError(
                f"Jinja2 render error in template id={template.id}: {exc}",
                detail=str(exc),
            ) from exc
