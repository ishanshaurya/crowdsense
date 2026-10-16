"""What each simulated fan says, decided up front from one random seed (#40, #78, P3-U03).

Pure: no I/O, no clock. `plan_fans` returns the turns; `scripts/seed.py` plays them through the
engine. Shares and rates below were approved for phase 3 (notes/phase-3.md, "Seed shape").
"""

import random
from dataclasses import dataclass
from datetime import datetime, timedelta

from core.catalog import BUDGET_OPTIONS, GROUP_OPTIONS, VENUES
from core.types import EventKind

CHANNEL = "seed"  # no adapter, not a push channel (#102)
WEEKS = 6
CITY_SHARE = {
    "Mumbai": 20,
    "Delhi NCR": 18,
    "Bengaluru": 16,
    "Hyderabad": 9,
    "Pune": 9,
    "Kolkata": 7,
    "Chennai": 7,
    "Ahmedabad": 5,
    "Jaipur": 5,
    "Indore": 4,
}
RISING = {"Jaipur": 1.35, "Indore": 1.35}  # weekly growth; other cities stay flat (#40)
DECLINE_RATE, DROP_RATE, OTHER_VENUE_RATE, EMAIL_RATE = 0.05, 0.10, 0.05, 0.30
METROS = {"Mumbai", "Delhi NCR", "Bengaluru"}
BUDGET_WEIGHTS = {"metro": (10, 35, 35, 20), "other": (25, 45, 22, 8)}
GROUP_WEIGHTS = (20, 40, 30, 10)
SOURCE_TAGS = {"ig_story": 40, "ig_bio": 25, "poster": 20, "yt": 15}
VENUE_NOTES = (
    "Near the metro",
    "Somewhere central",
    "Any open ground",
    "Close to my college",
    "Old city side",
)
STEPS = ("city", "venue", "budget", "group", "email")

Move = tuple[EventKind, str | None, str | None]  # kind, choice_step, choice_id or text


@dataclass(frozen=True)
class FanPlan:
    user: str
    city: str
    week: int  # 0 = oldest, WEEKS - 1 = the last 7 days
    start: datetime
    source_tag: str
    moves: tuple[Move, ...]  # after the /start


def plan_fans(count: int, seed: int, now: datetime) -> list[FanPlan]:
    rng = random.Random(seed)
    cities = list(CITY_SHARE)
    picked = rng.choices(cities, [CITY_SHARE[c] for c in cities], k=count)
    weeks = _weeks(picked, rng)
    return [_plan_one(n, city, weeks[n], rng, now) for n, city in enumerate(picked)]


def _weeks(picked: list[str], rng: random.Random) -> list[int]:
    """A fixed quota per city and week (growth^week), shuffled: the trend is exact, not noisy."""
    weeks = [0] * len(picked)
    for city in sorted(set(picked)):  # a set of str iterates in hash order: not reproducible
        fans = [n for n, c in enumerate(picked) if c == city]
        growth = RISING.get(city, 1.0)
        weights = [growth**w for w in range(WEEKS)]
        quotas = [int(len(fans) * w / sum(weights)) for w in weights]
        quotas[-1] += len(fans) - sum(quotas)
        slots = [w for w, q in enumerate(quotas) for _ in range(q)]
        rng.shuffle(slots)
        for n, week in zip(fans, slots, strict=True):
            weeks[n] = week
    return weeks


def _plan_one(n: int, city: str, week: int, rng: random.Random, now: datetime) -> FanPlan:
    week_start = now - timedelta(days=7 * (WEEKS - week))
    start = week_start + timedelta(seconds=rng.uniform(0, 7 * 86400 - 3600))
    tags = list(SOURCE_TAGS)
    tag = rng.choices(tags, [SOURCE_TAGS[t] for t in tags])[0]
    return FanPlan(f"seed-{n:06d}", city, week, start, tag, _moves(n, city, rng))


def _moves(n: int, city: str, rng: random.Random) -> tuple[Move, ...]:
    roll = rng.random()
    if roll < DECLINE_RATE:
        return (("choice", "consent", "no"),)
    stop_at = rng.choice(STEPS) if roll < DECLINE_RATE + DROP_RATE else None
    moves: list[Move] = [("choice", "consent", "yes")]
    for step in STEPS:
        if step == stop_at:
            break
        moves.extend(_answer(n, step, city, rng))
    return tuple(moves)


def _answer(n: int, step: str, city: str, rng: random.Random) -> list[Move]:
    if step == "city":
        return [("choice", "city", city)]
    if step == "venue":
        if rng.random() < OTHER_VENUE_RATE:
            return [("choice", "venue", "other"), ("text", None, rng.choice(VENUE_NOTES))]
        in_city = [v for v in VENUES if v.city == city]
        weights = [3, 2][: len(in_city)]  # bigger venue first in the catalog
        return [("choice", "venue", str(rng.choices(in_city, weights)[0].id))]
    if step == "budget":
        weights = BUDGET_WEIGHTS["metro" if city in METROS else "other"]
        return [("choice", "budget", rng.choices(BUDGET_OPTIONS, weights)[0].id)]
    if step == "group":
        return [("choice", "group", rng.choices(GROUP_OPTIONS, GROUP_WEIGHTS)[0].id)]
    if rng.random() < EMAIL_RATE:
        return [("text", None, f"fan{n:06d}@example.com")]
    return [("choice", "email", "skip")]
