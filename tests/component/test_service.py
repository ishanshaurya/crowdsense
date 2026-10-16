"""Webhook service plumbing: sweeper lifecycle, /health, /ready, DB down -> 503 (#71, #72)."""

import asyncio

import pytest

from api.sweeper import Sweeper
from api.webhooks import Webhook, build_app, create_app
from core.clock import ScriptedClock
from core.config import ConfigError
from core.store_memory import InMemoryStore
from core.store_postgres import PostgresStore
from tests.component.telegram_fake import SECRET, TOKEN, build_rig, text_update
from tests.support import NOW, decision


@decision(72)
async def test_sweeper_runs_in_the_lifespan_and_stops_cleanly_on_shutdown() -> None:
    rig = build_rig(InMemoryStore(), ScriptedClock(NOW))
    sweeps, closed = [], []
    sweeper = Sweeper(rig.store, rig.engine, rig.sweeper._sender, {}, rig.clock, interval=0.01)
    original = sweeper.sweep_once

    async def counted() -> int:
        sweeps.append(1)
        return await original()

    sweeper.sweep_once = counted  # type: ignore[method-assign]

    async def close() -> None:
        closed.append(True)

    webhook = Webhook(rig.engine, rig.store, {}, rig.clock, rig.sweeper._sender)
    app = create_app(webhook, sweeper=sweeper, on_shutdown=(close,))
    async with app.router.lifespan_context(app):
        await asyncio.sleep(0.05)
    running = len(sweeps)
    await asyncio.sleep(0.05)
    assert running >= 2 and len(sweeps) == running and closed == [True]
    await rig.close()


@decision(71)
async def test_health_and_ready_endpoints() -> None:
    rig = build_rig(InMemoryStore(), ScriptedClock(NOW))
    assert (await rig.http.get("/health")).json() == {"status": "ok"}
    assert (await rig.http.get("/ready")).status_code == 200
    await rig.close()


@pytest.fixture
async def dead_db_rig():  # type: ignore[no-untyped-def]
    store = PostgresStore("postgresql://nobody@127.0.0.1:1/none", timeout=0.5)
    rig = build_rig(store, ScriptedClock(NOW))
    yield rig
    await rig.close()
    await store.close()


@decision(71)
async def test_database_down_answers_503_so_telegram_retries(dead_db_rig) -> None:  # type: ignore[no-untyped-def]
    assert await dead_db_rig.post(text_update("/start")) == 503
    assert (await dead_db_rig.http.get("/ready")).status_code == 503
    assert dead_db_rig.telegram.calls == []  # no apology: the retry will get a real answer


@decision(63, 71)
def test_production_factory_needs_valid_telegram_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://u@localhost:1/db")
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    with pytest.raises(ConfigError, match="TELEGRAM_BOT_TOKEN"):
        build_app()
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKEN)
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", SECRET)
    monkeypatch.setenv("PUBLIC_URL", "https://example.ngrok-free.dev")
    paths = {getattr(r, "path", "") for r in build_app().routes}
    assert {"/hook/{channel}", "/health", "/ready"} <= paths
