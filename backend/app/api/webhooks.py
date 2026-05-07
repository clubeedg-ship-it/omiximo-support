"""Mirakl webhook endpoint (Phase 2).

Receives inbound Mirakl webhook notifications (new/updated message threads)
and triggers an immediate collection + pipeline run for the affected thread.

The endpoint:
  1. Returns 200 OK immediately to acknowledge receipt.
  2. Validates the X-Mirakl-Signature header when present (HMAC-SHA256).
  3. Spawns a background task to collect and process the notified thread.

Signature validation is intentionally lenient when no webhook secret is
configured (MIRAKL_WEBHOOK_SECRET is empty/unset): the signature check is
skipped and a warning is logged.  This allows development without a secret
while enforcing verification in production.

Mirakl webhook payload schema (standard):
    {
        "event_type": "MESSAGING_THREAD_CREATED" | "MESSAGING_THREAD_UPDATED",
        "payload": {
            "thread_id": "string",
            "order_id": "string",
            "shop_id": "string"
        }
    }
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request, status
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


# --------------------------------------------------------------------------- #
# Request / response schemas                                                   #
# --------------------------------------------------------------------------- #


class WebhookPayloadInner(BaseModel):
    """Inner payload block of a Mirakl webhook notification."""

    thread_id: str = Field(..., description="Mirakl thread identifier")
    order_id: str = Field(..., description="Mirakl order identifier")
    shop_id: str = Field(..., description="Mirakl shop/seller identifier")


class MiraklWebhookPayload(BaseModel):
    """Top-level Mirakl webhook notification body."""

    event_type: str = Field(
        ...,
        description="MESSAGING_THREAD_CREATED | MESSAGING_THREAD_UPDATED",
    )
    payload: WebhookPayloadInner


class WebhookAckResponse(BaseModel):
    """Synchronous acknowledgement response."""

    received: bool = True
    event_type: str
    thread_id: str


# --------------------------------------------------------------------------- #
# Endpoint                                                                     #
# --------------------------------------------------------------------------- #


@router.post(
    "/mirakl",
    response_model=WebhookAckResponse,
    status_code=status.HTTP_200_OK,
    summary="Receive Mirakl webhook notification",
    description=(
        "Accepts a Mirakl messaging webhook and triggers an async collection "
        "run for the notified thread.  Responds 200 immediately."
    ),
)
async def receive_mirakl_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_mirakl_signature: str | None = Header(default=None, alias="X-Mirakl-Signature"),
) -> WebhookAckResponse:
    """Process an inbound Mirakl webhook notification.

    The raw request body is read first for signature validation, then parsed
    into the expected schema.  Processing (collection + draft pipeline) happens
    asynchronously so this endpoint returns before the work is done.
    """
    raw_body = await request.body()

    # ------------------------------------------------------------------ #
    # Signature validation                                                 #
    # ------------------------------------------------------------------ #
    _validate_signature(raw_body, x_mirakl_signature)

    # ------------------------------------------------------------------ #
    # Parse payload                                                        #
    # ------------------------------------------------------------------ #
    try:
        import json
        body_dict: dict[str, Any] = json.loads(raw_body)
        webhook = MiraklWebhookPayload.model_validate(body_dict)
    except Exception as exc:
        logger.warning("Mirakl webhook received invalid payload: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid webhook payload: {exc}",
        ) from exc

    thread_id = webhook.payload.thread_id
    order_id = webhook.payload.order_id
    shop_id = webhook.payload.shop_id

    logger.info(
        "Webhook received: event_type=%s thread_id=%s order_id=%s shop_id=%s",
        webhook.event_type,
        thread_id,
        order_id,
        shop_id,
    )

    # ------------------------------------------------------------------ #
    # Trigger async processing                                             #
    # ------------------------------------------------------------------ #
    background_tasks.add_task(
        _process_webhook_async,
        thread_id=thread_id,
        order_id=order_id,
        shop_id=shop_id,
        event_type=webhook.event_type,
    )

    return WebhookAckResponse(
        received=True,
        event_type=webhook.event_type,
        thread_id=thread_id,
    )


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #


def _validate_signature(raw_body: bytes, signature_header: str | None) -> None:
    """Validate X-Mirakl-Signature using HMAC-SHA256 if a secret is configured.

    If MIRAKL_WEBHOOK_SECRET is not set, validation is skipped with a warning.
    If the secret is set and the signature does not match, HTTP 401 is raised.
    """
    from app.config import settings  # avoid circular import at module level

    secret: str = getattr(settings, "MIRAKL_WEBHOOK_SECRET", "")

    if not secret:
        if signature_header:
            logger.warning(
                "X-Mirakl-Signature header received but MIRAKL_WEBHOOK_SECRET "
                "is not configured — skipping signature validation"
            )
        else:
            logger.debug(
                "No MIRAKL_WEBHOOK_SECRET configured; webhook signature check skipped"
            )
        return

    if not signature_header:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=(
                "Missing X-Mirakl-Signature header. "
                "Webhook signature validation is required."
            ),
        )

    expected = hmac.new(
        secret.encode(),
        raw_body,
        hashlib.sha256,
    ).hexdigest()

    # Mirakl may prefix the digest with "sha256="
    provided = signature_header.removeprefix("sha256=")

    if not hmac.compare_digest(expected, provided):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Webhook signature validation failed.",
        )


async def _process_webhook_async(
    thread_id: str,
    order_id: str,
    shop_id: str,
    event_type: str,
) -> None:
    """Background task: collect and process the specific thread from the webhook.

    Looks up the marketplace account by shop_id, then runs a targeted
    collection + pipeline run for the notified thread.  Errors are logged and
    do not propagate — the webhook acknowledgement was already sent.
    """
    try:
        from app.database import AsyncSessionLocal
        from app.services.collector import ThreadCollector
        from app.services.draft_pipeline import DraftPipeline
        from app.services.mirakl_client import MiraklClient
        from app.models.marketplace_account import MarketplaceAccount
        from sqlalchemy import select

        async with AsyncSessionLocal() as db:
            # Find the account matching shop_id
            stmt = select(MarketplaceAccount).where(
                MarketplaceAccount.shop_id == shop_id,
                MarketplaceAccount.is_active.is_(True),
            )
            result = await db.execute(stmt)
            account = result.scalar_one_or_none()

            if account is None:
                logger.warning(
                    "Webhook: no active account found for shop_id=%s (thread_id=%s)",
                    shop_id,
                    thread_id,
                )
                return

            # Fetch the specific thread from Mirakl
            raw_thread: dict[str, Any] | None = None
            try:
                async with MiraklClient(account) as client:
                    # Use the general threads fetch and filter; Mirakl does not
                    # expose a single-thread-by-id endpoint in the standard API.
                    threads = await client.fetch_threads()
                    for t in threads:
                        if str(t.get("id", "")) == thread_id:
                            raw_thread = t
                            break
            except Exception as exc:
                logger.warning(
                    "Webhook: failed to fetch thread %s from Mirakl: %s",
                    thread_id,
                    exc,
                )
                # Fallback: synthesise a minimal raw thread so the collector
                # can still upsert a placeholder entry.
                raw_thread = {
                    "id": thread_id,
                    "order_id": order_id,
                    "messages": [],
                    "operator_message": False,
                }

            if raw_thread is None:
                # Thread not found in unanswered list — may have been answered
                # already; construct a minimal entry.
                raw_thread = {
                    "id": thread_id,
                    "order_id": order_id,
                    "messages": [],
                    "operator_message": False,
                }

            collector = ThreadCollector()
            await collector._upsert_thread(db, account, raw_thread)  # type: ignore[attr-defined]
            await db.commit()

        # Run the draft pipeline
        async with AsyncSessionLocal() as db:
            pipeline = DraftPipeline()
            processed = await pipeline.process_new_threads(db)
            logger.info(
                "Webhook pipeline: processed %d thread(s) for event_type=%s thread_id=%s",
                processed,
                event_type,
                thread_id,
            )

    except Exception as exc:
        logger.exception(
            "Webhook background processing failed for thread_id=%s: %s",
            thread_id,
            exc,
        )
