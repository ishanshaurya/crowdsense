"""Time every dashboard query (`docs/metrics.md`, "Dashboard query p95"). Read-only: safe anywhere.

    DASHBOARD_DATABASE_URL=postgresql://localhost:5433/bench uv run python -m scripts.bench_demand
    uv run --env-file .env python -m scripts.bench_demand --runs 20          # Supabase, as the role

For each query in `core.demand.QUERIES`: server time from `EXPLAIN (ANALYZE, BUFFERS)` and wall time
over the network, p50 and p95 over N runs, plus the plan's top node. Then the whole pipelined
`report` (one round trip, #106). The connection is read-only; only the host is printed.
"""

import argparse
import os
import statistics
import sys
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

import psycopg

from core import demand


def pct(values: Sequence[float], q: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(q * (len(ordered) - 1)))]


def explain(conn: psycopg.Connection[Any], query: Any, args: dict[str, Any]) -> tuple[float, str]:
    plan = conn.execute(
        b"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + query.encode(), args
    ).fetchone()
    assert plan is not None
    top = plan[0][0]
    return top["Execution Time"], top["Plan"]["Node Type"]


def bench_query(conn: psycopg.Connection[Any], query: Any, args: dict[str, Any], runs: int) -> str:
    server, wall, node = [], [], ""
    for _ in range(runs):
        ms, node = explain(conn, query, args)
        server.append(ms)
        started = time.perf_counter()
        demand.fetch(conn, query, args)
        wall.append((time.perf_counter() - started) * 1000)
    return (
        f"{statistics.median(server):8.2f} {pct(server, 0.95):8.2f} "
        f"{statistics.median(wall):8.2f} {pct(wall, 0.95):8.2f}  {node}"
    )


def bench_report(reader: demand.DemandReader, runs: int) -> str:
    """Warm refreshes, as the live dashboard sees them; the first connect is timed apart."""
    started = time.perf_counter()
    reader.report("simulated", datetime.now(UTC))  # opens the pool's connection (TLS + SCRAM)
    cold = (time.perf_counter() - started) * 1000
    wall = []
    for _ in range(runs):
        started = time.perf_counter()
        reader.report("simulated", datetime.now(UTC), with_email=True)
        wall.append((time.perf_counter() - started) * 1000)
    return (
        f"report (pipelined, all queries): first {cold:.1f} ms; warm p50 "
        f"{statistics.median(wall):.1f} ms, p95 {pct(wall, 0.95):.1f} ms, "
        f"max {max(wall):.1f} ms over {runs} runs"
    )


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="scripts.bench_demand")
    parser.add_argument("--runs", type=int, default=20)
    parser.add_argument("--env", default="DASHBOARD_DATABASE_URL", help="variable holding the URL")
    args = parser.parse_args(argv)
    url = os.environ.get(args.env, "")
    if not url:
        raise SystemExit(f"{args.env} is not set")
    out = sys.stdout
    out.write(f"host {urlparse(url).hostname}, {args.runs} runs, times in ms\n")
    out.write(
        f"{'query':<11} {'srv p50':>8} {'srv p95':>8} {'wall p50':>8} {'wall p95':>8}  plan\n"
    )
    query_args = demand.params("simulated", datetime.now(UTC), with_email=True)
    with psycopg.connect(url, prepare_threshold=None) as conn:
        conn.read_only = True
        for name, query in demand.QUERIES.items():
            out.write(f"{name:<11} {bench_query(conn, query, query_args, args.runs)}\n")
    reader = demand.DemandReader(url)
    out.write(bench_report(reader, args.runs) + "\n")
    reader.close()


if __name__ == "__main__":
    main()
