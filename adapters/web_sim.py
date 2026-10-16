"""Web chat adapter (phase 3): the page at `/chat` posts JSON; replies return in the response.

Proves the plugin design (#4, #16): same `InboundEvent` and `Reply` as Telegram, no flow logic.
The page can only answer a request, so it never pushes (`can_push_anytime=False`): the Done
message is the non-push text (#87) and announcements skip these fans (#76).

Body: `{user, msg_id, kind: start|choice|text, text?, choice_id?, choice_step?, src?}`. The body
is untrusted, so `parse` checks every field and returns None instead of raising.
"""

import re
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from adapters.base import Capabilities, Inbound, SendError, Tap
from core.types import EventKind, InboundEvent, Reply

CHANNEL = "web_sim"
MAX_BODY_BYTES = 4096
USER_ID = re.compile(r"[A-Za-z0-9-]{8,64}")  # a random id the page makes per load (#83)
MSG_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")
MAX_FIELD = 64
COMMANDS: dict[str, EventKind] = {
    "/start": "start",
    "/stop": "stop",
    "/delete": "delete",
    "/help": "help",
}
CAPABILITIES = Capabilities(buttons=True, max_buttons=20, has_phone=False, can_push_anytime=False)


def parse_body(body: Any, received_at: datetime) -> Inbound | None:
    """A valid body becomes an event; anything malformed is None (the route answers 400)."""
    if not isinstance(body, dict):
        return None
    user, msg_id, kind = body.get("user"), body.get("msg_id"), body.get("kind")
    if not _matches(USER_ID, user) or not _matches(MSG_ID, msg_id):
        return None
    common: dict[str, Any] = {
        "channel": CHANNEL,
        "external_user_id": user,
        "external_msg_id": msg_id,
        "ts": received_at,  # the client's clock is not trusted
    }
    if kind == "start":
        src = body.get("src")
        if src is not None and not isinstance(src, str):
            return None
        return Inbound(InboundEvent(kind="start", source_tag=src or None, **common))
    if kind == "choice":
        step, choice = body.get("choice_step"), body.get("choice_id")
        if not _short_text(step) or not _short_text(choice):
            return None
        return Inbound(InboundEvent(kind="choice", choice_step=step, choice_id=choice, **common))
    if kind == "text":
        text = body.get("text")
        return Inbound(_text_event(text, common)) if isinstance(text, str) and text else None
    return None


def _matches(pattern: re.Pattern[str], value: Any) -> bool:
    return isinstance(value, str) and pattern.fullmatch(value) is not None


def _short_text(value: Any) -> bool:
    return isinstance(value, str) and 0 < len(value) <= MAX_FIELD


def _text_event(text: str, common: dict[str, Any]) -> InboundEvent:
    """Typed commands map to the same kinds as Telegram; the length cap is the core's (#95)."""
    head, _, rest = text.strip().partition(" ")
    kind = COMMANDS.get(head.lower()) if head.startswith("/") else None
    if kind is None:
        return InboundEvent(kind="text", text=text, **common)
    tag = (rest.strip() or None) if kind == "start" else None
    return InboundEvent(kind=kind, source_tag=tag, **common)


def render_reply(reply: Reply) -> dict[str, Any]:
    """Option ids are the core's, so a tap sends back the same step/choice pair Telegram does."""
    options = [{"id": o.id, "label": o.label} for o in reply.options or ()]
    return {
        "text": reply.text,
        "step_id": reply.step_id,
        "expects": reply.expects,
        "options": options,
    }


class WebSimAdapter:
    channel = CHANNEL
    capabilities = CAPABILITIES

    def authorized(self, headers: Mapping[str, str]) -> bool:
        return True  # a public page; the route rate-limits by IP instead

    def parse(self, body: Any, received_at: datetime) -> Inbound | None:
        return parse_body(body, received_at)

    def render(self, reply: Reply) -> dict[str, Any]:
        return render_reply(reply)

    async def send(self, external_user_id: str, reply: Reply) -> None:
        raise SendError("web chat cannot push; replies go back in the HTTP response")

    async def answer_tap(self, tap: Tap) -> None:
        return None  # the page swaps its own buttons for "✓ <choice>"

    async def confirm_tap(self, tap: Tap) -> None:
        return None
