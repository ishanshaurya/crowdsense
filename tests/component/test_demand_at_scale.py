"""P4-C01, P4-C07: `core/demand.py` on the 20,000-fan seed (#26, #40, #42, #78).

The seed went through the real engine (phase 3), so the SQL path is checked against the Python
rules in `core/insights.py` on the same rows, and every query is timed (not a load test).
"""

import time
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import psycopg
import pytest
from psycopg.rows import dict_row

from core import demand, insights
from core.catalog import CITIES, VENUES
from core.store import FanRow
from scripts.seed import copy_rows
from tests.component.test_demand import SIM, insert
from tests.support import NOW, decision

LIMIT_SECONDS = 1.0
RUNS = 5


@pytest.fixture
def seeded(pg_migrated_url: str, full_rows: dict[str, list[Any]]) -> Iterator[str]:
    with psycopg.connect(pg_migrated_url) as conn:
        copy_rows(conn, full_rows, reset=False)
        conn.execute("ANALYZE")
    yield pg_migrated_url


def fan_rows(url: str, *, simulated: bool) -> list[FanRow]:
    with psycopg.connect(url) as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT id, city, venue_id, venue_note, budget_band, group_size, email, is_simulated, "
            "completed_at, furthest_step, created_at, last_seen FROM fans WHERE is_simulated = %s",
            (simulated,),
        )
        return [FanRow(**row) for row in cur.fetchall()]


@decision(26, 57, 78)
def test_p4_c01_seeded_results_match_the_rules_in_python(seeded: str) -> None:
    now = datetime.now(UTC)
    reader = demand.DemandReader(seeded)
    got = reader.report("simulated", now)
    fans = fan_rows(seeded, simulated=True)
    assert got.started == len(fans) == 20_000
    assert got.counted == len(insights.counted(fans))
    assert got.recommendations == insights.recommend(fans, list(VENUES), now)
    assert got.funnel == insights.funnel(fans)
    assert got.growth == insights.growth_by_city(fans, now)
    assert {c.city for c in got.cities} == set(CITIES)
    assert got.growth["Jaipur"] == got.growth["Indore"] == "growing"  # seed plan (phase 3)
    assert reader.report("real", now).counted == 0
    reader.close()


@decision(26, 73)
def test_p4_c01_fixture_slice_gives_the_same_answers_beside_20k_seeded(seeded: str) -> None:
    with psycopg.connect(seeded, autocommit=True) as conn:
        insert(conn, SIM, simulated=False)  # the hand-built fixture, as real fans
    reader = demand.DemandReader(seeded)
    real = reader.report("real", NOW)
    reader.close()
    assert (real.started, real.counted) == (11, 9)
    assert real.cities == [
        demand.CityCount("Pune", 4, 13),
        demand.CityCount("Indore", 1, 4),
        demand.CityCount("Jaipur", 2, 3),
        demand.CityCount("Mumbai", 2, 3),
    ]
    assert real.recommendations == insights.recommend(
        fan_rows(seeded, simulated=False), list(VENUES), NOW
    )


def _slowest(conn: psycopg.Connection[Any], query: Any, args: dict[str, Any]) -> float:
    times = []
    for _ in range(RUNS):
        started = time.perf_counter()
        demand.fetch(conn, query, args)
        times.append(time.perf_counter() - started)
    return max(times)


@decision(42, 78)
def test_p4_c07_every_query_under_one_second_at_20k(seeded: str) -> None:
    reader = demand.DemandReader(seeded)
    args = demand.params("simulated", datetime.now(UTC), with_email=True)
    with reader.snapshot() as conn:
        slow = {name: _slowest(conn, q, args) for name, q in demand.QUERIES.items()}
    assert max(slow.values()) < LIMIT_SECONDS, slow
    started = time.perf_counter()
    reader.report("simulated", datetime.now(UTC))
    assert time.perf_counter() - started < LIMIT_SECONDS
    reader.close()
