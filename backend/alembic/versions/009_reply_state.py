"""Add reply_state to support_threads.

Conversation state derived from Mirakl (NEEDS_REPLY / AWAITING_CUSTOMER /
RESOLVED), independent of the app's send-workflow ``status``. Lets the inbox
show which threads actually need a reply versus those already handled or
awaiting the customer.

Revision ID: 009
Revises: 008
Create Date: 2026-06-12

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "009"
down_revision: str | None = "008"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "support_threads",
        sa.Column("reply_state", sa.String(20), nullable=True),
    )
    op.create_index(
        "ix_support_threads_reply_state", "support_threads", ["reply_state"]
    )


def downgrade() -> None:
    op.drop_index("ix_support_threads_reply_state", table_name="support_threads")
    op.drop_column("support_threads", "reply_state")
