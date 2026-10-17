"""Shared test helpers: event builders, the `@decision` marker, the scenario YAML loader."""

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import yaml
from _pytest.mark import MarkDecorator

from core.decide import decide
from core.types import Decision, EventKind, FanState, InboundEvent

ROOT = Path(__file__).resolve().parent.parent
SCENARIOS = ROOT / "testing" / "scenarios"
NOW = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)
ARTIST = "Artist X"


def decision(*numbers: int) -> MarkDecorator:
    """Tag a test with the docs/decisions.md numbers it proves (checked by Q-10)."""
    return pytest.mark.decision(*numbers)


def event(
    kind: EventKind,
    *,
    text: str | None = None,
    choice_id: str | None = None,
    choice_step: str | None = None,
    source_tag: str | None = None,
    msg_id: str = "m1",
    user: str = "u1",
    channel: str = "telegram",
    ts: datetime = NOW,
) -> InboundEvent:
    return InboundEvent(
        channel=channel,
        external_user_id=user,
        external_msg_id=msg_id,
        kind=kind,
        ts=ts,
        text=text,
        choice_id=choice_id,
        choice_step=choice_step,
        source_tag=source_tag,
    )


def step(
    state: FanState,
    kind: EventKind,
    *,
    can_push: bool = True,
    now: datetime = NOW,
    **kwargs: Any,
) -> Decision:
    return decide(state, event(kind, **kwargs), now, artist=ARTIST, can_push=can_push)


def start(state: FanState) -> Decision:
    return step(state, "start")


def choose(state: FanState, choice_id: str, *, step_id: str | None = None) -> Decision:
    return step(state, "choice", choice_id=choice_id, choice_step=step_id or state.step_id)


def say(state: FanState, text: str) -> Decision:
    return step(state, "text", text=text)


def walk(state: FanState, *moves: tuple[str, str]) -> FanState:
    """Apply ("choice" | "text", value) moves in order and return the final state."""
    for kind, value in moves:
        decision_ = choose(state, value) if kind == "choice" else say(state, value)
        state = decision_.state
    return state


FULL_FLOW = (
    ("choice", "yes"),
    ("choice", "Pune"),
    ("choice", "8"),
    ("choice", "1500_3000"),
    ("choice", "3_5"),
    ("choice", "skip"),
)


def finished_fan() -> FanState:
    """A fan who has just reached `done` in Pune at Baner Greens."""
    return walk(start(FanState()).state, *FULL_FLOW)


class ScenarioLoader(yaml.SafeLoader):
    """SafeLoader that keeps `1500_3000` and `3_5` as strings (YAML 1.1 reads them as ints)."""


ScenarioLoader.yaml_implicit_resolvers = {
    key: [(tag, rx) for tag, rx in resolvers if tag != "tag:yaml.org,2002:int"]
    for key, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}
ScenarioLoader.add_implicit_resolver(
    "tag:yaml.org,2002:int", re.compile(r"^[-+]?(?:0|[1-9][0-9]*)$"), list("-+0123456789")
)


def load_yaml(name: str) -> Any:
    return yaml.load((SCENARIOS / name).read_text(encoding="utf-8"), Loader=ScenarioLoader)


DECISIONS_FILE = ROOT / "docs" / "decisions.md"


def venue_table() -> list[tuple[str, str, int]]:
    """(city, venue, capacity) rows parsed from the venue table in docs/decisions.md."""
    text = DECISIONS_FILE.read_text(encoding="utf-8")
    section = text.split("### Venue table", 1)[1].split("\n---", 1)[0]
    rows = []
    for line in section.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) == 3 and cells[2].replace(",", "").isdigit():
            rows.append((cells[0], cells[1], int(cells[2].replace(",", ""))))
    return rows
