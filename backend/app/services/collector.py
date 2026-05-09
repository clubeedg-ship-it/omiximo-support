"""Thread collector service.

In Mirakl Connect mode (``MIRAKL_CONNECT_CLIENT_ID`` set), a single
``fetch_threads`` call returns threads across all linked marketplaces. The
collector extracts the channel/marketplace identity from each thread's
``entities`` payload, auto-creates ``MarketplaceAccount`` records as needed,
and upserts into ``support_threads``.

In legacy mode (no Connect credentials), the original behaviour is preserved:
every active ``MarketplaceAccount`` is polled individually using its per-shop
API key.

Usage::

    collector = ThreadCollector()
    async with AsyncSessionLocal() as db:
        await collector.collect_all(db)
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.marketplace_account import MarketplaceAccount
from app.models.support_thread import SupportThread, ThreadStatus
from app.services.audit import write_audit_log
from app.services.mirakl_client import MiraklClient, MiraklConnectClient

logger = logging.getLogger(__name__)


class ThreadCollector:
    """Collects new Mirakl threads and upserts them into the database."""

    async def collect_all(self, db: AsyncSession, *, updated_since: str | None = None) -> int:
        """Run collection for all active marketplace accounts.

        In Connect mode, a single API call fetches threads across all channels.
        In legacy mode, each ``MarketplaceAccount`` is polled in turn.

        Args:
            db:            Database session. The caller is responsible for committing
                           any outstanding changes between calls.
            updated_since: ISO-8601 timestamp; only threads updated after this time
                           are fetched (Connect mode only).

        Returns:
            Total number of new threads upserted.
        """
        if settings.MIRAKL_CONNECT_CLIENT_ID:
            return await self._collect_connect(db, updated_since=updated_since)
        return await self._collect_legacy(db)

    # ---------------------------------------------------------------------- #
    # Mirakl Connect path                                                      #
    # ---------------------------------------------------------------------- #

    async def _collect_connect(
        self,
        db: AsyncSession,
        *,
        updated_since: str | None = None,
    ) -> int:
        """Fetch threads via the Mirakl Connect API and upsert them."""
        connect = await MiraklConnectClient.get_instance()

        try:
            raw_threads = await connect.fetch_threads(updated_since=updated_since)
        except Exception as exc:
            logger.exception("Connect thread collection failed: %s", exc)
            await write_audit_log(
                db,
                action="collection_failed",
                actor="system",
                thread_id=None,
                detail={"error": str(exc), "mode": "connect"},
            )
            await db.commit()
            return 0

        total_new = 0
        for raw in raw_threads:
            account = await self._resolve_account(db, raw)
            if account is None:
                logger.warning(
                    "Skipping Connect thread %s — could not resolve marketplace account",
                    raw.get("id"),
                )
                continue
            is_new = await self._upsert_thread(db, account, raw, mode="connect")
            if is_new:
                total_new += 1

        logger.info(
            "Connect collection complete: %d raw thread(s), %d new",
            len(raw_threads),
            total_new,
        )
        return total_new

    async def _resolve_account(
        self,
        db: AsyncSession,
        raw: dict[str, Any],
    ) -> MarketplaceAccount | None:
        """Find or create a ``MarketplaceAccount`` from a Connect thread payload.

        The Connect API embeds channel information in the ``entities`` list.
        We look for an entity with ``type="channel"`` and extract the channel
        name (used as the marketplace identifier) and optional shop_id.

        If no matching account exists in the database, a placeholder account is
        created with sensible defaults so the thread can still be stored and
        reviewed by a human.

        Args:
            db:  Open database session.
            raw: Raw thread dict from the Connect API.

        Returns:
            A ``MarketplaceAccount`` instance, or ``None`` if no channel info
            can be extracted from the thread.
        """
        entities: list[dict[str, Any]] = raw.get("entities", [])
        channel_entity = next(
            (e for e in entities if e.get("type") == "channel"),
            None,
        )

        if channel_entity is None:
            # Fallback: some Connect responses embed channel info at the top level
            channel_name: str = raw.get("channel_name") or raw.get("channel", "")
            shop_id: str = raw.get("shop_id") or raw.get("seller_id") or settings.MIRAKL_CONNECT_SELLER_ID
        else:
            channel_name = (
                channel_entity.get("label")
                or channel_entity.get("name")
                or channel_entity.get("id", "")
            )
            shop_id = (
                channel_entity.get("shop_id")
                or channel_entity.get("seller_id")
                or settings.MIRAKL_CONNECT_SELLER_ID
            )

        if not channel_name:
            return None

        # Look for an existing account with this marketplace name
        stmt = select(MarketplaceAccount).where(
            MarketplaceAccount.marketplace == channel_name,
            MarketplaceAccount.is_active.is_(True),
        )
        existing = (await db.execute(stmt)).scalar_one_or_none()
        if existing is not None:
            return existing

        # Create a placeholder account for this new channel
        logger.info(
            "Auto-creating MarketplaceAccount for new channel %r", channel_name
        )
        account = MarketplaceAccount(
            id=uuid.uuid4(),
            marketplace=channel_name,
            shop_id=shop_id or "unknown",
            api_key_encrypted=None,  # not needed in Connect mode
            base_url=settings.MIRAKL_CONNECT_API_URL,
            sla_hours=24,
            template_set="default",
            is_active=True,
        )
        db.add(account)
        await db.flush()
        return account

    # ---------------------------------------------------------------------- #
    # Legacy per-account path                                                  #
    # ---------------------------------------------------------------------- #

    async def _collect_legacy(self, db: AsyncSession) -> int:
        """Original collection strategy: poll each active account separately."""
        accounts = await self._fetch_active_accounts(db)
        total_new = 0

        for account in accounts:
            try:
                new_count = await self._collect_for_account(db, account)
                total_new += new_count
                logger.info(
                    "Collected %d new thread(s) for account %s (%s)",
                    new_count,
                    account.id,
                    account.marketplace,
                )
            except Exception as exc:
                logger.exception(
                    "Collection failed for account %s (%s): %s",
                    account.id,
                    account.marketplace,
                    exc,
                )
                await write_audit_log(
                    db,
                    action="collection_failed",
                    actor="system",
                    thread_id=None,
                    detail={
                        "account_id": str(account.id),
                        "marketplace": account.marketplace,
                        "error": str(exc),
                    },
                )
                await db.commit()

        return total_new

    async def _collect_for_account(
        self,
        db: AsyncSession,
        account: MarketplaceAccount,
    ) -> int:
        """Collect and upsert threads for a single legacy account."""
        async with MiraklClient(account) as client:
            raw_threads: list[dict[str, Any]] = await client.fetch_threads()

        new_count = 0
        for raw in raw_threads:
            is_new = await self._upsert_thread(db, account, raw, mode="legacy")
            if is_new:
                new_count += 1

        return new_count

    # ---------------------------------------------------------------------- #
    # Shared upsert logic                                                      #
    # ---------------------------------------------------------------------- #

    async def _upsert_thread(
        self,
        db: AsyncSession,
        account: MarketplaceAccount,
        raw: dict[str, Any],
        *,
        mode: str = "connect",
    ) -> bool:
        """Insert a new ``SupportThread`` or skip if it already exists.

        Thread IDs are stable; we rely on the unique constraint
        ``(mirakl_thread_id, marketplace_account_id)`` and skip rows that
        already exist rather than overwriting human-edited fields.

        The field mapping differs slightly between Connect and legacy payloads:
        - Connect: ``id``, ``topic.order_id`` or ``metadata.order_id``
        - Legacy:  ``id``, ``order_id``

        Returns:
            ``True`` if a new row was inserted.
        """
        mirakl_thread_id: str = str(raw.get("id", ""))

        # Extract order ID — M11 format uses entities list
        if mode == "connect":
            mirakl_order_id = (
                raw.get("topic", {}).get("order_id")
                or raw.get("metadata", {}).get("order_id")
                or str(raw.get("order_id", ""))
            )
        else:
            # M11 format: entities[0].id contains the order ID
            entities = raw.get("entities", [])
            if entities:
                mirakl_order_id = str(entities[0].get("id", ""))
            else:
                mirakl_order_id = str(raw.get("order_id", ""))

        mirakl_order_id = str(mirakl_order_id)

        if not mirakl_thread_id or not mirakl_order_id:
            logger.warning(
                "Skipping thread with missing id or order_id (mode=%s): %s",
                mode,
                raw,
            )
            return False

        # Check for existing row
        stmt = select(SupportThread).where(
            SupportThread.mirakl_thread_id == mirakl_thread_id,
            SupportThread.marketplace_account_id == account.id,
        )
        existing = (await db.execute(stmt)).scalar_one_or_none()
        if existing is not None:
            return False

        # Extract the latest customer message body
        messages: list[dict[str, Any]] = raw.get("messages", [])
        customer_message = _extract_customer_message(messages)
        if not customer_message:
            customer_message = (
                raw.get("subject")
                or raw.get("topic", {}).get("subject", "")
                or ""
            )
            if not customer_message:
                logger.warning(
                    "Empty customer_message for raw thread id=%s — no body, content, "
                    "or subject could be extracted. Thread will be stored with empty message.",
                    mirakl_thread_id,
                )

        # Determine if this is an operator/marketplace message
        # M11: check current_participants for OPERATOR type or if last message is from OPERATOR
        current_participants = raw.get("current_participants", [])
        has_operator = any(p.get("type") == "OPERATOR" for p in current_participants)
        has_customer = any(p.get("type") == "CUSTOMER" for p in current_participants)
        operator_required: bool = has_operator and not has_customer or raw.get("operator_message", False)

        # Compute SLA deadline
        response_deadline = datetime.now(UTC) + timedelta(hours=account.sla_hours)

        thread = SupportThread(
            id=uuid.uuid4(),
            mirakl_thread_id=mirakl_thread_id,
            mirakl_order_id=mirakl_order_id,
            marketplace_account_id=account.id,
            customer_message=customer_message,
            operator_required=operator_required,
            status=ThreadStatus.PENDING_REVIEW,
            response_deadline=response_deadline,
        )
        db.add(thread)
        await db.flush()

        await write_audit_log(
            db,
            action="thread_collected",
            actor="system",
            thread_id=thread.id,
            detail={
                "mirakl_thread_id": mirakl_thread_id,
                "mirakl_order_id": mirakl_order_id,
                "account_id": str(account.id),
                "marketplace": account.marketplace,
                "operator_required": operator_required,
                "mode": mode,
            },
        )
        await db.commit()
        return True

    @staticmethod
    async def _fetch_active_accounts(
        db: AsyncSession,
    ) -> list[MarketplaceAccount]:
        stmt = select(MarketplaceAccount).where(
            MarketplaceAccount.is_active.is_(True)
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())


def _extract_customer_message(messages: list[dict[str, Any]]) -> str:
    """Extract the most recent customer-authored message body from the thread.

    M11 format: each message has from.type = CUSTOMER | SHOP_USER | OPERATOR
    Legacy format: from_operator (bool), author_type (str)

    The body text is checked in order of preference:
      1. ``body``    — standard Mirakl M11 field
      2. ``content`` — alternative field name used by some Connect responses
    """
    customer_msgs = [
        m for m in messages
        if (
            m.get("from", {}).get("type") == "CUSTOMER"
            or (
                not m.get("from_operator", False)
                and m.get("author_type", "buyer") in ("buyer", "customer", "")
                and m.get("from", {}).get("type", "CUSTOMER") not in ("SHOP_USER", "OPERATOR")
            )
        )
    ]

    def _get_body(msg: dict[str, Any]) -> str:
        """Return the first non-empty body/content value from a message dict."""
        return msg.get("body", "") or msg.get("content", "") or ""

    if customer_msgs:
        return _get_body(customer_msgs[-1])
    if messages:
        return _get_body(messages[-1])
    return ""
