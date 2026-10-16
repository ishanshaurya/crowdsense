"""Dashboard read path (#57): the counted-fan rule and every SQL aggregate, sync and read-only.

Every query that reads `fans` filters `is_simulated` by the view, so Simulated and Real never mix
(#73). Counted = `completed_at` set (#52, #70); only the funnel sees partial fans. Rules (people
per group, price band, suggested venue, growth badge, city priority) stay in `core/insights.py`:
people per group is passed into SQL as parameters, the rest is applied to the aggregates here.
`report` sends every query in one pipeline inside one `READ ONLY` `REPEATABLE READ` transaction:
one snapshot, one round trip (#106). Time comes in as `now` (#56); no SQL reads the clock.
"""

from collections import Counter
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Literal, LiteralString

import psycopg
from psycopg import IsolationLevel
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from core import insights
from core.catalog import Venue
from core.flow import FUNNEL_ORDER
from core.store import StoreUnavailable

View = Literal["simulated", "real"]
VIEWS: tuple[View, ...] = ("simulated", "real")
DEFAULT_VIEW: View = "simulated"
LATEST_LIMIT = 50
WEEKS_SHOWN = 6
IST = "Asia/Kolkata"  # weeks use IST (#56)

Rows = list[dict[str, Any]]
Conn = psycopg.Connection[Any]

# The view filter and the counted-fan rule, defined once (#51, #52, #70, #73). Postgres inlines
# this CTE into each query, so it costs nothing.
_COUNTED: LiteralString = (
    "WITH counted AS (SELECT id, city, venue_id, venue_note, budget_band, group_size, email, "
    "completed_at FROM fans WHERE is_simulated = %(simulated)s AND completed_at IS NOT NULL) "
)
# People per fan from `insights.PEOPLE_PER_GROUP` (#33), passed in as arrays.
_WITH_PEOPLE: LiteralString = (
    "FROM counted c LEFT JOIN unnest(%(groups)s::text[], %(people)s::int[]) AS p (grp, people) "
    "ON p.grp = c.group_size "
)
_SUM_PEOPLE: LiteralString = "COALESCE(SUM(p.people), 0)::bigint AS people "

TOTALS: LiteralString = (
    _COUNTED + "SELECT (SELECT count(*) FROM fans WHERE is_simulated = %(simulated)s) AS started, "
    "(SELECT count(*) FROM counted) AS counted"
)
CITIES: LiteralString = (
    _COUNTED
    + "SELECT c.city, count(*) AS fans, "
    + _SUM_PEOPLE
    + _WITH_PEOPLE
    + "WHERE c.city IS NOT NULL GROUP BY c.city ORDER BY people DESC, fans DESC, c.city"
)
VENUES: LiteralString = (
    _COUNTED
    + "SELECT c.venue_id, count(*) AS fans, "
    + _SUM_PEOPLE
    + _WITH_PEOPLE
    + "WHERE c.venue_id IS NOT NULL GROUP BY c.venue_id "
    "ORDER BY fans DESC, people DESC, c.venue_id"
)
BUDGET: LiteralString = (
    _COUNTED + "SELECT city, budget_band, count(*) AS fans, GROUPING(city) = 1 AS overall "
    "FROM counted WHERE city IS NOT NULL AND budget_band IS NOT NULL "
    "GROUP BY GROUPING SETS ((budget_band), (city, budget_band))"
)
GROUPS: LiteralString = (
    _COUNTED + "SELECT group_size, count(*) AS fans FROM counted "
    "WHERE group_size IS NOT NULL GROUP BY group_size"
)
HEATMAP: LiteralString = (
    _COUNTED + "SELECT city, venue_id, count(*) AS fans FROM counted WHERE city IS NOT NULL "
    "GROUP BY city, venue_id ORDER BY city, venue_id NULLS LAST"
)
# The funnel is the one view that sees partial fans (#52, #84); deleted fans are real (#104).
FUNNEL: LiteralString = (
    "SELECT furthest_step AS step, count(*) AS fans, false AS deleted FROM fans "
    "WHERE is_simulated = %(simulated)s AND furthest_step IS NOT NULL GROUP BY furthest_step "
    "UNION ALL SELECT step_id, count, true FROM funnel_counts WHERE NOT %(simulated)s"
)
WEEKLY: LiteralString = (
    _COUNTED + "SELECT city, (date_trunc('week', completed_at AT TIME ZONE %(tz)s))::date "
    "AS week, count(*) AS fans, bool_or(completed_at >= (date_trunc('week', "
    "%(now)s::timestamptz AT TIME ZONE %(tz)s)) AT TIME ZONE %(tz)s) AS in_progress "
    "FROM counted WHERE city IS NOT NULL "
    "AND completed_at >= (date_trunc('week', %(now)s::timestamptz AT TIME ZONE %(tz)s) "
    "- make_interval(weeks => %(weeks)s::int - 1)) AT TIME ZONE %(tz)s "
    "GROUP BY city, week ORDER BY city, week"
)
# Same windows as `insights.growth_by_city` (#85).
GROWTH: LiteralString = (
    _COUNTED + "SELECT city, "
    "count(*) FILTER (WHERE completed_at > %(now)s::timestamptz - interval '7 days') "
    "AS this_week, "
    "count(*) FILTER (WHERE completed_at <= %(now)s::timestamptz - interval '7 days') "
    "AS prior_week FROM counted WHERE city IS NOT NULL "
    "AND completed_at > %(now)s::timestamptz - interval '14 days' GROUP BY city"
)
# One identity per fan (#37), so the join never counts a fan twice.
SOURCES: LiteralString = (
    _COUNTED + "SELECT i.source_tag, count(*) AS fans FROM counted c "
    "LEFT JOIN identities i ON i.fan_id = c.id "
    "GROUP BY i.source_tag ORDER BY fans DESC, i.source_tag NULLS LAST"
)
LATEST: LiteralString = (
    _COUNTED + "SELECT id, completed_at, city, venue_id, venue_note, budget_band, group_size, "
    "CASE WHEN %(with_email)s THEN email END AS email FROM counted "
    "ORDER BY completed_at DESC, id DESC LIMIT %(limit)s"
)
VENUE_LIST: LiteralString = "SELECT id, city, name, capacity FROM venues ORDER BY id"

# Every query `report` runs, in order. Q-17/P4-U09 tests scan this.
QUERIES: dict[str, LiteralString] = {
    "totals": TOTALS,
    "cities": CITIES,
    "venues": VENUES,
    "budget": BUDGET,
    "groups": GROUPS,
    "heatmap": HEATMAP,
    "funnel": FUNNEL,
    "weekly": WEEKLY,
    "growth": GROWTH,
    "sources": SOURCES,
    "latest": LATEST,
    "venue_list": VENUE_LIST,
}


@dataclass(frozen=True)
class CityCount:
    city: str
    fans: int
    people: int


@dataclass(frozen=True)
class VenueCount:
    venue: Venue
    fans: int
    people: int


@dataclass(frozen=True)
class Budget:
    overall: dict[str, int]  # band -> fans, in band order
    by_city: dict[str, dict[str, int]]


@dataclass(frozen=True)
class HeatCell:
    city: str
    venue: Venue | None  # None = "Other / not listed" or no venue yet (#27, #51)
    fans: int


@dataclass(frozen=True)
class WeekCount:
    city: str
    week: date  # Monday, IST
    fans: int
    in_progress: bool = False  # the current week: counts so far, not a drop


@dataclass(frozen=True)
class LatestFan:
    id: int
    completed_at: datetime
    city: str | None
    venue: Venue | None
    venue_note: str | None
    budget_band: str | None
    group_size: str | None
    email: str | None  # None unless asked for (#60)


@dataclass(frozen=True)
class DemandReport:
    view: View
    started: int
    counted: int
    cities: list[CityCount]
    venues: list[VenueCount]
    budget: Budget
    groups: dict[str, int]
    heatmap: list[HeatCell]
    funnel: insights.Funnel
    weekly: list[WeekCount]
    growth: dict[str, insights.Badge | None]
    sources: dict[str | None, int]  # None = no tag (#3)
    latest: list[LatestFan]
    recommendations: list[insights.CityRecommendation]


def params(view: View, now: datetime, *, with_email: bool = False) -> dict[str, Any]:
    if view not in VIEWS:
        raise ValueError(f"unknown view {view!r}")
    return {
        "simulated": view == "simulated",
        "groups": list(insights.PEOPLE_PER_GROUP),
        "people": list(insights.PEOPLE_PER_GROUP.values()),
        "now": now,
        "tz": IST,
        "weeks": WEEKS_SHOWN,
        "with_email": with_email,
        "limit": LATEST_LIMIT,
    }


def fetch(conn: Conn, query: LiteralString, args: Mapping[str, Any]) -> Rows:
    with conn.cursor(row_factory=dict_row) as cur:
        return cur.execute(query, args).fetchall()


def fetch_all(conn: Conn, args: Mapping[str, Any]) -> dict[str, Rows]:
    """Every query in one pipeline: one round trip, one snapshot (#106)."""
    cursors = {}
    with conn.pipeline():
        conn.execute("SET LOCAL statement_timeout = '5s'")
        for name, query in QUERIES.items():
            cursors[name] = conn.cursor(row_factory=dict_row)
            cursors[name].execute(query, args)
    return {name: cur.fetchall() for name, cur in cursors.items()}


def venue_list(rows: Rows) -> dict[int, Venue]:
    return {row["id"]: Venue(**row) for row in rows}


def cities(rows: Rows) -> list[CityCount]:
    return [CityCount(r["city"], r["fans"], r["people"]) for r in rows]


def venues(rows: Rows, by_id: Mapping[int, Venue]) -> list[VenueCount]:
    return [VenueCount(by_id[r["venue_id"]], r["fans"], r["people"]) for r in rows]


def budget(rows: Rows) -> Budget:
    order = insights.BAND_ORDER.index
    overall = {r["budget_band"]: r["fans"] for r in rows if r["overall"]}
    by_city: dict[str, dict[str, int]] = {}
    for r in sorted((r for r in rows if not r["overall"]), key=lambda r: order(r["budget_band"])):
        by_city.setdefault(r["city"], {})[r["budget_band"]] = r["fans"]
    return Budget(dict(sorted(overall.items(), key=lambda item: order(item[0]))), by_city)


def groups(rows: Rows) -> dict[str, int]:
    counts = {r["group_size"]: r["fans"] for r in rows}
    return {g: counts[g] for g in insights.PEOPLE_PER_GROUP if g in counts}


def heatmap(rows: Rows, by_id: Mapping[int, Venue]) -> list[HeatCell]:
    return [HeatCell(r["city"], by_id.get(r["venue_id"]), r["fans"]) for r in rows]


def funnel(rows: Rows, started: int, counted: int) -> insights.Funnel:
    """By furthest step (#84); Real adds deleted fans from `funnel_counts` (#104)."""
    steps: Counter[str] = Counter()
    for r in rows:
        steps[r["step"]] += r["fans"]
    deleted = sum(r["fans"] for r in rows if r["deleted"])
    return insights.Funnel(
        started=started + deleted,
        completed=counted,
        by_furthest_step={s: steps[s] for s in FUNNEL_ORDER if steps[s]},
    )


def weekly(rows: Rows) -> list[WeekCount]:
    return [WeekCount(r["city"], r["week"], r["fans"], r["in_progress"]) for r in rows]


def growth(rows: Rows) -> dict[str, insights.Badge | None]:
    return {r["city"]: insights.growth_badge(r["this_week"], r["prior_week"]) for r in rows}


def sources(rows: Rows) -> dict[str | None, int]:
    return {r["source_tag"]: r["fans"] for r in rows}


def latest(rows: Rows, by_id: Mapping[int, Venue]) -> list[LatestFan]:
    return [
        LatestFan(
            r["id"],
            r["completed_at"],
            r["city"],
            by_id.get(r["venue_id"]),
            r["venue_note"],
            r["budget_band"],
            r["group_size"],
            r["email"],
        )
        for r in rows
    ]


def recommendations(
    city_counts: Sequence[CityCount],
    by_city_bands: Mapping[str, Mapping[str, int]],
    badges: Mapping[str, insights.Badge | None],
    all_venues: Sequence[Venue],
) -> list[insights.CityRecommendation]:
    """`insights.recommend` over aggregates instead of fan rows (#31, #49, #50, #79, #85)."""
    attendance = {c.city: c.people for c in city_counts}
    return [
        insights.CityRecommendation(
            city,
            attendance[city],
            insights.suggested_venue(city, attendance[city], all_venues),
            insights.price_band(Counter(by_city_bands.get(city, {})).elements()),
            badges.get(city),
        )
        for city in insights.city_priority(attendance)
    ]


def build_report(view: View, rows: Mapping[str, Rows]) -> DemandReport:
    by_id = venue_list(rows["venue_list"])
    totals = rows["totals"][0]
    city_counts, money = cities(rows["cities"]), budget(rows["budget"])
    badges = growth(rows["growth"])
    return DemandReport(
        view=view,
        started=totals["started"],
        counted=totals["counted"],
        cities=city_counts,
        venues=venues(rows["venues"], by_id),
        budget=money,
        groups=groups(rows["groups"]),
        heatmap=heatmap(rows["heatmap"], by_id),
        funnel=funnel(rows["funnel"], totals["started"], totals["counted"]),
        weekly=weekly(rows["weekly"]),
        growth=badges,
        sources=sources(rows["sources"]),
        latest=latest(rows["latest"], by_id),
        recommendations=recommendations(city_counts, money.by_city, badges, list(by_id.values())),
    )


def report(conn: Conn, view: View, now: datetime, *, with_email: bool = False) -> DemandReport:
    return build_report(view, fetch_all(conn, params(view, now, with_email=with_email)))


class DemandReader:
    """Sync pool for the dashboard (#67): read-only, repeatable-read, transaction-pooler safe."""

    def __init__(self, dsn: str, *, max_size: int = 2, timeout: float = 5.0) -> None:
        self._pool = ConnectionPool(
            dsn,
            min_size=0,
            max_size=max_size,
            timeout=timeout,
            kwargs={"prepare_threshold": None},
            configure=_configure,
            open=False,
        )

    @contextmanager
    def snapshot(self) -> Iterator[Conn]:
        """One read-only transaction; committed (nothing to commit) on exit."""
        try:
            self._pool.open()
            with self._pool.connection() as conn:
                yield conn
        except psycopg.OperationalError as exc:  # includes PoolTimeout
            raise StoreUnavailable(type(exc).__name__) from exc

    def report(self, view: View, now: datetime, *, with_email: bool = False) -> DemandReport:
        with self.snapshot() as conn:
            return report(conn, view, now, with_email=with_email)

    def close(self) -> None:
        self._pool.close()


def _configure(conn: Conn) -> None:
    conn.read_only = True
    conn.isolation_level = IsolationLevel.REPEATABLE_READ
