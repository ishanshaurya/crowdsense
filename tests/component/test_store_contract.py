"""One suite, run on the in-memory fake and on Postgres (#54). Both must pass identically."""

import asyncio
from datetime import timedelta
from pathlib import Path

import pytest

from core.clock import ScriptedClock
from core.engine import Engine
from core.store import IntegrityViolation, Store
from tests.component.helpers import talk
from tests.support import ARTIST, NOW, decision, event


async def new_fan(store: Store, user: str = "u1", *, at=NOW) -> int:  # type: ignore[no-untyped-def]
    async with store.transaction() as tx:
        await tx.lock_identity("telegram", user, None)
        return await tx.create_fan("telegram", user, is_simulated=False, now=at)


@decision(41)
async def test_p1_s01_same_event_key_is_recorded_once(store: Store) -> None:
    ev = event("start", msg_id="m1")
    async with store.transaction() as tx:
        assert await tx.record_event(ev, NOW) is True
        assert await tx.record_event(ev, NOW) is False
    async with store.transaction() as tx:
        assert await tx.record_event(ev, NOW) is False
    assert len(await store.events()) == 1
    other_channel = event("start", msg_id="m1", channel="web_sim")
    async with store.transaction() as tx:
        assert await tx.record_event(other_channel, NOW) is True


@decision(55, 88)
async def test_p1_s02_second_turn_waits_for_the_identity_lock(store: Store) -> None:
    seen: list[tuple[str, int | None]] = []

    async def second() -> None:
        async with store.transaction() as tx:
            identity = await tx.lock_identity("telegram", "u1", None)
            seen.append(("second", identity.fan_id))

    async with store.transaction() as tx1:
        await tx1.lock_identity("telegram", "u1", None)
        task = asyncio.create_task(second())
        await asyncio.sleep(0.3)
        assert not task.done()
        fan_id = await tx1.create_fan("telegram", "u1", is_simulated=False, now=NOW)
        seen.append(("first", fan_id))
    await asyncio.wait_for(task, 5)
    assert seen == [("first", fan_id), ("second", fan_id)]


@decision(55)
async def test_p1_s03_failed_turn_saves_nothing(store: Store) -> None:
    fan_id = await new_fan(store)
    ev = event("choice", msg_id="m9")
    with pytest.raises(RuntimeError):
        async with store.transaction() as tx:
            await tx.record_event(ev, NOW)
            await tx.record_answer(fan_id, "city", "Pune", NOW)
            await tx.save_progress(fan_id, "venue", "venue", NOW)
            await tx.add_reply(fan_id, "telegram", "m9", _reply(), NOW)
            await tx.set_consent("telegram", "u1", True)
            raise RuntimeError("bug after writing the answer")
    assert await store.answers() == [] and await store.replies() == []
    assert await store.events() == []
    (fan,) = await store.fans()
    assert (fan.city, fan.furthest_step) == (None, None)
    assert [s.step_id for s in await store.sessions()] == ["consent"]
    assert [i.consent for i in await store.identities()] == [None]


def _reply():  # type: ignore[no-untyped-def]
    from core.types import Reply

    return Reply("hi", "city")


@decision(47, 55)
async def test_p1_s04_unsent_replies_survive_a_restart(store: Store, clock: ScriptedClock) -> None:
    first = Engine(store, clock, artist_name=ARTIST)
    result = await first.handle(event("start", msg_id="m1"))
    assert result.replies[0].id is not None
    restarted = Engine(store, clock, artist_name=ARTIST)  # crash before sending
    assert [r.status for r in await store.replies()] == ["unsent"]
    redelivered = await restarted.handle(event("start", msg_id="m1"))
    assert redelivered.duplicate
    assert [o.id for o in redelivered.replies] == [result.replies[0].id]
    assert redelivered.replies[0].reply == result.replies[0].reply


@decision(55)
async def test_p1_s05_duplicate_event_resends_only_unsent_replies(
    engine: Engine, store: Store
) -> None:
    ev = event("start", msg_id="m1")
    first = await engine.handle(ev)
    again = await engine.handle(ev)
    assert again.duplicate and [o.id for o in again.replies] == [o.id for o in first.replies]
    await engine.mark_sent(again.replies)
    third = await engine.handle(ev)
    assert third.duplicate and third.replies == ()
    assert len(await store.replies()) == 1 and len(await store.events()) == 1


@decision(56)
async def test_p1_s06_scripted_clock_drives_every_timestamp(
    engine: Engine, store: Store, clock: ScriptedClock
) -> None:
    await talk(engine, "u1", [("start", ""), ("choice", "yes"), ("choice", "Pune")])
    stamp = NOW + timedelta(days=2, hours=5)
    clock.set(stamp)
    await talk(engine, "u1", [("choice", "8")])
    (fan,) = await store.fans()
    assert (fan.created_at, fan.last_seen) == (NOW, stamp)
    (session,) = await store.sessions()
    assert session.updated_at == stamp
    assert {e.ts for e in await store.events()} == {NOW, stamp}
    assert {a.ts for a in await store.answers()} == {NOW, stamp}
    assert {r.ts for r in await store.replies()} == {NOW, stamp}


@decision(72)
async def test_p1_s07_two_claimers_get_disjoint_replies(store: Store) -> None:
    fan_id = await new_fan(store)
    async with store.transaction() as tx:
        await tx.record_event(event("start", msg_id="m1"), NOW)
        for _ in range(5):
            await tx.add_reply(fan_id, "telegram", "m1", _reply(), NOW)
    later = NOW + timedelta(seconds=30)
    async with store.transaction() as tx1:
        first = await tx1.claim_unsent(later, 3)
        async with store.transaction() as tx2:
            second = await tx2.claim_unsent(later, 10)
            await tx2.mark_sent([r.id for r in second])
        await tx1.mark_sent([r.id for r in first])
    ids_first, ids_second = {r.id for r in first}, {r.id for r in second}
    assert len(ids_first) == 3 and len(ids_second) == 2
    assert ids_first.isdisjoint(ids_second)
    async with store.transaction() as tx:
        assert await tx.claim_unsent(later, 10) == []


@decision(72)
async def test_claim_ignores_fresh_and_sent_replies(store: Store) -> None:
    fan_id = await new_fan(store)
    async with store.transaction() as tx:
        await tx.record_event(event("start", msg_id="m1"), NOW)
        sent = await tx.add_reply(fan_id, "telegram", "m1", _reply(), NOW)
        await tx.mark_sent([sent])
        fresh = await tx.add_reply(fan_id, "telegram", "m1", _reply(), NOW + timedelta(seconds=11))
        old = await tx.add_reply(fan_id, "telegram", "m1", _reply(), NOW)
    async with store.transaction() as tx:
        claimed = await tx.claim_unsent(NOW + timedelta(seconds=10), 10)
    assert [r.id for r in claimed] == [old]
    assert fresh != old


@decision(88)
async def test_p1_s08_two_messages_from_a_new_fan_make_one_fan(
    engine: Engine, store: Store
) -> None:
    pairs = [
        (event("start", user=f"u{i}", msg_id=f"a{i}"), event("start", user=f"u{i}", msg_id=f"b{i}"))
        for i in range(5)
    ]
    results = await asyncio.gather(*(engine.handle(e) for pair in pairs for e in pair))
    assert not any(r.duplicate for r in results)
    assert len(await store.identities()) == 5
    assert len(await store.fans()) == 5 and len(await store.sessions()) == 5
    assert len(await store.events()) == 10 and len(await store.replies()) == 10
    assert len({i.fan_id for i in await store.identities()}) == 5
    assert all(r.replies and not r.replies[0].reply.is_error for r in results)


@decision(41)
async def test_p1_c10_database_rejects_bad_values(store: Store) -> None:
    fan_id = await new_fan(store)
    for field, value in (("budget_band", "cheap"), ("group_size", "9")):
        with pytest.raises(IntegrityViolation):
            async with store.transaction() as tx:
                await tx.record_answer(fan_id, field, value, NOW)
    with pytest.raises(IntegrityViolation):
        async with store.transaction() as tx:
            await tx.record_answer(fan_id, "venue", "999", NOW)
    with pytest.raises(IntegrityViolation):
        async with store.transaction() as tx:
            await tx.record_answer(fan_id, "shoe_size", "9", NOW)
    assert await store.answers() == []


@decision(41)
async def test_venues_come_from_the_store(store: Store) -> None:
    venues = await store.venues()
    assert len(venues) == 14 and venues[0].name == "Mahalaxmi Maidan"


@decision(41, 54)
def test_p1_c11_every_contract_test_runs_on_both_backends(request: pytest.FixtureRequest) -> None:
    contract = [
        i for i in request.session.items if i.path == Path(__file__) and "store" in i.fixturenames
    ]
    names = {i.originalname for i in contract}
    assert len(names) >= 9
    for name in names:
        backends = {i.callspec.params["store"] for i in contract if i.originalname == name}
        assert backends == {"memory", "postgres"}, name


@decision(55)
async def test_event_can_be_recorded_with_its_fan(store: Store) -> None:
    fan_id = await new_fan(store)
    async with store.transaction() as tx:
        assert await tx.record_event(event("text", msg_id="m1"), NOW, fan_id)
        fan, session = await tx.load_state(fan_id)
    assert (fan.id, session.fan_id, session.step_id) == (fan_id, fan_id, "consent")
    assert [e.fan_id for e in await store.events()] == [fan_id]


@decision(72)
async def test_replies_carry_the_identity_and_claims_filter_by_channel(store: Store) -> None:
    fan_id = await new_fan(store, "chat-7")
    async with store.transaction() as tx:
        await tx.record_event(event("start", msg_id="m1"), NOW, fan_id)
        await tx.record_event(event("start", msg_id="w1", channel="web_sim"), NOW)
        tg = await tx.add_reply(fan_id, "telegram", "m1", _reply(), NOW)
        await tx.add_reply(fan_id, "web_sim", "w1", _reply(), NOW)
    later = NOW + timedelta(seconds=30)
    async with store.transaction() as tx:
        claimed = await tx.claim_unsent(later, 10, channels={"telegram"})
        assert [(r.id, r.external_user_id) for r in claimed] == [(tg, "chat-7")]
        (unsent,) = await tx.unsent_replies("telegram", "m1")
        assert unsent.external_user_id == "chat-7"
    by_channel = {r.channel: r.external_user_id for r in await store.replies()}
    assert by_channel == {"telegram": "chat-7", "web_sim": None}


@decision(93)
async def test_drop_unsent_removes_only_that_identitys_unsent_replies(store: Store) -> None:
    mine, other = await new_fan(store, "u1"), await new_fan(store, "u2")
    async with store.transaction() as tx:
        await tx.record_event(event("start", msg_id="m1"), NOW, mine)
        await tx.record_event(event("start", msg_id="m2", user="u2"), NOW, other)
        sent = await tx.add_reply(mine, "telegram", "m1", _reply(), NOW)
        await tx.mark_sent([sent])
        await tx.add_reply(mine, "telegram", "m1", _reply(), NOW)
        kept = await tx.add_reply(other, "telegram", "m2", _reply(), NOW)
    async with store.transaction() as tx:
        assert await tx.drop_unsent("telegram", "u1") == 1
        assert await tx.drop_unsent("telegram", "nobody") == 0
        await tx.set_opted_out("telegram", "nobody", True)
    assert sorted(r.id for r in await store.replies()) == [sent, kept]


@decision(71)
async def test_ping_succeeds_on_a_reachable_store(store: Store) -> None:
    await store.ping()
