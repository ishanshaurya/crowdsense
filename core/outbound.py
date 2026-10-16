"""Announcements (#53, #59, #75, #80): the dashboard only asks, the webhook service decides.

A request row holds a city and a ticket-open date. Here, inside one transaction, the oldest
pending request is claimed (`SKIP LOCKED`), the text is built from the fixed template, one unsent
priority-1 reply is queued per fan in the audience (#85), and the request is marked fanned out.
The sweeper then sends those replies like any other, after chat replies (#72). A crash after a
send but before `mark_sent` sends that one message again (at-least-once, as for chat replies).
"""

import logging
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

import psycopg

from core.clock import Clock
from core.demand import IST
from core.store import Store
from core.types import Reply

log = logging.getLogger("crowdsense.outbound")

ANNOUNCEMENT_TEXT = "{artist} is coming to {city}. Tickets open {date}."  # message-script #15
_IST = ZoneInfo(IST)


def announcement_reply(artist: str, city: str, event_date: date) -> Reply:
    """The exact text a fan receives; the dashboard preview uses this too (P5-U07)."""
    when = event_date.strftime("%d %b %Y").lstrip("0")
    return Reply(ANNOUNCEMENT_TEXT.format(artist=artist, city=city, date=when), "announcement")


def today_ist(now: datetime) -> date:
    return now.astimezone(_IST).date()


@dataclass(frozen=True)
class FanOut:
    request_id: int
    recipients: int  # 0 when the date had already passed


class Outbound:
    def __init__(self, store: Store, clock: Clock, *, artist_name: str) -> None:
        self._store, self._clock, self._artist = store, clock, artist_name

    async def fan_out_next(self) -> FanOut | None:
        """Fan out one pending request; None when there is none. Raises on store errors."""
        now = self._clock.now()
        async with self._store.transaction() as tx:
            request = await tx.claim_announcement()
            if request is None:
                return None
            if request.event_date < today_ist(now):  # no CHECK can hold this over time
                log.warning("announcement %d is for a past date; nothing queued", request.id)
                await tx.finish_announcement(request.id, 0, now)
                return FanOut(request.id, 0)
            reply = announcement_reply(self._artist, request.city, request.event_date)
            count = await tx.fan_out(request.id, request.city, reply, now)
            await tx.finish_announcement(request.id, count, now)
        log.info("announcement %d queued for %d fans in %s", request.id, count, request.city)
        return FanOut(request.id, count)


# The dashboard side (#75): run inside `DemandReader.snapshot()`, as the dashboard role.


def audience_count(conn: psycopg.Connection[Any], city: str) -> int:
    """How many fans an announcement for `city` reaches; the count, never the rows."""
    row = conn.execute("SELECT announcement_audience_count(%s)", (city,)).fetchone()
    return int(row[0]) if row else 0


def request_announcement(conn: psycopg.Connection[Any], city: str, event_date: date) -> bool:
    """The role's one write (#80); False when this city and date is already queued.

    Its transactions default to read-only, so this one opts in. No RETURNING (the role cannot
    read the table). The savepoint keeps a duplicate from aborting the caller's transaction.
    """
    conn.execute("SET TRANSACTION READ WRITE")
    try:
        with conn.transaction():
            conn.execute(
                "INSERT INTO announcement_requests (city, event_date) VALUES (%s, %s)",
                (city, event_date),
            )
    except psycopg.errors.UniqueViolation:
        return False
    return True
