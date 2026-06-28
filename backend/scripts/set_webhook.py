"""Register the Telegram webhook with the correct allowed_updates.

Run after a deploy, or whenever the bot token / public URL changes:

    kubectl exec -n omiximo-support deploy/api -c api -- python -m scripts.set_webhook

Telegram only delivers the update types listed in ``allowed_updates``. The
operator console needs BOTH:
  - ``callback_query`` — button taps (Approve/Deny/Edit/Translate/…)
  - ``message``        — slash commands (/pending, /thread, /stats, …) AND the
                         force-reply replies that drive the ✏️ Edit flow.

Omitting ``message`` silently breaks Edit and every /command — the webhook
simply never receives those updates. This script makes the registration
reproducible instead of a manual one-off.
"""

from __future__ import annotations

import asyncio

import httpx

from app.config import settings

ALLOWED_UPDATES = ["message", "callback_query"]


async def main() -> None:
    token = settings.TELEGRAM_BOT_TOKEN
    if not token:
        raise SystemExit("TELEGRAM_BOT_TOKEN is not set")

    url = f"{settings.PUBLIC_BASE_URL.rstrip('/')}/api/v1/telegram/webhook"
    body: dict = {"url": url, "allowed_updates": ALLOWED_UPDATES}
    if settings.TELEGRAM_WEBHOOK_SECRET:
        body["secret_token"] = settings.TELEGRAM_WEBHOOK_SECRET

    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.post(f"https://api.telegram.org/bot{token}/setWebhook", json=body)
        print("setWebhook:", resp.json())
        info = (await client.get(f"https://api.telegram.org/bot{token}/getWebhookInfo")).json()
        result = info.get("result", {})
        print("url:", result.get("url"))
        print("allowed_updates:", result.get("allowed_updates"))


if __name__ == "__main__":
    asyncio.run(main())
