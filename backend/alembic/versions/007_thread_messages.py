"""Create thread_messages table and add conversation tracking columns.

Enables multi-message support for Mirakl threads. Each message in the
conversation (inbound and outbound) is stored as a separate row. Existing
threads are backfilled with their current customer_message and (if sent)
drafted_response.

Revision ID: 007
Revises: 006
Create Date: 2026-05-17

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "007"
down_revision: str | None = "006"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # 1. Create thread_messages table
    op.create_table(
        "thread_messages",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "thread_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("support_threads.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("direction", sa.String(20), nullable=False),
        sa.Column("author_type", sa.String(20), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    # Index on thread_id for lookups
    op.create_index("ix_thread_messages_thread_id", "thread_messages", ["thread_id"])

    # Unique constraint on (thread_id, sequence_number)
    op.create_unique_constraint(
        "uq_thread_message_sequence",
        "thread_messages",
        ["thread_id", "sequence_number"],
    )

    # 2. Add new columns to support_threads
    op.add_column(
        "support_threads",
        sa.Column(
            "message_count",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
    )
    op.add_column(
        "support_threads",
        sa.Column(
            "last_customer_message_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )

    # 3. Backfill: insert ThreadMessage rows from existing data
    # For every existing thread, insert the customer_message as INBOUND seq=1
    op.execute(
        """
        INSERT INTO thread_messages (id, thread_id, direction, author_type, body, sequence_number, created_at)
        SELECT
            gen_random_uuid(),
            id,
            'INBOUND',
            'CUSTOMER',
            customer_message,
            1,
            created_at
        FROM support_threads
        WHERE customer_message IS NOT NULL AND customer_message != ''
        """
    )

    # For threads that were sent (APPROVED or SENT_AUTO) and have a drafted_response,
    # insert the response as OUTBOUND seq=2
    op.execute(
        """
        INSERT INTO thread_messages (id, thread_id, direction, author_type, body, sequence_number, created_at)
        SELECT
            gen_random_uuid(),
            id,
            'OUTBOUND',
            'SHOP_USER',
            drafted_response,
            2,
            updated_at
        FROM support_threads
        WHERE drafted_response IS NOT NULL
          AND status IN ('APPROVED', 'SENT_AUTO')
        """
    )

    # 4. Update message_count based on actual inserted messages
    op.execute(
        """
        UPDATE support_threads
        SET message_count = (
            SELECT COUNT(*) FROM thread_messages WHERE thread_messages.thread_id = support_threads.id
        )
        """
    )

    # 5. Set last_customer_message_at = created_at for all rows
    op.execute(
        """
        UPDATE support_threads
        SET last_customer_message_at = created_at
        """
    )


def downgrade() -> None:
    op.drop_column("support_threads", "last_customer_message_at")
    op.drop_column("support_threads", "message_count")
    op.drop_constraint("uq_thread_message_sequence", "thread_messages", type_="unique")
    op.drop_index("ix_thread_messages_thread_id", table_name="thread_messages")
    op.drop_table("thread_messages")
