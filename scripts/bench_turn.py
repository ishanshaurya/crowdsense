"""Time engine turns against a LOCAL Postgres (`docs/architecture.md` §11).

    DATABASE_URL=postgresql://localhost:5432/bench uv run python -m scripts.bench_turn 50

Runs N full flows (8 turns each) through the real engine and Postgres store, and reports p50/p95
turn time plus database round trips per turn. Refuses non-local hosts, so it never writes
benchmark fans into Supabase.
"""

import asyncio
import os
import statistics
import sys
import time
from typing import Any
from urllib.parse import urlparse

from psycopg import AsyncConnection, AsyncCursor

from core.clock import SystemClock
from core.engine import Engine
from core.store_postgres import PostgresStore
from core.types import EventKind, InboundEvent

MOVES: list[tuple[EventKind, str | None, str | None]] = [
    ("start", None, None),
    ("choice", "consent", "yes"),
    ("choice", "city", "Pune"),
    ("choice", "venue", "8"),
    ("choice", "budget", "1500_3000"),
    ("choice", "group", "3_5"),
    ("choice", "email", "skip"),
    ("text", None, None),
]
trips = 0
connects = 0


def _count_round_trips() -> None:
    """Count statements plus BEGIN/COMMIT, which psycopg sends outside `execute`."""
    execute, command = AsyncCursor.execute, AsyncConnection._exec_command

    async def counted_execute(self: Any, *args: Any, **kwargs: Any) -> Any:
        global trips
        trips += 1
        return await execute(self, *args, **kwargs)

    def counted_command(self: Any, *args: Any, **kwargs: Any) -> Any:  # a generator in psycopg
        global trips
        trips += 1
        return command(self, *args, **kwargs)

    connect = AsyncConnection.connect.__func__  # type: ignore[attr-defined]

    async def counted_connect(cls: Any, *args: Any, **kwargs: Any) -> Any:
        global connects
        connects += 1
        return await connect(cls, *args, **kwargs)

    AsyncCursor.execute = counted_execute  # type: ignore[method-assign]
    AsyncConnection._exec_command = counted_command  # type: ignore[method-assign]
    AsyncConnection.connect = classmethod(counted_connect)  # type: ignore[assignment,method-assign]


def _event(user: str, msg_id: str, move: tuple[EventKind, str | None, str | None]) -> InboundEvent:
    kind, step, choice = move
    return InboundEvent(
        channel="bench",
        external_user_id=user,
        external_msg_id=msg_id,
        kind=kind,
        ts=SystemClock().now(),
        choice_step=step,
        choice_id=choice,
        text="hi" if kind == "text" else None,
    )


async def run(url: str, fans: int) -> None:
    store = PostgresStore(url)
    engine = Engine(store, SystemClock(), artist_name="Bench")
    times: list[float] = []
    per_turn: list[int] = []
    run_id = time.time_ns()
    for n in range(fans):
        for i, move in enumerate(MOVES):
            event = _event(f"{run_id}-{n}", f"{run_id}-{n}-{i}", move)
            before, start = trips, time.perf_counter()
            result = await engine.handle(event)
            times.append((time.perf_counter() - start) * 1000)
            per_turn.append(trips - before)
            await engine.mark_sent(result.replies)
    close = getattr(store, "close", None)  # the phase 1 store had no pool to close
    if close is not None:
        await close()
    times.sort()
    p95 = times[int(len(times) * 0.95) - 1]
    sys.stdout.write(
        f"turns={len(times)} p50={statistics.median(times):.2f}ms p95={p95:.2f}ms "
        f"round_trips_per_turn={statistics.mean(per_turn):.1f} "
        f"(new fan {per_turn[0]}, known fan {statistics.mean(per_turn[1 : len(MOVES)]):.1f}) "
        f"connects={connects} for {len(times)} turns and their mark_sent\n"
    )


def main() -> None:
    url = os.environ["DATABASE_URL"]
    if urlparse(url).hostname not in ("localhost", "127.0.0.1", None):
        raise SystemExit("bench_turn only runs against a local database")
    _count_round_trips()
    asyncio.run(run(url, int(sys.argv[1]) if len(sys.argv) > 1 else 50))


if __name__ == "__main__":
    main()
