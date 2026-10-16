"""Webhook with a fake Telegram (P2-C01 to P2-C13), on the fake store and Postgres (P2-C06)."""

import asyncio
import logging
import re
from collections.abc import AsyncIterator
from datetime import timedelta
from pathlib import Path

import pytest

from adapters.telegram import SECRET_HEADER
from core import engine as engine_module
from core.clock import ScriptedClock
from core.flow import APOLOGY_TEXT, STALE_TEXT, STEP_BY_ID
from core.store import Store
from tests.component.telegram_fake import (
    CHAT,
    SECRET,
    Fan,
    Rig,
    build_rig,
    error,
    tap_update,
    text_update,
    unhandled,
)
from tests.scenario_runner import check_final_db
from tests.support import decision, load_yaml


@pytest.fixture
async def rig(store: Store, clock: ScriptedClock) -> AsyncIterator[Rig]:
    built = build_rig(store, clock)
    yield built
    await built.close()


async def start(rig: Rig, tag: str = "ig_story") -> Fan:
    fan = Fan(rig)
    assert await fan.say(f"/start {tag}") == 200
    return fan


@decision(4, 5)
async def test_p2_c01_happy_path_pune_through_the_webhook_matches_phase_1(rig: Rig) -> None:
    scenario = load_yaml("happy_path_pune.yaml")
    fan = await start(rig, scenario["steps"][0]["send"]["source_tag"])
    for turn in scenario["steps"][1:]:
        assert await fan.tap(turn["send"]["value"]) == 200
    await check_final_db(rig.store, scenario["final_db"])
    assert len(rig.telegram.sent()) == len(scenario["steps"])
    assert {r.status for r in await rig.store.replies()} == {"sent"}


@decision(41, 66)
async def test_p2_c02_wrong_or_missing_secret_is_rejected_before_the_engine(rig: Rig) -> None:
    update = text_update("/start")
    assert await rig.post(update, headers={}) == 401
    wrong = {SECRET_HEADER: "wrong"}  # pragma: allowlist secret
    assert await rig.post(update, headers=wrong) == 401
    assert await rig.post(update, headers={SECRET_HEADER: SECRET[:-1]}) == 401
    assert await rig.post(update, headers={"X-Other": SECRET}) == 401
    assert await rig.store.events() == [] and await rig.store.identities() == []
    assert rig.telegram.calls == []


@decision(41, 55, 90)
async def test_p2_c03_same_update_twice_makes_one_set_of_rows_and_one_message(rig: Rig) -> None:
    update = text_update("/start ig_story")
    assert await rig.post(update) == 200
    assert await rig.post(update) == 200
    assert len(await rig.store.events()) == 1 and len(await rig.store.replies()) == 1
    assert len(rig.telegram.sent()) == 1


@decision(55, 90)
async def test_duplicate_update_sends_replies_that_were_never_sent(rig: Rig) -> None:
    rig.telegram.script["sendMessage"] = [error(500, "Internal Server Error")]
    update = text_update("/start")
    await rig.post(update)
    assert [r.status for r in await rig.store.replies()] == ["unsent"]
    await rig.post(update)
    assert [r.status for r in await rig.store.replies()] == ["sent"]
    assert len(rig.telegram.sent()) == 2


@decision(41, 71)
async def test_p2_c04_engine_error_returns_200_saves_nothing_and_apologises_once(
    rig: Rig, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def broken(*_: object, **__: object) -> None:
        raise RuntimeError("bug in decide")

    monkeypatch.setattr(engine_module, "decide", broken)
    with caplog.at_level(logging.ERROR, logger="crowdsense.webhook"):
        assert await rig.post(text_update("/start")) == 200
    assert await rig.store.events() == [] and await rig.store.fans() == []
    assert await rig.store.replies() == []
    assert [p["text"] for p in rig.telegram.sent()] == [APOLOGY_TEXT]
    (record,) = caplog.records
    assert re.search(r"cid=[0-9a-f]{12} ", record.getMessage()) and record.exc_info


@decision(5, 69)
async def test_p2_c05_outgoing_message_is_plain_text_with_the_replys_keyboard(rig: Rig) -> None:
    fan = await start(rig)
    await fan.tap("Count me in")
    city = rig.telegram.sent()[-1]
    assert set(city) == {"chat_id", "text", "reply_markup"}  # no parse_mode (#69)
    assert city["text"] == "Which city are you in?"
    rows = city["reply_markup"]["inline_keyboard"]
    buttons = [b for row in rows for b in row]
    assert [b["text"] for b in buttons][:2] == ["Mumbai", "Delhi NCR"]
    assert [b["callback_data"] for b in buttons][:2] == ["city:Mumbai", "city:Delhi NCR"]
    assert len(buttons) == 10 and all(len(row) <= 2 for row in rows)


@decision(55, 72)
async def test_p2_c07_failed_send_stays_unsent_until_the_sweeper_resends_it(rig: Rig) -> None:
    rig.telegram.script["sendMessage"] = [error(502, "Bad Gateway")]
    await start(rig)
    assert [r.status for r in await rig.store.replies()] == ["unsent"]
    rig.clock.advance(timedelta(seconds=11))
    assert await rig.sweeper.sweep_once() == 1
    assert [r.status for r in await rig.store.replies()] == ["sent"]
    assert len(rig.telegram.sent()) == 2
    assert await rig.sweeper.sweep_once() == 0


@decision(72)
async def test_p2_c08_sweeper_leaves_fresh_unsent_replies_alone(rig: Rig) -> None:
    rig.telegram.script["sendMessage"] = [error(500, "oops")]
    await start(rig)
    rig.clock.advance(timedelta(seconds=9))
    assert await rig.sweeper.sweep_once() == 0
    assert [r.status for r in await rig.store.replies()] == ["unsent"]
    assert len(rig.telegram.sent()) == 1


@decision(91, 92)
async def test_p2_c09_double_tap_applies_the_first_and_ignores_the_second(rig: Rig) -> None:
    fan = await start(rig)
    await fan.tap("Count me in")
    first = tap_update(fan.data_for("Pune"), fan.keyboard, message_id=fan.message_id)
    second = tap_update(fan.data_for("Pune"), fan.keyboard, message_id=fan.message_id)
    sent_before = len(rig.telegram.sent())
    assert await asyncio.gather(rig.post(first), rig.post(second)) == [200, 200]
    assert [f.city for f in await rig.store.fans()] == ["Pune"]
    assert len([a for a in await rig.store.answers() if a.field == "city"]) == 1
    texts = [p["text"] for p in rig.telegram.sent()[sent_before:]]
    assert texts == [STEP_BY_ID["venue"].prompt]  # one reply; no "That question has passed"
    assert {r.status for r in await rig.store.replies()} == {"sent"}  # the hidden one too
    assert rig.telegram.methods().count("editMessageReplyMarkup") == 2  # consent, city: no 2nd
    assert rig.telegram.methods().count("answerCallbackQuery") == 3


@decision(91)
async def test_p2_c10_tap_on_an_earlier_question_changes_nothing(rig: Rig) -> None:
    fan = await start(rig)
    consent_keyboard, consent_message = fan.keyboard, fan.message_id
    await fan.say("hello")  # re-asks consent in a new message; the first keeps its buttons
    await fan.tap("Count me in")
    await fan.tap("Pune")
    stale = tap_update("consent:no", consent_keyboard, message_id=consent_message)
    before = len(rig.telegram.calls)
    assert await rig.post(stale) == 200
    assert rig.telegram.calls[before:] == [
        ("answerCallbackQuery", {"callback_query_id": stale["callback_query"]["id"]}),  # no text
        ("sendMessage", {"chat_id": str(CHAT), "text": STALE_TEXT}),  # buttons left unchanged
    ]
    assert [i.consent for i in await rig.store.identities()] == [True]
    (session,) = await rig.store.sessions()
    assert session.step_id == "venue"


@decision(92)
async def test_p2_c11_tap_is_answered_first_then_buttons_become_a_check(rig: Rig) -> None:
    fan = await start(rig)
    message_id = fan.message_id
    before = len(rig.telegram.calls)
    await fan.tap("Count me in")
    methods = rig.telegram.methods()[before:]
    assert methods == ["answerCallbackQuery", "editMessageReplyMarkup", "sendMessage"]
    assert set(rig.telegram.calls[before][1]) == {"callback_query_id"}  # answered with no text
    edit = rig.telegram.calls[before + 1][1]
    assert edit["message_id"] == message_id
    assert edit["reply_markup"] == {
        "inline_keyboard": [[{"text": "✓ Count me in", "callback_data": "noop"}]]
    }


@decision(92)
async def test_noop_button_is_answered_and_never_reaches_the_engine(rig: Rig) -> None:
    fan = await start(rig)
    events_before = len(await rig.store.events())
    update = tap_update("noop", {"inline_keyboard": []}, message_id=fan.message_id)
    assert await rig.post(update) == 200
    assert rig.telegram.methods()[-1] == "answerCallbackQuery"
    assert len(await rig.store.events()) == events_before


@decision(69, 93)
async def test_p2_c12_rate_limit_waits_retry_after_then_resends(rig: Rig) -> None:
    statuses: list[list[str]] = []

    async def snapshot() -> None:
        statuses.append([r.status for r in await rig.store.replies()])

    rig.on_sleep = snapshot
    rig.telegram.script["sendMessage"] = [error(429, "Too Many Requests", retry_after=7)]
    await start(rig)
    assert rig.sleeps and min(rig.sleeps) >= 7
    assert statuses == [["unsent"]]  # still unsent while waiting
    assert [r.status for r in await rig.store.replies()] == ["sent"]
    assert len(rig.telegram.sent()) == 2


@decision(93)
async def test_p2_c13_blocked_bot_opts_the_identity_out_and_stops_sending(
    rig: Rig, caplog: pytest.LogCaptureFixture
) -> None:
    rig.telegram.script["sendMessage"] = [error(403, "Forbidden: bot was blocked by the user")]
    with caplog.at_level(logging.INFO, logger="crowdsense.sender"):
        await start(rig)
    assert "1 unsent replies dropped" in caplog.text
    assert [i.opted_out for i in await rig.store.identities()] == [True]
    assert await rig.store.replies() == []
    rig.clock.advance(timedelta(seconds=60))
    assert await rig.sweeper.sweep_once() == 0
    await rig.post(text_update("anyone there?"))
    assert len(rig.telegram.sent()) == 1  # only the blocked attempt


@decision(93)
async def test_p2_c13_sweeper_that_hits_a_block_drops_the_rest_after_its_commit(rig: Rig) -> None:
    rig.telegram.script["sendMessage"] = [error(500, "down"), error(403, "Forbidden")]
    await start(rig)
    rig.clock.advance(timedelta(seconds=11))
    assert await rig.sweeper.sweep_once() == 0  # finishes: no wait on its own row locks
    assert [i.opted_out for i in await rig.store.identities()] == [True]
    assert await rig.store.replies() == []


@decision(91, 92)
async def test_p2_c17_stale_tap_on_an_old_or_never_confirmed_message_says_passed(rig: Rig) -> None:
    fan = await start(rig)
    consent = (fan.keyboard, fan.message_id)
    await fan.tap("Count me in")
    city = (fan.keyboard, fan.message_id)
    await fan.tap("Pune")
    rig.seconds[0] += 61  # the consent and city confirmations are now older than 60 s
    for keyboard, message_id, data in ((*consent, "consent:yes"), (*city, "city:Delhi NCR")):
        assert await rig.post(tap_update(data, keyboard, message_id=message_id)) == 200
        assert rig.telegram.sent()[-1]["text"] == STALE_TEXT
    never = tap_update("city:Pune", city[0], message_id=999)  # a message we never confirmed
    rig.seconds[0] -= 61
    assert await rig.post(never) == 200
    assert rig.telegram.sent()[-1]["text"] == STALE_TEXT
    assert [f.city for f in await rig.store.fans()] == ["Pune"]


@decision(5)
@pytest.mark.parametrize("name", ["edited_message", "photo", "group", "not_json_object"])
async def test_unhandled_updates_get_200_and_touch_nothing(rig: Rig, name: str) -> None:
    update: object = [1, 2] if name == "not_json_object" else unhandled(name)
    assert await rig.post(update) == 200  # type: ignore[arg-type]
    assert await rig.store.events() == [] and rig.telegram.calls == []


def test_p2_c06_every_webhook_test_runs_on_both_backends(request: pytest.FixtureRequest) -> None:
    here = [
        i for i in request.session.items if i.path == Path(__file__) and "rig" in i.fixturenames
    ]
    names = {i.originalname for i in here}
    assert len(names) >= 14
    for name in names:
        backends = {i.callspec.params["store"] for i in here if i.originalname == name}
        assert backends == {"memory", "postgres"}, name
