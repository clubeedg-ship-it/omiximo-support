"""Agent card re-render support.

Adds:
- ``agent_actions.context_json``: snapshot of the read-tool facts a card was
  built from, so the card can be re-rendered (edit/translate) after the run.
- ``telegram_sessions``: transient "awaiting typed input" state for the
  force-reply edit flow (keyed by the prompt's message id).

Revision ID: 012
Revises: 011
Create Date: 2026-06-28

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "012"
down_revision: str | None = "011"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "agent_actions",
        sa.Column("context_json", postgresql.JSON(astext_type=sa.Text()), nullable=True),
    )

    op.create_table(
        "telegram_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("chat_id", sa.String(length=64), nullable=False),
        sa.Column("prompt_message_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "action_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_actions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index(
        "ix_telegram_sessions_prompt_message_id", "telegram_sessions", ["prompt_message_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_telegram_sessions_prompt_message_id", table_name="telegram_sessions")
    op.drop_table("telegram_sessions")
    op.drop_column("agent_actions", "context_json")
