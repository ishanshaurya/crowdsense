"""Seed on real Postgres: P3-C04 to P3-C07, reset (#62), host guard. Postgres only: COPY."""

from datetime import UTC, datetime
from typing import Any

import psycopg
import pytest

from core import insights
from core.catalog import CITIES, VENUES
from core.clock import ScriptedClock
from core.engine import Engine
from core.store_postgres import PostgresStore
from scripts.seed import check_rows, copy_rows, guard_host
from scripts.seed_plan import CHANNEL
from tests.component.helpers import flow, talk
from tests.support import ARTIST, NOW, decision

Rows = dict[str, list[Any]]


def seed(url: str, rows: Rows, *, reset: bool = False) -> int:
    with psycopg.connect(url) as conn:
        return copy_rows(conn, rows, reset=reset)


def scalar(url: str, sql: str, *args: Any) -> Any:
    with psycopg.connect(url) as conn:
        row = conn.execute(sql, args).fetchone()
        return row[0] if row else None


@decision(14, 40, 78, 82)
def test_p3_c04_seed_copies_about_20000_simulated_fans_that_went_through_the_engine(
    pg_migrated_url: str, full_rows: Rows
) -> None:
    seed(pg_migrated_url, full_rows)
    url = pg_migrated_url
    assert 19_000 <= scalar(url, "SELECT count(*) FROM fans") <= 21_000
    assert scalar(url, "SELECT count(*) FROM fans WHERE NOT is_simulated") == 0
    no_events = (
        "SELECT count(*) FROM fans f "
        "WHERE NOT EXISTS (SELECT 1 FROM events e WHERE e.fan_id = f.id)"
    )
    assert scalar(url, no_events) == 0
    assert scalar(url, "SELECT count(DISTINCT channel) FROM identities") == 1
    assert scalar(url, "SELECT min(channel) FROM events") == CHANNEL
    orphans = (
        "SELECT count(*) FROM fans f "
        "LEFT JOIN identities i ON i.fan_id = f.id WHERE i.fan_id IS NULL"
    )
    assert scalar(url, orphans) == 0
    wrong_city = (
        "SELECT count(*) FROM fans f JOIN venues v ON v.id = f.venue_id WHERE v.city <> f.city"
    )
    assert scalar(url, wrong_city) == 0


@decision(14, 36, 102)
async def test_p3_c05_seed_never_messages(pg_migrated_url: str, small_rows: Rows) -> None:
    seed(pg_migrated_url, small_rows)
    assert scalar(pg_migrated_url, "SELECT count(*) FROM replies") == 0
    assert scalar(pg_migrated_url, "SELECT count(*) FROM funnel_counts") == 0
    store = PostgresStore(pg_migrated_url)
    try:
        async with store.transaction() as tx:
            far_future = datetime(2100, 1, 1, tzinfo=UTC)
            channels = {"telegram", "web_sim", CHANNEL}
            assert await tx.claim_unsent(far_future, 10_000, channels=channels) == []
    finally:
        await store.close()
    assert "replies" not in small_rows  # never copied, whatever the engine wrote in memory


@decision(18, 62)
async def test_p3_c06_reseeding_never_touches_real_fans(
    pg_migrated_url: str, small_rows: Rows
) -> None:
    store = PostgresStore(pg_migrated_url)
    engine = Engine(store, ScriptedClock(NOW), artist_name=ARTIST)
    try:
        await talk(engine, "42", flow("Pune", "8", "1500_3000", "3_5"))
        real_before = await _real_rows(pg_migrated_url)
        assert real_before
        seed(pg_migrated_url, small_rows)
        with pytest.raises(SystemExit, match="use --reset"):
            seed(pg_migrated_url, small_rows)
        assert seed(pg_migrated_url, small_rows, reset=True) == 1_000
        assert scalar(pg_migrated_url, "SELECT count(*) FROM fans WHERE is_simulated") == 1_000
        assert await _real_rows(pg_migrated_url) == real_before
        reply = await talk(engine, "42", [("text", "hi again")])  # the real fan still works
        assert reply is not None and reply.replies
    finally:
        await store.close()


async def _real_rows(url: str) -> list[tuple[Any, ...]]:
    sql = (
        "SELECT f.*, i.channel, i.external_user_id, "
        "(SELECT count(*) FROM answers a WHERE a.fan_id = f.id), "
        "(SELECT count(*) FROM events e WHERE e.fan_id = f.id), "
        "(SELECT count(*) FROM replies r WHERE r.fan_id = f.id) "
        "FROM fans f JOIN identities i ON i.fan_id = f.id WHERE NOT f.is_simulated ORDER BY f.id"
    )
    with psycopg.connect(url) as conn:
        return conn.execute(sql).fetchall()


@decision(31, 32, 33, 40)
async def test_p3_c07_insights_cover_every_seeded_city(
    pg_migrated_url: str, full_rows: Rows
) -> None:
    seed(pg_migrated_url, full_rows)
    store = PostgresStore(pg_migrated_url)
    try:
        fans = [f for f in await store.fans() if f.is_simulated]
    finally:
        await store.close()
    attendance = insights.city_attendance(fans)
    bands = insights.price_band_by_city(fans)
    assert set(insights.city_priority(attendance)) == set(CITIES)
    for city in CITIES:
        assert insights.suggested_venue(city, attendance[city], VENUES) is not None, city
        assert city in bands, city
    priority = insights.city_priority(attendance)
    assert set(priority[:3]) == {"Mumbai", "Delhi NCR", "Bengaluru"}
    badges = insights.growth_by_city(fans, datetime.now(UTC))
    assert badges["Jaipur"] == badges["Indore"] == "growing"
    assert badges["Mumbai"] is None  # flat cities do not light up


def test_check_rows_refuses_real_fans_or_other_channels(small_rows: Rows) -> None:
    real = dict(small_rows, fans=[*small_rows["fans"][:1]])
    real["fans"] = [type(real["fans"][0])(**{**vars(real["fans"][0]), "is_simulated": False})]
    with pytest.raises(SystemExit, match="not simulated"):
        check_rows(real)
    identity = small_rows["identities"][0]
    other = dict(
        small_rows, identities=[type(identity)(**{**vars(identity), "channel": "telegram"})]
    )
    with pytest.raises(SystemExit, match="unexpected channels"):
        check_rows(other)


@pytest.mark.parametrize(
    "url",
    ["postgresql://localhost:5432/dev", "postgresql://127.0.0.1/dev", "postgresql:///dev"],
)
def test_guard_allows_local_hosts(url: str) -> None:
    assert guard_host(url, allow_remote=False)


def test_guard_refuses_remote_hosts_without_the_flag() -> None:
    remote = "postgresql://user:pw@db.example.supabase.co:5432/postgres"  # pragma: allowlist secret
    with pytest.raises(SystemExit) as refused:
        guard_host(remote, allow_remote=False)
    assert "pw" not in str(refused.value) and "--allow-remote" in str(refused.value)
    assert guard_host(remote, allow_remote=True) == "db.example.supabase.co"
