"""One engine turn = one transaction (#55, docs/architecture.md §5).

input caps (#95) -> identity lock (#88) -> dedupe -> load state -> `decide` -> apply writes and
log replies -> commit. The caller sends the returned replies after the commit and then calls
`mark_sent` (#86).
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import datetime

from core.clock import Clock
from core.decide import decide
from core.store import SNAPSHOT_COLUMNS, FanRow, IdentityRow, SessionRow, Store, Tx
from core.types import (
    Decision,
    DeleteFan,
    FanState,
    InboundEvent,
    MarkCompleted,
    Reply,
    SaveAnswer,
    SetConsent,
    SetOptedOut,
    Write,
)

MAX_TEXT = 1000
SOURCE_TAG = re.compile(r"[A-Za-z0-9_-]{1,64}")  # Telegram's deep-link rule (#95)


def cap_inbound(event: InboundEvent) -> InboundEvent:
    """Cut text to `MAX_TEXT` characters; drop a source tag that breaks the pattern (#95)."""
    text = event.text[:MAX_TEXT] if event.text is not None else None
    tag = event.source_tag
    if tag is not None and not SOURCE_TAG.fullmatch(tag):
        tag = None
    return replace(event, text=text, source_tag=tag)


@dataclass(frozen=True)
class Outgoing:
    """A reply to send. `id` is None when it was never stored (the /delete confirmation, #81)."""

    id: int | None
    reply: Reply


@dataclass(frozen=True)
class TurnResult:
    """`applied` is True when the event changed the fan's state (a stale tap does not, #91)."""

    replies: tuple[Outgoing, ...] = ()
    duplicate: bool = False
    applied: bool = False


class Engine:
    def __init__(
        self,
        store: Store,
        clock: Clock,
        *,
        artist_name: str,
        push_channels: frozenset[str] = frozenset({"telegram"}),
        simulated: bool = False,
    ) -> None:
        self._store = store
        self._clock = clock
        self._artist = artist_name
        self._push_channels = push_channels
        self._simulated = simulated

    async def handle(self, event: InboundEvent) -> TurnResult:
        event = cap_inbound(event)
        now = self._clock.now()
        async with self._store.transaction() as tx:
            identity = await tx.lock_identity(
                event.channel, event.external_user_id, event.source_tag
            )
            if not await tx.record_event(event, now, identity.fan_id):
                rows = await tx.unsent_replies(event.channel, event.external_msg_id)
                return TurnResult(tuple(Outgoing(r.id, r.reply) for r in rows), duplicate=True)
            fan_id = identity.fan_id
            if fan_id is None:
                fan_id = await tx.create_fan(
                    event.channel, event.external_user_id, is_simulated=self._simulated, now=now
                )
                await tx.link_event(event.channel, event.external_msg_id, fan_id)
                state = FanState(consent=identity.consent, opted_out=identity.opted_out)
            else:
                state = _state_of(identity, *await tx.load_state(fan_id))
            decision = decide(
                state,
                event,
                now,
                artist=self._artist,
                can_push=event.channel in self._push_channels,
            )
            return await _apply(tx, event, fan_id, state, decision, now)

    async def mark_sent(self, sent: Sequence[Outgoing]) -> None:
        ids = [o.id for o in sent if o.id is not None]
        if ids:
            async with self._store.transaction() as tx:
                await tx.mark_sent(ids)

    async def opt_out_blocked(self, channel: str, external_user_id: str) -> int:
        """The fan blocked the bot (#93): opt the identity out and drop its unsent replies.

        One transaction; returns how many replies were dropped.
        """
        async with self._store.transaction() as tx:
            await tx.set_opted_out(channel, external_user_id, True)
            return await tx.drop_unsent(channel, external_user_id)

    async def drop_unsent(self, channel: str, external_user_id: str) -> int:
        """The channel refused a message for good: drop the identity's unsent replies, which
        would fail the same way. The fan stays opted in; their next message is answered."""
        async with self._store.transaction() as tx:
            return await tx.drop_unsent(channel, external_user_id)


def _state_of(identity: IdentityRow, fan: FanRow, session: SessionRow) -> FanState:
    return FanState(
        step_id=session.step_id,
        consent=identity.consent,
        opted_out=identity.opted_out,
        answers=_answers_of(fan),
        completed=fan.completed_at is not None,
        furthest_step=fan.furthest_step,
    )


def _answers_of(fan: FanRow) -> dict[str, str]:
    values = {field: getattr(fan, column) for field, column in SNAPSHOT_COLUMNS.items()}
    return {field: str(value) for field, value in values.items() if value is not None}


async def _apply(
    tx: Tx,
    event: InboundEvent,
    fan_id: int,
    state: FanState,
    decision: Decision,
    now: datetime,
) -> TurnResult:
    if any(isinstance(w, DeleteFan) for w in decision.writes):
        if state.furthest_step is not None:
            await tx.bump_funnel(state.furthest_step)
        await tx.delete_fan(fan_id)
        return TurnResult(tuple(Outgoing(None, r) for r in decision.replies), applied=True)
    for write in decision.writes:
        await _write(tx, event, fan_id, write, now)
    await tx.save_progress(fan_id, decision.state.step_id, decision.state.furthest_step, now)
    outgoing = [
        Outgoing(await tx.add_reply(fan_id, event.channel, event.external_msg_id, r, now), r)
        for r in decision.replies
    ]
    applied = bool(decision.writes) or decision.state.step_id != state.step_id
    return TurnResult(tuple(outgoing), applied=applied)


async def _write(tx: Tx, event: InboundEvent, fan_id: int, write: Write, now: datetime) -> None:
    channel, user = event.channel, event.external_user_id
    match write:
        case SaveAnswer(field, value):
            await tx.record_answer(fan_id, field, value, now)
        case SetConsent(value):
            await tx.set_consent(channel, user, value)
        case SetOptedOut(value):
            await tx.set_opted_out(channel, user, value)
            if value:  # /stop: nothing queued earlier (an announcement) may still go out (#36)
                await tx.drop_unsent(channel, user)
        case MarkCompleted(at):
            await tx.mark_completed(fan_id, at)
        case DeleteFan():
            pass
