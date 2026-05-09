"""Application configuration via pydantic-settings.

All settings are read from environment variables. Defaults are tuned for local
Docker Compose development; override via a .env file or shell environment.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ------------------------------------------------------------------ #
    # Database                                                             #
    # ------------------------------------------------------------------ #
    DATABASE_URL: str = "postgresql+asyncpg://omiximo:omiximo@localhost:5432/omiximo"

    # ------------------------------------------------------------------ #
    # Encryption                                                           #
    # A valid 32-byte, URL-safe base64-encoded Fernet key.                #
    # Generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    # ------------------------------------------------------------------ #
    FERNET_KEY: str = "YWJjZGVmZ2hpamtsbW5vcHFyc3R1dnd4eXoxMjM0NTY="

    # ------------------------------------------------------------------ #
    # LLM                                                                  #
    # ------------------------------------------------------------------ #
    LLM_API_KEY: str = ""
    LLM_MODEL: str = "anthropic/claude-sonnet-4"
    LLM_API_BASE_URL: str = "https://openrouter.ai/api/v1"

    # ------------------------------------------------------------------ #
    # Mirakl polling / webhooks                                           #
    # ------------------------------------------------------------------ #
    MIRAKL_POLL_INTERVAL_SECONDS: int = 300  # 5 minutes
    MIRAKL_WEBHOOK_SECRET: str = ""  # Optional; leave empty to skip validation

    # ------------------------------------------------------------------ #
    # CORS                                                                 #
    # ------------------------------------------------------------------ #
    CORS_ORIGINS: list[str] = [
        "http://localhost:5173",
        "http://localhost:3000",
        "https://support.abbamarkt.nl",
        "http://support.abbamarkt.nl",
    ]

    # ------------------------------------------------------------------ #
    # General                                                              #
    # ------------------------------------------------------------------ #
    DEBUG: bool = False
    API_V1_PREFIX: str = "/api/v1"


settings = Settings()
