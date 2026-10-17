"""Numbers the dashboard shows on top of the raw aggregates: percentages, ranks, shares (Q-17).

Pure functions and result types; `core.demand` assembles them into `Overview`. The dashboard
only formats these, it never does arithmetic of its own.
"""

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Literal

from core import insights
from core.catalog import Venue
from core.demand_types import CityCount, VenueCount, WeekCount

Level = Literal["high", "mid", "low"]
Trend = Literal["up", "down", "flat", "new"]
TOP_SHOWN = 5  # rows in the ranked list, bars and the growth chart
HIGH_FILL = 80  # percent of the venue's capacity
MID_FILL = 50


@dataclass(frozen=True)
class CityGrowth:
    this_week: int  # the same rolling 7-day windows as the badge (#85)
    prior_week: int


@dataclass(frozen=True)
class RankedCity:
    rank: int
    city: str
    venue: Venue | None
    people: int
    fill_percent: int | None
    fill_level: Level | None
    price_band: str | None
    trend: Trend
    trend_percent: int | None


@dataclass(frozen=True)
class Kpis:
    counted: int
    new_this_week: int
    cities: int
    cities_growing: int
    top_venue: Venue | None
    top_fill_percent: int | None
    top_trend: Trend
    top_trend_percent: int | None


@dataclass(frozen=True)
class CityBar:
    city: str
    people: int
    share_percent: int  # of the leading city


@dataclass(frozen=True)
class WeekTotal:
    week: date
    fans: int
    in_progress: bool


@dataclass(frozen=True)
class Share:
    key: str
    fans: int
    percent: int


@dataclass(frozen=True)
class VenueFill:
    venue: Venue
    fans: int
    people: int
    fill_percent: int


@dataclass(frozen=True)
class Overview:
    kpis: Kpis = field(default_factory=lambda: Kpis(0, 0, 0, 0, None, None, "flat", None))
    ranked: list[RankedCity] = field(default_factory=list)
    top_cities: list[CityBar] = field(default_factory=list)
    week_totals: list[WeekTotal] = field(default_factory=list)
    top_growth_cities: list[str] = field(default_factory=list)  # for the multi-city line chart
    funnel: list[Share] = field(default_factory=list)  # share of started fans, by furthest step
    price_mix: list[Share] = field(default_factory=list)
    group_mix: list[Share] = field(default_factory=list)
    venue_fill: list[VenueFill] = field(default_factory=list)


def percent_of(part: int, whole: int) -> int:
    return round(part * 100 / whole) if whole > 0 else 0


def growth_percent(growth: CityGrowth | None) -> int | None:
    if growth is None or growth.prior_week <= 0:
        return None
    return round((growth.this_week - growth.prior_week) * 100 / growth.prior_week)


def trend(growth: CityGrowth | None) -> Trend:
    if growth is None:
        return "flat"
    if growth.prior_week <= 0:
        return "new" if growth.this_week > 0 else "flat"
    if growth.this_week > growth.prior_week:
        return "up"
    return "down" if growth.this_week < growth.prior_week else "flat"


def fill_percent(people: int, venue: Venue | None) -> int | None:
    """Expected people as a share of the venue's capacity, capped at a full house."""
    if venue is None or venue.capacity <= 0:
        return None
    return min(percent_of(people, venue.capacity), 100)


def fill_level(percent: int | None) -> Level | None:
    if percent is None:
        return None
    if percent >= HIGH_FILL:
        return "high"
    return "mid" if percent >= MID_FILL else "low"


def has_headroom(people: int, venue: Venue) -> bool:
    """The recommendation's own test: the crowd is at most 80% of capacity (#31c)."""
    return people * 5 <= venue.capacity * 4


@dataclass(frozen=True)
class RoomFit:
    venue: Venue
    fill_percent: int  # the city's expected crowd against this room; over 100 means too small
    bar_percent: int  # the same, capped at a full bar
    picked: bool  # the room recommended for its city


@dataclass(frozen=True)
class CityRooms:
    city: str
    fans: int
    people: int
    rooms: list[RoomFit]  # biggest room first


def rooms_by_city(
    recs: Sequence[insights.CityRecommendation],
    fans: Iterable[tuple[str, int]],
    ranked: Sequence[RankedCity],
    venues: Iterable[Venue],
) -> list[CityRooms]:
    """Every catalog room judged against its city's expected crowd, biggest city first.

    Judging against the whole city, not only the fans who named the room, is how the pick is
    made, so a room marked "recommended" never reads as a poor fit next to a smaller one.
    """
    fan_counts: Counter[str] = Counter()
    for city, count in fans:
        fan_counts[city] += count
    picked = {r.venue.id for r in ranked if r.venue is not None}
    rooms: dict[str, list[Venue]] = {}
    for venue in sorted(venues, key=lambda v: -v.capacity):
        rooms.setdefault(venue.city, []).append(venue)
    result = []
    for rec in sorted(recs, key=lambda r: (-r.attendance, r.city)):
        if rec.city not in rooms:
            continue
        fits = [
            RoomFit(
                v,
                percent_of(rec.attendance, v.capacity),
                min(percent_of(rec.attendance, v.capacity), 100),
                v.id in picked,
            )
            for v in rooms[rec.city]
        ]
        result.append(CityRooms(rec.city, fan_counts[rec.city], rec.attendance, fits))
    return result


@dataclass(frozen=True)
class BudgetStack:
    cities: list[str]  # biggest first
    bands: list[str]  # cheapest first
    cells: list[tuple[str, str, int]]  # (city, band, fans)


def budget_stack(by_city: Mapping[str, Mapping[str, int]]) -> BudgetStack:
    totals = {city: sum(bands.values()) for city, bands in by_city.items()}
    return BudgetStack(
        sorted(totals, key=lambda c: (-totals[c], c)),
        list(insights.BAND_ORDER),
        [(city, band, fans) for city, bands in by_city.items() for band, fans in bands.items()],
    )


def ranked_cities(
    recs: Sequence[insights.CityRecommendation], counts: Mapping[str, CityGrowth]
) -> list[RankedCity]:
    ranked = []
    for rank, rec in enumerate(recs[:TOP_SHOWN], start=1):
        fill = fill_percent(rec.attendance, rec.venue)
        growth_of_city = counts.get(rec.city)
        ranked.append(
            RankedCity(
                rank=rank,
                city=rec.city,
                venue=rec.venue,
                people=rec.attendance,
                fill_percent=fill,
                fill_level=fill_level(fill),
                price_band=rec.price_band,
                trend=trend(growth_of_city),
                trend_percent=growth_percent(growth_of_city),
            )
        )
    return ranked


def shares(counts: Mapping[str, int]) -> list[Share]:
    whole = sum(counts.values())
    return [Share(key, fans, percent_of(fans, whole)) for key, fans in counts.items()]


def week_totals(rows: Sequence[WeekCount]) -> list[WeekTotal]:
    fans: Counter[date] = Counter()
    open_weeks: set[date] = set()
    for w in rows:
        fans[w.week] += w.fans
        if w.in_progress:
            open_weeks.add(w.week)
    return [WeekTotal(week, fans[week], week in open_weeks) for week in sorted(fans)]


def top_growth_cities(rows: Sequence[WeekCount]) -> list[str]:
    fans: Counter[str] = Counter()
    for w in rows:
        fans[w.city] += w.fans
    return [city for city, _ in fans.most_common(TOP_SHOWN)]


def kpis(
    counted: int,
    city_counts: Sequence[CityCount],
    counts: Mapping[str, CityGrowth],
    recs: Sequence[insights.CityRecommendation],
    ranked: Sequence[RankedCity],
) -> Kpis:
    top = ranked[0] if ranked else None
    return Kpis(
        counted=counted,
        new_this_week=sum(g.this_week for g in counts.values()),
        cities=len(city_counts),
        cities_growing=sum(1 for r in recs if r.badge == "growing"),
        top_venue=top.venue if top else None,
        top_fill_percent=top.fill_percent if top else None,
        top_trend=top.trend if top else "flat",
        top_trend_percent=top.trend_percent if top else None,
    )


def build_overview(
    counted: int,
    city_counts: Sequence[CityCount],
    venue_counts: Sequence[VenueCount],
    overall_bands: Mapping[str, int],
    group_counts: Mapping[str, int],
    steps: insights.Funnel,
    weeks: Sequence[WeekCount],
    counts: Mapping[str, CityGrowth],
    recs: Sequence[insights.CityRecommendation],
) -> Overview:
    ranked = ranked_cities(recs, counts)
    leader = city_counts[0].people if city_counts else 0
    return Overview(
        kpis=kpis(counted, city_counts, counts, recs, ranked),
        ranked=ranked,
        top_cities=[
            CityBar(c.city, c.people, percent_of(c.people, leader)) for c in city_counts[:TOP_SHOWN]
        ],
        week_totals=week_totals(weeks),
        top_growth_cities=top_growth_cities(weeks),
        funnel=[
            Share(step, fans, percent_of(fans, steps.started))
            for step, fans in steps.by_furthest_step.items()
        ],
        price_mix=shares(overall_bands),
        group_mix=shares(group_counts),
        venue_fill=[
            VenueFill(v.venue, v.fans, v.people, fill_percent(v.people, v.venue) or 0)
            for v in venue_counts
        ],
    )
