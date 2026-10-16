"""Per-IP token bucket for the public web chat routes (docs/plan.md Phase 3).

In process memory: fine for one laptop process, like `RecentTaps`. Memory stays bounded: idle
buckets (refilled to full) are dropped when the table grows, and at most `max_keys` are kept.
"""

import time
from collections.abc import Callable, Mapping


class RateLimiter:
    def __init__(
        self,
        *,
        capacity: float = 60,
        per_second: float = 1.0,
        max_keys: int = 10_000,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._capacity, self._rate, self._max_keys = capacity, per_second, max_keys
        self._clock = clock
        self._buckets: dict[str, tuple[float, float]] = {}  # key -> (tokens, updated)

    def hit(self, key: str) -> float:
        """Take one token. Returns 0 when allowed, else the seconds to wait (for Retry-After)."""
        now = self._clock()
        tokens, updated = self._buckets.get(key, (self._capacity, now))
        tokens = min(self._capacity, tokens + (now - updated) * self._rate)
        if tokens < 1:
            self._buckets[key] = (tokens, now)
            return (1 - tokens) / self._rate
        if key not in self._buckets and len(self._buckets) >= self._max_keys:
            self._prune(now)
        self._buckets[key] = (tokens - 1, now)
        return 0.0

    def _prune(self, now: float) -> None:
        full = self._capacity / self._rate
        self._buckets = {k: v for k, v in self._buckets.items() if now - v[1] < full}
        while len(self._buckets) >= self._max_keys:  # still full of active keys: drop the oldest
            del self._buckets[min(self._buckets, key=lambda k: self._buckets[k][1])]

    def __len__(self) -> int:
        return len(self._buckets)


def client_ip(headers: Mapping[str, str], peer: str | None) -> str:
    """The socket peer, unless the request came through the local ngrok agent.

    ngrok connects from localhost and appends the address it saw to `X-Forwarded-For`, so the
    last entry is the one ngrok wrote; earlier entries come from the client and can be forged
    (#99).
    """
    forwarded = headers.get("x-forwarded-for", "")
    if peer in ("127.0.0.1", "::1") and forwarded.strip():
        return forwarded.split(",")[-1].strip()
    return peer or "unknown"
