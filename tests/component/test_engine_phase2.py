"""Engine additions for the webhook: `applied`, `opt_out_blocked`, StoreUnavailable."""

import pytest

from core.engine import Engine
from core.store import Store, StoreUnavailable
from core.store_postgres import PostgresStore
from tests.component.helpers import talk
from tests.support import decision, event


@decision(91, 92)
async def test_applied_is_true_for_a_taken_tap_and_false_for_a_stale_one(
    engine: Engine, store: Store
) -> None:
    await talk(engine, "u1", [("start", ""), ("choice", "yes")])
    taken = await engine.handle(event("choice", choice_id="Pune", choice_step="city", msg_id="t1"))
    stale = await engine.handle(event("choice", choice_id="Delhi", choice_step="city", msg_id="t2"))
    bad = await engine.handle(event("choice", choice_id="nope", choice_step="venue", msg_id="t3"))
    assert (taken.applied, stale.applied, bad.applied) == (True, False, False)
    assert [f.city for f in await store.fans()] == ["Pune"]


@decision(93)
async def test_opt_out_blocked_marks_the_identity_and_drops_unsent_replies(
    engine: Engine, store: Store
) -> None:
    await talk(engine, "u1", [("start", "")])
    await engine.handle(event("choice", choice_id="yes", choice_step="consent", msg_id="x1"))
    assert [r.status for r in await store.replies()] == ["sent", "unsent"]
    await engine.opt_out_blocked("telegram", "u1")
    await engine.opt_out_blocked("telegram", "never-seen")
    assert [i.opted_out for i in await store.identities()] == [True]
    assert [r.status for r in await store.replies()] == ["sent"]
    later = await engine.handle(event("text", text="hi", msg_id="x2"))
    assert later.replies == ()


@decision(71)
async def test_unreachable_database_raises_store_unavailable() -> None:
    store = PostgresStore("postgresql://nobody@127.0.0.1:1/none", timeout=0.5)
    try:
        with pytest.raises(StoreUnavailable):
            await store.ping()
        with pytest.raises(StoreUnavailable):
            async with store.transaction():
                pass
    finally:
        await store.close()
