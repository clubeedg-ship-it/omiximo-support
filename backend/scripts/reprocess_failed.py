"""CLI script: bulk-reprocess FAILED threads.

Resets FAILED threads to PENDING_REVIEW so they can re-enter the
classification pipeline. Optionally filter by category.

Run from the backend directory:

    python -m scripts.reprocess_failed
    python -m scripts.reprocess_failed --limit 50
    python -m scripts.reprocess_failed --category shipping_delay --limit 10

Exit codes:
  0  - success
  1  - unexpected error (details printed to stderr)
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.models.support_thread import SupportThread, ThreadStatus
from app.services.audit import write_audit_log


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Bulk-reprocess FAILED support threads.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=100,
        help="Maximum number of threads to reprocess (default: 100).",
    )
    parser.add_argument(
        "--category",
        type=str,
        default=None,
        help="Only reprocess threads with this category (optional).",
    )
    return parser.parse_args()


async def _reprocess_thread(session: AsyncSession, thread: SupportThread) -> None:
    """Reset a single thread for reprocessing."""
    thread.status = ThreadStatus.PENDING_REVIEW
    thread.risk_level = None
    thread.category = None
    thread.drafted_response = None

    # Clear insight cache
    thread.message_summary = None
    thread.translated_message = None
    thread.draft_summary = None
    thread.draft_translated = None

    thread.updated_at = datetime.now(UTC)

    await write_audit_log(
        session,
        action="reprocess_initiated",
        actor="system:bulk_reprocess",
        thread_id=thread.id,
        detail={"previous_status": ThreadStatus.FAILED.value, "source": "cli_script"},
    )


async def _run(args: argparse.Namespace) -> None:
    """Query FAILED threads and reset them in batches."""
    print("Omiximo Support - bulk reprocess FAILED threads")
    print("=" * 50)
    print(f"  Limit:    {args.limit}")
    print(f"  Category: {args.category or '(all)'}")
    print()

    async with AsyncSessionLocal() as session:
        stmt = (
            select(SupportThread)
            .where(SupportThread.status == ThreadStatus.FAILED)
            .order_by(SupportThread.created_at.asc())
            .limit(args.limit)
        )

        if args.category:
            stmt = stmt.where(SupportThread.category == args.category)

        result = await session.execute(stmt)
        threads = list(result.scalars().all())

        if not threads:
            print("No FAILED threads found matching criteria.")
            return

        print(f"Found {len(threads)} FAILED thread(s) to reprocess.")
        print()

        for i, thread in enumerate(threads, start=1):
            await _reprocess_thread(session, thread)
            print(
                f"  [{i}/{len(threads)}] {thread.mirakl_thread_id} "
                f"(order: {thread.mirakl_order_id}) -> PENDING_REVIEW"
            )

        await session.commit()

    print()
    print(f"Done. Reprocessed {len(threads)} thread(s).")


def main() -> None:
    """Entry point; propagates exceptions as a non-zero exit code."""
    args = _parse_args()
    try:
        asyncio.run(_run(args))
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
