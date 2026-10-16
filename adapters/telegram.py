"""Telegram adapter: plain `httpx` against the Bot API (#66). Plain text only, no parse_mode (#69).

Request URLs contain the bot token (`/bot<TOKEN>/method`), so nothing here logs a URL or an
httpx exception message, and the webhook service sets the httpx loggers to WARNING (Q-12).
"""

import hmac
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

import httpx

from adapters.base import Blocked, Capabilities, Inbound, RetryAfter, SendError, Tap
from core.types import EventKind, InboundEvent, Option, Reply

CHANNEL = "telegram"
API_URL = "https://api.telegram.org"
SECRET_HEADER = "X-Telegram-Bot-Api-Secret-Token"  # pragma: allowlist secret
ALLOWED_UPDATES = ("message", "callback_query")
MAX_TEXT = 4096
MAX_CALLBACK_BYTES = 64
NOOP = "noop"
CHECK = "✓"
COMMANDS: dict[str, EventKind] = {
    "/start": "start",
    "/stop": "stop",
    "/delete": "delete",
    "/help": "help",
}
CAPABILITIES = Capabilities(buttons=True, max_buttons=100, has_phone=False, can_push_anytime=True)


def parse_update(update: Any, received_at: datetime) -> Inbound | None:
    """Private-chat text and button taps become events; every other update is ignored."""
    try:
        update_id = update["update_id"]
        if not isinstance(update_id, int):
            return None
        msg_id = str(update_id)  # dedupe key for text and taps alike (#90)
        if "message" in update:
            return _parse_message(update["message"], msg_id)
        if "callback_query" in update:
            return _parse_tap(update["callback_query"], msg_id, received_at)
    except (KeyError, TypeError, ValueError, AttributeError):
        return None
    return None


def _parse_message(message: dict[str, Any], msg_id: str) -> Inbound | None:
    chat, text = message["chat"], message.get("text")
    if chat.get("type") != "private" or not isinstance(text, str):
        return None
    ts = datetime.fromtimestamp(message["date"], UTC)
    common = {"channel": CHANNEL, "external_user_id": str(chat["id"]), "external_msg_id": msg_id}
    head, _, rest = text.strip().partition(" ")
    kind = COMMANDS.get(head.split("@", 1)[0].lower()) if head.startswith("/") else None
    if kind is None:
        return Inbound(InboundEvent(kind="text", text=text, ts=ts, **common))
    tag = (rest.strip() or None) if kind == "start" else None
    return Inbound(InboundEvent(kind=kind, source_tag=tag, ts=ts, **common))


def _parse_tap(query: dict[str, Any], msg_id: str, received_at: datetime) -> Inbound:
    message = query.get("message") or {}
    chat = message.get("chat") or {}
    user = str(chat.get("id", query["from"]["id"]))
    data = query.get("data")
    tap = Tap(str(query["id"]), user, message.get("message_id"), _button_label(message, data))
    if chat.get("type", "private") != "private" or not isinstance(data, str) or data == NOOP:
        return Inbound(None, tap)
    step, sep, choice = data.partition(":")
    if not sep or not step or not choice:
        return Inbound(None, tap)
    event = InboundEvent(
        channel=CHANNEL,
        external_user_id=user,
        external_msg_id=msg_id,
        kind="choice",
        choice_step=step,
        choice_id=choice,
        ts=received_at,
    )
    return Inbound(event, tap)


def _button_label(message: dict[str, Any], data: Any) -> str | None:
    rows = (message.get("reply_markup") or {}).get("inline_keyboard") or []
    for button in (b for row in rows for b in row):
        if button.get("callback_data") == data:
            label = button.get("text")
            return label if isinstance(label, str) else None
    return None


def callback_data(step_id: str, option: Option) -> str:
    data = f"{step_id}:{option.id}"
    if len(data.encode()) > MAX_CALLBACK_BYTES:
        raise ValueError(f"callback data for {step_id}/{option.id} is over 64 bytes")
    return data


def keyboard_rows(options: Sequence[Option]) -> list[list[Option]]:
    """Short labels share a row: 4 for group sizes, 2 for cities and bands, else 1 per row."""
    longest = max(len(o.label) for o in options)
    per_row = 4 if longest <= 4 else 2 if longest <= 14 else 1
    return [list(options[i : i + per_row]) for i in range(0, len(options), per_row)]


def render_reply(reply: Reply) -> dict[str, Any]:
    text = reply.text if len(reply.text) <= MAX_TEXT else reply.text[: MAX_TEXT - 1] + "…"
    payload: dict[str, Any] = {"text": text}
    if reply.options:
        payload["reply_markup"] = {
            "inline_keyboard": [
                [{"text": o.label, "callback_data": callback_data(reply.step_id, o)} for o in row]
                for row in keyboard_rows(reply.options)
            ]
        }
    return payload


def confirmed_markup(label: str) -> dict[str, Any]:
    return {"inline_keyboard": [[{"text": f"{CHECK} {label}", "callback_data": NOOP}]]}


class TelegramAdapter:
    channel = CHANNEL
    capabilities = CAPABILITIES

    def __init__(self, token: str, webhook_secret: str, client: httpx.AsyncClient) -> None:
        self._path = f"/bot{token}/"
        self._secret = webhook_secret.encode()
        self._client = client

    def authorized(self, headers: Mapping[str, str]) -> bool:
        given = headers.get(SECRET_HEADER, "").encode()
        return hmac.compare_digest(given, self._secret)

    def parse(self, body: Any, received_at: datetime) -> Inbound | None:
        return parse_update(body, received_at)

    def render(self, reply: Reply) -> dict[str, Any]:
        return render_reply(reply)

    async def send(self, external_user_id: str, reply: Reply) -> None:
        await self.call("sendMessage", {"chat_id": external_user_id, **render_reply(reply)})

    async def answer_tap(self, tap: Tap) -> None:
        await self.call("answerCallbackQuery", {"callback_query_id": tap.id})

    async def confirm_tap(self, tap: Tap) -> None:
        if tap.message_id is None or tap.label is None:
            return
        await self.call(
            "editMessageReplyMarkup",
            {
                "chat_id": tap.chat_id,
                "message_id": tap.message_id,
                "reply_markup": confirmed_markup(tap.label),
            },
        )

    async def call(self, method: str, payload: dict[str, Any]) -> Any:
        """POST a Bot API method. Errors carry the method and Telegram's text, never the URL."""
        try:
            response = await self._client.post(API_URL + self._path + method, json=payload)
            data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise SendError(f"{method}: {type(exc).__name__}") from None
        if response.status_code == 429:
            retry = (data.get("parameters") or {}).get("retry_after", 1)
            raise RetryAfter(float(retry))
        if response.status_code == 403:
            raise Blocked(f"{method}: {data.get('description', 'forbidden')}")
        if not data.get("ok"):
            raise SendError(f"{method}: {response.status_code} {data.get('description', '')}")
        return data.get("result")
