"""Pure decision core (docs/architecture.md §9): (state, event, now) -> Decision.

No I/O, no clock, no randomness. The engine loads the state and applies the writes.
"""

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime

from core import flow
from core.flow import Step
from core.types import (
    Decision,
    DeleteFan,
    FanState,
    InboundEvent,
    MarkCompleted,
    Option,
    Reply,
    SaveAnswer,
    SetConsent,
    SetOptedOut,
    Write,
)


@dataclass(frozen=True)
class _Ctx:
    now: datetime
    artist: str
    can_push: bool


@dataclass(frozen=True)
class _Picked:
    choice: str | None = None
    text: str | None = None


def decide(
    state: FanState, event: InboundEvent, now: datetime, *, artist: str, can_push: bool
) -> Decision:
    ctx = _Ctx(now, artist, can_push)
    if event.kind == "delete":
        return Decision(state, (Reply(flow.DELETED_TEXT, "deleted"),), (DeleteFan(),))
    if event.kind == "help":
        return Decision(state, (Reply(flow.HELP_TEXT.format(artist=artist), "help"),))
    if event.kind == "stop":
        return _stop(state)
    if event.kind == "start":
        return _start(state, ctx)
    if state.opted_out:
        return Decision(state)
    return _respond(state, event, ctx)


def _stop(state: FanState) -> Decision:
    if state.opted_out:
        return Decision(state)
    reply = Reply(flow.STOPPED_TEXT, "stopped")
    return Decision(replace(state, opted_out=True), (reply,), (SetOptedOut(True),))


def _start(state: FanState, ctx: _Ctx) -> Decision:
    writes: tuple[Write, ...] = ()
    if state.opted_out:
        state = replace(state, opted_out=False)
        writes += (SetOptedOut(False),)
    if state.consent is False:
        state = replace(state, consent=None, step_id="consent")
        writes += (SetConsent(None),)
    if state.step_id in ("done", "edit_menu"):
        return _menu(state, writes)
    step = flow.STEP_BY_ID[state.step_id]
    return Decision(_move(state, step.id), (_ask(step, state.answers, ctx),), writes)


def _respond(state: FanState, event: InboundEvent, ctx: _Ctx) -> Decision:
    if event.kind == "choice" and event.choice_step not in (None, state.step_id):
        return Decision(state, (Reply(flow.STALE_TEXT, state.step_id, is_error=True),))
    if state.step_id == "declined":
        return Decision(state, (Reply(flow.DECLINED_TEXT, "declined"),))
    if state.step_id == "done":
        return _menu(state, ())
    if state.step_id == "edit_menu":
        return _from_menu(state, event, ctx)
    return _from_step(flow.STEP_BY_ID[state.step_id], state, event, ctx)


def _menu(state: FanState, writes: tuple[Write, ...]) -> Decision:
    reply = Reply(flow.edit_menu_text(state.answers), "edit_menu", flow.EDIT_OPTIONS, "choice")
    return Decision(replace(state, step_id="edit_menu"), (reply,), writes)


def _from_menu(state: FanState, event: InboundEvent, ctx: _Ctx) -> Decision:
    picked = _pick(event, flow.EDIT_OPTIONS)
    if picked is None:
        reply = Reply(
            flow.INVALID_CHOICE_TEXT, "edit_menu", flow.EDIT_OPTIONS, "choice", is_error=True
        )
        return Decision(state, (reply,))
    return _enter(state, flow.MENU_TARGETS[picked], state.answers, (), ctx)


def _from_step(step: Step, state: FanState, event: InboundEvent, ctx: _Ctx) -> Decision:
    options = flow.step_options(step, state.answers)
    picked = _read(step, event, options)
    if picked is None:
        reply = Reply(step.invalid, step.id, options, step.expects, is_error=True)
        return Decision(state, (reply,))
    value = _value_of(step, picked)
    answers, saves = _record(step, state.answers, value)
    writes: tuple[Write, ...] = saves
    if step.id == "consent":
        state = replace(state, consent=picked.choice == "yes")
        writes += (SetConsent(state.consent),)
    nxt = _next_step(step, picked.choice, state.completed, changed=bool(saves))
    return _enter(state, nxt, answers, writes, ctx)


def _value_of(step: Step, picked: _Picked) -> str | None:
    if picked.choice is None:
        return picked.text
    return None if picked.choice == step.null_choice else picked.choice


def _read(step: Step, event: InboundEvent, options: tuple[Option, ...] | None) -> _Picked | None:
    if options:
        choice = _pick(event, options)
        if choice is not None:
            return _Picked(choice=choice)
    if event.kind == "text" and step.validate and event.text is not None:
        text = step.validate(event.text)
        return _Picked(text=text) if text is not None else None
    return None


def _pick(event: InboundEvent, options: tuple[Option, ...]) -> str | None:
    if event.kind == "choice":
        return event.choice_id if event.choice_id in {o.id for o in options} else None
    typed = (event.text or "").strip().casefold()
    return next((o.id for o in options if o.label.casefold() == typed), None)


def _record(
    step: Step, answers: Mapping[str, str], value: str | None
) -> tuple[dict[str, str], tuple[SaveAnswer, ...]]:
    if step.field is None or value == answers.get(step.field):
        return dict(answers), ()
    writes = [SaveAnswer(step.field, value)]
    if value is not None:
        writes += [SaveAnswer(f, None) for f in step.clears if f in answers]
    updated = {k: v for k, v in answers.items() if k not in {w.field for w in writes}}
    updated.update({w.field: w.value for w in writes if w.value is not None})
    return updated, tuple(writes)


def _next_step(step: Step, choice: str | None, completed: bool, *, changed: bool) -> str:
    branch = step.branches.get(choice) if choice else None
    if branch:
        return branch
    if completed:
        return step.edit_next if changed else "done"
    return step.next


def _enter(
    state: FanState,
    step_id: str,
    answers: Mapping[str, str],
    writes: tuple[Write, ...],
    ctx: _Ctx,
) -> Decision:
    state = replace(_move(state, step_id), answers=answers)
    if step_id == "declined":
        return Decision(state, (Reply(flow.DECLINED_TEXT, "declined"),), writes)
    if step_id == "done":
        return _finish(state, writes, ctx)
    return Decision(state, (_ask(flow.STEP_BY_ID[step_id], answers, ctx),), writes)


def _finish(state: FanState, writes: tuple[Write, ...], ctx: _Ctx) -> Decision:
    text = flow.DONE_PUSH_TEXT if ctx.can_push else flow.DONE_NO_PUSH_TEXT
    reply = Reply(text.format(artist=ctx.artist), "done")
    if state.completed:
        return Decision(state, (reply,), writes)
    return Decision(replace(state, completed=True), (reply,), (*writes, MarkCompleted(ctx.now)))


def _move(state: FanState, step_id: str) -> FanState:
    furthest = state.furthest_step
    if flow.funnel_rank(step_id) > flow.funnel_rank(furthest):
        furthest = step_id
    return replace(state, step_id=step_id, furthest_step=furthest)


def _ask(step: Step, answers: Mapping[str, str], ctx: _Ctx) -> Reply:
    return Reply(
        step.prompt.format(artist=ctx.artist),
        step.id,
        flow.step_options(step, answers),
        step.expects,
    )
