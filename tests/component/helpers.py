from itertools import count

from core.engine import Engine
from tests.support import event

_ids = count(1)


async def talk(
    engine: Engine, user: str, moves: list[tuple[str, str]], *, channel: str = "telegram"
):  # type: ignore[no-untyped-def]
    """Send ("start"|"choice"|"text", value) moves as `user`; return the last TurnResult."""
    result = None
    step_id: str | None = None
    for kind, value in moves:
        msg_id = f"{user}-{channel}-{next(_ids)}"
        common = {"user": user, "channel": channel, "msg_id": msg_id}
        if kind == "start":
            ev = event("start", source_tag=value or None, **common)
        elif kind == "choice":
            ev = event("choice", choice_id=value, choice_step=step_id, **common)
        else:
            ev = event("text", text=value, **common)
        result = await engine.handle(ev)
        await engine.mark_sent(result.replies)
        if result.replies:
            step_id = result.replies[-1].reply.step_id
    return result


def flow(city: str, venue_id: str, band: str, group: str) -> list[tuple[str, str]]:
    return [
        ("start", ""),
        ("choice", "yes"),
        ("choice", city),
        ("choice", venue_id),
        ("choice", band),
        ("choice", group),
        ("choice", "skip"),
    ]
