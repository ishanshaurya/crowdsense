"""Clock seam (#56): the engine and the seed get time from here, never from `now()` inline."""

from datetime import UTC, datetime, timedelta
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class ScriptedClock:
    def __init__(self, start: datetime) -> None:
        self._now = start

    def now(self) -> datetime:
        return self._now

    def set(self, at: datetime) -> None:
        self._now = at

    def advance(self, delta: timedelta) -> None:
        self._now += delta
