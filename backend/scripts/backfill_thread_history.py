"""Backfill full conversation history for existing threads from Mirakl.

The original ingestion stored only the latest customer message per thread.
This script re-fetches every thread from Mirakl and rebuilds its
``thread_messages`` from the complete message list (customer, shop, and
operator messages with their original timestamps and sender names).

It is idempotent: each matched thread's messages are deleted and rebuilt from
the Mirakl source of truth, so re-running produces the same result. Threads
Mirakl no longer returns are left untouched and reported.

Safe to run because reconstruction reads from Mirakl, the authoritative store.
Drafts live on ``support_threads.drafted_response`` (not in thread_messages),
so they are never affected.

Usage (inside the api container)::

    # Dry run — report what would change, write nothing:
    docker exec -w /app -e PYTHONPATH=/app omiximo-support-api-1 \
        python scripts/backfill_thread_history.py

    # Apply:
    docker exec -w /app -e PYTHONPATH=/app omiximo-support-api-1 \
        python scripts/backfill_thread_history.py --apply
"""

from __future__ import annotations

import argparse
import asyncio

from sqlalchemy import delete, select

from app.database import AsyncSessionLocal
from app.models.marketplace_account import MarketplaceAccount
from app.models.support_thread import SupportThread
from app.models.thread_message import MessageAuthorType, ThreadMessage
from app.services.collector import (
    _build_thread_messages,
    _extract_customer_message,
)
from app.services.mirakl_client import MiraklClient


async def main(apply: bool) -> None:
    mode = "APPLY" if apply else "DRY-RUN"
    print(f"=== Backfill thread history ({mode}) ===\n")

    total_matched = 0
    total_unmatched = 0
    total_messages = 0
    unmatched_ids: list[str] = []

    async with AsyncSessionLocal() as db:
        accounts = list(
            (
                await db.execute(
                    select(MarketplaceAccount).where(
                        MarketplaceAccount.is_active.is_(True)
                    )
                )
            ).scalars().all()
        )

        for account in accounts:
            print(f"Account {account.marketplace} ({account.id})")
            try:
                async with MiraklClient(account) as client:
                    threads = await client.fetch_threads()
            except Exception as exc:  # noqa: BLE001
                print(f"  fetch_threads FAILED: {type(exc).__name__}: {exc}\n")
                continue

            by_id = {str(t.get("id", "")): t for t in threads}
            print(f"  Mirakl returned {len(by_id)} threads")

            stored = list(
                (
                    await db.execute(
                        select(SupportThread).where(
                            SupportThread.marketplace_account_id == account.id
                        )
                    )
                ).scalars().all()
            )
            print(f"  stored threads for this account: {len(stored)}")

            for thread in stored:
                raw = by_id.get(thread.mirakl_thread_id)
                if raw is None:
                    total_unmatched += 1
                    unmatched_ids.append(thread.mirakl_thread_id)
                    continue

                messages = raw.get("messages", [])
                built = _build_thread_messages(messages, default_dt=thread.created_at)
                if not built:
                    # Nothing structured to rebuild — keep the existing row.
                    continue

                total_matched += 1
                total_messages += len(built)

                if not apply:
                    continue

                # Delete the existing messages and rebuild from Mirakl.
                await db.execute(
                    delete(ThreadMessage).where(
                        ThreadMessage.thread_id == thread.id
                    )
                )
                for msg in built:
                    msg.thread_id = thread.id
                    db.add(msg)

                thread.message_count = len(built)
                cust = _extract_customer_message(messages)
                if cust:
                    thread.customer_message = cust
                thread.last_customer_message_at = next(
                    (
                        m.created_at
                        for m in reversed(built)
                        if m.author_type == MessageAuthorType.CUSTOMER.value
                    ),
                    thread.created_at,
                )
                await db.commit()

            print()

    print("=== Summary ===")
    print(f"  threads rebuilt:        {total_matched}")
    print(f"  messages reconstructed: {total_messages}")
    print(f"  threads not returned by Mirakl (left as-is): {total_unmatched}")
    if unmatched_ids:
        print(f"  unmatched mirakl_thread_ids: {unmatched_ids}")
    if not apply:
        print("\n(DRY-RUN — no changes written. Re-run with --apply to persist.)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Persist changes. Without this flag the script only reports.",
    )
    args = parser.parse_args()
    asyncio.run(main(apply=args.apply))
