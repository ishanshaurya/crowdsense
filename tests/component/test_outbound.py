"""Announcement fan-out (#59, #80, #85), on the in-memory store and on Postgres.

The dashboard's INSERT is stood in for by `ask()`: plain SQL on Postgres, the fake's
`request_announcement` in memory.
"""

import asyncio
from datetime import date, timedelta
from typing import Any

import psycopg
import pytest

from api.sweeper import Sweeper
from core import store_memory, store_postgres
from core.clock import ScriptedClock
from core.engine import Engine
from core.outbound import ANNOUNCEMENT_TEXT, Outbound, announcement_reply, today_ist
from core.store import Store
from core.store_memory import InMemoryStore
from core.types import Reply
from tests.component.telegram_fake import build_rig
from tests.support import ARTIST, decision, event

SHOW = date(2026, 12, 1)  # after NOW
PAST = date(2026, 10, 1)


async def ask(store: Store, pytest_request: Any, city: str, day: date = SHOW) -> int:
    if isinstance(store, InMemoryStore):
        return store.request_announcement(city, day)
    url = pytest_request.getfixturevalue("pg_migrated_url")
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO announcement_requests (city, event_date) VALUES (%s, %s)", (city, day)
        )
        row = conn.execute("SELECT max(id) FROM announcement_requests").fetchone()
    return int(row[0])  # type: ignore[index]


async def status(store: Store, pytest_request: Any, request_id: int) -> str:
    if isinstance(store, InMemoryStore):
        return store.request_status(request_id)
    url = pytest_request.getfixturevalue("pg_migrated_url")
    with psycopg.connect(url) as conn:
        row = conn.execute(
            "SELECT status FROM announcement_requests WHERE id = %s", (request_id,)
        ).fetchone()
    return str(row[0])  # type: ignore[index]


async def add_fan(
    store: Store,
    clock: ScriptedClock,
    user: str,
    *,
    city: str = "Pune",
    channel: str = "telegram",
    completed: bool = True,
    simulated: bool = False,
    consent: bool | None = True,
    opted_out: bool = False,
) -> int:
    now = clock.now()
    async with store.transaction() as tx:
        await tx.lock_identity(channel, user, None)
        fan_id = await tx.create_fan(channel, user, is_simulated=simulated, now=now)
        await tx.record_answer(fan_id, "city", city, now)
        await tx.set_consent(channel, user, consent)
        await tx.set_opted_out(channel, user, opted_out)
        if completed:
            await tx.mark_completed(fan_id, now)
    return fan_id


def outbound(store: Store, clock: ScriptedClock) -> Outbound:
    return Outbound(store, clock, artist_name=ARTIST)


async def unsent(store: Store) -> list[Any]:
    return [r for r in await store.replies() if r.status == "unsent"]


@decision(15, 75)
def test_p5_u05_u07_the_text_is_the_template_filled_in() -> None:
    reply = announcement_reply("Artist X", "Pune", SHOW)
    assert reply.text == "Artist X is coming to Pune. Tickets open 1 Dec 2026."
    assert "{" not in reply.text and ANNOUNCEMENT_TEXT.startswith("{artist}")


@decision(59, 80, 85, 111)
async def test_p5_c01_one_priority_1_reply_per_fan_in_the_audience(
    store: Store, clock: ScriptedClock, request: pytest.FixtureRequest
) -> None:
    fans = [await add_fan(store, clock, f"u{n}") for n in range(3)]
    await add_fan(store, clock, "elsewhere", city="Mumbai")
    request_id = await ask(store, request, "Pune")
    done = await outbound(store, clock).fan_out_next()
    assert done is not None and (done.request_id, done.recipients) == (request_id, 3)
    rows = await unsent(store)
    assert sorted(r.fan_id for r in rows) == fans
    assert {(r.priority, r.reply) for r in rows} == {(1, announcement_reply(ARTIST, "Pune", SHOW))}
    assert {r.external_user_id for r in rows} == {"u0", "u1", "u2"}
    assert await status(store, request, request_id) == "fanned_out"
    assert await outbound(store, clock).fan_out_next() is None  # nothing pending


EXCLUDED: dict[str, dict[str, Any]] = {
    "not completed": {"completed": False},
    "consent refused": {"consent": False},
    "consent unanswered": {"consent": None},
    "opted out": {"opted_out": True},
    "simulated": {"simulated": True},
    "web chat cannot push": {"channel": "web_sim"},
    "seeded channel": {"channel": "seed"},
    "other city": {"city": "Mumbai"},
}


@decision(36, 76, 85, 102, 110)
@pytest.mark.parametrize("why", EXCLUDED)
async def test_p5_u01_u04_c06_both_stores_skip_the_same_fans(
    store: Store, clock: ScriptedClock, request: pytest.FixtureRequest, why: str
) -> None:
    await add_fan(store, clock, "bad", **EXCLUDED[why])
    await ask(store, request, "Pune")
    done = await outbound(store, clock).fan_out_next()
    assert done is not None and done.recipients == 0
    assert await unsent(store) == []


@decision(41, 80, 111)
async def test_p5_c03_fanning_out_twice_queues_each_fan_once(
    store: Store, clock: ScriptedClock, request: pytest.FixtureRequest
) -> None:
    await add_fan(store, clock, "u1")
    request_id = await ask(store, request, "Pune")
    reply = announcement_reply(ARTIST, "Pune", SHOW)
    async with store.transaction() as tx:
        assert await tx.fan_out(request_id, "Pune", reply, clock.now()) == 1
    async with store.transaction() as tx:
        assert await tx.fan_out(request_id, "Pune", reply, clock.now()) == 0
    assert len(await unsent(store)) == 1


@decision(41, 80, 111)
async def test_two_sweepers_at_once_fan_out_a_request_once(
    store: Store, clock: ScriptedClock, request: pytest.FixtureRequest
) -> None:
    await add_fan(store, clock, "u1")
    await ask(store, request, "Pune")
    results = await asyncio.gather(
        outbound(store, clock).fan_out_next(), outbound(store, clock).fan_out_next()
    )
    assert sorted(r is None for r in results) == [False, True]
    assert len(await unsent(store)) == 1


@decision(80, 111)
async def test_a_crash_before_commit_leaves_nothing_and_the_rerun_works(
    store: Store,
    clock: ScriptedClock,
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await add_fan(store, clock, "u1")
    request_id = await ask(store, request, "Pune")

    async def boom(*_: object) -> None:
        raise RuntimeError("crash before commit")

    for tx_class in (store_memory._MemoryTx, store_postgres._PgTx):
        monkeypatch.setattr(tx_class, "finish_announcement", boom)
    with pytest.raises(RuntimeError):
        await outbound(store, clock).fan_out_next()
    assert await unsent(store) == []
    assert await status(store, request, request_id) == "pending"
    monkeypatch.undo()
    done = await outbound(store, clock).fan_out_next()
    assert done is not None and done.recipients == 1


@decision(80, 111)
async def test_chat_replies_are_claimed_before_announcements(
    store: Store, clock: ScriptedClock, request: pytest.FixtureRequest
) -> None:
    fan_id = await add_fan(store, clock, "u1")
    await ask(store, request, "Pune")
    await outbound(store, clock).fan_out_next()
    async with store.transaction() as tx:
        msg = event("text", text="hi", user="u1", msg_id="later")
        await tx.record_event(msg, clock.now(), fan_id)
        await tx.add_reply(fan_id, "telegram", "later", Reply("chat", "help"), clock.now())
    clock.advance(timedelta(minutes=1))
    async with store.transaction() as tx:
        first = await tx.claim_unsent(clock.now(), 1)
    assert [(r.priority, r.reply.text) for r in first] == [(0, "chat")]


@decision(36, 75, 114)
async def test_p5_c05_stop_after_fan_out_drops_the_announcement(
    store: Store, clock: ScriptedClock, engine: Engine, request: pytest.FixtureRequest
) -> None:
    await add_fan(store, clock, "u1")
    await add_fan(store, clock, "u2")
    await ask(store, request, "Pune")
    await outbound(store, clock).fan_out_next()
    await engine.handle(event("stop", user="u1", msg_id="stop-1"))
    left = [(r.external_user_id, r.reply.step_id) for r in await unsent(store)]
    assert ("u1", "announcement") not in left
    assert ("u2", "announcement") in left


@decision(75, 113)
async def test_p5_u09_a_past_date_queues_nothing(
    store: Store, clock: ScriptedClock, request: pytest.FixtureRequest
) -> None:
    await add_fan(store, clock, "u1")
    assert today_ist(clock.now()) > PAST
    request_id = await ask(store, request, "Pune", PAST)
    done = await outbound(store, clock).fan_out_next()
    assert done is not None and done.recipients == 0
    assert await unsent(store) == []
    assert await status(store, request, request_id) == "fanned_out"


@decision(72, 80, 111)
async def test_the_sweeper_sends_the_announcement_on_telegram(
    store: Store, clock: ScriptedClock, request: pytest.FixtureRequest
) -> None:
    rig = build_rig(store, clock)
    await add_fan(store, clock, "4242")
    await ask(store, request, "Pune")
    sweeper = Sweeper(
        store,
        rig.engine,
        rig.sweeper._sender,
        rig.sweeper._adapters,
        clock,
        outbound=outbound(store, clock),
    )
    assert await sweeper.sweep_once() == 1  # fanned out and sent in the same pass, no age wait
    sent = [p for method, p in rig.telegram.calls if method == "sendMessage"]
    assert [(p["chat_id"], p["text"]) for p in sent] == [
        ("4242", announcement_reply(ARTIST, "Pune", SHOW).text)
    ]
    assert await unsent(store) == []
    await rig.close()
