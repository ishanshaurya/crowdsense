"""The dashboard's SQL (#57): one string per aggregate, run by `core.demand` in one pipeline.

Every query that reads `fans` filters `is_simulated` by the view (#73) and counts only fans with
`completed_at` set (#52, #70); only the funnel sees partial fans.
"""

from typing import LiteralString

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
