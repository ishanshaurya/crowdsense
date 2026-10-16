"""A fake Telegram Bot API (httpx.MockTransport) and a fan that talks to the webhook over ASGI.

Updates are built from the recorded fixtures in testing/fixtures/telegram/, never by hand.
"""

import copy
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from itertools import count
from typing import Any

import httpx

from adapters.telegram import SECRET_HEADER, TelegramAdapter
from api.sender import Pacer, Sender
from api.sweeper import Sweeper
from api.taps import RecentTaps
from api.webhooks import Webhook, create_app
from core.clock import ScriptedClock
from core.engine import Engine
from core.store import Store
from tests.support import ARTIST, ROOT

FIXTURES = ROOT / "testing" / "fixtures" / "telegram"
TOKEN = "123456789:AAFakeTokenForTestsOnly_abcdefghijklmn"
SECRET = "test-webhook-secret-0123456789"  # pragma: allowlist secret
HEADERS = {SECRET_HEADER: SECRET}
CHAT = 1000001

Responder = Callable[[str, dict[str, Any]], httpx.Response | None]


def fixture(name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    return data


def unhandled(name: str) -> dict[str, Any]:
    """Recorded updates the bot ignores. No group or sticker was recorded, so "group" is the
    recorded text message moved into a group chat (the only field the parser checks)."""
    if name != "group":
        return fixture(f"{name}.json")
    update = copy.deepcopy(fixture("text.json"))
    update["message"]["chat"] = {"id": -1000000009, "title": "Test Group", "type": "group"}
    return update


def ok(result: Any = True) -> httpx.Response:
    return httpx.Response(200, json={"ok": True, "result": result})


def error(status: int, description: str, **parameters: Any) -> httpx.Response:
    body: dict[str, Any] = {"ok": False, "error_code": status, "description": description}
    if parameters:
        body["parameters"] = parameters
    return httpx.Response(status, json=body)


@dataclass
class FakeTelegram:
    """Records every Bot API call. `script` answers the next calls of a method, then ok()."""

    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    delivered: list[tuple[int, dict[str, Any]]] = field(default_factory=list)  # message_id, body
    script: dict[str, list[httpx.Response]] = field(default_factory=dict)
    _ids: "count[int]" = field(default_factory=lambda: count(500))

    def handler(self, request: httpx.Request) -> httpx.Response:
        assert request.url.path.startswith(f"/bot{TOKEN}/")
        method = request.url.path.rsplit("/", 1)[1]
        payload = json.loads(request.content)
        self.calls.append((method, payload))
        queued = self.script.get(method)
        if queued:
            return queued.pop(0)
        if method == "sendMessage":
            message_id = next(self._ids)
            self.delivered.append((message_id, payload))
            return ok({"message_id": message_id})
        return ok()

    def methods(self) -> list[str]:
        return [m for m, _ in self.calls]

    def sent(self) -> list[dict[str, Any]]:
        return [p for m, p in self.calls if m == "sendMessage"]


@dataclass
class Rig:
    store: Store
    engine: Engine
    clock: ScriptedClock
    telegram: FakeTelegram
    sweeper: Sweeper
    sleeps: list[float]
    http: httpx.AsyncClient
    bot_client: httpx.AsyncClient
    on_sleep: Callable[[], Awaitable[None]] | None = None  # runs inside each sender wait
    seconds: list[float] = field(default_factory=lambda: [0.0])  # monotonic time for tap memory

    async def post(self, update: dict[str, Any], headers: dict[str, str] | None = None) -> int:
        response = await self.http.post(
            "/hook/telegram", json=update, headers=HEADERS if headers is None else headers
        )
        return response.status_code

    async def close(self) -> None:
        await self.http.aclose()
        await self.bot_client.aclose()


def build_rig(store: Store, clock: ScriptedClock) -> Rig:
    telegram = FakeTelegram()
    bot_client = httpx.AsyncClient(transport=httpx.MockTransport(telegram.handler))
    adapter = TelegramAdapter(TOKEN, SECRET, bot_client)
    engine = Engine(store, clock, artist_name=ARTIST)
    sleeps: list[float] = []

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        if rig.on_sleep is not None:
            await rig.on_sleep()

    sender = Sender(engine, Pacer(per_chat=0, overall=0), sleep=sleep)
    adapters = {"telegram": adapter}
    sweeper = Sweeper(store, engine, sender, adapters, clock)
    seconds = [0.0]
    taps = RecentTaps(clock=lambda: seconds[0])
    app = create_app(Webhook(engine, store, adapters, clock, sender, taps))
    http = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    rig = Rig(store, engine, clock, telegram, sweeper, sleeps, http, bot_client, seconds=seconds)
    return rig


_update_ids = count(900_001)


def text_update(text: str, *, chat: int = CHAT, update_id: int | None = None) -> dict[str, Any]:
    update = copy.deepcopy(fixture("text.json"))
    update["update_id"] = update_id or next(_update_ids)
    message = update["message"]
    message["text"] = text
    message["chat"]["id"] = message["from"]["id"] = chat
    message.pop("entities", None)
    return update


def tap_update(
    data: str,
    keyboard: dict[str, Any],
    *,
    message_id: int,
    chat: int = CHAT,
    update_id: int | None = None,
) -> dict[str, Any]:
    update = copy.deepcopy(fixture("button_tap.json"))
    update["update_id"] = update_id or next(_update_ids)
    query = update["callback_query"]
    query["id"] = f"cq{update['update_id']}"
    query["data"] = data
    query["from"]["id"] = chat
    query["message"]["chat"]["id"] = chat
    query["message"]["message_id"] = message_id
    query["message"]["reply_markup"] = keyboard
    return update


class Fan:
    """Taps buttons by label on the last message that had a keyboard, like a person would."""

    def __init__(self, rig: Rig, chat: int = CHAT) -> None:
        self.rig, self.chat = rig, chat
        self.keyboard: dict[str, Any] = {}
        self.message_id = 0

    def _remember_keyboard(self, before: int) -> None:
        for message_id, payload in self.rig.telegram.delivered[before:]:
            if "reply_markup" in payload and payload["chat_id"] == str(self.chat):
                self.keyboard, self.message_id = payload["reply_markup"], message_id

    async def say(self, text: str) -> int:
        before = len(self.rig.telegram.delivered)
        status = await self.rig.post(text_update(text, chat=self.chat))
        self._remember_keyboard(before)
        return status

    def data_for(self, label: str) -> str:
        for button in (b for row in self.keyboard["inline_keyboard"] for b in row):
            if button["text"] == label:
                return str(button["callback_data"])
        raise AssertionError(f"no button {label!r}")

    async def tap(self, label: str) -> int:
        update = tap_update(
            self.data_for(label), self.keyboard, message_id=self.message_id, chat=self.chat
        )
        before = len(self.rig.telegram.delivered)
        status = await self.rig.post(update)
        self._remember_keyboard(before)
        return status
