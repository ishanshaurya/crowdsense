"""Postgres store (psycopg 3, parameterised SQL only).

Every query is a string literal (`LiteralString`), so mypy rejects any query built from data.
One connection per transaction; pooling arrives with the webhook (#67).
"""

from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, LiteralString

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from core.catalog import Venue
from core.flow import FLOW_ID
from core.store import (
    AnswerRow,
    EventRow,
    FanRow,
    IdentityRow,
    IntegrityViolation,
    ReplyRow,
    SessionRow,
    Tx,
    event_payload,
    reply_from_json,
    reply_to_json,
)
from core.types import InboundEvent, Reply

_SELECT_FANS: LiteralString = (
    "SELECT id, city, venue_id, venue_note, budget_band, group_size, email, "
    "is_simulated, completed_at, furthest_step, created_at, last_seen FROM fans"
)
_SELECT_IDENTITIES: LiteralString = (
    "SELECT channel, external_user_id, fan_id, source_tag, consent, opted_out, "
    "can_message_until FROM identities"
)
_SELECT_REPLIES: LiteralString = (
    "SELECT id, fan_id, channel, external_msg_id, payload, status, ts FROM replies"
)

_SET_SNAPSHOT: dict[str, LiteralString] = {
    "city": "UPDATE fans SET city = %s WHERE id = %s",
    "venue": "UPDATE fans SET venue_id = %s WHERE id = %s",
    "venue_note": "UPDATE fans SET venue_note = %s WHERE id = %s",
    "budget_band": "UPDATE fans SET budget_band = %s WHERE id = %s",
    "group_size": "UPDATE fans SET group_size = %s WHERE id = %s",
    "email": "UPDATE fans SET email = %s WHERE id = %s",
}


class PostgresStore:
    def __init__(self, dsn: str) -> None:
        self._dsn = dsn

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[Tx]:
        connection = await psycopg.AsyncConnection.connect(self._dsn, prepare_threshold=None)
        async with connection as conn, conn.transaction():
            yield _PgTx(conn)

    async def _read(self, query: LiteralString) -> list[dict[str, Any]]:
        async with await psycopg.AsyncConnection.connect(
            self._dsn, prepare_threshold=None, row_factory=dict_row
        ) as conn:
            cursor = await conn.execute(query)
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
        rows = await self._read(_SELECT_REPLIES + " ORDER BY id")
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
    )


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

    async def record_event(self, event: InboundEvent, now: datetime) -> bool:
        cursor = await self._run(
            "INSERT INTO events (channel, external_msg_id, direction, payload, ts) "
            "VALUES (%s, %s, 'in', %s, %s) ON CONFLICT DO NOTHING",
            (event.channel, event.external_msg_id, Jsonb(event_payload(event)), now),
        )
        return cursor.rowcount == 1

    async def unsent_replies(self, channel: str, external_msg_id: str) -> list[ReplyRow]:
        cursor = await self._run(
            _SELECT_REPLIES
            + " WHERE channel = %s AND external_msg_id = %s AND status = 'unsent' ORDER BY id",
            (channel, external_msg_id),
        )
        return [_reply_row(row) for row in await cursor.fetchall()]

    async def lock_identity(
        self, channel: str, external_user_id: str, source_tag: str | None
    ) -> IdentityRow:
        await self._run(
            "INSERT INTO identities (channel, external_user_id, source_tag) "
            "VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
            (channel, external_user_id, source_tag),
        )
        cursor = await self._run(
            _SELECT_IDENTITIES + " WHERE channel = %s AND external_user_id = %s FOR UPDATE",
            (channel, external_user_id),
        )
        return IdentityRow(**(await cursor.fetchone() or {}))

    async def create_fan(
        self, channel: str, external_user_id: str, *, is_simulated: bool, now: datetime
    ) -> int:
        cursor = await self._run(
            "INSERT INTO fans (is_simulated, created_at, last_seen) VALUES (%s, %s, %s) "
            "RETURNING id",
            (is_simulated, now, now),
        )
        fan_id: int = (await cursor.fetchone() or {})["id"]
        await self._run(
            "INSERT INTO sessions (fan_id, flow_id, step_id, updated_at) "
            "VALUES (%s, %s, 'consent', %s)",
            (fan_id, FLOW_ID, now),
        )
        await self._run(
            "UPDATE identities SET fan_id = %s WHERE channel = %s AND external_user_id = %s",
            (fan_id, channel, external_user_id),
        )
        return fan_id

    async def link_event(self, channel: str, external_msg_id: str, fan_id: int) -> None:
        await self._run(
            "UPDATE events SET fan_id = %s WHERE channel = %s AND external_msg_id = %s",
            (fan_id, channel, external_msg_id),
        )

    async def load_fan(self, fan_id: int) -> FanRow:
        cursor = await self._run(_SELECT_FANS + " WHERE id = %s", (fan_id,))
        return FanRow(**(await cursor.fetchone() or {}))

    async def load_session(self, fan_id: int) -> SessionRow:
        cursor = await self._run(
            "SELECT fan_id, flow_id, step_id, updated_at FROM sessions WHERE fan_id = %s",
            (fan_id,),
        )
        return SessionRow(**(await cursor.fetchone() or {}))

    async def record_answer(
        self, fan_id: int, field: str, value: str | None, now: datetime
    ) -> None:
        if field not in _SET_SNAPSHOT:
            raise IntegrityViolation(f"unknown answer field {field!r}")
        await self._run(
            "INSERT INTO answers (fan_id, field, value, ts) VALUES (%s, %s, %s, %s)",
            (fan_id, field, value, now),
        )
        stored = int(value) if field == "venue" and value is not None else value
        await self._run(_SET_SNAPSHOT[field], (stored, fan_id))

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
            "UPDATE sessions SET step_id = %s, updated_at = %s WHERE fan_id = %s",
            (step_id, now, fan_id),
        )
        await self._run(
            "UPDATE fans SET furthest_step = %s, last_seen = %s WHERE id = %s",
            (furthest_step, now, fan_id),
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

    async def claim_unsent(self, older_than: datetime, limit: int) -> list[ReplyRow]:
        cursor = await self._run(
            _SELECT_REPLIES
            + " WHERE status = 'unsent' AND ts < %s ORDER BY id LIMIT %s"
            + " FOR UPDATE SKIP LOCKED",
            (older_than, limit),
        )
        return [_reply_row(row) for row in await cursor.fetchall()]

    async def bump_funnel(self, step_id: str) -> None:
        await self._run(
            "INSERT INTO funnel_counts (step_id, count) VALUES (%s, 1) "
            "ON CONFLICT (step_id) DO UPDATE SET count = funnel_counts.count + 1",
            (step_id,),
        )

    async def delete_fan(self, fan_id: int) -> None:
        await self._run("DELETE FROM fans WHERE id = %s", (fan_id,))
