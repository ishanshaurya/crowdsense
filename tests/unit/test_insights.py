from dataclasses import replace
from datetime import timedelta
from typing import Any

import pytest

from core import insights
from core.catalog import VENUES
from core.store import FanRow
from core.types import MarkCompleted
from tests.support import NOW, choose, decision, finished_fan, load_yaml, start

CASES = load_yaml("insights_cases.yaml")
VENUE_ID = {v.name: v.id for v in VENUES}
VENUE_NAME = {v.id: v.name for v in VENUES}
_ids = iter(range(1, 10_000))


def fan(
    city: str | None = "Pune",
    *,
    venue: str | None = None,
    completed: bool = True,
    **fields: Any,
) -> FanRow:
    note = fields.pop("venue_note", None)
    return FanRow(
        id=next(_ids),
        city=city,
        venue_id=VENUE_ID[venue] if venue else None,
        venue_note=note,
        budget_band=fields.pop("budget_band", None),
        group_size=fields.pop("group_size", None),
        email=None,
        is_simulated=False,
        completed_at=NOW if completed else None,
        furthest_step=fields.pop("furthest_step", "done" if completed else "group"),
        created_at=NOW,
        last_seen=NOW,
    )


def fans_of(case: list[dict[str, Any]]) -> list[FanRow]:
    return [fan(f["city"], **{k: v for k, v in f.items() if k != "city"}) for f in case]


def by_name(demand: dict[int, insights.VenueDemand]) -> dict[str, dict[str, int]]:
    return {VENUE_NAME[v]: {"fans": d.fans, "people": d.people} for v, d in demand.items()}


@decision(31, 33)
def test_p1_u20_attendance_sums_people_not_fans() -> None:
    case = CASES["people_sum_and_venue_pick"]
    fans = fans_of(case["fans"])
    assert insights.city_attendance(fans) == case["expect"]["city_attendance"]
    assert by_name(insights.venue_demand(fans)) == case["expect"]["venue_demand"]


@decision(31)
def test_p1_u21_suggested_venue_is_the_smallest_fit() -> None:
    case = CASES["people_sum_and_venue_pick"]
    attendance = insights.city_attendance(fans_of(case["fans"]))["Pune"]
    venue = insights.suggested_venue("Pune", attendance, VENUES)
    assert venue is not None
    assert venue.name == case["expect"]["suggested_venue"]["Pune"]


def suggested(row: dict[str, Any]) -> str:
    venue = insights.suggested_venue(row["city"], row["attendance"], VENUES)
    return venue.name if venue else "none"


@decision(31)
@pytest.mark.parametrize(
    "row",
    [r for r in CASES["venue_rule"]["cases"] if r["attendance"] != 25000],
    ids=lambda r: str(r["attendance"]),
)
def test_p1_u22_boundary_is_inclusive_at_80_percent_fill(row: dict[str, Any]) -> None:
    assert suggested(row) == row["suggested"]


@decision(31)
def test_p1_u23_demand_above_every_venue_gives_the_largest() -> None:
    (row,) = [r for r in CASES["venue_rule"]["cases"] if r["attendance"] == 25000]
    assert suggested(row) == row["suggested"] == "Mahalaxmi Maidan"


@decision(32, 79)
@pytest.mark.parametrize("row", CASES["price_band"]["cases"], ids=lambda r: str(r["expect"]))
def test_p1_u24_price_band_is_the_mode_and_ties_go_lower(row: dict[str, Any]) -> None:
    assert (insights.price_band(row["budgets"]) or "none") == row["expect"]


@decision(32, 79)
def test_p1_u24_price_band_is_per_city_and_counted_only() -> None:
    fans = [
        fan("Pune", budget_band="lt_1500"),
        fan("Pune", budget_band="gte_6000", completed=False),
        fan("Mumbai", budget_band="gte_6000"),
    ]
    assert insights.price_band_by_city(fans) == {"Pune": "lt_1500", "Mumbai": "gte_6000"}


@decision(31)
def test_p1_u25_cities_sorted_by_attendance_descending() -> None:
    case = CASES["city_priority_order"]
    assert insights.city_priority(case["city_attendance_input"]) == case["expect"]["order"]


@decision(31, 85)
@pytest.mark.parametrize("row", CASES["growth_badge"]["cases"], ids=lambda r: str(r["this_week"]))
def test_p1_u26_growth_badge_thresholds(row: dict[str, Any]) -> None:
    badge = insights.growth_badge(row["this_week"], row["prior_week"])
    expected = {True: "growing", False: None, "new": "new", "none": None}[row["badge"]]
    assert badge == expected


@decision(31, 85)
def test_p1_u26_growth_counts_completed_fans_in_rolling_windows() -> None:
    def done(days_ago: float, city: str = "Pune", completed: bool = True) -> FanRow:
        row = fan(city, completed=completed)
        return replace(row, completed_at=NOW - timedelta(days=days_ago) if completed else None)

    this_week = [done(1), done(3), done(6.9)]
    prior_week = [done(7.1), done(10)]
    too_old = [done(14.1), done(40)]
    partial = [done(0, completed=False)]
    badges = insights.growth_by_city(this_week + prior_week + too_old + partial, NOW)
    assert badges == {"Pune": "growing"}  # 3 vs 2 = +50%
    assert insights.growth_by_city([done(2)], NOW) == {"Pune": "new"}


@decision(31)
def test_p1_u27_partial_fans_change_no_number() -> None:
    case = CASES["completed_only"]
    fans = fans_of(case["fans"])
    assert insights.city_attendance(fans) == case["expect"]["city_attendance"]
    funnel = insights.funnel(fans)
    assert (funnel.started, funnel.completed) == (2, 1)


@decision(27, 31)
def test_p1_u29_other_venue_counts_for_city_not_venue() -> None:
    case = CASES["other_venue_counts_in_city"]
    fans = fans_of(case["fans"])
    assert insights.city_attendance(fans) == case["expect"]["city_attendance"]
    assert by_name(insights.venue_demand(fans)) == case["expect"]["venue_demand"]
    assert insights.price_band_by_city(fans) == case["expect"]["price_band"]


@decision(31)
def test_p1_u30_empty_data_gives_empty_results() -> None:
    assert insights.city_attendance([]) == {}
    assert insights.venue_demand([]) == {}
    assert insights.price_band_by_city([]) == {}
    assert insights.growth_by_city([], NOW) == {}
    assert insights.recommend([], VENUES, NOW) == []
    assert insights.funnel([]) == insights.Funnel(0, 0, {})
    assert insights.city_priority({}) == []


@decision(70)
def test_p1_u31_edit_keeps_a_fan_counted() -> None:
    state = start(finished_fan()).state
    result = choose(state, "city")
    assert not any(isinstance(w, MarkCompleted) for w in result.writes)
    row = fan("Pune", group_size="2", venue="Baner Greens")
    assert insights.counted([row]) == [row]


@decision(51, 70)
def test_p1_u32_changed_city_counts_for_city_but_no_venue() -> None:
    row = fan("Mumbai", group_size="3_5", budget_band="1500_3000")  # venue cleared, not re-picked
    assert insights.city_attendance([row]) == {"Mumbai": 4}
    assert insights.venue_demand([row]) == {}
    assert insights.price_band_by_city([row]) == {"Mumbai": "1500_3000"}


@decision(84)
def test_p1_u33_funnel_counts_by_furthest_step() -> None:
    rows = [
        fan(completed=False, furthest_step="consent"),
        fan(completed=False, furthest_step="budget"),
        fan(completed=False, furthest_step="budget"),
        fan(furthest_step="done"),
    ]
    funnel = insights.funnel(rows)
    assert funnel.by_furthest_step == {"consent": 1, "budget": 2, "done": 1}
    assert (funnel.started, funnel.completed) == (4, 1)


@decision(31)
def test_recommend_composes_the_rules() -> None:
    rows = fan_group("Pune", ["1", "2", "3_5", "6_plus"]) + fan_group("Jaipur", ["2"])
    result = insights.recommend(rows, VENUES, NOW)
    assert [r.city for r in result] == ["Pune", "Jaipur"]
    pune = result[0]
    assert (pune.attendance, pune.venue.name if pune.venue else None) == (13, "Koregaon Park Lawns")
    assert pune.price_band == "1500_3000"


def fan_group(city: str, groups: list[str]) -> list[FanRow]:
    return [fan(city, group_size=g, budget_band="1500_3000") for g in groups]
