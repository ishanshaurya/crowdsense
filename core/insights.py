"""Recommendation rules as pure functions (#31 to #33, #49 to #52, #70, #79, #85).

Input is fan rows and venues; nothing here reads a database or the clock. Streamlit only draws.
"""

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from core.catalog import BUDGET_OPTIONS, Venue
from core.flow import FUNNEL_ORDER
from core.store import FanRow

# Group bucket -> people (#33).
PEOPLE_PER_GROUP = {"1": 1, "2": 2, "3_5": 4, "6_plus": 6}
BAND_ORDER = tuple(o.id for o in BUDGET_OPTIONS)

Badge = Literal["growing", "new"]


@dataclass(frozen=True)
class VenueDemand:
    fans: int
    people: int


@dataclass(frozen=True)
class Funnel:
    started: int
    completed: int
    by_furthest_step: dict[str, int]


@dataclass(frozen=True)
class CityRecommendation:
    city: str
    attendance: int
    venue: Venue | None
    price_band: str | None
    badge: Badge | None


def counted(fans: Iterable[FanRow]) -> list[FanRow]:
    """A fan counts from the first time they reach done and stays counted (#52, #70)."""
    return [fan for fan in fans if fan.completed_at is not None]


def people(fan: FanRow) -> int:
    return PEOPLE_PER_GROUP.get(fan.group_size or "", 0)


def city_attendance(fans: Iterable[FanRow]) -> dict[str, int]:
    """Expected attendance per city: people summed over counted fans."""
    totals: Counter[str] = Counter()
    for fan in counted(fans):
        if fan.city is not None:
            totals[fan.city] += people(fan)
    return dict(totals)


def venue_demand(fans: Iterable[FanRow]) -> dict[int, VenueDemand]:
    """Per-venue demand for ranking; fans with no venue ("Other", re-asked) are skipped (#51)."""
    fan_counts: Counter[int] = Counter()
    people_counts: Counter[int] = Counter()
    for fan in counted(fans):
        if fan.venue_id is not None:
            fan_counts[fan.venue_id] += 1
            people_counts[fan.venue_id] += people(fan)
    return {v: VenueDemand(fan_counts[v], people_counts[v]) for v in fan_counts}


def suggested_venue(city: str, attendance: int, venues: Iterable[Venue]) -> Venue | None:
    """Smallest venue with capacity >= attendance / 0.8, else the city's largest (#31c)."""
    in_city = sorted((v for v in venues if v.city == city), key=lambda v: v.capacity)
    if attendance <= 0 or not in_city:
        return None
    fits = [v for v in in_city if v.capacity * 4 >= attendance * 5]
    return fits[0] if fits else in_city[-1]


def price_band(bands: Iterable[str | None]) -> str | None:
    """Most common band; a tie picks the lower band (#50)."""
    counts = Counter(b for b in bands if b is not None)
    if not counts:
        return None
    return min(counts, key=lambda b: (-counts[b], BAND_ORDER.index(b)))


def price_band_by_city(fans: Iterable[FanRow]) -> dict[str, str]:
    per_city: dict[str, list[str | None]] = {}
    for fan in counted(fans):
        if fan.city is not None:
            per_city.setdefault(fan.city, []).append(fan.budget_band)
    bands = {city: price_band(values) for city, values in per_city.items()}
    return {city: band for city, band in bands.items() if band is not None}


def city_priority(attendance: Mapping[str, int]) -> list[str]:
    return sorted(attendance, key=lambda city: (-attendance[city], city))


def growth_badge(this_week: int, prior_week: int) -> Badge | None:
    """+20% or more over the prior 7 days; "new" when the prior 7 days were empty (A5)."""
    if prior_week == 0:
        return "new" if this_week > 0 else None
    return "growing" if this_week * 5 >= prior_week * 6 else None


def growth_by_city(fans: Iterable[FanRow], now: datetime) -> dict[str, Badge | None]:
    """Rolling 7 days vs the 7 days before, by `completed_at` (#85)."""
    recent_from, prior_from = now - timedelta(days=7), now - timedelta(days=14)
    windows: dict[str, tuple[int, int]] = {}
    for fan in counted(fans):
        if fan.city is None or fan.completed_at is None or fan.completed_at <= prior_from:
            continue
        this_week, prior_week = windows.get(fan.city, (0, 0))
        if fan.completed_at > recent_from:
            windows[fan.city] = (this_week + 1, prior_week)
        else:
            windows[fan.city] = (this_week, prior_week + 1)
    return {city: growth_badge(*counts) for city, counts in windows.items()}


def funnel(fans: Sequence[FanRow]) -> Funnel:
    """Fans by furthest step reached (#84); `completed` is `completed_at` set."""
    steps = Counter(fan.furthest_step for fan in fans if fan.furthest_step is not None)
    return Funnel(
        started=len(fans),
        completed=len(counted(fans)),
        by_furthest_step={step: steps[step] for step in FUNNEL_ORDER if step in steps},
    )


def recommend(
    fans: Sequence[FanRow], venues: Sequence[Venue], now: datetime
) -> list[CityRecommendation]:
    attendance = city_attendance(fans)
    bands = price_band_by_city(fans)
    badges = growth_by_city(fans, now)
    return [
        CityRecommendation(
            city,
            attendance[city],
            suggested_venue(city, attendance[city], venues),
            bands.get(city),
            badges.get(city),
        )
        for city in city_priority(attendance)
    ]
