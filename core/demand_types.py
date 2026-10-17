"""Row types of the dashboard read path (`core.demand`): plain frozen data, no logic."""

from dataclasses import dataclass
from datetime import date, datetime

from core.catalog import Venue


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
