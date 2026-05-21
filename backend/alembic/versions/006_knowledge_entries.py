"""Create knowledge_entries table.

Stores knowledge base entries (policies, FAQs, product info, marketplace rules)
that provide context to the LLM during draft generation.

Revision ID: 006
Revises: 005
Create Date: 2026-05-17

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "006"
down_revision: str | None = "005"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # Enable pg_trgm extension for fuzzy text search
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    op.create_table(
        "knowledge_entries",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("entry_type", sa.String(50), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("category_tags", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("marketplace_tags", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("language", sa.String(10), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    # Index on entry_type for filtering
    op.create_index("ix_knowledge_entries_entry_type", "knowledge_entries", ["entry_type"])

    # GIN index on category_tags for containment queries (cast to jsonb for GIN support)
    op.execute(
        "CREATE INDEX ix_knowledge_category_tags ON knowledge_entries "
        "USING GIN (CAST(category_tags AS jsonb) jsonb_path_ops)"
    )

    # GIN index on marketplace_tags for containment queries (cast to jsonb for GIN support)
    op.execute(
        "CREATE INDEX ix_knowledge_marketplace_tags ON knowledge_entries "
        "USING GIN (CAST(marketplace_tags AS jsonb) jsonb_path_ops)"
    )

    # Full-text search index on title + content
    op.execute(
        "CREATE INDEX ix_knowledge_content_fts ON knowledge_entries "
        "USING GIN (to_tsvector('simple', title || ' ' || content))"
    )


def downgrade() -> None:
    op.drop_index("ix_knowledge_content_fts", table_name="knowledge_entries")
    op.drop_index("ix_knowledge_marketplace_tags", table_name="knowledge_entries")
    op.drop_index("ix_knowledge_category_tags", table_name="knowledge_entries")
    op.drop_index("ix_knowledge_entries_entry_type", table_name="knowledge_entries")
    op.drop_table("knowledge_entries")
