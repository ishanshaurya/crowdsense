"""Record raw Telegram updates for fixtures (testing/fixtures/telegram/README.md).

Runs the real webhook on the in-memory store, so the bot answers with real buttons and
nothing touches Supabase. Every authorised update body is saved as
`.recordings/<update_id>.json` (gitignored). Scrub before copying into the fixtures folder.

    uv run python -m scripts.set_webhook --record
    uv run uvicorn scripts.record_updates:build_app --factory --env-file .env --port 8000
"""

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI

from adapters.base import Adapter, Inbound
from adapters.telegram import TelegramAdapter
from api.logs import configure_logging
from api.sender import Pacer, Sender
from api.webhooks import Webhook, create_app
from core.clock import SystemClock
from core.config import load_telegram_settings
from core.engine import Engine
from core.store_memory import InMemoryStore

ROOT = Path(__file__).resolve().parent.parent
RECORDINGS = ROOT / ".recordings"
log = logging.getLogger("crowdsense.recorder")


class RecordingTelegram(TelegramAdapter):
    def parse(self, body: Any, received_at: datetime) -> Inbound | None:
        name = f"{body.get('update_id', 'unknown')}.json" if isinstance(body, dict) else "bad.json"
        (RECORDINGS / name).write_text(json.dumps(body, indent=2, ensure_ascii=False) + "\n")
        log.info("recorded %s", name)
        return super().parse(body, received_at)


def build_app() -> FastAPI:
    telegram = load_telegram_settings(os.environ)
    configure_logging([telegram.bot_token, telegram.webhook_secret])
    RECORDINGS.mkdir(exist_ok=True)
    store, clock = InMemoryStore(), SystemClock()
    engine = Engine(store, clock, artist_name=os.environ.get("ARTIST_NAME") or "Artist X")
    client = httpx.AsyncClient(timeout=10.0)
    adapters: dict[str, Adapter] = {
        "telegram": RecordingTelegram(telegram.bot_token, telegram.webhook_secret, client),
    }
    webhook = Webhook(engine, store, adapters, clock, Sender(engine, Pacer()))
    return create_app(webhook, on_shutdown=(client.aclose,))
