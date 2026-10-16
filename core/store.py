"""Conversation store contract (#54): one interface, an in-memory fake and a Postgres store.

Both implementations run the same contract suite. Callers pass every timestamp in, so the
store never reads the clock (#56).
"""

from collections.abc import Collection, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Protocol

from core.catalog import Venue
from core.types import InboundEvent, Option, Reply

# Answer field -> column on `fans` (the snapshot, #12).
SNAPSHOT_COLUMNS = {
    "city": "city",
    "venue": "venue_id",
    "venue_note": "venue_note",
    "budget_band": "budget_band",
    "group_size": "group_size",
    "email": "email",
}


class IntegrityViolation(Exception):
    """A CHECK or foreign key rejected a write."""


class StoreUnavailable(Exception):
    """The database cannot be reached; the webhook answers 5xx so the channel retries (#71)."""


@dataclass(frozen=True)
class FanRow:
    id: int
    city: str | None
    venue_id: int | None
    venue_note: str | None
    budget_band: str | None
    group_size: str | None
    email: str | None
    is_simulated: bool
    completed_at: datetime | None
    furthest_step: str | None
    created_at: datetime
    last_seen: datetime


@dataclass(frozen=True)
class IdentityRow:
    channel: str
    external_user_id: str
    fan_id: int | None
    source_tag: str | None
    consent: bool | None
    opted_out: bool
    can_message_until: datetime | None


@dataclass(frozen=True)
class SessionRow:
    fan_id: int
    flow_id: str
    step_id: str
    updated_at: datetime


@dataclass(frozen=True)
class AnswerRow:
    id: int
    fan_id: int
    field: str
    value: str | None
    ts: datetime


@dataclass(frozen=True)
class EventRow:
    channel: str
    external_msg_id: str
    fan_id: int | None
    direction: str
    payload: dict[str, Any]
    ts: datetime


@dataclass(frozen=True)
class ReplyRow:
    id: int
    fan_id: int
    channel: str
    external_msg_id: str
    reply: Reply
    status: str
    ts: datetime
    external_user_id: str | None = None  # the fan's identity on `channel`, for resends (#72)
    priority: int = 0  # 0 = chat reply, 1 = announcement; chat replies are claimed first


@dataclass(frozen=True)
class AnnouncementRow:
    """A pending `announcement_requests` row: the only fields the dashboard can set (#80)."""

    id: int
    city: str
    event_date: date


class Tx(Protocol):
    async def record_event(
        self, event: InboundEvent, now: datetime, fan_id: int | None = None
    ) -> bool:
        """Insert the inbound event; False when `(channel, external_msg_id)` already exists."""
        ...

    async def unsent_replies(self, channel: str, external_msg_id: str) -> list[ReplyRow]: ...

    async def lock_identity(
        self, channel: str, external_user_id: str, source_tag: str | None
    ) -> IdentityRow:
        """Create the identity if missing, then lock it until the transaction ends (#88)."""
        ...

    async def create_fan(
        self, channel: str, external_user_id: str, *, is_simulated: bool, now: datetime
    ) -> int:
        """Create the fan and its session, and attach the fan to the locked identity."""
        ...

    async def link_event(self, channel: str, external_msg_id: str, fan_id: int) -> None: ...

    async def load_state(self, fan_id: int) -> tuple[FanRow, SessionRow]: ...

    async def record_answer(
        self, fan_id: int, field: str, value: str | None, now: datetime
    ) -> None:
        """Append to `answers` and overwrite the `fans` snapshot together."""
        ...

    async def set_consent(
        self, channel: str, external_user_id: str, value: bool | None
    ) -> None: ...

    async def set_opted_out(self, channel: str, external_user_id: str, value: bool) -> None: ...

    async def save_progress(
        self, fan_id: int, step_id: str, furthest_step: str | None, now: datetime
    ) -> None: ...

    async def mark_completed(self, fan_id: int, at: datetime) -> None:
        """Set `completed_at` once; later calls keep the first value (#70)."""
        ...

    async def add_reply(
        self, fan_id: int, channel: str, external_msg_id: str, reply: Reply, now: datetime
    ) -> int: ...

    async def mark_sent(self, reply_ids: Sequence[int]) -> None: ...

    async def claim_unsent(
        self, older_than: datetime, limit: int, channels: Collection[str] | None = None
    ) -> list[ReplyRow]:
        """Claim unsent replies no other open transaction holds (`SKIP LOCKED`, #72)."""
        ...

    async def drop_unsent(self, channel: str, external_user_id: str) -> int:
        """Delete the identity's unsent replies, so nothing retries a fan who blocked us (#93)."""
        ...

    async def bump_funnel(self, step_id: str) -> None: ...

    async def claim_announcement(self) -> AnnouncementRow | None:
        """Claim the oldest pending request no other open transaction holds (`SKIP LOCKED`)."""
        ...

    async def fan_out(self, request_id: int, city: str, reply: Reply, now: datetime) -> int:
        """Queue `reply` once per fan in the city's audience (#85); returns how many were new.

        Each fan gets an outbound event and an unsent priority-1 reply; a fan already queued
        for this request is skipped, so a rerun adds nothing.
        """
        ...

    async def finish_announcement(
        self, request_id: int, recipients: int, now: datetime
    ) -> None: ...

    async def delete_fan(self, fan_id: int) -> None:
        """Remove the fan with its identities, sessions, answers, events and replies (#81)."""
        ...


class Store(Protocol):
    def transaction(self) -> AbstractAsyncContextManager[Tx]: ...

    async def ping(self) -> None:
        """Raise `StoreUnavailable` when the database cannot be reached."""
        ...

    async def close(self) -> None: ...

    async def venues(self) -> list[Venue]: ...

    async def fans(self) -> list[FanRow]: ...

    async def identities(self) -> list[IdentityRow]: ...

    async def sessions(self) -> list[SessionRow]: ...

    async def answers(self) -> list[AnswerRow]: ...

    async def events(self) -> list[EventRow]: ...

    async def replies(self) -> list[ReplyRow]: ...

    async def funnel_counts(self) -> dict[str, int]: ...


def event_payload(event: InboundEvent) -> dict[str, Any]:
    return {
        "external_user_id": event.external_user_id,
        "kind": event.kind,
        "text": event.text,
        "choice_id": event.choice_id,
        "choice_step": event.choice_step,
        "source_tag": event.source_tag,
        "ts": event.ts.isoformat(),
    }


def reply_to_json(reply: Reply) -> dict[str, Any]:
    options = None
    if reply.options is not None:
        options = [{"id": o.id, "label": o.label} for o in reply.options]
    return {
        "text": reply.text,
        "step_id": reply.step_id,
        "options": options,
        "expects": reply.expects,
        "is_error": reply.is_error,
    }


def reply_from_json(data: dict[str, Any]) -> Reply:
    options = data["options"]
    return Reply(
        text=data["text"],
        step_id=data["step_id"],
        options=None if options is None else tuple(Option(o["id"], o["label"]) for o in options),
        expects=data["expects"],
        is_error=data["is_error"],
    )
