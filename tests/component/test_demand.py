"""P4-U01 to P4-U10: `core/demand.py` on real Postgres (#57) with a hand-built fixture.

Every expected number below is worked out by hand from `SIM` and `REAL`.
"""

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime, timedelta

import psycopg
import pytest
from psycopg.rows import dict_row

from core import demand, insights
from core.catalog import VENUES
from core.clock import ScriptedClock
from core.engine import Engine
from core.store import FanRow, StoreUnavailable
from core.store_postgres import PostgresStore
from tests.component.helpers import flow, talk
from tests.support import ARTIST, NOW, ROOT, decision

VENUE = {v.id: v for v in VENUES}


@dataclass(frozen=True)
class F:
    city: str | None
    venue: int | None
    band: str | None
    group: str | None
    tag: str | None
    days_ago: float | None  # completed this long before NOW; None = never completed
    furthest: str
    note: str | None = None
    email: str | None = None


SIM = [
    F("Pune", 8, "1500_3000", "3_5", "ig_story", 2, "done", email="s1@example.com"),
    F("Pune", 9, "1500_3000", "6_plus", "poster", 3, "done"),
    F("Pune", 8, "lt_1500", "2", None, 10, "done"),
    F("Pune", None, "gte_6000", "1", "ig_story", 1, "done", note="Some club"),
    F("Mumbai", 2, "3000_6000", "1", "yt", 9, "done"),
    F("Mumbai", 2, "lt_1500", "2", "yt", 20, "done"),
    F("Jaipur", 13, "gte_6000", "2", "ig_bio", 1, "done"),
    F("Jaipur", 13, "1500_3000", "1", "ig_bio", 12, "done"),
    F("Indore", None, "lt_1500", "3_5", "poster", 5, "done"),  # city edited, venue re-asked
    F("Delhi NCR", None, "1500_3000", None, "yt", None, "group"),
    F(None, None, None, None, None, None, "consent"),  # declined
]
REAL = [
    F("Pune", 9, "3000_6000", "2", None, 1, "done", email="r1@example.com"),
    F("Mumbai", None, None, None, "ig_story", None, "venue"),
]
CREATED = NOW - timedelta(days=30)
DELETED = {"city": 2, "done": 1}  # funnel_counts: always real (#102)


def insert(conn: psycopg.Connection, fans: list[F], *, simulated: bool) -> None:
    for f in fans:
        done = None if f.days_ago is None else NOW - timedelta(days=f.days_ago)
        row = conn.execute(
            "INSERT INTO fans (city, venue_id, venue_note, budget_band, group_size, email, "
            "is_simulated, completed_at, furthest_step, created_at, last_seen) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
            (
                f.city,
                f.venue,
                f.note,
                f.band,
                f.group,
                f.email,
                simulated,
                done,
                f.furthest,
                CREATED,
                NOW,
            ),
        ).fetchone()
        assert row is not None
        channel = "seed" if simulated else "telegram"
        conn.execute(
            "INSERT INTO identities (channel, external_user_id, fan_id, source_tag) "
            "VALUES (%s, %s, %s, %s)",
            (channel, f"{channel}-fan-{row[0]}", row[0], f.tag),
        )


def add_real(conn: psycopg.Connection) -> None:
    insert(conn, REAL, simulated=False)
    for step, count in DELETED.items():
        conn.execute("INSERT INTO funnel_counts (step_id, count) VALUES (%s, %s)", (step, count))


@pytest.fixture
def db(pg_migrated_url: str) -> Iterator[psycopg.Connection]:
    with psycopg.connect(pg_migrated_url, autocommit=True) as conn:
        yield conn


@pytest.fixture
def reader(pg_migrated_url: str) -> Iterator[demand.DemandReader]:
    reader = demand.DemandReader(pg_migrated_url)
    yield reader
    reader.close()


@pytest.fixture
def full(db: psycopg.Connection) -> psycopg.Connection:
    insert(db, SIM, simulated=True)
    add_real(db)
    return db


def fan_rows(conn: psycopg.Connection, *, simulated: bool) -> list[FanRow]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT id, city, venue_id, venue_note, budget_band, group_size, email, is_simulated, "
            "completed_at, furthest_step, created_at, last_seen FROM fans WHERE is_simulated = %s",
            (simulated,),
        )
        return [FanRow(**row) for row in cur.fetchall()]


@decision(31, 33, 49, 52)
def test_p4_u01_top_cities_and_venues_by_attendance(full, reader) -> None:  # type: ignore[no-untyped-def]
    report = reader.report("simulated", NOW)
    assert report.cities == [
        demand.CityCount("Pune", 4, 13),
        demand.CityCount("Indore", 1, 4),
        demand.CityCount("Jaipur", 2, 3),
        demand.CityCount("Mumbai", 2, 3),
    ]
    assert [(v.venue.id, v.fans, v.people) for v in report.venues] == [
        (8, 2, 6),
        (2, 2, 3),
        (13, 2, 3),
        (9, 1, 6),
    ]


@decision(32, 50, 52, 79)
def test_p4_u02_price_distribution_and_band_per_city(full, reader) -> None:  # type: ignore[no-untyped-def]
    budget = reader.report("simulated", NOW).budget
    assert budget.overall == {"lt_1500": 3, "1500_3000": 3, "3000_6000": 1, "gte_6000": 2}
    assert list(budget.overall) == list(insights.BAND_ORDER)
    assert budget.by_city == {
        "Pune": {"lt_1500": 1, "1500_3000": 2, "gte_6000": 1},
        "Mumbai": {"lt_1500": 1, "3000_6000": 1},
        "Jaipur": {"1500_3000": 1, "gte_6000": 1},
        "Indore": {"lt_1500": 1},
    }
    bands = {r.city: r.price_band for r in reader.report("simulated", NOW).recommendations}
    assert bands == {
        "Pune": "1500_3000",
        "Mumbai": "lt_1500",
        "Jaipur": "1500_3000",
        "Indore": "lt_1500",
    }  # ties pick the lower band (#50)


@decision(22, 52)
def test_p4_u03_group_size_distribution(full, reader) -> None:  # type: ignore[no-untyped-def]
    groups = reader.report("simulated", NOW).groups
    assert groups == {"1": 3, "2": 3, "3_5": 2, "6_plus": 1}
    assert list(groups) == list(insights.PEOPLE_PER_GROUP)


@decision(27, 51, 52)
def test_p4_u04_heatmap_keeps_other_separate(full, reader) -> None:  # type: ignore[no-untyped-def]
    cells = {
        (c.city, c.venue.id if c.venue else None): c.fans
        for c in reader.report("simulated", NOW).heatmap
    }
    assert cells == {
        ("Indore", None): 1,
        ("Jaipur", 13): 2,
        ("Mumbai", 2): 2,
        ("Pune", 8): 2,
        ("Pune", 9): 1,
        ("Pune", None): 1,
    }


@decision(4, 70, 84, 104)
def test_p4_u05_funnel_by_furthest_step_real_adds_deleted(full, reader) -> None:  # type: ignore[no-untyped-def]
    sim = reader.report("simulated", NOW).funnel
    assert sim == insights.Funnel(11, 9, {"consent": 1, "group": 1, "done": 9})
    assert sim == insights.funnel(fan_rows(full, simulated=True))
    real = reader.report("real", NOW).funnel
    assert real == insights.Funnel(
        started=5, completed=1, by_furthest_step={"city": 2, "venue": 1, "done": 2}
    )


@decision(70, 84)
async def test_p4_u05_editing_fan_stays_completed(pg_migrated_url: str, reader) -> None:  # type: ignore[no-untyped-def]
    store = PostgresStore(pg_migrated_url)
    engine = Engine(store, ScriptedClock(NOW), artist_name=ARTIST)
    await talk(engine, "editor", flow("Pune", "8", "lt_1500", "2"))
    await talk(engine, "editor", [("start", ""), ("choice", "city"), ("choice", "Jaipur")])
    await store.close()
    report = reader.report("real", NOW)
    assert (report.started, report.counted, report.funnel.completed) == (1, 1, 1)
    assert report.cities == [demand.CityCount("Jaipur", 1, 2)]
    assert [(c.city, c.venue) for c in report.heatmap] == [("Jaipur", None)]  # no venue (#70)


@decision(31, 56, 85)
def test_p4_u06_weekly_growth_and_badges(full, reader) -> None:  # type: ignore[no-untyped-def]
    report = reader.report("simulated", NOW)
    assert report.growth == {"Pune": "growing", "Mumbai": None, "Jaipur": None, "Indore": "new"}
    assert report.growth == {
        city: badge
        for city, badge in insights.growth_by_city(fan_rows(full, simulated=True), NOW).items()
    }
    assert [w.week for w in report.weekly if w.in_progress] == [date(2026, 10, 12)] * 2
    weeks = [(w.city, w.week, w.fans) for w in report.weekly]
    assert weeks == [
        ("Indore", date(2026, 10, 5), 1),
        ("Jaipur", date(2026, 9, 28), 1),
        ("Jaipur", date(2026, 10, 12), 1),
        ("Mumbai", date(2026, 9, 21), 1),
        ("Mumbai", date(2026, 10, 5), 1),
        ("Pune", date(2026, 10, 5), 1),
        ("Pune", date(2026, 10, 12), 3),
    ]


@decision(56)
def test_p4_u06_weeks_are_ist_and_only_the_last_six(db, reader) -> None:  # type: ignore[no-untyped-def]
    sunday_late_utc = datetime(2026, 10, 11, 19, 0, tzinfo=NOW.tzinfo)  # Monday 00:30 IST
    start_of_window = datetime(2026, 9, 6, 18, 30, tzinfo=NOW.tzinfo)  # Mon 7 Sep 00:00 IST
    for at in (sunday_late_utc, start_of_window, start_of_window - timedelta(seconds=1)):
        days = (NOW - at) / timedelta(days=1)
        insert(db, [F("Pune", 8, "lt_1500", "1", None, days, "done")], simulated=True)
    weeks = [(w.week, w.fans) for w in reader.report("simulated", NOW).weekly]
    assert weeks == [(date(2026, 9, 7), 1), (date(2026, 10, 12), 1)]


@decision(3, 52)
def test_p4_u07_source_breakdown_includes_no_tag(full, reader) -> None:  # type: ignore[no-untyped-def]
    sources = reader.report("simulated", NOW).sources
    assert list(sources.items()) == [
        ("ig_bio", 2),
        ("ig_story", 2),
        ("poster", 2),
        ("yt", 2),
        (None, 1),
    ]
    assert reader.report("real", NOW).sources == {None: 1}


@decision(31, 32, 33, 49, 50, 51, 79, 85)
@pytest.mark.parametrize("view", demand.VIEWS)
def test_p4_u08_recommendations_equal_insights(full, reader, view) -> None:  # type: ignore[no-untyped-def]
    got = reader.report(view, NOW).recommendations
    fans = fan_rows(full, simulated=view == "simulated")
    assert got == insights.recommend(fans, list(VENUES), NOW)
    if view == "simulated":
        assert [(r.city, r.attendance, r.venue and r.venue.id, r.badge) for r in got] == [
            ("Pune", 13, 9, "growing"),
            ("Indore", 4, 14, "new"),
            ("Jaipur", 3, 13, None),
            ("Mumbai", 3, 2, None),
        ]


@decision(18, 73, 107)
def test_p4_u09_views_never_mix(db, reader) -> None:  # type: ignore[no-untyped-def]
    insert(db, SIM, simulated=True)
    before = reader.report("simulated", NOW)
    add_real(db)
    assert reader.report("simulated", NOW) == before
    real = reader.report("real", NOW)
    assert (before.started, before.counted) == (11, 9)
    assert (real.started, real.counted) == (2, 1)
    assert real.cities == [demand.CityCount("Pune", 1, 2)]
    assert [f.id for f in real.latest] == [
        f.id for f in fan_rows(db, simulated=False) if f.completed_at is not None
    ]
    assert demand.DEFAULT_VIEW == "simulated"


@decision(73)
def test_p4_u09_every_fan_query_filters_the_view() -> None:
    for name, query in demand.QUERIES.items():
        if "fans" in query:
            assert "is_simulated = %(simulated)s" in query, name
        if "funnel_counts" in query:
            assert "WHERE NOT %(simulated)s" in query, name  # deleted fans are real only
    with pytest.raises(ValueError):
        demand.params("both", NOW)  # type: ignore[arg-type]


@decision(60)
def test_latest_fans_hide_email_unless_asked(full, reader) -> None:  # type: ignore[no-untyped-def]
    hidden = reader.report("simulated", NOW).latest
    shown = reader.report("simulated", NOW, with_email=True).latest
    assert len(hidden) == 9 and all(f.email is None for f in hidden)
    assert [f.email for f in shown if f.email] == ["s1@example.com"]
    assert [f.completed_at for f in hidden] == sorted(
        (f.completed_at for f in hidden), reverse=True
    )


@decision(31)
@pytest.mark.parametrize("view", demand.VIEWS)
def test_p4_u10_empty_database(reader, view) -> None:  # type: ignore[no-untyped-def]
    report = reader.report(view, NOW)
    assert (report.started, report.counted) == (0, 0)
    assert report.cities == report.venues == report.heatmap == report.weekly == []
    assert report.latest == report.recommendations == []
    assert report.budget == demand.Budget({}, {})
    assert report.groups == report.growth == report.sources == {}
    assert report.funnel == insights.Funnel(0, 0, {})


@decision(57, 106)
def test_pipeline_matches_one_query_at_a_time(full, reader) -> None:  # type: ignore[no-untyped-def]
    args = demand.params("simulated", NOW)
    with reader.snapshot() as conn:
        rows = {name: demand.fetch(conn, q, args) for name, q in demand.QUERIES.items()}
    assert demand.build_report("simulated", rows) == reader.report("simulated", NOW)


@decision(57, 106)
def test_reader_transactions_are_read_only(full, reader) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(psycopg.errors.ReadOnlySqlTransaction), reader.snapshot() as conn:
        conn.execute("DELETE FROM fans")
    with reader.snapshot() as conn:
        level = conn.execute("SHOW transaction_isolation").fetchone()
    assert level == ("repeatable read",)
    assert reader.report("simulated", NOW).started == 11


@decision(52, 57)
def test_counted_rule_is_written_once() -> None:
    source = (ROOT / "core" / "demand.py").read_text(encoding="utf-8")
    assert source.count("completed_at IS NOT NULL") == 1


def test_database_down_raises_store_unavailable() -> None:
    reader = demand.DemandReader("postgresql://127.0.0.1:1/none", timeout=0.5)
    with pytest.raises(StoreUnavailable):
        reader.report("simulated", NOW)
    reader.close()


@decision(106)
def test_report_runs_under_a_statement_timeout(full, reader) -> None:  # type: ignore[no-untyped-def]
    with reader.snapshot() as conn:
        demand.fetch_all(conn, demand.params("simulated", NOW))
        assert conn.execute("SHOW statement_timeout").fetchone() == ("5s",)
