"""Tests for runtime configuration hardening."""

from __future__ import annotations

import pytest

from app.config import DEFAULT_FERNET_KEY, Settings


class TestSettingsValidation:

    def test_production_rejects_default_fernet_key(self):
        settings = Settings(
            ENVIRONMENT="production",
            FERNET_KEY=DEFAULT_FERNET_KEY,
            CLERK_ISSUER="https://example.clerk.accounts.dev",
            CLERK_JWKS_URL="https://example.clerk.accounts.dev/.well-known/jwks.json",
            ALLOWED_EMAIL_DOMAIN="omiximo.nl",
            MIRAKL_WEBHOOK_SECRET="webhook-secret",
        )

        with pytest.raises(ValueError, match="FERNET_KEY"):
            settings.validate_runtime()

    def test_production_requires_allowlist(self):
        settings = Settings(
            ENVIRONMENT="production",
            FERNET_KEY="wzxdoW9iXct-qfLk7GQ2lYq7Rr0wzLVHTp_vg0oV3No=",  # gitleaks:allow
            CLERK_ISSUER="https://example.clerk.accounts.dev",
            CLERK_JWKS_URL="https://example.clerk.accounts.dev/.well-known/jwks.json",
            MIRAKL_WEBHOOK_SECRET="webhook-secret",
        )

        with pytest.raises(ValueError, match="ALLOWED_ADMIN_EMAILS|ALLOWED_EMAIL_DOMAIN"):
            settings.validate_runtime()

    def test_development_allows_default_fernet_key(self):
        settings = Settings(ENVIRONMENT="development", FERNET_KEY=DEFAULT_FERNET_KEY)

        assert settings.validate_runtime() is settings
