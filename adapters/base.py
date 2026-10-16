"""What every channel adapter provides (docs/architecture.md §3): parse, render, send, capabilities.

Adapters only translate. They never import the flow or the engine (Q-11).
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from core.types import InboundEvent, Reply


@dataclass(frozen=True)
class Capabilities:
    buttons: bool
    max_buttons: int
    has_phone: bool
    can_push_anytime: bool  # once the fan has started the chat


@dataclass(frozen=True)
class Tap:
    """A button press the channel wants acknowledged at once (#92)."""

    id: str
    chat_id: str
    message_id: int | None
    label: str | None  # text on the tapped button, for "✓ <choice>"


@dataclass(frozen=True)
class Inbound:
    """`event` is None when there is nothing for the engine (a "noop" button, a bad tap)."""

    event: InboundEvent | None
    tap: Tap | None = None


class SendError(Exception):
    """The channel did not take the message. The reply stays unsent for the sweeper (#72)."""


class RetryAfter(SendError):
    def __init__(self, seconds: float) -> None:
        super().__init__(f"retry after {seconds}s")
        self.seconds = seconds


class Blocked(SendError):
    """The fan blocked the bot; opt the identity out (#93)."""


class Adapter(Protocol):
    channel: str
    capabilities: Capabilities

    def authorized(self, headers: Mapping[str, str]) -> bool: ...

    def parse(self, body: Any, received_at: datetime) -> Inbound | None:
        """None for anything the bot does not handle; never raises on odd input."""
        ...

    def render(self, reply: Reply) -> dict[str, Any]: ...

    async def send(self, external_user_id: str, reply: Reply) -> None: ...

    async def answer_tap(self, tap: Tap) -> None: ...

    async def confirm_tap(self, tap: Tap) -> None: ...
