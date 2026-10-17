"""In-memory fake of the store contract. Same behaviour as Postgres, so tests run on both.

A transaction mutates shared tables directly and keeps an undo log for rollback. The identity
lock and the reply claim set are held until the transaction ends, like `FOR UPDATE` and
`SKIP LOCKED`.
"""

import asyncio
from collections.abc import AsyncIterator, Callable, Collection, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from typing import Any, cast

from core.catalog import BUDGET_OPTIONS, GROUP_OPTIONS, VENUES, Venue
from core.flow import FLOW_ID
from core.store import (
    SNAPSHOT_COLUMNS,
    AnnouncementRow,
    AnswerRow,
    EventRow,
    FanRow,
    IdentityRow,
    IntegrityViolation,
    ReplyRow,
    SessionRow,
    Tx,
    event_payload,
)
from core.types import InboundEvent, Reply

_CHECKED_VALUES = {
    "budget_band": {o.id for o in BUDGET_OPTIONS},
    "group_size": {o.id for o in GROUP_OPTIONS},
}
_MISSING = object()


@dataclass
class _Tables:
    fans: dict[int, FanRow] = field(default_factory=dict)
    identities: dict[tuple[str, str], IdentityRow] = field(default_factory=dict)
    sessions: dict[int, SessionRow] = field(default_factory=dict)
    answers: dict[int, AnswerRow] = field(default_factory=dict)
    events: dict[tuple[str, str], EventRow] = field(default_factory=dict)
    replies: dict[int, ReplyRow] = field(default_factory=dict)
    funnel: dict[str, int] = field(default_factory=dict)
    identity_locks: dict[tuple[str, str], asyncio.Lock] = field(default_factory=dict)
    claimed: set[int] = field(default_factory=set)
    requests: dict[int, tuple[AnnouncementRow, str]] = field(default_factory=dict)  # row, status
    claimed_requests: set[int] = field(default_factory=set)
    last_id: int = 0

    def next_id(self) -> int:
        self.last_id += 1
        return self.last_id


class InMemoryStore:
    def __init__(self) -> None:
        self._t = _Tables()

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[Tx]:
        tx = _MemoryTx(self._t)
        await asyncio.sleep(0)  # a real store yields on I/O; keep interleaving honest
        try:
            yield tx
        except BaseException:
            tx.rollback()
            raise
        finally:
            tx.release()

    async def ping(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def venues(self) -> list[Venue]:
        return list(VENUES)

    async def fans(self) -> list[FanRow]:
        return sorted(self._t.fans.values(), key=lambda r: r.id)

    async def identities(self) -> list[IdentityRow]:
        return list(self._t.identities.values())

    async def sessions(self) -> list[SessionRow]:
        return list(self._t.sessions.values())

    async def answers(self) -> list[AnswerRow]:
        return sorted(self._t.answers.values(), key=lambda r: r.id)

    async def events(self) -> list[EventRow]:
        return list(self._t.events.values())

    async def replies(self) -> list[ReplyRow]:
        return [
            _with_user(self._t, r) for r in sorted(self._t.replies.values(), key=lambda r: r.id)
        ]

    async def funnel_counts(self) -> dict[str, int]:
        return dict(self._t.funnel)

    def request_announcement(self, city: str, event_date: date) -> int:
        """What the dashboard's INSERT does on Postgres; the fake has no dashboard role."""
        if any((r.city, r.event_date) == (city, event_date) for r, _ in self._t.requests.values()):
            raise IntegrityViolation(f"already requested: {city} {event_date}")
        request_id = self._t.next_id()
        self._t.requests[request_id] = (AnnouncementRow(request_id, city, event_date), "pending")
        return request_id

    def request_status(self, request_id: int) -> str:
        return self._t.requests[request_id][1]


def audience(t: _Tables, city: str) -> list[IdentityRow]:
    """The `announcement_audience` SQL rule (#85); the contract suite runs both stores."""
    return sorted(
        (
            i
            for i in t.identities.values()
            if i.fan_id is not None
            and i.channel == "telegram"
            and i.consent is True
            and not i.opted_out
            and (fan := t.fans.get(i.fan_id)) is not None
            and fan.city == city
            and fan.completed_at is not None
            and not fan.is_simulated
        ),
        key=lambda i: cast(int, i.fan_id),
    )


def _with_user(t: _Tables, row: ReplyRow) -> ReplyRow:
    user = next(
        (
            i.external_user_id
            for i in t.identities.values()
            if i.fan_id == row.fan_id and i.channel == row.channel
        ),
        None,
    )
    return replace(row, external_user_id=user)


class _MemoryTx:
    def __init__(self, tables: _Tables) -> None:
        self._t = tables
        self._undo: list[Callable[[], None]] = []
        self._locks: list[asyncio.Lock] = []
        self._claims: set[int] = set()
        self._request_claims: set[int] = set()

    def rollback(self) -> None:
        for undo in reversed(self._undo):
            undo()
        self._undo.clear()

    def release(self) -> None:
        self._t.claimed -= self._claims
        self._t.claimed_requests -= self._request_claims
        for lock in self._locks:
            lock.release()

    def _put[K, V](self, table: dict[K, V], key: K, value: V) -> None:
        old = table.get(key, _MISSING)
        table[key] = value

        def undo() -> None:
            if old is _MISSING:
                table.pop(key, None)
            else:
                table[key] = cast(V, old)

        self._undo.append(undo)

    def _pop[K, V](self, table: dict[K, V], key: K) -> None:
        if key in table:
            old = table.pop(key)
            self._undo.append(lambda: table.__setitem__(key, old))

    async def record_event(
        self, event: InboundEvent, now: datetime, fan_id: int | None = None
    ) -> bool:
        key = (event.channel, event.external_msg_id)
        if key in self._t.events:
            return False
        row = EventRow(*key, fan_id, "in", event_payload(event), now)
        self._put(self._t.events, key, row)
        return True

    async def unsent_replies(self, channel: str, external_msg_id: str) -> list[ReplyRow]:
        rows = self._t.replies.values()
        return sorted(
            (
                _with_user(self._t, r)
                for r in rows
                if (r.channel, r.external_msg_id) == (channel, external_msg_id)
                and r.status == "unsent"
            ),
            key=lambda r: r.id,
        )

    async def lock_identity(
        self, channel: str, external_user_id: str, source_tag: str | None
    ) -> IdentityRow:
        key = (channel, external_user_id)
        blank = IdentityRow(channel, external_user_id, None, source_tag, None, False, None)
        if key not in self._t.identities:
            self._put(self._t.identities, key, blank)
        lock = self._t.identity_locks.setdefault(key, asyncio.Lock())
        if lock not in self._locks:
            await lock.acquire()
            self._locks.append(lock)
        if key not in self._t.identities:  # the holder before us rolled back or deleted it
            self._put(self._t.identities, key, blank)
        return self._t.identities[key]

    async def create_fan(
        self, channel: str, external_user_id: str, *, is_simulated: bool, now: datetime
    ) -> int:
        fan_id = self._t.next_id()
        fan = FanRow(fan_id, None, None, None, None, None, None, is_simulated, None, None, now, now)
        self._put(self._t.fans, fan_id, fan)
        self._put(self._t.sessions, fan_id, SessionRow(fan_id, FLOW_ID, "consent", now))
        key = (channel, external_user_id)
        self._put(self._t.identities, key, replace(self._t.identities[key], fan_id=fan_id))
        return fan_id

    async def link_event(self, channel: str, external_msg_id: str, fan_id: int) -> None:
        key = (channel, external_msg_id)
        self._put(self._t.events, key, replace(self._t.events[key], fan_id=fan_id))

    async def load_state(self, fan_id: int) -> tuple[FanRow, SessionRow]:
        return self._t.fans[fan_id], self._t.sessions[fan_id]

    async def record_answer(
        self, fan_id: int, field: str, value: str | None, now: datetime
    ) -> None:
        self._check_answer(field, value)
        answer_id = self._t.next_id()
        self._put(self._t.answers, answer_id, AnswerRow(answer_id, fan_id, field, value, now))
        column = SNAPSHOT_COLUMNS[field]
        stored = int(value) if column == "venue_id" and value is not None else value
        changes: dict[str, Any] = {column: stored}
        self._put(self._t.fans, fan_id, replace(self._t.fans[fan_id], **changes))

    def _check_answer(self, field: str, value: str | None) -> None:
        if field not in SNAPSHOT_COLUMNS:
            raise IntegrityViolation(f"unknown answer field {field!r}")
        allowed = _CHECKED_VALUES.get(SNAPSHOT_COLUMNS[field])
        if value is not None and allowed is not None and value not in allowed:
            raise IntegrityViolation(f"{value!r} is not valid for {field}")
        if field == "venue" and value is not None and int(value) not in {v.id for v in VENUES}:
            raise IntegrityViolation(f"venue {value} does not exist")

    async def set_consent(self, channel: str, external_user_id: str, value: bool | None) -> None:
        key = (channel, external_user_id)
        self._put(self._t.identities, key, replace(self._t.identities[key], consent=value))

    async def set_opted_out(self, channel: str, external_user_id: str, value: bool) -> None:
        key = (channel, external_user_id)
        if key not in self._t.identities:  # like an UPDATE that matches no row
            return
        self._put(self._t.identities, key, replace(self._t.identities[key], opted_out=value))

    async def save_progress(
        self, fan_id: int, step_id: str, furthest_step: str | None, now: datetime
    ) -> None:
        session = replace(self._t.sessions[fan_id], step_id=step_id, updated_at=now)
        self._put(self._t.sessions, fan_id, session)
        fan = replace(self._t.fans[fan_id], furthest_step=furthest_step, last_seen=now)
        self._put(self._t.fans, fan_id, fan)

    async def mark_completed(self, fan_id: int, at: datetime) -> None:
        fan = self._t.fans[fan_id]
        if fan.completed_at is None:
            self._put(self._t.fans, fan_id, replace(fan, completed_at=at))

    async def add_reply(
        self, fan_id: int, channel: str, external_msg_id: str, reply: Reply, now: datetime
    ) -> int:
        reply_id = self._t.next_id()
        row = ReplyRow(reply_id, fan_id, channel, external_msg_id, reply, "unsent", now)
        self._put(self._t.replies, reply_id, row)
        return reply_id

    async def mark_sent(self, reply_ids: Sequence[int]) -> None:
        for reply_id in reply_ids:
            row = self._t.replies[reply_id]
            self._put(self._t.replies, reply_id, replace(row, status="sent"))

    async def claim_unsent(
        self, older_than: datetime, limit: int, channels: Collection[str] | None = None
    ) -> list[ReplyRow]:
        free = (
            _with_user(self._t, r)
            for r in sorted(self._t.replies.values(), key=lambda r: (r.priority, r.id))
            if r.status == "unsent"
            and (r.priority > 0 or r.ts < older_than)
            and r.id not in self._t.claimed
            and (channels is None or r.channel in channels)
        )
        rows = [row for _, row in zip(range(limit), free, strict=False)]
        self._t.claimed |= {r.id for r in rows}
        self._claims |= {r.id for r in rows}
        return rows

    async def drop_unsent(self, channel: str, external_user_id: str) -> int:
        identity = self._t.identities.get((channel, external_user_id))
        if identity is None or identity.fan_id is None:
            return 0
        doomed = [
            k
            for k, r in self._t.replies.items()
            if (r.fan_id, r.channel, r.status) == (identity.fan_id, channel, "unsent")
        ]
        for key in doomed:
            self._pop(self._t.replies, key)
        return len(doomed)

    async def claim_announcement(self) -> AnnouncementRow | None:
        for request_id, (row, status) in sorted(self._t.requests.items()):
            if status == "pending" and request_id not in self._t.claimed_requests:
                self._t.claimed_requests.add(request_id)
                self._request_claims.add(request_id)
                return row
        return None

    async def fan_out(self, request_id: int, city: str, reply: Reply, now: datetime) -> int:
        queued = {
            r.fan_id
            for r in self._t.replies.values()
            if r.external_msg_id.startswith(f"ann-{request_id}-")
        }
        added = 0
        for identity in audience(self._t, city):
            fan_id = cast(int, identity.fan_id)
            msg_id = f"ann-{request_id}-{fan_id}"
            key = (identity.channel, msg_id)
            if key not in self._t.events:
                payload = {"kind": "announcement", "request_id": request_id}
                self._put(self._t.events, key, EventRow(*key, fan_id, "out", payload, now))
            if fan_id in queued:
                continue
            reply_id = self._t.next_id()
            row = ReplyRow(
                reply_id, fan_id, identity.channel, msg_id, reply, "unsent", now, priority=1
            )
            self._put(self._t.replies, reply_id, row)
            added += 1
        return added

    async def finish_announcement(self, request_id: int, recipients: int, now: datetime) -> None:
        row, _ = self._t.requests[request_id]
        self._put(self._t.requests, request_id, (row, "fanned_out"))

    async def bump_funnel(self, step_id: str) -> None:
        self._put(self._t.funnel, step_id, self._t.funnel.get(step_id, 0) + 1)

    async def delete_fan(self, fan_id: int) -> None:
        t = self._t
        self._pop(t.fans, fan_id)
        self._pop(t.sessions, fan_id)
        for akey in [k for k, row in t.answers.items() if row.fan_id == fan_id]:
            self._pop(t.answers, akey)
        for rkey in [k for k, row in t.replies.items() if row.fan_id == fan_id]:
            self._pop(t.replies, rkey)
        for ikey in [k for k, row in t.identities.items() if row.fan_id == fan_id]:
            self._pop(t.identities, ikey)
        for ekey in [k for k, row in t.events.items() if row.fan_id == fan_id]:
            self._pop(t.events, ekey)
