"""Sending replies with Telegram's limits and failure rules (#69, #93).

429 -> wait `retry_after`, then resend (the reply stays unsent meanwhile). 403 -> the fan blocked
the bot. Anything else -> give up for now; the sweeper resends unsent replies later (#72).
"""

import asyncio
import enum
import logging
import time
from collections.abc import Awaitable, Callable, Sequence

from adapters.base import Adapter, Blocked, RetryAfter, SendError
from core.engine import Engine, Outgoing
from core.types import Reply

log = logging.getLogger("crowdsense.sender")

Sleep = Callable[[float], Awaitable[None]]


class Outcome(enum.Enum):
    SENT = "sent"
    BLOCKED = "blocked"
    FAILED = "failed"


class Pacer:
    """Spaces sends about 1 s apart per chat and about 1/30 s apart overall (#69)."""

    def __init__(
        self,
        *,
        per_chat: float = 1.0,
        overall: float = 1 / 30,
        clock: Callable[[], float] = time.monotonic,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        self._per_chat, self._overall = per_chat, overall
        self._clock, self._sleep = clock, sleep
        self._next_any = 0.0
        self._next_in_chat: dict[str, float] = {}

    async def wait(self, chat: str) -> None:
        now = self._clock()
        slot = max(now, self._next_any, self._next_in_chat.get(chat, 0.0))
        self._next_any = slot + self._overall
        self._next_in_chat[chat] = slot + self._per_chat
        if len(self._next_in_chat) > 10_000:
            self._next_in_chat = {c: t for c, t in self._next_in_chat.items() if t > now}
        if slot > now:
            await self._sleep(slot - now)


async def block(engine: Engine, channel: str, user: str) -> None:
    dropped = await engine.opt_out_blocked(channel, user)
    log.info("%s fan blocked the bot: opted out, %d unsent replies dropped", channel, dropped)


class Sender:
    def __init__(
        self, engine: Engine, pacer: Pacer, *, sleep: Sleep = asyncio.sleep, attempts: int = 3
    ) -> None:
        self._engine = engine
        self._pacer = pacer
        self._sleep = sleep
        self._attempts = attempts

    async def send(self, adapter: Adapter, user: str, reply: Reply) -> Outcome:
        """One reply, with 429 waits. Does not touch the database."""
        for attempt in range(1, self._attempts + 1):
            await self._pacer.wait(user)
            try:
                await adapter.send(user, reply)
            except RetryAfter as exc:
                log.warning(
                    "%s rate limited, waiting %.0fs (attempt %d)",
                    adapter.channel,
                    exc.seconds,
                    attempt,
                )
                await self._sleep(exc.seconds)
            except Blocked:
                return Outcome.BLOCKED
            except SendError as exc:
                log.warning("%s send failed, left for the sweeper: %s", adapter.channel, exc)
                return Outcome.FAILED
            else:
                return Outcome.SENT
        return Outcome.FAILED

    async def deliver(self, adapter: Adapter, user: str, replies: Sequence[Outgoing]) -> None:
        """Send a turn's replies in order and mark each one sent (#86). Never raises."""
        try:
            for out in replies:
                outcome = await self.send(adapter, user, out.reply)
                if outcome is Outcome.BLOCKED:
                    await block(self._engine, adapter.channel, user)
                if outcome is not Outcome.SENT:
                    return  # the rest stay unsent, in order, for the sweeper
                await self._engine.mark_sent([out])
        except Exception:
            log.exception(
                "%s delivery stopped; unsent replies are left for the sweeper", adapter.channel
            )
