"""Add last_activity_at to support_threads.

Timestamp of the most recent message in the conversation (from Mirakl
``metadata.last_message_date``). Lets the inbox sort by recent activity so
threads that received a new message this week surface on top, regardless of
when the thread was originally opened.

Revision ID: 010
Revises: 009
Create Date: 2026-06-12

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "010"
down_revision: str | None = "009"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "support_threads",
        sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_support_threads_last_activity_at",
        "support_threads",
        ["last_activity_at"],
    )
    # Seed from the best signal we already have so sorting works before the
    # next poll refreshes it from Mirakl.
    op.execute(
        "UPDATE support_threads "
        "SET last_activity_at = COALESCE(last_customer_message_at, created_at)"
    )


def downgrade() -> None:
    op.drop_index(
        "ix_support_threads_last_activity_at", table_name="support_threads"
    )
    op.drop_column("support_threads", "last_activity_at")
