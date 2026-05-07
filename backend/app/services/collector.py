"""Thread collector service.

Iterates all active marketplace accounts, fetches new message threads from
the Mirakl API, and upserts them into support_threads. Each collection run
is fully audit-logged.

Usage (from the background task or CLI):
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

from app.models.marketplace_account import MarketplaceAccount
from app.models.support_thread import SupportThread, ThreadStatus
from app.services.audit import write_audit_log
from app.services.mirakl_client import MiraklClient

logger = logging.getLogger(__name__)


class ThreadCollector:
    """Collects new Mirakl threads and upserts them into the database."""

    async def collect_all(self, db: AsyncSession) -> int:
        """Run collection for every active marketplace account.

        Args:
            db: Database session. The caller is responsible for committing.

        Returns:
            Total number of new threads upserted across all accounts.
        """
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
        """Collect and upsert threads for a single account.

        Returns the number of threads that were newly inserted.
        """
        async with MiraklClient(account) as client:
            raw_threads: list[dict[str, Any]] = await client.fetch_threads()

        new_count = 0
        for raw in raw_threads:
            is_new = await self._upsert_thread(db, account, raw)
            if is_new:
                new_count += 1

        return new_count

    async def _upsert_thread(
        self,
        db: AsyncSession,
        account: MarketplaceAccount,
        raw: dict[str, Any],
    ) -> bool:
        """Insert a new SupportThread or skip if it already exists.

        Mirakl thread IDs are stable; we rely on the unique constraint
        (mirakl_thread_id, marketplace_account_id) and simply skip rows that
        already exist rather than overwriting human-edited fields.

        Returns True if a new row was inserted.
        """
        mirakl_thread_id: str = str(raw.get("id", ""))
        mirakl_order_id: str = str(raw.get("order_id", ""))

        if not mirakl_thread_id or not mirakl_order_id:
            logger.warning(
                "Skipping Mirakl thread with missing id or order_id: %s", raw
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
            customer_message = raw.get("subject", "")

        # Determine if this is an operator/marketplace message
        operator_required: bool = raw.get("operator_message", False)

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
    """Extract the most recent customer-authored message body from the thread."""
    # Mirakl message objects have a "from_operator" or "author_type" field.
    # We want the latest message authored by the buyer.
    customer_msgs = [
        m for m in messages
        if not m.get("from_operator", False)
        and m.get("author_type", "buyer") in ("buyer", "customer", "")
    ]
    if customer_msgs:
        # Take the last one (most recent)
        return customer_msgs[-1].get("body", "")
    # Fallback: last message regardless of author
    if messages:
        return messages[-1].get("body", "")
    return ""
