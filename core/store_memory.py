"""In-memory fake of the store contract. Same behaviour as Postgres, so tests run on both.

A transaction mutates shared tables directly and keeps an undo log for rollback. The identity
lock and the reply claim set are held until the transaction ends, like `FOR UPDATE` and
`SKIP LOCKED`.
"""

import asyncio
from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any, cast

from core.catalog import BUDGET_OPTIONS, GROUP_OPTIONS, VENUES, Venue
from core.flow import FLOW_ID
from core.store import (
    SNAPSHOT_COLUMNS,
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
        return sorted(self._t.replies.values(), key=lambda r: r.id)

    async def funnel_counts(self) -> dict[str, int]:
        return dict(self._t.funnel)


class _MemoryTx:
    def __init__(self, tables: _Tables) -> None:
        self._t = tables
        self._undo: list[Callable[[], None]] = []
        self._locks: list[asyncio.Lock] = []
        self._claims: set[int] = set()

    def rollback(self) -> None:
        for undo in reversed(self._undo):
            undo()
        self._undo.clear()

    def release(self) -> None:
        self._t.claimed -= self._claims
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

    async def record_event(self, event: InboundEvent, now: datetime) -> bool:
        key = (event.channel, event.external_msg_id)
        if key in self._t.events:
            return False
        row = EventRow(*key, None, "in", event_payload(event), now)
        self._put(self._t.events, key, row)
        return True

    async def unsent_replies(self, channel: str, external_msg_id: str) -> list[ReplyRow]:
        rows = self._t.replies.values()
        return sorted(
            (
                r
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

    async def load_fan(self, fan_id: int) -> FanRow:
        return self._t.fans[fan_id]

    async def load_session(self, fan_id: int) -> SessionRow:
        return self._t.sessions[fan_id]

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

    async def claim_unsent(self, older_than: datetime, limit: int) -> list[ReplyRow]:
        free = (
            r
            for r in sorted(self._t.replies.values(), key=lambda r: r.id)
            if r.status == "unsent" and r.ts < older_than and r.id not in self._t.claimed
        )
        rows = [row for _, row in zip(range(limit), free, strict=False)]
        self._t.claimed |= {r.id for r in rows}
        self._claims |= {r.id for r in rows}
        return rows

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
