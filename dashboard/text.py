"""Labels and sentences for the dashboard. Formatting only; every number comes from core.demand."""

from datetime import date, datetime
from html import escape
from zoneinfo import ZoneInfo

from core.catalog import BUDGET_OPTIONS, GROUP_OPTIONS, Venue
from core.demand import IST, DemandReport
from core.overview import CityRooms, RankedCity, RoomFit, Trend, has_headroom

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
DATASET_LABEL = {"simulated": "Simulated dataset", "real": "Real data"}
ANNOUNCE_TITLE = "Announce a show"
NOBODY = "Nobody to notify in this city yet."
PAST_DATE = "Pick today or a later date."
QUEUED = "Queued. Fans get it within a minute or two."
ALREADY_QUEUED = "Already queued for this city and date."
STATUS_LABEL = {"pending": "Waiting", "fanned_out": "Queued for fans"}
TREND_WORD: dict[Trend, str] = {"up": "Up", "down": "Down", "flat": "Steady", "new": "New"}
OTHER = "Other / not listed"
NO_TAG = "no tag"
_IST = ZoneInfo(IST)


def banner(report: DemandReport) -> str:
    """#107: which dataset, counted fans, started fans. Plain text: the label is what matters."""
    fans = "fan" if report.counted == 1 else "fans"
    return (
        f"Updated just now · {DATASET_LABEL[report.view]} · "
        f"{report.counted:,} counted {fans} ({report.started:,} started)"
    )


def will_send(count: int) -> str:
    return f"Will send to {count:,} {'fan' if count == 1 else 'fans'}"


def venue_label(venue: Venue | None) -> str:
    return venue.name if venue is not None else OTHER


def band_label(band: str | None) -> str:
    return BAND_LABEL.get(band or "", "")


def week_label(week: date, in_progress: bool) -> str:
    """The current week is still filling up; say so, or the chart reads as a drop."""
    return f"{week.isoformat()} (so far)" if in_progress else week.isoformat()  # ISO sorts


def when(at: datetime) -> str:
    return at.astimezone(_IST).strftime("%d %b %Y, %H:%M IST")


def trend_text(trend: Trend, percent: int | None) -> str:
    """The row trend: a signed percent when the prior week had fans, else a word."""
    if percent is not None and trend in ("up", "down"):
        return f"{percent:+d}%"
    return TREND_WORD[trend]


def trend_html(trend: Trend, percent: int | None) -> str:
    return f'<span class="trend trend-{trend}">{trend_text(trend, percent)}</span>'


def recommendation_html(top: RankedCity | None) -> str:
    """The top pick as a compact strip heading (#31, #79); the figures sit beside it."""
    if top is None or top.venue is None:
        return (
            '<div class="rec-label">Recommended next show</div>'
            '<div class="rec-title">Nothing to recommend yet</div>'
            '<div class="rec-sub">No fan has finished the chat in this view.</div>'
        )
    return (
        '<div class="rec-label">Recommended next show</div>'
        f'<div class="rec-title">{escape(top.city)} · {escape(top.venue.name)}</div>'
    )


def stat_html(label: str, value: str) -> str:
    return (
        f'<div class="stat-label">{escape(label)}</div>'
        f'<div class="stat-value">{escape(value)}</div>'
    )


FIT_CEILING = 80  # percent of capacity: the smallest room at or under this is recommended (#31c)
VERDICT = {
    "low": "Spare room",
    "good": "Good fit",
    "tight": "Tight",
    "over": "Too small",
}


def strip_html(items: list[tuple[str, str, str]]) -> str:
    """The headline numbers as one row: (value, label, detail)."""
    cells = "".join(
        f'<div><div class="strip-value">{escape(value)}</div>'
        f'<div class="strip-label">{escape(label)}</div>'
        f'<div class="strip-sub">{escape(sub)}</div></div>'
        for value, label, sub in items
    )
    return f'<div class="strip">{cells}</div>'


def fit_level(fill_percent: int) -> str:
    if fill_percent > 100:
        return "over"
    if fill_percent > FIT_CEILING:
        return "tight"
    return "good" if fill_percent >= 50 else "low"


def fit_line(top: RankedCity) -> str:
    """Why this room: the rule in #31c, in words."""
    if top.venue is None:
        return ""
    if has_headroom(top.people, top.venue):
        return f"The smallest {top.city} room that holds {top.people:,} people with space to spare."
    return f"The largest {top.city} room. Expected demand is bigger than any room there."


def hero_meter_html(fill_percent: int, capacity: int) -> str:
    return (
        f'<div class="room-head"><span>{fill_percent}% full</span>'
        f"<span>Room holds {capacity:,}</span></div>"
        f'<div class="room-track"><span class="room-fill" style="width:{fill_percent}%">'
        f'</span><span class="room-mark" style="left:{FIT_CEILING}%"></span></div>'
        f'<div class="room-foot">The line marks {FIT_CEILING}%. Past it the room gets tight.</div>'
    )


def fit_meter_html(fill_percent: int, bar_percent: int) -> str:
    level = fit_level(fill_percent)
    return (
        f'<div class="fit fit-{level}"><span class="fit-track">'
        f'<span class="fit-fill" style="width:{bar_percent}%"></span>'
        f'<span class="fit-mark" style="left:{FIT_CEILING}%"></span></span>'
        f'<span class="fit-pct">{fill_percent}%</span></div>'
    )


def room_row_html(room: RoomFit) -> str:
    level = fit_level(room.fill_percent)
    pick = '<span class="pick">Recommended</span>' if room.picked else ""
    return (
        f'<div class="room-row"><span class="room-name"><b>{escape(room.venue.name)}</b>{pick}'
        f'</span><span class="room-seats">{room.venue.capacity:,} seats</span>'
        f"{fit_meter_html(room.fill_percent, room.bar_percent)}"
        f'<span class="verdict verdict-{level}">{VERDICT[level]}</span></div>'
    )


def city_block_html(block: CityRooms) -> str:
    rooms = "".join(room_row_html(room) for room in block.rooms)
    return (
        f'<div class="city"><div class="city-head">'
        f'<span class="city-name">{escape(block.city)}</span>'
        f'<span class="city-meta">{block.fans:,} fans · {block.people:,} expected people</span>'
        f"</div>{rooms}</div>"
    )


def bar_row(label: str, value: str, percent: int) -> str:
    return (
        f'<div class="bar-row"><span class="bar-label">{escape(label)}</span>'
        f'<span class="bar-track"><span class="bar-fill" style="width:{percent}%"></span></span>'
        f'<span class="bar-value">{escape(value)}</span></div>'
    )
