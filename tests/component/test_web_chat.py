"""Web chat over ASGI on both stores: routes (#77, #99, #100), parity (P3-C01, P3-C02, P3-C08)."""

from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import timedelta
from typing import Any

import pytest

from api.sweeper import Sweeper
from core.clock import ScriptedClock
from core.flow import APOLOGY_TEXT, DONE_NO_PUSH_TEXT, DONE_PUSH_TEXT
from core.store import Store, StoreUnavailable
from core.types import InboundEvent
from tests.component.telegram_fake import Fan, build_rig
from tests.component.web_fake import WebFan, WebRig, build_web_rig
from tests.scenario_runner import check_final_db, tables
from tests.support import ARTIST, decision, load_yaml

SCENARIOS = sorted(
    p.removesuffix(".yaml")
    for p in (
        "happy_path_pune.yaml",
        "duplicate_message.yaml",
        "decline_consent.yaml",
        "stop_command.yaml",
        "delete_command.yaml",
        "bad_input_then_ok.yaml",
        "other_venue.yaml",
        "returning_fan_edit.yaml",
        "email_validation.yaml",
        "edit_city_clears_venue.yaml",
    )
)


@pytest.fixture
async def rig(store: Store, clock: ScriptedClock) -> AsyncIterator[WebRig]:
    built = build_web_rig(store, clock)
    yield built
    await built.close()


async def play_web(fan: WebFan, scenario_id: str, *, stop_before: str | None = None) -> None:
    """`tests/scenario_runner.play`, but every turn goes through `POST /chat/message`."""
    scenario = load_yaml(f"{scenario_id}.yaml")
    if "setup" in scenario:
        setup = scenario["setup"]
        await play_web(fan, setup["scenario"], stop_before=setup.get("stop_before"))
    for turn in scenario["steps"]:
        send, expect = turn["send"], turn["expect"]
        response = await _send(fan, send)
        assert response.status_code == 200, response.text
        replies = response.json()["replies"]
        if expect.get("no_reply"):
            assert replies == []
        else:
            assert replies[-1]["step_id"] == expect["step"]
            if "options" in expect:
                assert [o["label"] for o in replies[-1]["options"]] == expect["options"]
            if "text_contains" in expect:
                assert expect["text_contains"] in replies[-1]["text"]
        if stop_before and expect.get("step") == stop_before:
            return


async def _send(fan: WebFan, send: dict[str, Any]) -> Any:
    kind, value, msg_id = send["kind"], send.get("value"), send.get("msg_id")
    if kind == "start":
        return await fan.start(send.get("source_tag"), msg_id)
    if kind in ("command", "text"):
        return await fan.say(value, msg_id)
    options = {o["label"]: o["id"] for o in (fan.buttons or {}).get("options", [])}
    step = (fan.buttons or fan.replies[-1])["step_id"]
    choice = options.get(value, value)  # an unknown value goes as is, like a forged tap
    return await fan.send(msg_id, kind="choice", choice_step=step, choice_id=choice)


@decision(4, 16)
@pytest.mark.parametrize("name", SCENARIOS)
async def test_p3_c01_every_scenario_through_the_web_chat(rig: WebRig, name: str) -> None:
    await play_web(WebFan(rig), name)
    await check_final_db(rig.store, load_yaml(f"{name}.yaml")["final_db"])
    assert {r.channel for r in await rig.store.replies()} <= {"web_sim"}


def _rows_of(rows: dict[str, list[dict[str, Any]]], fan_id: int) -> dict[str, list[Any]]:
    """One fan's rows without what differs by design: ids, channel, user and message ids."""
    drop = {"id", "fan_id", "channel", "external_user_id", "external_msg_id"}
    out: dict[str, list[Any]] = {}
    for table, table_rows in rows.items():
        mine = [r for r in table_rows if r.get("fan_id", r.get("id")) == fan_id]
        out[table] = [_without(r, drop) for r in mine]
    return out


def _without(row: dict[str, Any], drop: set[str]) -> dict[str, Any]:
    kept = {k: v for k, v in row.items() if k not in drop}
    if isinstance(kept.get("payload"), dict):  # events keep the parsed event, ids included
        # and its ts: Telegram's message date vs the web chat's receive time (client untrusted)
        kept["payload"] = _without(kept["payload"], drop | {"ts"})
    return kept


@decision(4, 87)
async def test_p3_c02_telegram_and_web_chat_write_the_same_rows(
    store: Store, clock: ScriptedClock
) -> None:
    scenario = load_yaml("happy_path_pune.yaml")
    tag = scenario["steps"][0]["send"]["source_tag"]
    labels = [t["send"]["value"] for t in scenario["steps"][1:]]
    telegram = build_rig(store, clock)
    fan = Fan(telegram)
    await fan.say(f"/start {tag}")
    for label in labels:
        await fan.tap(label)
    await telegram.close()
    web = build_web_rig(store, clock)
    web_fan = WebFan(web)
    await web_fan.start(tag)
    for label in labels:
        await web_fan.tap(label)
    await web.close()

    rows = await tables(store)
    by_channel = {i["channel"]: i["fan_id"] for i in rows["identities"]}
    via_telegram = _rows_of(rows, by_channel["telegram"])
    via_web = _rows_of(rows, by_channel["web_sim"])
    done = DONE_PUSH_TEXT.format(artist=ARTIST)
    for row in via_telegram["replies"]:  # the only intended difference: the Done text (#87)
        if row["reply"].text == done:
            row["reply"] = replace(row["reply"], text=DONE_NO_PUSH_TEXT)
    assert via_telegram["fans"] and via_telegram["events"]
    assert via_web == via_telegram


@decision(18, 76)
async def test_p3_c08_a_person_in_the_web_chat_is_a_real_fan(rig: WebRig) -> None:
    await play_web(WebFan(rig), "happy_path_pune")
    fans = await rig.store.fans()
    assert len(fans) == 1 and fans[0].is_simulated is False
    assert fans[0].completed_at is not None


@decision(87)
async def test_web_chat_done_text_promises_no_updates(rig: WebRig) -> None:
    fan = WebFan(rig)
    await play_web(fan, "happy_path_pune")
    assert fan.replies[-1]["text"] == DONE_NO_PUSH_TEXT


@decision(77)
@pytest.mark.parametrize(
    ("path", "kind"),
    [("/chat", "text/html"), ("/chat/app.js", "javascript"), ("/chat/app.css", "css")],
)
async def test_chat_page_files_carry_security_headers(rig: WebRig, path: str, kind: str) -> None:
    response = await rig.http.get(path)
    assert response.status_code == 200
    assert kind in response.headers["content-type"]
    assert "default-src 'self'" in response.headers["content-security-policy"]
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "no-referrer"


@decision(77)
async def test_web_chat_is_not_a_webhook_channel(rig: WebRig) -> None:
    response = await rig.http.post("/hook/web_sim", json={"user": "x"})
    assert response.status_code == 404


@pytest.mark.parametrize(
    "content",
    [b"not json", b"[]", b'{"kind": "start"}', b"[" * 2000 + b"]" * 2000],
    ids=["text", "list", "no-user", "deep"],
)
async def test_bad_body_is_400_and_nothing_is_stored(rig: WebRig, content: bytes) -> None:
    response = await rig.http.post("/chat/message", content=content)
    assert response.status_code == 400
    assert await rig.store.events() == []


async def test_body_over_the_cap_is_413_with_or_without_content_length(rig: WebRig) -> None:
    big = b'{"text": "' + b"x" * 5000 + b'"}'
    assert (await rig.http.post("/chat/message", content=big)).status_code == 413

    async def chunks() -> AsyncIterator[bytes]:  # no Content-Length: the stream is cut off
        for _ in range(10):
            yield b"x" * 1000

    assert (await rig.http.post("/chat/message", content=chunks())).status_code == 413
    assert await rig.store.events() == []


@decision(99)
async def test_rate_limit_is_429_with_retry_after_then_recovers(
    store: Store, clock: ScriptedClock
) -> None:
    rig = build_web_rig(store, clock, capacity=2)
    fan = WebFan(rig)
    assert (await rig.http.get("/chat")).status_code == 200  # page files count too
    assert (await fan.start()).status_code == 200
    limited = await fan.say("hello")
    assert limited.status_code == 429
    assert int(limited.headers["retry-after"]) >= 1
    rig.seconds[0] += 2
    assert (await fan.tap("Count me in")).status_code == 200
    await rig.close()


async def test_engine_bug_gives_one_apology_and_saves_nothing(
    rig: WebRig, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def broken(event: InboundEvent) -> None:
        raise RuntimeError("bug")

    monkeypatch.setattr(rig.engine, "handle", broken)
    response = await WebFan(rig).start()
    assert response.status_code == 200
    assert [r["text"] for r in response.json()["replies"]] == [APOLOGY_TEXT]
    assert await rig.store.replies() == []


async def test_database_down_is_503(rig: WebRig, monkeypatch: pytest.MonkeyPatch) -> None:
    async def down(event: InboundEvent) -> None:
        raise StoreUnavailable("down")

    monkeypatch.setattr(rig.engine, "handle", down)
    assert (await WebFan(rig).start()).status_code == 503


async def test_replies_are_marked_sent_after_the_response(rig: WebRig) -> None:
    await WebFan(rig).start()
    replies = await rig.store.replies()
    assert replies and {r.status for r in replies} == {"sent"}


@decision(72, 100)
async def test_sweeper_never_claims_web_chat_replies_and_expiry_does(rig: WebRig) -> None:
    fan = WebFan(rig)
    await fan.start()
    await rig.engine.handle(  # a turn whose mark_sent never ran
        InboundEvent(
            kind="text",
            channel="web_sim",
            external_user_id=fan.user,
            external_msg_id="lost1",
            ts=rig.clock.now(),
            text="hi",
        )
    )
    sweeper = Sweeper(rig.store, rig.engine, None, {"telegram": None}, rig.clock)  # type: ignore[arg-type]
    rig.clock.advance(timedelta(minutes=5))
    assert await sweeper.sweep_once() == 0
    assert await rig.chat.expire_unsent() == 0  # younger than 10 minutes
    rig.clock.advance(timedelta(minutes=6))
    assert await sweeper.sweep_once() == 0
    assert await rig.chat.expire_unsent() >= 1
    assert {r.status for r in await rig.store.replies()} == {"sent"}


@decision(100)
async def test_expiry_runs_at_most_once_a_minute(
    rig: WebRig, monkeypatch: pytest.MonkeyPatch
) -> None:
    runs: list[int] = []

    async def counted() -> int:
        runs.append(1)
        return 0

    monkeypatch.setattr(rig.chat, "expire_unsent", counted)
    fan = WebFan(rig)
    await fan.start()
    await fan.tap("Count me in")
    assert len(runs) == 1
    rig.seconds[0] += 61
    await fan.tap("Pune")
    assert len(runs) == 2
