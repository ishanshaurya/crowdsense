"""Webhook service: `/hook/{channel}` -> adapter.parse -> engine -> 200, then send (#86).

Failure policy (#71): an engine bug rolls the turn back, logs a correlation id, sends one
apology that is never stored, and still answers 200 so the channel stops retrying. Only an
unreachable database answers 5xx, so the channel retries later.

Run: `uv run uvicorn api.webhooks:build_app --factory --env-file .env --port 8000`
"""

import asyncio
import logging
import os
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, field

import httpx
from fastapi import BackgroundTasks, FastAPI, Request, Response

from adapters.base import Adapter, Tap
from adapters.telegram import TelegramAdapter
from api.chat import mount_chat
from api.logs import configure_logging
from api.sender import Pacer, Sender
from api.sweeper import Sweeper
from api.taps import RecentTaps
from core.clock import Clock, SystemClock
from core.config import load_settings, load_telegram_settings
from core.engine import Engine
from core.flow import APOLOGY_TEXT
from core.store import Store, StoreUnavailable
from core.store_postgres import PostgresStore
from core.types import InboundEvent, Reply

log = logging.getLogger("crowdsense.webhook")

Close = Callable[[], Awaitable[None]]


def _status(code: int) -> Response:
    return Response(status_code=code)  # fresh each time: FastAPI hangs background tasks on it


@dataclass(frozen=True)
class Webhook:
    engine: Engine
    store: Store
    adapters: Mapping[str, Adapter]
    clock: Clock
    sender: Sender
    taps: RecentTaps = field(default_factory=RecentTaps)

    async def hook(self, channel: str, request: Request, background: BackgroundTasks) -> Response:
        adapter = self.adapters.get(channel)
        if adapter is None:
            return _status(404)
        if not adapter.authorized(request.headers):
            return _status(401)
        try:
            body = await request.json()
        except ValueError:
            return _status(400)
        inbound = adapter.parse(body, self.clock.now())
        if inbound is None:
            return _status(200)
        if inbound.tap is not None:
            await _quietly(adapter.answer_tap, inbound.tap)  # stop the spinner first (#92)
        if inbound.event is None:
            return _status(200)
        return await self._turn(adapter, inbound.event, inbound.tap, background)

    async def _turn(
        self, adapter: Adapter, event: InboundEvent, tap: Tap | None, background: BackgroundTasks
    ) -> Response:
        user, cid = event.external_user_id, uuid.uuid4().hex[:12]
        try:
            result = await self.engine.handle(event)
        except StoreUnavailable:
            log.warning("cid=%s database unreachable; 503 so %s retries", cid, adapter.channel)
            return _status(503)
        except Exception:
            log.exception("cid=%s engine error on a %s update; rolled back", cid, adapter.channel)
            background.add_task(self.sender.send, adapter, user, Reply(APOLOGY_TEXT, "error"))
            return _status(200)
        if tap is not None and result.applied:
            self.taps.remember(tap)
            background.add_task(_quietly, adapter.confirm_tap, tap)  # buttons -> "✓ <choice>"
        elif tap is not None and not result.duplicate and self.taps.is_double(tap):
            await self.engine.mark_sent(result.replies)  # double tap: nothing extra (#91, #92)
            return _status(200)
        background.add_task(self.sender.deliver, adapter, user, result.replies)
        return _status(200)

    async def ready(self) -> Response:
        try:
            await self.store.ping()
        except StoreUnavailable:
            return _status(503)
        return _status(200)


async def _quietly(call: Callable[[Tap], Awaitable[None]], tap: Tap) -> None:
    try:
        await call(tap)
    except Exception as exc:
        log.warning("%s failed: %s", getattr(call, "__name__", "tap call"), exc)


def create_app(
    webhook: Webhook, *, sweeper: Sweeper | None = None, on_shutdown: Sequence[Close] = ()
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        task = asyncio.create_task(sweeper.run()) if sweeper else None
        try:
            yield
        finally:
            if task:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
            for close in on_shutdown:
                await close()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.add_api_route("/hook/{channel}", webhook.hook, methods=["POST"])
    app.add_api_route("/ready", webhook.ready, methods=["GET"])
    app.add_api_route("/health", _health, methods=["GET"])
    return app


async def _health() -> dict[str, str]:
    return {"status": "ok"}


def build_app() -> FastAPI:
    """Production wiring from the environment (uvicorn `--factory`)."""
    settings = load_settings(os.environ)
    telegram = load_telegram_settings(os.environ)
    configure_logging([telegram.bot_token, telegram.webhook_secret])
    store = PostgresStore(settings.database_url, max_size=5)
    clock = SystemClock()
    engine = Engine(store, clock, artist_name=settings.artist_name)
    client = httpx.AsyncClient(timeout=10.0)
    adapters: dict[str, Adapter] = {
        "telegram": TelegramAdapter(telegram.bot_token, telegram.webhook_secret, client),
    }
    sender = Sender(engine, Pacer())
    webhook = Webhook(engine, store, adapters, clock, sender)
    sweeper = Sweeper(store, engine, sender, adapters, clock)
    app = create_app(webhook, sweeper=sweeper, on_shutdown=(client.aclose, store.close))
    return mount_chat(app, engine, store, clock)  # web chat at /chat (#77), not in `adapters`
