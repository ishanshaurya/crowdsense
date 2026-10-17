"""Dashboard wording and the latest-fans rows (#60, #107): formatting only, no database."""

import re
from datetime import UTC, date, datetime

from core.catalog import VENUES
from core.demand import Budget, DemandReport, LatestFan
from core.insights import Funnel
from core.overview import RankedCity
from dashboard import text
from dashboard.views import latest_rows
from tests.support import ROOT, decision

PUNE_LAWNS = VENUES[8]


def report(**changes: object) -> DemandReport:
    base: dict[str, object] = {
        "view": "simulated",
        "started": 20_000,
        "counted": 17_012,
        "cities": [],
        "venues": [],
        "budget": Budget({}, {}),
        "groups": {},
        "heatmap": [],
        "funnel": Funnel(0, 0, {}),
        "weekly": [],
        "growth": {},
        "sources": {},
        "latest": [],
        "recommendations": [],
    }
    return DemandReport(**(base | changes))  # type: ignore[arg-type]


@decision(107)
def test_banner_shows_view_counted_and_started() -> None:
    assert text.banner(report()) == (
        "Updated just now · Simulated dataset · 17,012 counted fans (20,000 started)"
    )
    real = report(view="real", started=2, counted=1)
    assert text.banner(real) == "Updated just now · Real data · 1 counted fan (2 started)"


@decision(56)
def test_current_week_is_labelled_so_far() -> None:
    assert text.week_label(date(2026, 10, 12), in_progress=True) == "2026-10-12 (so far)"
    assert text.week_label(date(2026, 10, 5), in_progress=False) == "2026-10-05"


def ranked(trend: str, percent: int | None, price: str | None = "1500_3000") -> RankedCity:
    return RankedCity(1, "Pune", PUNE_LAWNS, 4_120, 69, "mid", price, trend, percent)  # type: ignore[arg-type]


@decision(31, 79)
def test_recommendation_names_the_city_and_venue() -> None:
    html = text.recommendation_html(ranked("up", 40))
    assert "Recommended next show" in html and "Pune · Koregaon Park Lawns" in html
    assert "Nothing to recommend yet" in text.recommendation_html(None)


def test_trend_text_and_html() -> None:
    assert text.trend_text("up", 210) == "+210%" and text.trend_text("down", -12) == "-12%"
    assert text.trend_text("new", None) == "New" and text.trend_text("flat", None) == "Steady"
    assert text.trend_html("up", 5) == '<span class="trend trend-up">+5%</span>'


def test_no_emoji_in_dashboard_sources() -> None:
    """The look rule: no emoji anywhere in the dashboard code or styles."""
    emoji = re.compile("[\U0001f300-\U0001faff\u2600-\u27bf\u2b50]")
    for path in (ROOT / "dashboard").glob("*"):
        if path.suffix in {".py", ".css"}:
            assert not emoji.search(path.read_text(encoding="utf-8")), path.name


def fan(email: str | None, venue_note: str | None = None) -> LatestFan:
    venue = None if venue_note else PUNE_LAWNS
    at = datetime(2026, 10, 15, 18, 45, tzinfo=UTC)
    return LatestFan(1, at, "Pune", venue, venue_note, "lt_1500", "3_5", email)


@decision(60)
def test_p4_u11_latest_rows_hide_email_and_blank_missing_ones() -> None:
    latest = report(latest=[fan("a@example.com"), fan(None, venue_note="Some club")])
    hidden = latest_rows(latest, show_emails=False)
    assert all("Email" not in row for row in hidden)
    assert hidden[0] == {
        "Completed": "16 Oct 2026, 00:15 IST",
        "City": "Pune",
        "Venue": "Koregaon Park Lawns",
        "Budget": "Under ₹1,500",
        "Group": "3–5",
    }
    assert hidden[1]["Venue"] == "Some club"
    assert [row["Email"] for row in latest_rows(latest, show_emails=True)] == ["a@example.com", ""]
