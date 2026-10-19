"""HTML snippets the dashboard draws itself: the announcement ticket and the artist card."""

from datetime import date
from html import escape


def ticket(artist: str, city: str, day: date, fans: int) -> str:
    """The announcement drawn as a ticket; every value is escaped, never markdown."""
    when = day.strftime("%d %b %Y").lstrip("0")
    noun = "fan" if fans == 1 else "fans"
    waiting = "Nobody waiting yet" if fans == 0 else f"{fans} {noun} will hear first"
    return (
        '<div class="ticket"><div class="ticket-main">'
        '<div class="ticket-kicker">Roomcall presents</div>'
        f'<div class="ticket-artist">{escape(artist)}</div>'
        f'<div class="ticket-msg">Live in {escape(city)}. Tickets open {when}.</div>'
        f'<div class="ticket-fans">{waiting}</div></div>'
        f'<div class="ticket-stub"><span>{escape(city)}</span>'
        f"<b>{day.strftime('%d %b').lstrip('0')}</b>"
        "<em>Admit one</em></div></div>"
    )


def artist_card(artist: str) -> str:
    return (
        f'<div class="artist-card"><i>{escape(artist[:1])}</i>'
        f"<div><b>{escape(artist)}</b><br><span>Artist account</span></div></div>"
    )
