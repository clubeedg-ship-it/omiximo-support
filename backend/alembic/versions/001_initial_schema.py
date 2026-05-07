"""Initial schema: marketplace_accounts, support_threads, audit_log, response_templates.

Revision ID: 001
Revises:
Create Date: 2026-05-07

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "001"
down_revision: str | None = None
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute("CREATE TYPE customer_language_enum AS ENUM ('nl', 'en', 'fr', 'de')")
    op.execute("CREATE TYPE risk_level_enum AS ENUM ('GREEN', 'ORANGE', 'RED')")
    op.execute(
        "CREATE TYPE thread_status_enum AS ENUM "
        "('PENDING_REVIEW', 'APPROVED', 'SENT_AUTO', 'ESCALATED', 'FAILED')"
    )

    op.create_table(
        "marketplace_accounts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("marketplace", sa.String(100), nullable=False),
        sa.Column("shop_id", sa.String(100), nullable=False),
        sa.Column("api_key_encrypted", sa.String(500), nullable=False),
        sa.Column("base_url", sa.String(255), nullable=False),
        sa.Column("sla_hours", sa.Integer(), nullable=False, server_default="24"),
        sa.Column("template_set", sa.String(100), nullable=False, server_default="default"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    op.create_table(
        "support_threads",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("mirakl_thread_id", sa.String(100), nullable=False),
        sa.Column("mirakl_order_id", sa.String(100), nullable=False),
        sa.Column(
            "marketplace_account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("marketplace_accounts.id", ondelete="CASCADE", name="fk_support_threads_marketplace_account_id"),
            nullable=False,
        ),
        sa.Column("customer_language", postgresql.ENUM("nl", "en", "fr", "de", name="customer_language_enum", create_type=False), nullable=True),
        sa.Column("category", sa.String(100), nullable=True),
        sa.Column("risk_level", postgresql.ENUM("GREEN", "ORANGE", "RED", name="risk_level_enum", create_type=False), nullable=True),
        sa.Column("status", postgresql.ENUM("PENDING_REVIEW", "APPROVED", "SENT_AUTO", "ESCALATED", "FAILED", name="thread_status_enum", create_type=False), nullable=False, server_default="PENDING_REVIEW"),
        sa.Column("operator_required", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("customer_message", sa.Text(), nullable=False),
        sa.Column("drafted_response", sa.Text(), nullable=True),
        sa.Column("tracking_status", sa.String(100), nullable=True),
        sa.Column("invoice_status", sa.String(100), nullable=True),
        sa.Column("response_deadline", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("mirakl_thread_id", "marketplace_account_id", name="uq_thread_account"),
    )

    op.create_index("ix_support_threads_marketplace_account_id", "support_threads", ["marketplace_account_id"])
    op.create_index("ix_support_threads_status", "support_threads", ["status"])
    op.create_index("ix_support_threads_risk_level", "support_threads", ["risk_level"])
    op.create_index("ix_support_threads_response_deadline", "support_threads", ["response_deadline"])

    op.create_table(
        "audit_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "thread_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("support_threads.id", ondelete="SET NULL", name="fk_audit_log_thread_id"),
            nullable=True,
        ),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("actor", sa.String(100), nullable=False),
        sa.Column("detail_json", postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    op.create_index("ix_audit_log_thread_id", "audit_log", ["thread_id"])
    op.create_index("ix_audit_log_created_at", "audit_log", ["created_at"])

    op.create_table(
        "response_templates",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "marketplace_account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("marketplace_accounts.id", ondelete="CASCADE", name="fk_response_templates_marketplace_account_id"),
            nullable=True,
        ),
        sa.Column("category", sa.String(100), nullable=False),
        sa.Column("language", sa.String(10), nullable=False),
        sa.Column("template_body", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    op.create_index("ix_response_templates_category_language", "response_templates", ["category", "language"])


def downgrade() -> None:
    op.drop_table("response_templates")
    op.drop_table("audit_log")
    op.drop_table("support_threads")
    op.drop_table("marketplace_accounts")
    op.execute("DROP TYPE IF EXISTS thread_status_enum")
    op.execute("DROP TYPE IF EXISTS risk_level_enum")
    op.execute("DROP TYPE IF EXISTS customer_language_enum")
