"""Web chat routes (#77): `GET /chat`, `/chat/app.js`, `/chat/app.css`; `POST /chat/message`.

`POST /chat/message`: parse -> engine -> the replies go back IN the response -> then `mark_sent`.
The web chat is not in the webhook's adapter registry, so `/hook/web_sim` is a 404 and the resend
sweeper never claims its replies (it only claims registered channels). A reply left unsent (the
`mark_sent` after the response failed) is marked sent by `expire_unsent` once it is 10 minutes
old, so none pile up (#100).

Failure policy as for Telegram (#71): engine bug -> one apology in a 200, nothing saved, logged
with a correlation id; database down -> 503.
"""

import json
import logging
import time
import uuid
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, Request, Response
from fastapi.responses import JSONResponse

from adapters.web_sim import CHANNEL, MAX_BODY_BYTES, WebSimAdapter
from api.ratelimit import RateLimiter, client_ip
from core.clock import Clock
from core.engine import Engine
from core.flow import APOLOGY_TEXT
from core.store import Store, StoreUnavailable
from core.types import Reply

log = logging.getLogger("crowdsense.chat")

STATIC = Path(__file__).parent / "static"
SECURITY_HEADERS = {
    "Content-Security-Policy": "default-src 'self'; base-uri 'none'; frame-ancestors 'none'",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}
FILES = {
    "/chat": ("chat.html", "text/html; charset=utf-8"),
    "/chat/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/chat/app.css": ("app.css", "text/css; charset=utf-8"),
    "/chat/logo.svg": ("logo.svg", "image/svg+xml"),
}
UNSENT_MAX_AGE = timedelta(minutes=10)


async def _read_capped(request: Request) -> bytes | None:
    """The body, or None once it passes `MAX_BODY_BYTES` (stops reading; never buffers more)."""
    length = request.headers.get("content-length", "")
    if length.isdigit() and int(length) > MAX_BODY_BYTES:
        return None
    raw = b""
    async for chunk in request.stream():
        raw += chunk
        if len(raw) > MAX_BODY_BYTES:
            return None
    return raw


def _json(status: int, body: object, headers: dict[str, str] | None = None) -> JSONResponse:
    return JSONResponse(body, status_code=status, headers={**SECURITY_HEADERS, **(headers or {})})


class WebChat:
    def __init__(
        self,
        engine: Engine,
        store: Store,
        clock: Clock,
        *,
        limiter: RateLimiter | None = None,
        expire_every: float = 60.0,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.adapter = WebSimAdapter()
        self._engine, self._store, self._clock = engine, store, clock
        self.limiter = limiter if limiter is not None else RateLimiter()  # empty is falsy
        self._expire_every, self._monotonic = expire_every, monotonic
        self._next_expiry = 0.0
        self._files = {path: (STATIC / name).read_bytes() for path, (name, _) in FILES.items()}

    def _limited(self, request: Request) -> Response | None:
        peer = request.client.host if request.client else None
        wait = self.limiter.hit(client_ip(request.headers, peer))
        if not wait:
            return None
        retry = {"Retry-After": str(max(1, round(wait + 0.5)))}
        return _json(429, {"error": "too many requests"}, retry)

    async def static(self, request: Request) -> Response:
        if limited := self._limited(request):
            return limited
        path = request.url.path
        return Response(self._files[path], media_type=FILES[path][1], headers=SECURITY_HEADERS)

    async def message(self, request: Request, background: BackgroundTasks) -> Response:
        if limited := self._limited(request):
            return limited
        raw = await _read_capped(request)
        if raw is None:
            return _json(413, {"error": "message too large"})
        try:
            inbound = self.adapter.parse(json.loads(raw), self._clock.now())
        except ValueError:
            inbound = None
        if inbound is None or inbound.event is None:
            return _json(400, {"error": "bad request"})
        cid = uuid.uuid4().hex[:12]
        try:
            result = await self._engine.handle(inbound.event)
        except StoreUnavailable:
            log.warning("cid=%s database unreachable; 503 to the web chat", cid)
            return _json(503, {"error": "temporarily unavailable, try again"})
        except Exception:
            log.exception("cid=%s engine error on a %s message; rolled back", cid, CHANNEL)
            return _json(200, {"replies": [self.adapter.render(Reply(APOLOGY_TEXT, "error"))]})
        background.add_task(self._engine.mark_sent, result.replies)
        if self._monotonic() >= self._next_expiry:
            self._next_expiry = self._monotonic() + self._expire_every
            background.add_task(self.expire_unsent)
        return _json(200, {"replies": [self.adapter.render(o.reply) for o in result.replies]})

    async def expire_unsent(self) -> int:
        """Mark web chat replies still unsent after 10 minutes as sent: the page got them in
        its response or is gone; nothing can push them (#100). Never raises."""
        try:
            async with self._store.transaction() as tx:
                stale = self._clock.now() - UNSENT_MAX_AGE
                rows = await tx.claim_unsent(stale, 500, channels={CHANNEL})
                if rows:
                    await tx.mark_sent([r.id for r in rows])
        except Exception:
            log.exception("expiring unsent web chat replies failed; trying again later")
            return 0
        if rows:
            log.info("marked %d stale unsent web chat replies as sent", len(rows))
        return len(rows)


def mount_chat(app: FastAPI, engine: Engine, store: Store, clock: Clock) -> FastAPI:
    """The one registry line in `build_app`: add the web chat routes to the webhook service."""
    chat = WebChat(engine, store, clock)
    return add_chat_routes(app, chat)


def add_chat_routes(app: FastAPI, chat: WebChat) -> FastAPI:
    for path in FILES:
        app.add_api_route(path, chat.static, methods=["GET"], include_in_schema=False)
    app.add_api_route("/chat/message", chat.message, methods=["POST"], include_in_schema=False)
    return app
