"""Dashboard sign-in tokens: random, kept in server memory, expire after a fixed time.

Streamlit forgets `session_state` on every page reload, new tab or dropped connection. After the
password check the dashboard hands the browser one of these tokens in a cookie, so the next session
from the same browser signs in without the password until the token expires or the server restarts.
"""

import secrets
from datetime import datetime, timedelta

from core.clock import Clock

SESSION_HOURS = 12
SESSION_SECONDS = SESSION_HOURS * 3600
MAX_TOKENS = 1_000


class SessionTokens:
    def __init__(self, clock: Clock, ttl: timedelta = timedelta(hours=SESSION_HOURS)) -> None:
        self._clock, self._ttl = clock, ttl
        self._expires: dict[str, datetime] = {}

    def issue(self) -> str:
        now = self._clock.now()
        self._expires = {t: at for t, at in self._expires.items() if at > now}
        while len(self._expires) >= MAX_TOKENS:
            del self._expires[next(iter(self._expires))]  # the oldest goes first
        token = secrets.token_urlsafe(32)
        self._expires[token] = now + self._ttl
        return token

    def valid(self, token: str | None) -> bool:
        expires = self._expires.get(token) if token else None
        return expires is not None and expires > self._clock.now()

    def revoke(self, token: str | None) -> None:
        if token:
            self._expires.pop(token, None)
