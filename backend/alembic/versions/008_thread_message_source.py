"""Add mirakl_message_id and author_name to thread_messages.

Enables idempotent message sync/backfill (keyed by the stable Mirakl message
ID) and sender attribution in the conversation UI (author_name).

Revision ID: 008
Revises: 007
Create Date: 2026-06-12

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "008"
down_revision: str | None = "007"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "thread_messages",
        sa.Column("mirakl_message_id", sa.String(255), nullable=True),
    )
    op.add_column(
        "thread_messages",
        sa.Column("author_name", sa.String(255), nullable=True),
    )
    op.create_index(
        "ix_thread_messages_mirakl_message_id",
        "thread_messages",
        ["mirakl_message_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_thread_messages_mirakl_message_id", table_name="thread_messages"
    )
    op.drop_column("thread_messages", "author_name")
    op.drop_column("thread_messages", "mirakl_message_id")
