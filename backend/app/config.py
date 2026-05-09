"""Application configuration via pydantic-settings."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Literal

from cryptography.fernet import Fernet
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_FERNET_KEY = "YWJjZGVmZ2hpamtsbW5vcHFyc3R1dnd4eXoxMjM0NTY="  # gitleaks:allow


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ------------------------------------------------------------------ #
    # General                                                              #
    # ------------------------------------------------------------------ #
    ENVIRONMENT: Literal["development", "test", "production"] = "development"
    DEBUG: bool = False
    API_V1_PREFIX: str = "/api/v1"

    # ------------------------------------------------------------------ #
    # Database                                                             #
    # ------------------------------------------------------------------ #
    DATABASE_URL: str = "postgresql+asyncpg://omiximo:omiximo@localhost:5432/omiximo"

    # ------------------------------------------------------------------ #
    # Authentication / authorization                                       #
    # ------------------------------------------------------------------ #
    CLERK_ISSUER: str = ""
    CLERK_JWKS_URL: str = ""
    CLERK_AUDIENCE: str = ""
    CLERK_JWKS_CACHE_TTL_SECONDS: int = 300
    CLERK_CLOCK_SKEW_SECONDS: int = 5
    ALLOWED_ADMIN_EMAILS: tuple[str, ...] = ()
    ALLOWED_EMAIL_DOMAIN: str = ""
    ALLOW_INSECURE_DEV_AUTH_BYPASS: bool = False
    DEV_AUTH_BYPASS_EMAIL: str = "dev-admin@example.com"

    # ------------------------------------------------------------------ #
    # Encryption                                                           #
    # ------------------------------------------------------------------ #
    FERNET_KEY: str = DEFAULT_FERNET_KEY

    # ------------------------------------------------------------------ #
    # LLM                                                                  #
    # ------------------------------------------------------------------ #
    LLM_API_KEY: str = ""
    LLM_MODEL: str = "anthropic/claude-sonnet-4"
    LLM_API_BASE_URL: str = "https://openrouter.ai/api/v1"

    # ------------------------------------------------------------------ #
    # Mirakl Connect (centralized OAuth2 API)                             #
    # ------------------------------------------------------------------ #
    MIRAKL_CONNECT_CLIENT_ID: str = ""
    MIRAKL_CONNECT_CLIENT_SECRET: str = ""
    MIRAKL_CONNECT_SELLER_ID: str = ""
    MIRAKL_CONNECT_API_URL: str = "https://connect-api.mirakl.net"

    # ------------------------------------------------------------------ #
    # Mirakl polling / webhooks                                           #
    # ------------------------------------------------------------------ #
    MIRAKL_POLL_INTERVAL_SECONDS: int = 300
    MIRAKL_WEBHOOK_SECRET: str = ""

    # ------------------------------------------------------------------ #
    # CORS                                                                 #
    # ------------------------------------------------------------------ #
    CORS_ORIGINS: list[str] = [
        "http://localhost:5173",
        "http://localhost:3000",
        "https://support.abbamarkt.nl",
        "http://support.abbamarkt.nl",
    ]

    @field_validator(
        "CLERK_ISSUER",
        "CLERK_JWKS_URL",
        "CLERK_AUDIENCE",
        "ALLOWED_EMAIL_DOMAIN",
        "DEV_AUTH_BYPASS_EMAIL",
        "FERNET_KEY",
        "MIRAKL_WEBHOOK_SECRET",
        mode="before",
    )
    @classmethod
    def _normalize_str(cls, value: str | None) -> str:
        return value.strip() if isinstance(value, str) else ""

    @field_validator("ALLOWED_ADMIN_EMAILS", mode="before")
    @classmethod
    def _parse_allowed_admin_emails(
        cls,
        value: str | Iterable[str] | None,
    ) -> tuple[str, ...]:
        if value in (None, ""):
            return ()
        if isinstance(value, str):
            items = value.split(",")
        else:
            items = value
        return tuple(
            email.strip().lower()
            for email in items
            if isinstance(email, str) and email.strip()
        )

    @field_validator("ALLOWED_EMAIL_DOMAIN")
    @classmethod
    def _normalize_domain(cls, value: str) -> str:
        return value.removeprefix("@").lower()

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"

    def is_email_allowed(self, email: str | None) -> bool:
        if not email:
            return False

        normalized_email = email.strip().lower()
        if normalized_email in self.ALLOWED_ADMIN_EMAILS:
            return True

        if not self.ALLOWED_EMAIL_DOMAIN:
            return False

        _, _, domain = normalized_email.partition("@")
        return domain == self.ALLOWED_EMAIL_DOMAIN

    def validate_runtime(self) -> Settings:
        self._validate_fernet_key()

        if not self.is_production:
            return self

        if self.FERNET_KEY == DEFAULT_FERNET_KEY:
            raise ValueError("FERNET_KEY must not use the development default in production.")
        if not self.CLERK_ISSUER or not self.CLERK_JWKS_URL:
            raise ValueError(
                "CLERK_ISSUER and CLERK_JWKS_URL are required in production."
            )
        if not self.ALLOWED_ADMIN_EMAILS and not self.ALLOWED_EMAIL_DOMAIN:
            raise ValueError(
                "Configure ALLOWED_ADMIN_EMAILS or ALLOWED_EMAIL_DOMAIN in production."
            )
        if self.ALLOW_INSECURE_DEV_AUTH_BYPASS:
            raise ValueError(
                "ALLOW_INSECURE_DEV_AUTH_BYPASS must be disabled in production."
            )
        if not self.MIRAKL_WEBHOOK_SECRET:
            raise ValueError(
                "MIRAKL_WEBHOOK_SECRET is required in production when webhooks are exposed."
            )

        return self

    def _validate_fernet_key(self) -> None:
        try:
            Fernet(self.FERNET_KEY.encode())
        except Exception as exc:  # pragma: no cover - exact exception is implementation detail
            raise ValueError(
                "FERNET_KEY must be a valid Fernet key. Generate one with "
                "`python -c \"from cryptography.fernet import Fernet; "
                "print(Fernet.generate_key().decode())\"`."
            ) from exc


settings = Settings()
