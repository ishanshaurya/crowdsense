"""Seed ~20,000 simulated fans (#78): the real engine in memory, then a bulk COPY to Postgres.

    uv run --env-file .env python -m scripts.seed --dry-run          # memory only, prints counts
    DATABASE_URL=postgresql://localhost:5432/dev uv run python -m scripts.seed --reset

Every fan goes through `Engine(simulated=True)` (#82) on channel `seed` (#102). Replies are never
copied and the seed never sends `/delete`, so nothing can message a seeded fan (P3-C05) and
`funnel_counts` stays real-only. One transaction: `--reset` deletes `is_simulated` fans (their
rows cascade) and copies the new ones; without it the run stops if simulated fans exist (#62).
Real fans are never touched (P3-C06). Seeded dates are relative to now: reseed on demo day.
Non-local hosts need `--allow-remote`. The URL is never printed, only its host.
"""

import argparse
import asyncio
import json
import os
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlparse

import psycopg

from core.clock import ScriptedClock
from core.config import DEFAULT_ARTIST_NAME
from core.engine import Engine
from core.store_memory import InMemoryStore
from core.types import InboundEvent
from scripts.seed_plan import CHANNEL, FanPlan, plan_fans

LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1", None)
TURN_GAP = timedelta(seconds=40)


@dataclass(frozen=True)
class Seeded:
    store: InMemoryStore
    fans: int
    seconds: float


async def run_engine(plans: Sequence[FanPlan]) -> InMemoryStore:
    """Play every plan through the real engine on the in-memory store."""
    store = InMemoryStore()
    clock = ScriptedClock(datetime.now(UTC))
    engine = Engine(store, clock, artist_name=DEFAULT_ARTIST_NAME, simulated=True)
    for plan in plans:
        clock.set(plan.start)
        await engine.handle(_event(plan, 0, "start", None, None, plan.source_tag))
        for i, (kind, step, value) in enumerate(plan.moves, start=1):
            clock.advance(TURN_GAP)
            text = value if kind == "text" else None
            choice = value if kind == "choice" else None
            await engine.handle(_event(plan, i, kind, step, choice, None, text))
    return store


def _event(
    plan: FanPlan,
    i: int,
    kind: Any,
    step: str | None,
    choice: str | None,
    tag: str | None,
    text: str | None = None,
) -> InboundEvent:
    return InboundEvent(
        kind=kind,
        channel=CHANNEL,
        external_user_id=plan.user,
        external_msg_id=f"{plan.user}-{i}",
        ts=plan.start + TURN_GAP * i,
        text=text,
        choice_id=choice,
        choice_step=step,
        source_tag=tag,
    )


async def build(count: int, seed: int, now: datetime) -> Seeded:
    started = time.perf_counter()
    store = await run_engine(plan_fans(count, seed, now))
    return Seeded(store, count, time.perf_counter() - started)


async def rows_of(store: InMemoryStore) -> dict[str, list[Any]]:
    """The tables to copy. Replies are left out on purpose (#102)."""
    return {
        "fans": await store.fans(),
        "identities": await store.identities(),
        "sessions": await store.sessions(),
        "answers": await store.answers(),
        "events": await store.events(),
    }


def check_rows(rows: dict[str, list[Any]]) -> None:
    """Refuse to copy anything that is not a simulated fan on the seed channel."""
    if not all(f.is_simulated for f in rows["fans"]):
        raise SystemExit("refusing: a fan in the seed run is not simulated")
    channels = {r.channel for r in rows["identities"]} | {r.channel for r in rows["events"]}
    if channels - {CHANNEL}:
        raise SystemExit(f"refusing: unexpected channels {sorted(channels - {CHANNEL})}")


def _reserve(cur: psycopg.Cursor[Any], table: str, count: int) -> list[int]:
    cur.execute(
        "SELECT nextval(pg_get_serial_sequence(%s, 'id')) FROM generate_series(1, %s)",
        (table, count),
    )
    return [row[0] for row in cur.fetchall()]


def _copy(cur: psycopg.Cursor[Any], sql: str, records: Sequence[tuple[Any, ...]]) -> None:
    with cur.copy(sql) as copy:
        for record in records:
            copy.write_row(record)


def copy_rows(conn: psycopg.Connection[Any], rows: dict[str, list[Any]], *, reset: bool) -> int:
    """One transaction: optional reset, then COPY with ids taken from the database sequences."""
    check_rows(rows)
    with conn.transaction(), conn.cursor() as cur:
        if reset:
            cur.execute("DELETE FROM fans WHERE is_simulated")
            deleted = cur.rowcount
            cur.execute("DELETE FROM identities WHERE channel = %s", (CHANNEL,))  # orphans
        else:
            cur.execute("SELECT count(*) FROM fans WHERE is_simulated")
            existing = cur.fetchone()
            if existing and existing[0]:
                raise SystemExit(f"{existing[0]} simulated fans exist: use --reset")
            deleted = 0
        new_ids = _reserve(cur, "fans", len(rows["fans"]))
        fan_id = dict(zip([f.id for f in rows["fans"]], new_ids, strict=True))
        _copy_fans(cur, rows, fan_id)
        _copy_children(cur, rows, fan_id)
    return deleted


Rows = dict[str, list[Any]]


def _copy_fans(cur: psycopg.Cursor[Any], rows: Rows, fan_id: dict[int, int]) -> None:
    _copy(
        cur,
        "COPY fans (id, city, venue_id, venue_note, budget_band, group_size, email, "
        "is_simulated, completed_at, furthest_step, created_at, last_seen) FROM STDIN",
        [
            (fan_id[f.id], f.city, f.venue_id, f.venue_note, f.budget_band, f.group_size,
             f.email, True, f.completed_at, f.furthest_step, f.created_at, f.last_seen)
            for f in rows["fans"]
        ],
    )  # fmt: skip


def _copy_children(
    cur: psycopg.Cursor[Any], rows: dict[str, list[Any]], fan_id: dict[int, int]
) -> None:
    _copy(
        cur,
        "COPY identities (channel, external_user_id, fan_id, source_tag, consent, opted_out, "
        "can_message_until) FROM STDIN",
        [
            (i.channel, i.external_user_id, fan_id[i.fan_id], i.source_tag, i.consent,
             i.opted_out, i.can_message_until)
            for i in rows["identities"]
        ],
    )  # fmt: skip
    _copy(
        cur,
        "COPY sessions (fan_id, flow_id, step_id, updated_at) FROM STDIN",
        [(fan_id[s.fan_id], s.flow_id, s.step_id, s.updated_at) for s in rows["sessions"]],
    )
    answer_ids = _reserve(cur, "answers", len(rows["answers"]))
    _copy(
        cur,
        "COPY answers (id, fan_id, field, value, ts) FROM STDIN",
        [
            (new_id, fan_id[a.fan_id], a.field, a.value, a.ts)
            for new_id, a in zip(answer_ids, rows["answers"], strict=True)
        ],
    )
    _copy(
        cur,
        "COPY events (channel, external_msg_id, fan_id, direction, payload, ts) FROM STDIN",
        [
            (e.channel, e.external_msg_id, fan_id[e.fan_id], e.direction, json.dumps(e.payload),
             e.ts)
            for e in rows["events"]
        ],
    )  # fmt: skip


def guard_host(url: str, allow_remote: bool) -> str:
    host = urlparse(url).hostname
    if host not in LOCAL_HOSTS and not allow_remote:
        raise SystemExit(f"refusing non-local host {host!r}: pass --allow-remote to seed it")
    return host or "local socket"


def _args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="scripts.seed", description=__doc__.splitlines()[0])
    parser.add_argument("--fans", type=int, default=20_000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--reset", action="store_true", help="wipe simulated fans first (#62)")
    parser.add_argument("--dry-run", action="store_true", help="engine run only; no database")
    parser.add_argument("--allow-remote", action="store_true", help="allow a non-local host")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    args = _args(argv)
    url = "" if args.dry_run else os.environ.get("DATABASE_URL", "")
    if not url and not args.dry_run:
        raise SystemExit("DATABASE_URL is not set (or pass --dry-run)")
    host = guard_host(url, args.allow_remote) if url else "none (dry run)"
    seeded = asyncio.run(build(args.fans, args.seed, datetime.now(UTC)))
    rows = asyncio.run(rows_of(seeded.store))
    counts = ", ".join(f"{name} {len(table)}" for name, table in rows.items())
    sys.stdout.write(f"engine run: {seeded.fans} fans in {seeded.seconds:.1f}s; {counts}\n")
    if args.dry_run:
        return
    started = time.perf_counter()
    with psycopg.connect(url, prepare_threshold=None) as conn:
        deleted = copy_rows(conn, rows, reset=args.reset)
    took = time.perf_counter() - started
    sys.stdout.write(f"host {host}: deleted {deleted} simulated fans, copied in {took:.1f}s\n")


if __name__ == "__main__":
    main()
