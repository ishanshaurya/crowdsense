"""Postgres store (psycopg 3, parameterised SQL only).

Every query is a string literal (`LiteralString`), so mypy rejects any query built from data.
Connections come from an async pool with `prepare_threshold=None`, which the Supabase
transaction pooler needs (#67). A turn is about eight round trips: writes that touch two
tables share one statement through a CTE.
"""

from collections.abc import AsyncIterator, Collection, Sequence
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, LiteralString

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

from core.catalog import Venue
from core.flow import FLOW_ID
from core.store import (
    AnnouncementRow,
    AnswerRow,
    EventRow,
    FanRow,
    IdentityRow,
    IntegrityViolation,
    ReplyRow,
    SessionRow,
    StoreUnavailable,
    Tx,
    event_payload,
    reply_from_json,
    reply_to_json,
)
from core.types import InboundEvent, Reply

_FAN_COLUMNS: LiteralString = (
    "id, city, venue_id, venue_note, budget_band, group_size, email, "
    "is_simulated, completed_at, furthest_step, created_at, last_seen"
)
_SELECT_FANS: LiteralString = "SELECT " + _FAN_COLUMNS + " FROM fans"
_SELECT_STATE: LiteralString = (
    "SELECT " + _FAN_COLUMNS + ", s.flow_id, s.step_id, s.updated_at "
    "FROM fans f JOIN sessions s ON s.fan_id = f.id WHERE f.id = %s"
)
_SELECT_IDENTITIES: LiteralString = (
    "SELECT channel, external_user_id, fan_id, source_tag, consent, opted_out, "
    "can_message_until FROM identities"
)
_SELECT_REPLIES: LiteralString = (
    "SELECT r.id, r.fan_id, r.channel, r.external_msg_id, r.payload, r.status, r.ts, "
    "r.priority, i.external_user_id FROM replies r "
    "LEFT JOIN identities i ON i.fan_id = r.fan_id AND i.channel = r.channel"
)

# One statement appends to `answers` and overwrites the snapshot column (#12).
_ANSWER: LiteralString = (
    "WITH a AS (INSERT INTO answers (fan_id, field, value, ts) VALUES (%s, %s, %s, %s)) "
)
_SET_SNAPSHOT: dict[str, LiteralString] = {
    "city": _ANSWER + "UPDATE fans SET city = %s WHERE id = %s",
    "venue": _ANSWER + "UPDATE fans SET venue_id = %s WHERE id = %s",
    "venue_note": _ANSWER + "UPDATE fans SET venue_note = %s WHERE id = %s",
    "budget_band": _ANSWER + "UPDATE fans SET budget_band = %s WHERE id = %s",
    "group_size": _ANSWER + "UPDATE fans SET group_size = %s WHERE id = %s",
    "email": _ANSWER + "UPDATE fans SET email = %s WHERE id = %s",
}


class PostgresStore:
    """Opens its pool on first use; `close()` it on shutdown."""

    def __init__(
        self, dsn: str, *, min_size: int = 1, max_size: int = 10, timeout: float = 5.0
    ) -> None:
        self._pool = AsyncConnectionPool(
            dsn,
            min_size=min_size,
            max_size=max_size,
            timeout=timeout,
            kwargs={"prepare_threshold": None},
            open=False,
        )

    @asynccontextmanager
    async def _connection(self) -> AsyncIterator[psycopg.AsyncConnection[Any]]:
        try:
            await self._pool.open()
            async with self._pool.connection() as conn:
                yield conn
        except psycopg.OperationalError as exc:  # includes PoolTimeout
            raise StoreUnavailable(type(exc).__name__) from exc

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[Tx]:
        async with self._connection() as conn, conn.transaction():
            yield _PgTx(conn)

    async def ping(self) -> None:
        async with self._connection() as conn:
            await conn.execute("SELECT 1")

    async def close(self) -> None:
        await self._pool.close()

    async def _read(self, query: LiteralString) -> list[dict[str, Any]]:
        async with self._connection() as conn:
            cursor = await conn.cursor(row_factory=dict_row).execute(query)
            return await cursor.fetchall()

    async def venues(self) -> list[Venue]:
        rows = await self._read("SELECT id, city, name, capacity FROM venues ORDER BY id")
        return [Venue(**row) for row in rows]

    async def fans(self) -> list[FanRow]:
        rows = await self._read(_SELECT_FANS + " ORDER BY id")
        return [FanRow(**row) for row in rows]

    async def identities(self) -> list[IdentityRow]:
        rows = await self._read(_SELECT_IDENTITIES + " ORDER BY channel, external_user_id")
        return [IdentityRow(**row) for row in rows]

    async def sessions(self) -> list[SessionRow]:
        rows = await self._read("SELECT fan_id, flow_id, step_id, updated_at FROM sessions")
        return [SessionRow(**row) for row in rows]

    async def answers(self) -> list[AnswerRow]:
        rows = await self._read("SELECT id, fan_id, field, value, ts FROM answers ORDER BY id")
        return [AnswerRow(**row) for row in rows]

    async def events(self) -> list[EventRow]:
        rows = await self._read(
            "SELECT channel, external_msg_id, fan_id, direction, payload, ts FROM events"
        )
        return [EventRow(**row) for row in rows]

    async def replies(self) -> list[ReplyRow]:
        rows = await self._read(_SELECT_REPLIES + " ORDER BY r.id")
        return [_reply_row(row) for row in rows]

    async def funnel_counts(self) -> dict[str, int]:
        rows = await self._read("SELECT step_id, count FROM funnel_counts")
        return {row["step_id"]: row["count"] for row in rows}


def _reply_row(row: dict[str, Any]) -> ReplyRow:
    return ReplyRow(
        id=row["id"],
        fan_id=row["fan_id"],
        channel=row["channel"],
        external_msg_id=row["external_msg_id"],
        reply=reply_from_json(row["payload"]),
        status=row["status"],
        ts=row["ts"],
        external_user_id=row["external_user_id"],
        priority=row["priority"],
    )


def _fan_row(row: dict[str, Any]) -> FanRow:
    return FanRow(**{k: row[k] for k in FanRow.__dataclass_fields__})


class _PgTx:
    def __init__(self, conn: psycopg.AsyncConnection[Any]) -> None:
        self._conn = conn

    async def _run(
        self, query: LiteralString, params: Sequence[Any] = ()
    ) -> psycopg.AsyncCursor[dict[str, Any]]:
        cursor = self._conn.cursor(row_factory=dict_row)
        try:
            await cursor.execute(query, params)
        except psycopg.errors.IntegrityError as exc:
            raise IntegrityViolation(str(exc)) from exc
        return cursor

    async def record_event(
        self, event: InboundEvent, now: datetime, fan_id: int | None = None
    ) -> bool:
        cursor = await self._run(
            "INSERT INTO events (channel, external_msg_id, fan_id, direction, payload, ts) "
            "VALUES (%s, %s, %s, 'in', %s, %s) ON CONFLICT DO NOTHING",
            (event.channel, event.external_msg_id, fan_id, Jsonb(event_payload(event)), now),
        )
        return cursor.rowcount == 1

    async def unsent_replies(self, channel: str, external_msg_id: str) -> list[ReplyRow]:
        cursor = await self._run(
            _SELECT_REPLIES
            + " WHERE r.channel = %s AND r.external_msg_id = %s AND r.status = 'unsent'"
            + " ORDER BY r.id",
            (channel, external_msg_id),
        )
        return [_reply_row(row) for row in await cursor.fetchall()]

    async def lock_identity(
        self, channel: str, external_user_id: str, source_tag: str | None
    ) -> IdentityRow:
        # Known fans need one round trip. A new one is inserted first (#88); a second turn
        # for the same new fan blocks on that insert until the first commits.
        query = _SELECT_IDENTITIES + " WHERE channel = %s AND external_user_id = %s FOR UPDATE"
        row = await (await self._run(query, (channel, external_user_id))).fetchone()
        if row is None:
            await self._run(
                "INSERT INTO identities (channel, external_user_id, source_tag) "
                "VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                (channel, external_user_id, source_tag),
            )
            row = await (await self._run(query, (channel, external_user_id))).fetchone()
        return IdentityRow(**(row or {}))

    async def create_fan(
        self, channel: str, external_user_id: str, *, is_simulated: bool, now: datetime
    ) -> int:
        cursor = await self._run(
            "WITH f AS (INSERT INTO fans (is_simulated, created_at, last_seen) "
            "VALUES (%s, %s, %s) RETURNING id), "
            "s AS (INSERT INTO sessions (fan_id, flow_id, step_id, updated_at) "
            "SELECT id, %s, 'consent', %s FROM f), "
            "i AS (UPDATE identities SET fan_id = (SELECT id FROM f) "
            "WHERE channel = %s AND external_user_id = %s) "
            "SELECT id FROM f",
            (is_simulated, now, now, FLOW_ID, now, channel, external_user_id),
        )
        fan_id: int = (await cursor.fetchone() or {})["id"]
        return fan_id

    async def link_event(self, channel: str, external_msg_id: str, fan_id: int) -> None:
        await self._run(
            "UPDATE events SET fan_id = %s WHERE channel = %s AND external_msg_id = %s",
            (fan_id, channel, external_msg_id),
        )

    async def load_state(self, fan_id: int) -> tuple[FanRow, SessionRow]:
        # A separate statement after the identity lock, so it reads rows committed while
        # this turn waited for the lock.
        row = await (await self._run(_SELECT_STATE, (fan_id,))).fetchone() or {}
        session = SessionRow(row["id"], row["flow_id"], row["step_id"], row["updated_at"])
        return _fan_row(row), session

    async def record_answer(
        self, fan_id: int, field: str, value: str | None, now: datetime
    ) -> None:
        if field not in _SET_SNAPSHOT:
            raise IntegrityViolation(f"unknown answer field {field!r}")
        stored = int(value) if field == "venue" and value is not None else value
        await self._run(_SET_SNAPSHOT[field], (fan_id, field, value, now, stored, fan_id))

    async def set_consent(self, channel: str, external_user_id: str, value: bool | None) -> None:
        await self._run(
            "UPDATE identities SET consent = %s WHERE channel = %s AND external_user_id = %s",
            (value, channel, external_user_id),
        )

    async def set_opted_out(self, channel: str, external_user_id: str, value: bool) -> None:
        await self._run(
            "UPDATE identities SET opted_out = %s WHERE channel = %s AND external_user_id = %s",
            (value, channel, external_user_id),
        )

    async def save_progress(
        self, fan_id: int, step_id: str, furthest_step: str | None, now: datetime
    ) -> None:
        await self._run(
            "WITH s AS (UPDATE sessions SET step_id = %s, updated_at = %s WHERE fan_id = %s) "
            "UPDATE fans SET furthest_step = %s, last_seen = %s WHERE id = %s",
            (step_id, now, fan_id, furthest_step, now, fan_id),
        )

    async def mark_completed(self, fan_id: int, at: datetime) -> None:
        await self._run(
            "UPDATE fans SET completed_at = COALESCE(completed_at, %s) WHERE id = %s",
            (at, fan_id),
        )

    async def add_reply(
        self, fan_id: int, channel: str, external_msg_id: str, reply: Reply, now: datetime
    ) -> int:
        cursor = await self._run(
            "INSERT INTO replies (fan_id, channel, external_msg_id, payload, ts) "
            "VALUES (%s, %s, %s, %s, %s) RETURNING id",
            (fan_id, channel, external_msg_id, Jsonb(reply_to_json(reply)), now),
        )
        reply_id: int = (await cursor.fetchone() or {})["id"]
        return reply_id

    async def mark_sent(self, reply_ids: Sequence[int]) -> None:
        await self._run("UPDATE replies SET status = 'sent' WHERE id = ANY(%s)", (list(reply_ids),))

    async def claim_unsent(
        self, older_than: datetime, limit: int, channels: Collection[str] | None = None
    ) -> list[ReplyRow]:
        wanted = None if channels is None else list(channels)
        cursor = await self._run(
            _SELECT_REPLIES
            + " WHERE r.status = 'unsent' AND (r.priority > 0 OR r.ts < %s)"
            + " AND (%s::text[] IS NULL OR r.channel = ANY(%s::text[]))"
            + " ORDER BY r.priority, r.id LIMIT %s FOR UPDATE OF r SKIP LOCKED",
            (older_than, wanted, wanted, limit),
        )
        return [_reply_row(row) for row in await cursor.fetchall()]

    async def drop_unsent(self, channel: str, external_user_id: str) -> int:
        cursor = await self._run(
            "DELETE FROM replies r USING identities i "
            "WHERE i.channel = %s AND i.external_user_id = %s "
            "AND r.fan_id = i.fan_id AND r.channel = i.channel AND r.status = 'unsent'",
            (channel, external_user_id),
        )
        return cursor.rowcount

    async def claim_announcement(self) -> AnnouncementRow | None:
        cursor = await self._run(
            "SELECT id, city, event_date FROM announcement_requests WHERE status = 'pending' "
            "ORDER BY id LIMIT 1 FOR UPDATE SKIP LOCKED"
        )
        row = await cursor.fetchone()
        return None if row is None else AnnouncementRow(**row)

    async def fan_out(self, request_id: int, city: str, reply: Reply, now: datetime) -> int:
        # The event row comes first: `replies` has a foreign key to `events` (#47).
        event = Jsonb({"kind": "announcement", "request_id": request_id})
        await self._run(
            "INSERT INTO events (channel, external_msg_id, fan_id, direction, payload, ts) "
            "SELECT a.channel, 'ann-' || %s || '-' || a.fan_id, a.fan_id, 'out', %s, %s "
            "FROM announcement_audience(%s) a ON CONFLICT DO NOTHING",
            (request_id, event, now, city),
        )
        cursor = await self._run(
            "INSERT INTO replies "
            "(fan_id, channel, external_msg_id, payload, ts, priority, announcement_id) "
            "SELECT a.fan_id, a.channel, 'ann-' || %s || '-' || a.fan_id, %s, %s, 1, %s "
            "FROM announcement_audience(%s) a "
            "ON CONFLICT (announcement_id, fan_id) WHERE announcement_id IS NOT NULL DO NOTHING",
            (request_id, Jsonb(reply_to_json(reply)), now, request_id, city),
        )
        return cursor.rowcount

    async def finish_announcement(self, request_id: int, recipients: int, now: datetime) -> None:
        await self._run(
            "UPDATE announcement_requests "
            "SET status = 'fanned_out', recipients = %s, fanned_out_at = %s WHERE id = %s",
            (recipients, now, request_id),
        )

    async def bump_funnel(self, step_id: str) -> None:
        await self._run(
            "INSERT INTO funnel_counts (step_id, count) VALUES (%s, 1) "
            "ON CONFLICT (step_id) DO UPDATE SET count = funnel_counts.count + 1",
            (step_id,),
        )

    async def delete_fan(self, fan_id: int) -> None:
        await self._run("DELETE FROM fans WHERE id = %s", (fan_id,))
