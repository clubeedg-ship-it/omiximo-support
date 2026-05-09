"""Make marketplace_accounts.api_key_encrypted nullable.

With the migration to Mirakl Connect OAuth2, authentication is centralised
and per-marketplace API keys are no longer required. Existing rows that were
created with the old flow will keep their encrypted key intact; new accounts
created in Connect mode will have NULL in this column.

Revision ID: 003
Revises: 002
Create Date: 2026-05-09

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# ---------------------------------------------------------------------------
# Revision identifiers
# ---------------------------------------------------------------------------
revision: str = "003"
down_revision: str | None = "002"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.alter_column(
        "marketplace_accounts",
        "api_key_encrypted",
        existing_type=sa.String(500),
        nullable=True,
        comment=(
            "Fernet-encrypted Mirakl API key — never stored in plaintext. "
            "NULL when Mirakl Connect OAuth2 is used (api key not required)."
        ),
    )


def downgrade() -> None:
    # Before reverting nullable → not nullable, fill any NULL values with a
    # placeholder so that the NOT NULL constraint can be re-applied safely.
    op.execute(
        "UPDATE marketplace_accounts "
        "SET api_key_encrypted = 'PLACEHOLDER_KEY_REMOVED' "
        "WHERE api_key_encrypted IS NULL"
    )
    op.alter_column(
        "marketplace_accounts",
        "api_key_encrypted",
        existing_type=sa.String(500),
        nullable=False,
        comment="Fernet-encrypted Mirakl API key — never stored in plaintext",
    )
