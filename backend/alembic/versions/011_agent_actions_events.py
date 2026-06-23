"""Agent action gate + activity log.

Adds two tables for the autonomous support agent:
- ``agent_actions``: proposed actions awaiting human Approve/Deny (the gate).
- ``agent_events``: per-thread activity / tool-call timeline (telemetry).

Revision ID: 011
Revises: 010
Create Date: 2026-06-23

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "011"
down_revision: str | None = "010"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "agent_actions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "thread_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("support_threads.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("action_type", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="proposed"),
        sa.Column("payload_json", postgresql.JSON(astext_type=sa.Text()), nullable=False),
        sa.Column("telegram_message_id", sa.Integer(), nullable=True),
        sa.Column("decided_by", sa.String(length=128), nullable=True),
        sa.Column("result_json", postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_agent_actions_thread_id", "agent_actions", ["thread_id"])
    op.create_index("ix_agent_actions_status", "agent_actions", ["status"])

    op.create_table(
        "agent_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "thread_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("support_threads.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("detail_json", postgresql.JSON(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_agent_events_thread_id", "agent_events", ["thread_id"])
    op.create_index("ix_agent_events_event_type", "agent_events", ["event_type"])
    op.create_index("ix_agent_events_created_at", "agent_events", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_agent_events_created_at", table_name="agent_events")
    op.drop_index("ix_agent_events_event_type", table_name="agent_events")
    op.drop_index("ix_agent_events_thread_id", table_name="agent_events")
    op.drop_table("agent_events")
    op.drop_index("ix_agent_actions_status", table_name="agent_actions")
    op.drop_index("ix_agent_actions_thread_id", table_name="agent_actions")
    op.drop_table("agent_actions")
