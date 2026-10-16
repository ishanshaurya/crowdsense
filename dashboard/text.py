"""Labels and sentences for the dashboard. Formatting only; every number comes from core.demand."""

from datetime import date, datetime
from zoneinfo import ZoneInfo

from core.catalog import BUDGET_OPTIONS, GROUP_OPTIONS, Venue
from core.demand import IST, DemandReport
from core.insights import Badge, CityRecommendation

BAND_LABEL = {o.id: o.label for o in BUDGET_OPTIONS}
GROUP_LABEL = {o.id: o.label for o in GROUP_OPTIONS}
STEP_LABEL = {
    "consent": "Consent",
    "city": "City",
    "venue": "Venue",
    "venue_note": "Venue note",
    "budget": "Budget",
    "group": "Group size",
    "email": "Email",
    "done": "Done",
}
VIEW_LABEL = {"simulated": "Simulated data", "real": "Real"}
BADGE_LABEL: dict[Badge | None, str] = {"growing": "📈 Growing", "new": "🆕 New", None: ""}
OTHER = "Other / not listed"
NO_TAG = "no tag"
_IST = ZoneInfo(IST)


def banner(report: DemandReport) -> str:
    """#107: the view (as a coloured badge, P4-C06), counted fans, started fans."""
    colour = "orange" if report.view == "simulated" else "green"
    fans = "fan" if report.counted == 1 else "fans"
    return (
        f":{colour}-badge[{VIEW_LABEL[report.view]}] **{report.counted:,} counted {fans}** "
        f"({report.started:,} started)"
    )


def venue_label(venue: Venue | None) -> str:
    return venue.name if venue is not None else OTHER


def band_label(band: str | None) -> str:
    return BAND_LABEL.get(band or "", "")


def week_label(week: date, in_progress: bool) -> str:
    """The current week is still filling up; say so, or the chart reads as a drop."""
    return f"{week.isoformat()} (so far)" if in_progress else week.isoformat()  # ISO sorts


def when(at: datetime) -> str:
    return at.astimezone(_IST).strftime("%d %b %Y, %H:%M IST")


def hero(rec: CityRecommendation | None) -> str:
    """The top recommendation in plain words (#31, #79)."""
    if rec is None or rec.venue is None:
        return "No fan has finished the chat in this view yet, so there is nothing to recommend."
    lines = [
        f"### Play **{rec.city}** first, at **{rec.venue.name}**",
        f"About **{rec.attendance:,} people** want to come (the venue holds "
        f"{rec.venue.capacity:,}).",
    ]
    if rec.price_band is not None:
        lines.append(f"Price tickets at **{band_label(rec.price_band)}**: most fans picked it.")
    if rec.badge == "growing":
        lines.append("Demand is **growing**: up 20% or more on the week before.")
    elif rec.badge == "new":
        lines.append("Demand is **new** this week.")
    return "\n\n".join(lines)
