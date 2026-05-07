"""Initial schema: marketplace_accounts, support_threads, audit_log, response_templates.

Revision ID: 001
Revises:
Create Date: 2026-05-07

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# ---------------------------------------------------------------------------
# Revision identifiers
# ---------------------------------------------------------------------------
revision: str = "001"
down_revision: str | None = None
branch_labels: str | None = None
depends_on: str | None = None


# ---------------------------------------------------------------------------
# Enum type objects (defined once; reused in upgrade/downgrade)
# ---------------------------------------------------------------------------
customer_language_enum = sa.Enum(
    "nl", "en", "fr", "de",
    name="customer_language_enum",
)
risk_level_enum = sa.Enum(
    "GREEN", "ORANGE", "RED",
    name="risk_level_enum",
)
thread_status_enum = sa.Enum(
    "PENDING_REVIEW", "APPROVED", "SENT_AUTO", "ESCALATED", "FAILED",
    name="thread_status_enum",
)


def upgrade() -> None:
    # ------------------------------------------------------------------ #
    # Create enum types                                                    #
    # ------------------------------------------------------------------ #
    customer_language_enum.create(op.get_bind(), checkfirst=True)
    risk_level_enum.create(op.get_bind(), checkfirst=True)
    thread_status_enum.create(op.get_bind(), checkfirst=True)

    # ------------------------------------------------------------------ #
    # marketplace_accounts                                                 #
    # ------------------------------------------------------------------ #
    op.create_table(
        "marketplace_accounts",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "marketplace",
            sa.String(100),
            nullable=False,
            comment="Human-readable marketplace name, e.g. MediaMarkt, Boulanger",
        ),
        sa.Column(
            "shop_id",
            sa.String(100),
            nullable=False,
            comment="Seller shop ID within the marketplace",
        ),
        sa.Column(
            "api_key_encrypted",
            sa.String(500),
            nullable=False,
            comment="Fernet-encrypted Mirakl API key — never stored in plaintext",
        ),
        sa.Column(
            "base_url",
            sa.String(255),
            nullable=False,
            comment="Mirakl API base URL, e.g. https://markt.mediamarkt.nl",
        ),
        sa.Column(
            "sla_hours",
            sa.Integer(),
            nullable=False,
            server_default="24",
            comment="SLA response time in hours for this marketplace",
        ),
        sa.Column(
            "template_set",
            sa.String(100),
            nullable=False,
            server_default="default",
            comment="Template set identifier; maps to response_templates.template_set",
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
            comment="Inactive accounts are skipped during polling",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # ------------------------------------------------------------------ #
    # support_threads                                                      #
    # ------------------------------------------------------------------ #
    op.create_table(
        "support_threads",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "mirakl_thread_id",
            sa.String(100),
            nullable=False,
            comment="Mirakl-assigned thread identifier",
        ),
        sa.Column(
            "mirakl_order_id",
            sa.String(100),
            nullable=False,
            comment="Mirakl-assigned order identifier associated with this thread",
        ),
        sa.Column(
            "marketplace_account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "marketplace_accounts.id",
                ondelete="CASCADE",
                name="fk_support_threads_marketplace_account_id",
            ),
            nullable=False,
        ),
        sa.Column(
            "customer_language",
            customer_language_enum,
            nullable=True,
            comment="Detected customer language; populated after classification",
        ),
        sa.Column(
            "category",
            sa.String(100),
            nullable=True,
            comment="Message category returned by the LLM classifier",
        ),
        sa.Column(
            "risk_level",
            risk_level_enum,
            nullable=True,
            comment="Risk classification: GREEN / ORANGE / RED",
        ),
        sa.Column(
            "status",
            thread_status_enum,
            nullable=False,
            server_default="PENDING_REVIEW",
            comment="Lifecycle status of this thread",
        ),
        sa.Column(
            "operator_required",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
            comment=(
                "True when the message originates from the marketplace operator; "
                "auto-reply is permanently blocked for these threads"
            ),
        ),
        sa.Column(
            "customer_message",
            sa.Text(),
            nullable=False,
            comment="Raw customer message text as received from Mirakl",
        ),
        sa.Column(
            "drafted_response",
            sa.Text(),
            nullable=True,
            comment=(
                "Template-rendered response; NULL until classification + drafting completes"
            ),
        ),
        sa.Column(
            "tracking_status",
            sa.String(100),
            nullable=True,
            comment="Latest carrier tracking status (Phase 2)",
        ),
        sa.Column(
            "invoice_status",
            sa.String(100),
            nullable=True,
            comment="Invoice status from billing system (Phase 2)",
        ),
        sa.Column(
            "response_deadline",
            sa.DateTime(timezone=True),
            nullable=False,
            comment=(
                "SLA deadline; computed as created_at + marketplace_account.sla_hours"
            ),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "mirakl_thread_id",
            "marketplace_account_id",
            name="uq_thread_account",
        ),
    )

    # Indexes on support_threads
    op.create_index(
        "ix_support_threads_mirakl_thread_id",
        "support_threads",
        ["mirakl_thread_id"],
    )
    op.create_index(
        "ix_support_threads_mirakl_order_id",
        "support_threads",
        ["mirakl_order_id"],
    )
    op.create_index(
        "ix_support_threads_marketplace_account_id",
        "support_threads",
        ["marketplace_account_id"],
    )
    op.create_index(
        "ix_support_threads_status",
        "support_threads",
        ["status"],
    )
    op.create_index(
        "ix_support_threads_risk_level",
        "support_threads",
        ["risk_level"],
    )
    op.create_index(
        "ix_support_threads_category",
        "support_threads",
        ["category"],
    )
    op.create_index(
        "ix_support_threads_response_deadline",
        "support_threads",
        ["response_deadline"],
    )

    # ------------------------------------------------------------------ #
    # audit_log                                                            #
    # ------------------------------------------------------------------ #
    op.create_table(
        "audit_log",
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
                ondelete="SET NULL",
                name="fk_audit_log_thread_id",
            ),
            nullable=True,
            comment="FK to the associated support thread; NULL for account-level events",
        ),
        sa.Column(
            "action",
            sa.String(100),
            nullable=False,
            comment=(
                "Action identifier, e.g. thread_collected, classified, draft_generated, "
                "safety_validated, auto_sent, human_approved, escalated, pipeline_failed"
            ),
        ),
        sa.Column(
            "actor",
            sa.String(100),
            nullable=False,
            comment="Who or what triggered this action: 'system' or a user identifier",
        ),
        sa.Column(
            "detail_json",
            postgresql.JSON(astext_type=sa.Text()),
            nullable=True,
            comment="Arbitrary structured context for this audit event",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # Indexes on audit_log
    op.create_index(
        "ix_audit_log_thread_id",
        "audit_log",
        ["thread_id"],
    )
    op.create_index(
        "ix_audit_log_action",
        "audit_log",
        ["action"],
    )
    op.create_index(
        "ix_audit_log_created_at",
        "audit_log",
        ["created_at"],
    )

    # ------------------------------------------------------------------ #
    # response_templates                                                   #
    # ------------------------------------------------------------------ #
    op.create_table(
        "response_templates",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "marketplace_account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "marketplace_accounts.id",
                ondelete="CASCADE",
                name="fk_response_templates_marketplace_account_id",
            ),
            nullable=True,
            comment="NULL means this template is available to all marketplace accounts",
        ),
        sa.Column(
            "category",
            sa.String(100),
            nullable=False,
            comment=(
                "Message category this template handles, "
                "e.g. tracking_update, return_inquiry"
            ),
        ),
        sa.Column(
            "language",
            sa.String(10),
            nullable=False,
            comment="ISO 639-1 language code: nl, en, fr, de",
        ),
        sa.Column(
            "template_body",
            sa.Text(),
            nullable=False,
            comment=(
                "Jinja2 template. Available slots: {{ order_id }}, "
                "{{ tracking_number }}, {{ delivery_date }}, "
                "{{ marketplace_name }}, {{ customer_name }}"
            ),
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
            comment="Inactive templates are skipped during resolution",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # Indexes on response_templates
    op.create_index(
        "ix_response_templates_marketplace_account_id",
        "response_templates",
        ["marketplace_account_id"],
    )
    op.create_index(
        "ix_response_templates_category",
        "response_templates",
        ["category"],
    )
    op.create_index(
        "ix_response_templates_language",
        "response_templates",
        ["language"],
    )
    # Composite index for the primary resolution query (category + language)
    op.create_index(
        "ix_response_templates_category_language",
        "response_templates",
        ["category", "language"],
    )


def downgrade() -> None:
    # Drop tables in reverse dependency order
    op.drop_table("response_templates")
    op.drop_table("audit_log")
    op.drop_table("support_threads")
    op.drop_table("marketplace_accounts")

    # Drop enum types
    thread_status_enum.drop(op.get_bind(), checkfirst=True)
    risk_level_enum.drop(op.get_bind(), checkfirst=True)
    customer_language_enum.drop(op.get_bind(), checkfirst=True)
