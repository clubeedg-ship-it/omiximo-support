"""Add draft_summary and draft_translated columns to support_threads.

Caches the draft insight so repeated page loads don't trigger LLM calls.
Invalidated when the drafted_response changes.

Revision ID: 005
Revises: 004
Create Date: 2026-05-09

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "005"
down_revision: str | None = "004"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "support_threads",
        sa.Column("draft_summary", sa.Text(), nullable=True),
    )
    op.add_column(
        "support_threads",
        sa.Column("draft_translated", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("support_threads", "draft_translated")
    op.drop_column("support_threads", "draft_summary")
