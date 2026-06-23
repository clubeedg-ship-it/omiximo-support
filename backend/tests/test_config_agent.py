"""Agent/Telegram settings have safe defaults."""

from app.config import Settings


def test_agent_settings_have_safe_defaults():
    s = Settings(_env_file=None)
    assert s.AGENT_ENABLED is False          # off until explicitly enabled
    assert s.AGENT_MODEL                       # non-empty default model
    assert s.AGENT_MAX_STEPS >= 1
    assert s.TELEGRAM_BOT_TOKEN == ""          # secret, empty by default
    assert s.TELEGRAM_CHAT_ID == ""
    assert s.TELEGRAM_WEBHOOK_SECRET == ""
