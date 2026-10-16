"""One draw function per view (`docs/architecture.md` §7). Streamlit only draws (Q-17)."""

from typing import Any

import streamlit as st

from core.demand import DemandReport
from dashboard.text import (
    BADGE_LABEL,
    GROUP_LABEL,
    NO_TAG,
    OTHER,
    STEP_LABEL,
    band_label,
    banner,
    hero,
    venue_label,
    week_label,
    when,
)

Table = list[dict[str, Any]]
EMPTY = "Nothing in this view yet."


def _section(title: str, data: object) -> bool:
    """Heading, then a caption instead of an empty chart when the view has no data."""
    st.subheader(title)
    if not data:
        st.caption(EMPTY)
    return bool(data)


def draw_banner(report: DemandReport) -> None:
    st.markdown(banner(report))


def draw_hero(report: DemandReport) -> None:
    with st.container(border=True):
        st.markdown(hero(report.recommendations[0] if report.recommendations else None))


def draw_recommendations(report: DemandReport) -> None:
    if not _section("Recommendations by city", report.recommendations):
        return
    rows: Table = [
        {
            "City": r.city,
            "Expected people": r.attendance,
            "Suggested venue": venue_label(r.venue),
            "Capacity": r.venue.capacity if r.venue else None,
            "Price band": band_label(r.price_band),
            "Trend": BADGE_LABEL[r.badge],
        }
        for r in report.recommendations
    ]
    st.dataframe(rows, hide_index=True)


def draw_cities(report: DemandReport) -> None:
    if not _section("Top cities", report.cities):
        return
    data = {"City": [c.city for c in report.cities], "People": [c.people for c in report.cities]}
    st.bar_chart(data, x="City", y="People", horizontal=True, sort=False)
    st.dataframe(
        [{"City": c.city, "Fans": c.fans, "People": c.people} for c in report.cities],
        hide_index=True,
    )


def draw_venues(report: DemandReport) -> None:
    if not _section("Top venues", report.venues):
        return
    rows: Table = [
        {"Venue": v.venue.name, "City": v.venue.city, "Fans": v.fans, "People": v.people}
        for v in report.venues
    ]
    st.dataframe(rows, hide_index=True)


def draw_budget(report: DemandReport) -> None:
    if not _section("Budget bands", report.budget.overall):
        return
    overall = report.budget.overall
    data = {"Band": [band_label(b) for b in overall], "Fans": list(overall.values())}
    st.bar_chart(data, x="Band", y="Fans", sort=False)
    rows: Table = [
        {"City": city} | {band_label(b): n for b, n in bands.items()}
        for city, bands in report.budget.by_city.items()
    ]
    st.dataframe(rows, hide_index=True)


def draw_groups(report: DemandReport) -> None:
    if not _section("Group sizes", report.groups):
        return
    groups = report.groups
    data = {"Group": [GROUP_LABEL[g] for g in groups], "Fans": list(groups.values())}
    st.bar_chart(data, x="Group", y="Fans", sort=False)


def draw_heatmap(report: DemandReport) -> None:
    if not _section("City × venue", report.heatmap):
        return
    cells: Table = [
        {"City": c.city, "Venue": venue_label(c.venue), "Fans": c.fans} for c in report.heatmap
    ]
    venues = [*dict.fromkeys(c["Venue"] for c in cells if c["Venue"] != OTHER), OTHER]
    axes = {
        "x": {"field": "Venue", "type": "nominal", "sort": venues, "axis": {"labelAngle": -35}},
        "y": {"field": "City", "type": "nominal"},
    }
    spec = {
        "height": 360,
        "layer": [
            {
                "mark": "rect",
                "encoding": axes | {"color": {"field": "Fans", "type": "quantitative"}},
            },
            {"mark": "text", "encoding": axes | {"text": {"field": "Fans", "format": ","}}},
        ],
    }
    st.vega_lite_chart(cells, spec)


def draw_funnel(report: DemandReport) -> None:
    funnel = report.funnel
    if not _section("Response funnel", funnel.by_furthest_step):
        return
    st.caption(f"{funnel.started:,} started · {funnel.completed:,} completed")
    steps = funnel.by_furthest_step
    data = {"Furthest step": [STEP_LABEL[s] for s in steps], "Fans": list(steps.values())}
    st.bar_chart(data, x="Furthest step", y="Fans", sort=False)


def draw_weekly(report: DemandReport) -> None:
    if not _section("Growth per city (IST weeks)", report.weekly):
        return
    data = {
        "Week": [week_label(w.week, w.in_progress) for w in report.weekly],
        "City": [w.city for w in report.weekly],
        "Fans": [w.fans for w in report.weekly],
    }
    st.line_chart(data, x="Week", y="Fans", color="City")
    badges = [f"{city}: {BADGE_LABEL[b]}" for city, b in report.growth.items() if b]
    st.caption(" · ".join(badges) or "No city is growing this week.")


def draw_sources(report: DemandReport) -> None:
    if not _section("Sources", report.sources):
        return
    data = {
        "Source": [tag or NO_TAG for tag in report.sources],
        "Fans": list(report.sources.values()),
    }
    st.bar_chart(data, x="Source", y="Fans", sort=False)


def latest_rows(report: DemandReport, show_emails: bool) -> Table:
    """Email column only after the toggle; blank when a fan left none (#60, P4-U11)."""
    rows: Table = []
    for fan in report.latest:
        row = {
            "Completed": when(fan.completed_at),
            "City": fan.city or "",
            "Venue": fan.venue.name if fan.venue else (fan.venue_note or ""),
            "Budget": band_label(fan.budget_band),
            "Group": GROUP_LABEL.get(fan.group_size or "", ""),
        }
        if show_emails:
            row["Email"] = fan.email or ""
        rows.append(row)
    return rows


def draw_latest(report: DemandReport, show_emails: bool) -> None:
    rows = latest_rows(report, show_emails)
    if _section("Latest fans", rows):
        st.table(rows, hide_index=True)  # st.table has no download button: emails never export


def draw_all(report: DemandReport, show_emails: bool) -> None:
    draw_banner(report)
    draw_hero(report)
    draw_recommendations(report)
    left, right = st.columns(2)
    with left:
        draw_cities(report)
        draw_budget(report)
        draw_funnel(report)
    with right:
        draw_venues(report)
        draw_groups(report)
        draw_sources(report)
    draw_heatmap(report)
    draw_weekly(report)
    draw_latest(report, show_emails)
