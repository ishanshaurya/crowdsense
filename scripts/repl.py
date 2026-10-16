"""Dev REPL: play the whole conversation against the engine on the in-memory store.

    uv run python -m scripts.repl

Type a button number or its label, free text, or a command: /start [tag], /stop, /delete,
/help, /rows (show what is stored), /quit. Nothing here touches a database.
"""

import asyncio
import os
import sys
from itertools import count

from core.clock import SystemClock
from core.config import DEFAULT_ARTIST_NAME
from core.engine import Engine, Outgoing
from core.store_memory import InMemoryStore
from core.types import EventKind, InboundEvent, Option

CHANNEL = "repl"
COMMANDS: dict[str, EventKind] = {
    "/start": "start",
    "/stop": "stop",
    "/delete": "delete",
    "/help": "help",
}


def say(text: str = "") -> None:
    sys.stdout.write(text + "\n")


def show(replies: tuple[Outgoing, ...]) -> tuple[tuple[Option, ...], str | None]:
    options: tuple[Option, ...] = ()
    step_id: str | None = None
    for out in replies:
        say(f"\nbot [{out.reply.step_id}]: {out.reply.text}")
        for number, option in enumerate(out.reply.options or (), start=1):
            say(f"  {number}. {option.label}")
        if out.reply.options is not None:
            options, step_id = out.reply.options, out.reply.step_id
    return options, step_id


def parse(line: str, options: tuple[Option, ...], step_id: str | None, msg_id: str) -> InboundEvent:
    common = {
        "channel": CHANNEL,
        "external_user_id": "me",
        "external_msg_id": msg_id,
        "ts": SystemClock().now(),
    }
    word, _, rest = line.partition(" ")
    if word in COMMANDS:
        return InboundEvent(**common, kind=COMMANDS[word], source_tag=rest or None)
    if line.isdigit() and 1 <= int(line) <= len(options):
        choice = options[int(line) - 1].id
        return InboundEvent(**common, kind="choice", choice_id=choice, choice_step=step_id)
    return InboundEvent(**common, kind="text", text=line)


async def rows(store: InMemoryStore) -> None:
    for fan in await store.fans():
        say(f"fan: {fan}")
    for answer in await store.answers():
        say(f"answer: {answer.field} = {answer.value}")
    say(f"funnel_counts: {await store.funnel_counts()}")


async def main() -> None:
    store = InMemoryStore()
    artist = os.environ.get("ARTIST_NAME", DEFAULT_ARTIST_NAME)
    engine = Engine(store, SystemClock(), artist_name=artist, push_channels=frozenset({CHANNEL}))
    ids = count(1)
    options: tuple[Option, ...] = ()
    step_id: str | None = None
    say("Crowdsense dev REPL. Start with /start ig_story. /quit exits.")
    while True:
        line = (await asyncio.to_thread(sys.stdin.readline)).strip()
        if line in ("", "/quit"):
            return
        if line == "/rows":
            await rows(store)
            continue
        result = await engine.handle(parse(line, options, step_id, f"r{next(ids)}"))
        shown_options, shown_step = show(result.replies)
        if shown_step is not None:
            options, step_id = shown_options, shown_step
        await engine.mark_sent(result.replies)


if __name__ == "__main__":
    asyncio.run(main())
