"""Register the Telegram webhook (#66): `setWebhook` with `secret_token` and `allowed_updates`.

    uv run python -m scripts.set_webhook            # message + callback_query
    uv run python -m scripts.set_webhook --record   # also edited_message, for recording fixtures
    uv run python -m scripts.set_webhook --info     # show the current registration only

Reads TELEGRAM_BOT_TOKEN, TELEGRAM_WEBHOOK_SECRET and PUBLIC_URL from the environment or `.env`.
Prints the public webhook URL and Telegram's status, never the token or the secret.
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

from adapters.telegram import ALLOWED_UPDATES, TelegramAdapter
from api.logs import configure_logging
from core.config import load_telegram_settings

ROOT = Path(__file__).resolve().parent.parent


async def run(record: bool, info_only: bool) -> None:
    settings = load_telegram_settings(os.environ)
    configure_logging([settings.bot_token, settings.webhook_secret])
    async with httpx.AsyncClient(timeout=10.0) as client:
        bot = TelegramAdapter(settings.bot_token, settings.webhook_secret, client)
        if not info_only:
            allowed = [*ALLOWED_UPDATES, *(["edited_message"] if record else [])]
            await bot.call(
                "setWebhook",
                {
                    "url": settings.webhook_url,
                    "secret_token": settings.webhook_secret,
                    "allowed_updates": allowed,
                },
            )
        info = await bot.call("getWebhookInfo", {})
    for key in ("url", "allowed_updates", "pending_update_count", "last_error_message"):
        sys.stdout.write(f"{key}: {info.get(key)}\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--record", action="store_true", help="also deliver edited messages")
    parser.add_argument("--info", action="store_true", help="only show the registration")
    args = parser.parse_args()
    load_dotenv(ROOT / ".env")
    asyncio.run(run(args.record, args.info))


if __name__ == "__main__":
    main()
