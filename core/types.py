"""Adapter contract (docs/architecture.md §3) and the values `decide` consumes and returns."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

EventKind = Literal["text", "choice", "start", "stop", "delete", "help"]
Expects = Literal["choice", "free_text", "none"]

ANSWER_FIELDS = ("city", "venue", "venue_note", "budget_band", "group_size", "email")


@dataclass(frozen=True)
class Option:
    id: str
    label: str


@dataclass(frozen=True, kw_only=True)
class InboundEvent:
    channel: str
    external_user_id: str
    external_msg_id: str
    kind: EventKind
    ts: datetime
    text: str | None = None
    choice_id: str | None = None
    choice_step: str | None = None
    source_tag: str | None = None


@dataclass(frozen=True)
class Reply:
    text: str
    step_id: str
    options: tuple[Option, ...] | None = None
    expects: Expects = "none"
    is_error: bool = False


@dataclass(frozen=True)
class FanState:
    """What `decide` knows about a fan; the engine rebuilds it from rows each turn."""

    step_id: str = "consent"
    consent: bool | None = None
    opted_out: bool = False
    answers: Mapping[str, str] = field(default_factory=dict)
    completed: bool = False
    furthest_step: str | None = None


@dataclass(frozen=True)
class SaveAnswer:
    field: str
    value: str | None


@dataclass(frozen=True)
class SetConsent:
    value: bool | None


@dataclass(frozen=True)
class SetOptedOut:
    value: bool


@dataclass(frozen=True)
class MarkCompleted:
    at: datetime


@dataclass(frozen=True)
class DeleteFan:
    pass


Write = SaveAnswer | SetConsent | SetOptedOut | MarkCompleted | DeleteFan


@dataclass(frozen=True)
class Decision:
    state: FanState
    replies: tuple[Reply, ...] = ()
    writes: tuple[Write, ...] = ()
