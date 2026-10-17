"""The numbers behind the dashboard pages (Q-17): fill, growth, shares and ranking, no database."""

from datetime import date

from core.catalog import VENUES
from core.demand_types import CityCount, VenueCount, WeekCount
from core.insights import CityRecommendation, Funnel
from core.overview import (
    CityGrowth,
    budget_stack,
    build_overview,
    fill_level,
    fill_percent,
    growth_percent,
    has_headroom,
    percent_of,
    ranked_cities,
    rooms_by_city,
    trend,
)
from tests.support import decision

PUNE_LAWNS = VENUES[8]  # capacity 6,000 in the catalog


@decision(31, 85)
def test_growth_percent_and_trend_use_the_badge_windows() -> None:
    assert growth_percent(CityGrowth(14, 10)) == 40
    assert growth_percent(CityGrowth(5, 10)) == -50
    assert growth_percent(CityGrowth(3, 0)) is None and growth_percent(None) is None
    assert [trend(CityGrowth(*c)) for c in [(14, 10), (5, 10), (10, 10), (3, 0), (0, 0)]] == [
        "up",
        "down",
        "flat",
        "new",
        "flat",
    ]
    assert trend(None) == "flat"


def test_fill_is_capped_at_a_full_house_and_graded() -> None:
    assert fill_percent(3_000, PUNE_LAWNS) == 50
    assert fill_percent(9_000, PUNE_LAWNS) == 100
    assert fill_percent(10, None) is None
    assert [fill_level(p) for p in (None, 80, 79, 50, 49)] == [None, "high", "mid", "mid", "low"]
    assert percent_of(1, 0) == 0 and percent_of(1, 3) == 33


def test_overview_ranks_five_cities_and_sizes_the_bars_to_the_leader() -> None:
    cities = [CityCount(f"C{i}", 10 - i, (10 - i) * 1_000) for i in range(7)]
    recs = [CityRecommendation(c.city, c.people, PUNE_LAWNS, "1500_3000", None) for c in cities]
    overview = build_overview(
        counted=7,
        city_counts=cities,
        venue_counts=[VenueCount(PUNE_LAWNS, 10, 3_000)],
        overall_bands={"1500_3000": 3, "lt_1500": 1},
        group_counts={"solo": 1},
        steps=Funnel(started=20, completed=7, by_furthest_step={"done": 7, "city": 13}),
        weeks=[
            WeekCount("C0", date(2026, 10, 5), 4),
            WeekCount("C1", date(2026, 10, 5), 1),
            WeekCount("C0", date(2026, 10, 12), 2, in_progress=True),
        ],
        counts={"C0": CityGrowth(4, 2)},
        recs=recs,
    )
    assert [r.rank for r in overview.ranked] == [1, 2, 3, 4, 5]
    assert overview.ranked[0].trend == "up" and overview.ranked[0].trend_percent == 100
    assert [b.share_percent for b in overview.top_cities] == [100, 90, 80, 70, 60]
    assert overview.kpis.cities == 7 and overview.kpis.new_this_week == 4
    assert overview.kpis.top_venue == PUNE_LAWNS and overview.kpis.top_fill_percent == 100
    assert [(w.week.day, w.fans, w.in_progress) for w in overview.week_totals] == [
        (5, 5, False),
        (12, 2, True),
    ]
    assert overview.top_growth_cities == ["C0", "C1"]
    assert [(s.key, s.percent) for s in overview.funnel] == [("done", 35), ("city", 65)]
    assert [(s.key, s.percent) for s in overview.price_mix] == [("1500_3000", 75), ("lt_1500", 25)]
    assert overview.venue_fill[0].fill_percent == 50


def test_overview_of_an_empty_view_is_empty() -> None:
    empty = build_overview(0, [], [], {}, {}, Funnel(0, 0, {}), [], {}, [])
    assert empty.ranked == [] and empty.top_cities == [] and empty.kpis.top_venue is None
    assert empty.kpis.top_trend == "flat"


@decision(31)
def test_rooms_are_judged_against_the_whole_city_crowd() -> None:
    mumbai = [v for v in VENUES if v.city == "Mumbai"]  # 30,000 and 4,000 seats
    recs = [CityRecommendation("Mumbai", 9_828, mumbai[0], None, None)]
    ranked = ranked_cities(recs, {})
    (block,) = rooms_by_city(recs, [("Mumbai", 1_000), ("Mumbai", 2_447)], ranked, VENUES)
    assert block.fans == 3_447 and block.people == 9_828
    big, small = block.rooms
    assert (big.venue.capacity, big.fill_percent, big.picked) == (30_000, 33, True)
    assert (small.fill_percent, small.bar_percent, small.picked) == (246, 100, False)
    assert has_headroom(9_828, mumbai[0]) and not has_headroom(9_828, mumbai[1])
    assert has_headroom(3_200, mumbai[1]) and not has_headroom(3_201, mumbai[1])


def test_budget_stack_puts_the_biggest_city_first_and_bands_cheapest_first() -> None:
    stack = budget_stack({"Pune": {"1500_3000": 5}, "Mumbai": {"lt_1500": 4, "1500_3000": 9}})
    assert stack.cities == ["Mumbai", "Pune"]
    assert stack.bands[0] == "lt_1500"
    assert ("Pune", "1500_3000", 5) in stack.cells
