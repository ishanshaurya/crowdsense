from datetime import timedelta

from core.clock import ScriptedClock
from core.engine import Engine
from core.store import Store
from tests.component.helpers import flow, talk
from tests.support import ARTIST, NOW, decision, event

PUNE = flow("Pune", "8", "1500_3000", "3_5")


@decision(11, 37)
async def test_p1_c03_same_external_id_on_two_channels_is_two_fans(
    engine: Engine, store: Store
) -> None:
    await talk(engine, "42", [("start", "")], channel="telegram")
    await talk(engine, "42", [("start", "")], channel="web_sim")
    keys = {(i.channel, i.external_user_id) for i in await store.identities()}
    assert keys == {("telegram", "42"), ("web_sim", "42")}
    fan_ids = {i.fan_id for i in await store.identities()}
    assert len(fan_ids) == 2 and len(await store.fans()) == 2


@decision(3)
async def test_p1_c04_source_tag_is_saved_at_first_contact_only(
    engine: Engine, store: Store
) -> None:
    await talk(engine, "u1", [("start", "ig_story"), ("start", "poster")])
    assert [i.source_tag for i in await store.identities()] == ["ig_story"]
    await talk(engine, "u2", [("start", "")])
    await talk(engine, "u2", [("start", "late_tag")])
    tags = {i.external_user_id: i.source_tag for i in await store.identities()}
    assert tags == {"u1": "ig_story", "u2": None}


@decision(12)
async def test_p1_c05_a_new_engine_resumes_at_the_saved_step(
    engine: Engine, store: Store, clock: ScriptedClock
) -> None:
    await talk(engine, "u1", PUNE[:4])
    restarted = Engine(store, clock, artist_name=ARTIST)
    result = await restarted.handle(event("start", msg_id="again"))
    assert result.replies[0].reply.step_id == "budget"
    assert [s.step_id for s in await store.sessions()] == ["budget"]


@decision(12)
async def test_p1_c06_edit_appends_an_answer_and_snapshot_matches_latest(
    engine: Engine, store: Store
) -> None:
    await talk(engine, "u1", [*PUNE, ("start", ""), ("choice", "budget"), ("choice", "3000_6000")])
    answers = await store.answers()
    assert [a.value for a in answers if a.field == "budget_band"] == ["1500_3000", "3000_6000"]
    (fan,) = await store.fans()
    latest = {a.field: a.value for a in answers}
    assert fan.budget_band == latest["budget_band"] == "3000_6000"
    assert str(fan.venue_id) == latest["venue"]
    assert (fan.city, fan.group_size) == (latest["city"], latest["group_size"])
    assert fan.completed_at == NOW


@decision(36, 81, 84)
async def test_p1_c07_delete_scrubs_the_fan_and_keeps_the_funnel_count(
    engine: Engine, store: Store
) -> None:
    await talk(engine, "u1", PUNE[:4])
    result = await talk(engine, "u1", [("choice", "x")])  # leaves an unsent-then-sent reply trail
    assert result is not None
    deleted = await engine.handle(event("delete", msg_id="bye"))
    assert [o.reply.step_id for o in deleted.replies] == ["deleted"]
    assert [o.id for o in deleted.replies] == [None]
    assert await store.fans() == [] and await store.identities() == []
    assert await store.sessions() == [] and await store.answers() == []
    assert await store.events() == [] and await store.replies() == []
    assert await store.funnel_counts() == {"budget": 1}


@decision(81, 84)
async def test_delete_of_a_fan_who_never_started_counts_nothing(
    engine: Engine, store: Store
) -> None:
    ev = event("delete", msg_id="bye")
    await engine.handle(ev)
    assert await store.funnel_counts() == {}
    assert await store.fans() == [] and await store.identities() == []


@decision(36)
async def test_p1_c08_opted_out_fan_is_resubscribed_by_start(engine: Engine, store: Store) -> None:
    await talk(engine, "u1", PUNE[:4])
    await engine.handle(event("stop", msg_id="s1"))
    assert [i.opted_out for i in await store.identities()] == [True]
    quiet = await engine.handle(event("text", text="hello", msg_id="s2"))
    assert quiet.replies == ()
    back = await engine.handle(event("start", msg_id="s3"))
    assert back.replies[0].reply.step_id == "budget"
    assert [i.opted_out for i in await store.identities()] == [False]


@decision(82)
async def test_p1_c14_simulated_engine_flags_the_fan_and_nothing_else(
    store: Store, clock: ScriptedClock
) -> None:
    real = Engine(store, clock, artist_name=ARTIST)
    simulated = Engine(store, clock, artist_name=ARTIST, simulated=True)
    await talk(real, "real", PUNE)
    await talk(simulated, "sim", PUNE)
    fans = {f.is_simulated: f for f in await store.fans()}
    assert set(fans) == {True, False}
    strip = lambda f: {k: v for k, v in vars(f).items() if k not in ("id", "is_simulated")}  # noqa: E731
    assert strip(fans[True]) == strip(fans[False])


@decision(70)
async def test_completed_at_is_set_once_and_survives_edits(
    engine: Engine, store: Store, clock: ScriptedClock
) -> None:
    await talk(engine, "u1", PUNE)
    clock.advance(timedelta(days=3))
    await talk(engine, "u1", [("start", ""), ("choice", "city"), ("choice", "Mumbai")])
    (fan,) = await store.fans()
    assert fan.completed_at == NOW
    assert (fan.city, fan.venue_id, fan.furthest_step) == ("Mumbai", None, "done")
    assert fan.last_seen == NOW + timedelta(days=3)
    assert [a.value for a in await store.answers() if a.field == "venue"] == ["8", None]


@decision(91)
async def test_stale_tap_is_ignored_through_the_engine(engine: Engine, store: Store) -> None:
    await talk(engine, "u1", PUNE[:4])
    before = await store.answers()
    result = await engine.handle(
        event("choice", choice_id="Mumbai", choice_step="city", msg_id="old-tap")
    )
    assert result.replies[0].reply.is_error
    assert await store.answers() == before


@decision(47)
async def test_replies_are_logged_unsent_until_marked_sent(engine: Engine, store: Store) -> None:
    result = await engine.handle(event("start", msg_id="m1"))
    assert [r.status for r in await store.replies()] == ["unsent"]
    await engine.mark_sent(result.replies)
    assert [r.status for r in await store.replies()] == ["sent"]
