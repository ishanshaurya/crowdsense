"""The web chat on the real webhook app over ASGI, and a fan that taps buttons by label."""

from dataclasses import dataclass, field
from itertools import count
from typing import Any

import httpx

from adapters.telegram import TelegramAdapter
from api.chat import WebChat, add_chat_routes
from api.ratelimit import RateLimiter
from api.sender import Pacer, Sender
from api.webhooks import Webhook, create_app
from core.clock import ScriptedClock
from core.engine import Engine
from core.store import Store
from tests.component.telegram_fake import SECRET, TOKEN
from tests.support import ARTIST

PEER = ("203.0.113.5", 40000)


@dataclass
class WebRig:
    store: Store
    engine: Engine
    clock: ScriptedClock
    chat: WebChat
    http: httpx.AsyncClient
    bot_client: httpx.AsyncClient
    seconds: list[float] = field(default_factory=lambda: [0.0])  # monotonic time

    async def post(self, body: Any, **kwargs: Any) -> httpx.Response:
        return await self.http.post("/chat/message", json=body, **kwargs)

    async def close(self) -> None:
        await self.http.aclose()
        await self.bot_client.aclose()


def build_web_rig(
    store: Store, clock: ScriptedClock, *, capacity: float = 1000, peer: tuple[str, int] = PEER
) -> WebRig:
    """Production shape: the Telegram webhook app with the chat routes added (`mount_chat`)."""
    engine = Engine(store, clock, artist_name=ARTIST)
    seconds = [0.0]
    limiter = RateLimiter(capacity=capacity, clock=lambda: seconds[0])
    chat = WebChat(engine, store, clock, limiter=limiter, monotonic=lambda: seconds[0])
    bot_client = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(500)))
    adapters = {"telegram": TelegramAdapter(TOKEN, SECRET, bot_client)}
    webhook = Webhook(engine, store, adapters, clock, Sender(engine, Pacer(per_chat=0, overall=0)))
    app = add_chat_routes(create_app(webhook), chat)
    transport = httpx.ASGITransport(app=app, client=peer)
    http = httpx.AsyncClient(transport=transport, base_url="http://test")
    return WebRig(store, engine, clock, chat, http, bot_client, seconds)


_ids = count(1)


class WebFan:
    """Keeps the last reply that had buttons, like the page (`app.js`) does."""

    def __init__(self, rig: WebRig, user: str = "web-fan-0001") -> None:
        self.rig, self.user = rig, user
        self.buttons: dict[str, Any] | None = None
        self.replies: list[dict[str, Any]] = []

    async def send(self, msg_id: str | None = None, **fields: Any) -> httpx.Response:
        body = {"user": self.user, "msg_id": msg_id or f"w{next(_ids)}", **fields}
        response = await self.rig.post(body)
        if response.status_code == 200:
            self.replies = response.json()["replies"]
            with_options = [r for r in self.replies if r["options"]]
            self.buttons = with_options[-1] if with_options else None
        return response

    async def start(self, src: str | None = None, msg_id: str | None = None) -> httpx.Response:
        return await self.send(msg_id, kind="start", **({"src": src} if src else {}))

    async def say(self, text: str, msg_id: str | None = None) -> httpx.Response:
        return await self.send(msg_id, kind="text", text=text)

    async def tap(self, label: str, msg_id: str | None = None) -> httpx.Response:
        assert self.buttons is not None, "no buttons on screen"
        ids = {o["label"]: o["id"] for o in self.buttons["options"]}
        assert label in ids, f"no button {label!r} in {list(ids)}"
        step = self.buttons["step_id"]
        return await self.send(msg_id, kind="choice", choice_step=step, choice_id=ids[label])
