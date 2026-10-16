"""Dashboard wording and the latest-fans rows (#60, #107): formatting only, no database."""

from datetime import UTC, date, datetime

from core.catalog import VENUES
from core.demand import Budget, DemandReport, LatestFan
from core.insights import CityRecommendation, Funnel
from dashboard import text
from dashboard.views import latest_rows
from tests.support import decision

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
        ":orange-badge[Simulated data] **17,012 counted fans** (20,000 started)"
    )
    real = report(view="real", started=2, counted=1)
    assert text.banner(real) == ":green-badge[Real] **1 counted fan** (2 started)"


@decision(56)
def test_current_week_is_labelled_so_far() -> None:
    assert text.week_label(date(2026, 10, 12), in_progress=True) == "2026-10-12 (so far)"
    assert text.week_label(date(2026, 10, 5), in_progress=False) == "2026-10-05"


@decision(31, 79)
def test_hero_reads_in_plain_language() -> None:
    rec = CityRecommendation("Pune", 4_120, PUNE_LAWNS, "1500_3000", "growing")
    assert text.hero(rec) == (
        "### Play **Pune** first, at **Koregaon Park Lawns**\n\n"
        "About **4,120 people** want to come (the venue holds 6,000).\n\n"
        "Price tickets at **₹1,500–3,000**: most fans picked it.\n\n"
        "Demand is **growing**: up 20% or more on the week before."
    )
    new = text.hero(CityRecommendation("Pune", 4, PUNE_LAWNS, None, "new"))
    assert "Price" not in new and new.endswith("Demand is **new** this week.")
    assert text.hero(None).startswith("No fan has finished")


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
