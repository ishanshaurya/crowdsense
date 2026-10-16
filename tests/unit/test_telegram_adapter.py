"""Telegram adapter, no network (P2-U01 to P2-U11). Parse tests read recorded fixtures."""

import copy
from typing import Any

import pytest

from adapters.base import Inbound
from adapters.telegram import (
    CAPABILITIES,
    MAX_CALLBACK_BYTES,
    MAX_TEXT,
    callback_data,
    keyboard_rows,
    parse_update,
    render_reply,
)
from core import flow
from core.catalog import CITIES
from core.types import Option, Reply
from tests.component.telegram_fake import fixture, unhandled
from tests.support import NOW, decision

USER = "1000000001"


def parse(name: str) -> Inbound:
    inbound = parse_update(fixture(f"{name}.json"), NOW)
    assert inbound is not None, name
    return inbound


def with_text(name: str, text: str) -> dict[str, Any]:
    """A recorded command with its text swapped (no `/help@bot` update was recorded)."""
    update = copy.deepcopy(fixture(f"{name}.json"))
    update["message"]["text"] = text
    return update


@decision(3)
def test_p2_u01_start_with_a_tag() -> None:
    event = parse("start_with_tag").event
    assert event is not None
    assert (event.kind, event.source_tag, event.channel) == ("start", "ig_story", "telegram")
    assert event.external_user_id == USER and event.text is None


@decision(3)
def test_p2_u02_start_without_a_tag() -> None:
    event = parse("start_no_tag").event
    assert event is not None and event.kind == "start" and event.source_tag is None
    named = parse_update(with_text("start_with_tag", "/start@crowdsense_live_bot ig_story"), NOW)
    assert named and named.event and named.event.source_tag == "ig_story"


@decision(13, 92)
def test_p2_u03_button_tap_is_a_choice_with_the_tap_to_answer() -> None:
    inbound = parse("button_tap")
    assert inbound.event is not None
    assert (inbound.event.kind, inbound.event.choice_step, inbound.event.choice_id) == (
        "choice",
        "consent",
        "yes",
    )
    assert inbound.event.ts == NOW  # a callback query carries no date of its own
    assert inbound.tap is not None
    assert (inbound.tap.chat_id, inbound.tap.label) == (USER, "Count me in")
    assert inbound.tap.message_id is not None and inbound.tap.id


@decision(13)
def test_p2_u04_plain_text() -> None:
    event = parse("text").event
    assert event is not None and (event.kind, event.text) == ("text", "Hi")
    assert event.ts.tzinfo is not None


@decision(36)
@pytest.mark.parametrize("name", ["stop", "delete", "help"])
def test_p2_u05_commands(name: str) -> None:
    event = parse(name).event
    assert event is not None and event.kind == name
    named = parse_update(with_text(name, f"/{name}@crowdsense_live_bot"), NOW)
    assert named and named.event and named.event.kind == name


IGNORED = {
    "edited": fixture("edited_message.json"),
    "photo": fixture("photo.json"),
    "group": unhandled("group"),
    "empty": {},
    "bad_id": {"update_id": "1"},
    "no_chat": {"update_id": 1, "message": {"text": "no chat"}},
    "bad_tap": {"update_id": 1, "callback_query": {}},
    "member": {"update_id": 1, "my_chat_member": {}},
    "list": [],
    "none": None,
}


@decision(5)
@pytest.mark.parametrize("update", list(IGNORED.values()), ids=list(IGNORED))
def test_p2_u06_unhandled_updates_are_ignored_without_raising(update: Any) -> None:
    assert parse_update(update, NOW) is None


@decision(92)
def test_noop_and_malformed_taps_are_answered_but_reach_no_engine() -> None:
    noop = parse("tap_noop")
    assert noop.event is None and noop.tap is not None
    bad = copy.deepcopy(fixture("button_tap.json"))
    bad["callback_query"]["data"] = "no-colon"
    inbound = parse_update(bad, NOW)
    assert inbound is not None and inbound.event is None and inbound.tap is not None


@decision(20)
def test_p2_u07_options_render_as_inline_keyboard_rows() -> None:
    cities = tuple(Option(c, c) for c in CITIES)
    payload = render_reply(Reply("Which city?", "city", cities, "choice"))
    rows = payload["reply_markup"]["inline_keyboard"]
    assert [len(r) for r in rows] == [2, 2, 2, 2, 2]
    assert [b["text"] for r in rows for b in r] == list(CITIES)
    assert "parse_mode" not in payload
    groups = [len(r) for r in keyboard_rows(flow.step_options(flow.STEP_BY_ID["group"], {}) or ())]
    assert groups == [4]
    venues = flow.step_options(flow.STEP_BY_ID["venue"], {"city": "Mumbai"}) or ()
    assert all(len(r) == 1 for r in keyboard_rows(venues))
    plain = render_reply(Reply("x" * 5000, "done"))
    assert len(plain["text"]) == MAX_TEXT and "reply_markup" not in plain


def _every_step_option() -> list[tuple[str, Option]]:
    pairs = [("edit_menu", o) for o in flow.EDIT_OPTIONS]
    for step in flow.STEPS:
        for city in CITIES:
            pairs += [(step.id, o) for o in flow.step_options(step, {"city": city}) or ()]
    return pairs


@decision(5, 91)
def test_p2_u08_every_callback_value_fits_64_bytes() -> None:
    pairs = _every_step_option()
    assert len(pairs) > 30
    assert all(len(callback_data(s, o).encode()) <= MAX_CALLBACK_BYTES for s, o in pairs)
    with pytest.raises(ValueError, match="64 bytes"):
        callback_data("venue", Option("x" * 60, "Too long"))


@decision(41, 90)
def test_p2_u09_event_ids_are_stable_per_update_and_distinct_across_updates() -> None:
    names = ["start_with_tag", "start_no_tag", "button_tap", "tap_city", "text", "stop", "help"]
    ids = [parse(n).event.external_msg_id for n in names]  # type: ignore[union-attr]
    assert len(set(ids)) == len(ids)
    again = parse_update(fixture("button_tap.json"), NOW)
    assert again and again.event and again.event.external_msg_id == ids[2]


@decision(4)
def test_p2_u10_capabilities() -> None:
    assert CAPABILITIES.buttons and CAPABILITIES.max_buttons >= 10
    assert CAPABILITIES.has_phone is False
    assert CAPABILITIES.can_push_anytime is True


@decision(90, 91)
def test_p2_u11_tap_parse_splits_step_and_choice_and_uses_update_id() -> None:
    update = fixture("tap_city.json")
    event = parse("tap_city").event
    assert event is not None
    assert update["callback_query"]["data"] == "city:Pune"
    assert (event.choice_step, event.choice_id) == ("city", "Pune")
    assert event.external_msg_id == str(update["update_id"])
