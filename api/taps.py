"""Tells a double tap from a tap on an old question (#91, #92).

Core treats both as stale. A stale tap on a message whose earlier tap was just applied is a
double tap: the fan already got the next question, so the "That question has passed" reply is
marked sent without being delivered. Kept in process memory; after a restart the worst case is
one extra "passed" message.
"""

import time
from collections.abc import Callable

from adapters.base import Tap


class RecentTaps:
    def __init__(self, ttl: float = 60.0, clock: Callable[[], float] = time.monotonic) -> None:
        self._ttl, self._clock = ttl, clock
        self._applied: dict[tuple[str, int], float] = {}

    def remember(self, tap: Tap) -> None:
        if tap.message_id is None:
            return
        now = self._clock()
        self._applied = {k: t for k, t in self._applied.items() if now - t < self._ttl}
        self._applied[(tap.chat_id, tap.message_id)] = now

    def is_double(self, tap: Tap) -> bool:
        if tap.message_id is None:
            return False
        at = self._applied.get((tap.chat_id, tap.message_id))
        return at is not None and self._clock() - at < self._ttl
