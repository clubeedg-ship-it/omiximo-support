"""Register the Telegram webhook with the correct allowed_updates.

The API also does this automatically on startup (``register_webhook``); this
script is the manual/CI equivalent:

    kubectl exec -n omiximo-support deploy/api -c api -- python -m scripts.set_webhook

Telegram only delivers the update types in ``allowed_updates``. The console needs
both ``callback_query`` (button taps) and ``message`` (slash commands + the
force-reply ✏️ Edit flow); omitting ``message`` silently breaks Edit and every
/command.
"""

from __future__ import annotations

import asyncio

import httpx

from app.config import settings
from app.services.telegram import register_webhook


async def main() -> None:
    ok = await register_webhook()
    print("register_webhook ok:", ok)
    token = settings.TELEGRAM_BOT_TOKEN
    if not token:
        print("TELEGRAM_BOT_TOKEN not set — nothing registered")
        return
    async with httpx.AsyncClient(timeout=20.0) as client:
        info = (await client.get(f"https://api.telegram.org/bot{token}/getWebhookInfo")).json()
    result = info.get("result", {})
    print("url:", result.get("url"))
    print("allowed_updates:", result.get("allowed_updates"))


if __name__ == "__main__":
    asyncio.run(main())
