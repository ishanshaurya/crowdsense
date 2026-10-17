"""Resend sweeper (#72): every 5 s, claim unsent replies, send, mark sent.

Each pass first fans out pending announcement requests (#80, `core.outbound`); their replies are
priority 1, so chat replies are claimed before them, and they skip the age wait (nothing else is
sending them), so an announcement goes out within one tick.

Chat replies must be 10 s old: that keeps the sweeper away from replies the webhook is still
sending. Claims use `FOR UPDATE SKIP LOCKED`, so two sweepers never take the same row.
Delivery is at-least-once: a crash after a send but before the commit sends that reply again.
"""

import asyncio
import logging
from collections.abc import Mapping
from datetime import timedelta

from adapters.base import Adapter
from api.sender import Outcome, Sender, block
from core.clock import Clock
from core.engine import Engine
from core.outbound import Outbound
from core.store import Store

log = logging.getLogger("crowdsense.sweeper")


class Sweeper:
    def __init__(
        self,
        store: Store,
        engine: Engine,
        sender: Sender,
        adapters: Mapping[str, Adapter],
        clock: Clock,
        *,
        interval: float = 5.0,
        min_age: float = 10.0,
        batch: int = 50,
        outbound: Outbound | None = None,
    ) -> None:
        self._store, self._engine, self._sender = store, engine, sender
        self._adapters, self._clock = adapters, clock
        self.interval, self.min_age, self.batch = interval, min_age, batch
        self._outbound = outbound

    async def sweep_once(self) -> int:
        """One pass; returns how many replies were sent."""
        if self._outbound is not None:
            while await self._outbound.fan_out_next() is not None:
                pass
        cutoff = self._clock.now() - timedelta(seconds=self.min_age)
        stuck: set[tuple[str, str]] = set()
        blocked: set[tuple[str, str]] = set()
        async with self._store.transaction() as tx:
            rows = await tx.claim_unsent(cutoff, self.batch, channels=set(self._adapters))
            sent = []
            for row in rows:
                who = (row.channel, row.external_user_id or "")
                if row.external_user_id is None or who in stuck:
                    continue  # keep each fan's replies in order
                outcome = await self._sender.send(
                    self._adapters[row.channel], row.external_user_id, row.reply
                )
                if outcome is Outcome.SENT:
                    sent.append(row.id)
                else:
                    stuck.add(who)
                    if outcome is Outcome.BLOCKED:
                        blocked.add(who)
            if sent:
                await tx.mark_sent(sent)
        # After the commit: dropping the replies here would wait on our own row locks.
        for channel, user in blocked:
            await block(self._engine, channel, user)
        return len(sent)

    async def run(self) -> None:
        """Loop until cancelled (the webhook's lifespan cancels it on shutdown)."""
        while True:
            try:
                count = await self.sweep_once()
                if count:
                    log.info("sweeper resent %d replies", count)
            except Exception:
                log.exception("sweep failed; trying again next round")
            await asyncio.sleep(self.interval)
