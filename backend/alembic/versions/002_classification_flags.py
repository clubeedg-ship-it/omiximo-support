"""Add classification_flags table.

Revision ID: 002
Revises: 001
Create Date: 2026-05-07

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# ---------------------------------------------------------------------------
# Revision identifiers
# ---------------------------------------------------------------------------
revision: str = "002"
down_revision: str | None = "001"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "classification_flags",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "thread_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "support_threads.id",
                ondelete="CASCADE",
                name="fk_classification_flags_thread_id",
            ),
            nullable=False,
            comment="The thread whose classification is disputed",
        ),
        # Snapshot of the original classification
        sa.Column(
            "original_category",
            sa.String(100),
            nullable=True,
            comment="Category value on the thread when the flag was created",
        ),
        sa.Column(
            "original_risk_level",
            sa.String(20),
            nullable=True,
            comment="risk_level on the thread when the flag was created",
        ),
        sa.Column(
            "original_language",
            sa.String(10),
            nullable=True,
            comment="customer_language on the thread when the flag was created",
        ),
        # Proposed corrections
        sa.Column(
            "correct_category",
            sa.String(100),
            nullable=False,
            comment="Proposed correct category",
        ),
        sa.Column(
            "correct_risk_level",
            sa.String(20),
            nullable=False,
            comment="Proposed correct risk_level: GREEN / ORANGE / RED",
        ),
        sa.Column(
            "correct_language",
            sa.String(10),
            nullable=False,
            comment="Proposed correct ISO 639-1 language code",
        ),
        sa.Column(
            "reason",
            sa.Text(),
            nullable=False,
            comment="Human-readable explanation for why the classification is wrong",
        ),
        sa.Column(
            "actor",
            sa.String(100),
            nullable=False,
            comment="User ID or email of the person submitting the flag",
        ),
        # Resolution fields
        sa.Column(
            "resolution",
            sa.String(20),
            nullable=True,
            comment="accepted | rejected | NULL (pending)",
        ),
        sa.Column(
            "resolved_by",
            sa.String(100),
            nullable=True,
            comment="User ID or email of the reviewer who resolved the flag",
        ),
        sa.Column(
            "resolved_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Timestamp when the flag was resolved",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    op.create_index(
        "ix_classification_flags_thread_id",
        "classification_flags",
        ["thread_id"],
    )
    op.create_index(
        "ix_classification_flags_resolution",
        "classification_flags",
        ["resolution"],
    )
    op.create_index(
        "ix_classification_flags_created_at",
        "classification_flags",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_table("classification_flags")
