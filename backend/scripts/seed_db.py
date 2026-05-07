"""CLI script: seed the database with initial reference data.

Run from the backend directory:

    python -m scripts.seed_db

The script:
  1. Creates a single async database session using the application engine.
  2. Calls seed_templates() to insert global response templates.
  3. Commits the transaction.
  4. Prints a summary of what was inserted / skipped.

Exit codes:
  0  – success
  1  – unexpected error (details printed to stderr)
"""

from __future__ import annotations

import asyncio
import sys

from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.seeds import seed_templates


async def _run() -> None:
    """Execute all seed operations inside a single transaction."""
    print("Omiximo Support — database seed")
    print("=" * 40)

    async with AsyncSessionLocal() as session:  # type: AsyncSession
        try:
            print("Seeding response templates...")
            template_summary = await seed_templates(session)
            await session.commit()
        except Exception:
            await session.rollback()
            raise

    # ------------------------------------------------------------------ #
    # Summary                                                              #
    # ------------------------------------------------------------------ #
    print()
    print("Response templates")
    print(f"  Total defined : {template_summary['total']}")
    print(f"  Inserted      : {template_summary['inserted']}")
    print(f"  Skipped       : {template_summary['skipped']} (already existed)")
    print()
    print("Seed complete.")


def main() -> None:
    """Entry point; propagates exceptions as a non-zero exit code."""
    try:
        asyncio.run(_run())
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
