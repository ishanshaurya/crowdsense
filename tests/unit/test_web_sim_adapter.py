"""Web chat adapter (P3-U01, P3-U02) and the per-IP rate limiter (#99)."""

from typing import Any

import pytest

from adapters.telegram import parse_update, render_reply
from adapters.web_sim import CAPABILITIES, CHANNEL, WebSimAdapter, parse_body
from adapters.web_sim import render_reply as render_web
from api.ratelimit import RateLimiter, client_ip
from core.types import InboundEvent, Option, Reply
from tests.component.telegram_fake import text_update
from tests.support import NOW, decision

USER = "web-fan-0001"


def body(**fields: Any) -> dict[str, Any]:
    return {"user": USER, "msg_id": "m1", **fields}


@decision(4)
def test_p3_u01_parse_gives_the_same_event_type_as_telegram() -> None:
    web = parse_body(body(kind="text", text="hello"), NOW)
    telegram = parse_update(text_update("hello"), NOW)
    assert web is not None and telegram is not None
    assert type(web.event) is type(telegram.event) is InboundEvent
    assert web.event is not None and telegram.event is not None
    assert (web.event.kind, web.event.text) == (telegram.event.kind, telegram.event.text)
    assert web.event.channel == CHANNEL
    assert web.event.external_user_id == USER


@decision(4)
def test_p3_u01_choice_and_start_carry_the_core_ids() -> None:
    choice = parse_body(body(kind="choice", choice_step="city", choice_id="pune"), NOW)
    assert choice is not None and choice.event is not None
    assert (choice.event.kind, choice.event.choice_step, choice.event.choice_id) == (
        "choice",
        "city",
        "pune",
    )
    start = parse_body(body(kind="start", src="ig_story"), NOW)
    assert start is not None and start.event is not None
    assert (start.event.kind, start.event.source_tag) == ("start", "ig_story")


@decision(4)
@pytest.mark.parametrize(
    ("text", "kind", "tag"),
    [
        ("/start", "start", None),
        ("/start poster", "start", "poster"),
        ("/STOP", "stop", None),
        ("/delete", "delete", None),
        ("/help", "help", None),
        ("/foo", "text", None),
    ],
)
def test_p3_u01_typed_commands_map_like_telegram(text: str, kind: str, tag: str | None) -> None:
    inbound = parse_body(body(kind="text", text=text), NOW)
    assert inbound is not None and inbound.event is not None
    assert (inbound.event.kind, inbound.event.source_tag) == (kind, tag)


@decision(4)
def test_p3_u01_render_uses_the_core_reply_and_option_ids() -> None:
    reply = Reply("Which city?", "city", (Option("pune", "Pune"),), "choice")
    assert render_web(reply) == {
        "text": "Which city?",
        "step_id": "city",
        "expects": "choice",
        "options": [{"id": "pune", "label": "Pune"}],
    }
    assert render_reply(reply)["text"] == render_web(reply)["text"]  # same Reply in, same text
    assert render_web(Reply("Bye", "done"))["options"] == []


@decision(4, 87)
def test_p3_u02_capabilities_buttons_and_no_push() -> None:
    adapter = WebSimAdapter()
    assert adapter.channel == CHANNEL
    assert adapter.capabilities is CAPABILITIES
    assert CAPABILITIES.buttons and CAPABILITIES.max_buttons >= 10
    assert not CAPABILITIES.can_push_anytime and not CAPABILITIES.has_phone
    assert adapter.authorized({})


@pytest.mark.parametrize(
    "bad",
    [
        None,
        [],
        "x",
        {"user": USER, "msg_id": "m1"},
        body(kind="nope"),
        body(kind="text"),
        body(kind="text", text=""),
        body(kind="text", text=5),
        body(kind="start", src=7),
        body(kind="choice", choice_step="city"),
        body(kind="choice", choice_step="c" * 65, choice_id="pune"),
        {"user": "short", "msg_id": "m1", "kind": "start"},
        {"user": USER + "!", "msg_id": "m1", "kind": "start"},
        {"user": USER, "msg_id": "m 1", "kind": "start"},
        {"user": USER, "msg_id": "m" * 65, "kind": "start"},
    ],
)
def test_p3_u01_malformed_bodies_are_none_never_raise(bad: Any) -> None:
    assert parse_body(bad, NOW) is None


def test_the_client_clock_is_ignored() -> None:
    inbound = parse_body(body(kind="text", text="hi", ts="1999-01-01T00:00:00Z"), NOW)
    assert inbound is not None and inbound.event is not None and inbound.event.ts == NOW


async def test_web_chat_cannot_push() -> None:
    adapter = WebSimAdapter()
    with pytest.raises(Exception, match="cannot push"):
        await adapter.send(USER, Reply("hi", "done"))


@decision(99)
def test_rate_limit_allows_a_burst_then_refills() -> None:
    now = [0.0]
    limiter = RateLimiter(capacity=3, per_second=1.0, clock=lambda: now[0])
    assert [limiter.hit("ip") for _ in range(3)] == [0.0, 0.0, 0.0]
    assert limiter.hit("ip") == pytest.approx(1.0)
    assert limiter.hit("other") == 0.0  # per key
    now[0] = 1.0
    assert limiter.hit("ip") == 0.0


@decision(99)
def test_rate_limit_memory_stays_bounded() -> None:
    now = [0.0]
    limiter = RateLimiter(capacity=2, per_second=1.0, max_keys=3, clock=lambda: now[0])
    for i in range(10):
        now[0] = float(i) / 100
        limiter.hit(f"ip{i}")
        assert len(limiter) <= 3
    now[0] = 100.0  # every bucket refilled: idle ones are dropped first
    limiter.hit("fresh")
    assert len(limiter) == 1


@decision(99)
@pytest.mark.parametrize(
    ("forwarded", "peer", "expected"),
    [
        ("", "203.0.113.5", "203.0.113.5"),
        ("198.51.100.1", "203.0.113.5", "203.0.113.5"),  # XFF from a non-local peer: ignored
        ("198.51.100.1", "127.0.0.1", "198.51.100.1"),
        ("6.6.6.6, 198.51.100.1", "127.0.0.1", "198.51.100.1"),  # forged first entry ignored
        ("6.6.6.6, 198.51.100.1", "::1", "198.51.100.1"),
        ("   ", "127.0.0.1", "127.0.0.1"),
        ("", None, "unknown"),
    ],
)
def test_client_ip_trusts_only_the_last_hop_from_ngrok(
    forwarded: str, peer: str | None, expected: str
) -> None:
    headers = {"x-forwarded-for": forwarded} if forwarded else {}
    assert client_ip(headers, peer) == expected
