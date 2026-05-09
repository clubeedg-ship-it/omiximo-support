"""Add message_summary and translated_message columns to support_threads.

These two nullable Text columns store the output of the MessageInsightService
(Gemini 2.5 Flash via OpenRouter). They are populated asynchronously after
classification and are never required for the core classify → draft → send
pipeline.

Revision ID: 004
Revises: 003
Create Date: 2026-05-09

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# ---------------------------------------------------------------------------
# Revision identifiers
# ---------------------------------------------------------------------------
revision: str = "004"
down_revision: str | None = "003"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "support_threads",
        sa.Column(
            "message_summary",
            sa.Text(),
            nullable=True,
            comment=(
                "1-2 sentence English summary of the customer message; "
                "populated by the insight service after classification"
            ),
        ),
    )
    op.add_column(
        "support_threads",
        sa.Column(
            "translated_message",
            sa.Text(),
            nullable=True,
            comment=(
                "Full English translation of the customer message; "
                "NULL or empty string when the original message is already in English"
            ),
        ),
    )


def downgrade() -> None:
    op.drop_column("support_threads", "translated_message")
    op.drop_column("support_threads", "message_summary")
