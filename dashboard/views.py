"""One draw function per page (`docs/architecture.md` §7). Streamlit only draws (Q-17)."""

from collections.abc import Callable
from html import escape
from typing import Any

import streamlit as st

from core.catalog import VENUES
from core.demand import DemandReport
from core.overview import budget_stack, rooms_by_city
from dashboard import charts
from dashboard.text import (
    GROUP_LABEL,
    NO_TAG,
    OTHER,
    STEP_LABEL,
    band_label,
    banner,
    bar_row,
    city_block_html,
    fit_line,
    fit_meter_html,
    hero_meter_html,
    recommendation_html,
    stat_html,
    strip_html,
    trend_html,
    trend_text,
    venue_label,
    week_label,
    when,
)

Table = list[dict[str, Any]]
PlanShow = Callable[[str], None]
EMPTY = "Nothing in this view yet."
ROW_WIDTHS = [0.4, 1.2, 3.3, 1.4, 1.7, 1.5, 0.8, 1.3]
ROW_HEADS = ["#", "City", "Room", "Expected crowd", "Room full", "Ticket price", "Trend"]


def _section(name: str) -> Any:
    """A bordered block; Streamlit puts the key on the element as a class for the stylesheet."""
    return st.container(border=True, key=f"sec_{name}")


def _card(title: str, subtitle: str, data: object) -> bool:
    """Card heading, then a caption instead of an empty chart when the view has no data."""
    st.subheader(title)
    if subtitle:
        st.caption(subtitle)
    if not data:
        st.caption(EMPTY)
    return bool(data)


def draw_banner(report: DemandReport) -> None:
    st.markdown(f'<div class="meta">{banner(report)}</div>', unsafe_allow_html=True)


def _strip(report: DemandReport) -> None:
    kpis = report.overview.kpis
    fill = f"{kpis.top_fill_percent}%" if kpis.top_fill_percent is not None else "–"
    st.markdown(
        strip_html(
            [
                (f"{kpis.counted:,}", "Interested fans", f"+{kpis.new_this_week:,} this week"),
                (f"{kpis.cities:,}", "Cities with demand", f"{kpis.cities_growing} growing"),
                (
                    fill,
                    "Fill of the top room",
                    venue_label(kpis.top_venue) if kpis.top_venue else "No room yet",
                ),
                (trend_text_or_dash(report), "Weekly growth", "top city, against last week"),
            ]
        ),
        unsafe_allow_html=True,
    )


def trend_text_or_dash(report: DemandReport) -> str:
    kpis = report.overview.kpis
    return trend_text(kpis.top_trend, kpis.top_trend_percent) if report.overview.ranked else "–"


def _recommendation(report: DemandReport, plan: PlanShow, details: Any) -> None:
    top = report.overview.ranked[0] if report.overview.ranked else None
    with st.container(key="hero"):
        text, facts = st.columns([5, 4], gap="large", vertical_alignment="center")
        with text:
            st.markdown(recommendation_html(top), unsafe_allow_html=True)
            if top is None or top.venue is None:
                return
            reason = f'<div class="rec-sub">{escape(fit_line(top))}</div>'
            st.markdown(reason, unsafe_allow_html=True)
            if st.button("Plan this show", key="plan_hero", type="primary"):
                plan(top.city)
            st.page_link(details, label="See every room")
        with facts:
            stats = [
                ("Expected audience", f"{top.people:,}"),
                ("Ticket price", band_label(top.price_band) or "–"),
            ]
            cells = "".join(f"<div>{stat_html(label, value)}</div>" for label, value in stats)
            meter = hero_meter_html(top.fill_percent or 0, top.venue.capacity)
            st.markdown(f'<div class="hero-stats">{cells}</div>{meter}', unsafe_allow_html=True)


def _ranked(report: DemandReport, plan: PlanShow) -> None:
    with _section("ranked"):
        if not _card(
            "Where to play next",
            "Ranked by fan demand, room fit and growth",
            report.overview.ranked,
        ):
            return
        for column, head in zip(st.columns(ROW_WIDTHS), ROW_HEADS, strict=False):
            align = " num" if head == "Expected crowd" else ""
            column.markdown(f'<span class="th{align}">{head}</span>', unsafe_allow_html=True)
        for row in report.overview.ranked:
            cells = st.columns(ROW_WIDTHS, vertical_alignment="center")
            room = (
                f'**{row.venue.name}** <span class="muted">{row.venue.capacity:,} seats</span>'
                if row.venue
                else OTHER
            )
            cells[0].markdown(f'<span class="muted">{row.rank}</span>', unsafe_allow_html=True)
            cells[1].markdown(f"**{row.city}**")
            cells[2].markdown(room, unsafe_allow_html=True)
            cells[3].markdown(f'<span class="num">{row.people:,}</span>', unsafe_allow_html=True)
            cells[4].markdown(
                fit_meter_html(row.fill_percent, row.fill_percent)
                if row.fill_percent is not None
                else "–",
                unsafe_allow_html=True,
            )
            cells[5].write(band_label(row.price_band) or "–")
            cells[6].markdown(trend_html(row.trend, row.trend_percent), unsafe_allow_html=True)
            if cells[7].button("Plan show", key=f"plan_{row.city}", type="tertiary"):
                plan(row.city)


def _trend_chart(report: DemandReport) -> None:
    with _section("trend_chart"):
        totals = report.overview.week_totals
        if not _card("Demand trend", "Fans who finished the chat, per IST week", totals):
            return
        st.vega_lite_chart(
            [{"Week": week_label(w.week, w.in_progress), "Fans": w.fans} for w in totals],
            charts.trend_spec(),
        )


def draw_dashboard(report: DemandReport, plan: PlanShow, details: Any) -> None:
    _recommendation(report, plan, details)
    _strip(report)
    _ranked(report, plan)
    _trend_chart(report)


def _price_donut(report: DemandReport) -> None:
    with _section("price_donut"):
        mix = report.overview.price_mix
        if not _card("Price range distribution", "What fans are willing to pay", mix):
            return
        labels = [f"{band_label(s.key)} · {s.percent}%" for s in mix]
        st.vega_lite_chart(
            [{"Band": b, "Fans": s.fans} for b, s in zip(labels, mix, strict=True)],
            charts.donut_spec(labels),
        )


def _groups(report: DemandReport) -> None:
    with _section("groups"):
        mix = report.overview.group_mix
        if _card("Group sizes", "Who is coming with whom", mix):
            chips = "".join(
                f'<span class="chip">{GROUP_LABEL[s.key]} <b>{s.percent}%</b></span>' for s in mix
            )
            st.markdown(chips, unsafe_allow_html=True)


def _funnel(report: DemandReport) -> None:
    with _section("funnel"):
        steps = report.overview.funnel
        if not _card("Response funnel", "Where fans stopped in the chat", steps):
            return
        funnel = report.funnel
        st.caption(f"{funnel.started:,} started · {funnel.completed:,} completed")
        st.markdown(
            "".join(bar_row(STEP_LABEL[s.key], f"{s.fans:,}", s.percent) for s in steps),
            unsafe_allow_html=True,
        )


def _sources(report: DemandReport) -> None:
    with _section("sources"):
        if _card("Sources", "Where fans found the chat", report.sources):
            rows: Table = [
                {"Source": tag or NO_TAG, "Fans": fans} for tag, fans in report.sources.items()
            ]
            st.dataframe(rows, hide_index=True)


def _growth(report: DemandReport) -> None:
    with _section("growth"):
        if not _card("Growth per city", "Fans per IST week", report.weekly):
            return
        everyone = st.toggle("Show every city", value=False, key="growth_all")
        shown = report.overview.top_growth_cities
        rows = [w for w in report.weekly if everyone or w.city in shown]
        st.vega_lite_chart(
            [
                {"Week": week_label(w.week, w.in_progress), "City": w.city, "Fans": w.fans}
                for w in rows
            ],
            charts.growth_spec(),
        )


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


def _latest(report: DemandReport, show_emails: bool) -> None:
    with _section("latest"):
        rows = latest_rows(report, show_emails)
        if _card("Latest fans", "The 50 most recent", rows):
            st.table(rows, hide_index=True)  # st.table has no download button: emails never export


def draw_analytics(report: DemandReport, show_emails: bool) -> None:
    price, groups, sources = st.columns(3)
    with price:
        _price_donut(report)
    with groups:
        _groups(report)
    with sources:
        _sources(report)
    funnel, growth = st.columns(2)
    with funnel:
        _funnel(report)
    with growth:
        _growth(report)
    _latest(report, show_emails)


def _rooms(report: DemandReport) -> None:
    with _section("rooms"):
        blocks = rooms_by_city(
            report.recommendations,
            ((cell.city, cell.fans) for cell in report.heatmap),
            report.overview.ranked,
            VENUES,
        )
        if not _card(
            "Rooms by city",
            "Each room against the city's expected crowd. The line marks 80% full.",
            blocks,
        ):
            return
        st.markdown("".join(city_block_html(block) for block in blocks), unsafe_allow_html=True)


def _budget(report: DemandReport) -> None:
    with _section("budget"):
        if not _card(
            "Budget by city", "What fans say they would pay for a ticket", report.budget.by_city
        ):
            return
        stack = budget_stack(report.budget.by_city)
        rows: Table = [
            {"City": city, "Band": band_label(band), "Fans": fans}
            for city, band, fans in stack.cells
        ]
        st.vega_lite_chart(
            rows, charts.budget_spec(stack.cities, [band_label(b) for b in stack.bands])
        )


def draw_cities_venues(report: DemandReport) -> None:
    _rooms(report)
    _budget(report)
