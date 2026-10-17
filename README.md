# CrowdSense

[![CI](https://github.com/ishanshaurya/crowdsense/actions/workflows/ci.yml/badge.svg)](https://github.com/ishanshaurya/crowdsense/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

**Fans tell a Telegram bot where and how they'd see a show. The artist's dashboard turns those answers into demand, venue, ticket-price and city recommendations, before any venue is booked.**

Proof of concept: a simulated artist, about 20,000 simulated fans and about 10 real testers.

**Try it live:** [Telegram bot](https://t.me/crowdsense_live_bot) · [Web chat](https://crowdsense-production.up.railway.app/chat) · [Artist dashboard](https://positive-delight-production.up.railway.app) (password on request)

## Demo

**Telegram and dashboard (62 s).** A fan consents and answers a few taps. The artist announces a show to one city, the fan receives it, then `/stop` opts out and `/delete` removes the data.

[![CrowdSense demo: Telegram and dashboard](docs/media/demo-poster.jpg)](docs/media/crowdsense-demo.mp4)

**Web chat (25 s).** The same engine behind a second channel, including a free-text answer.

[![CrowdSense web chat](docs/media/web-chat-poster.jpg)](docs/media/web-chat.mp4)

| Recommendation | Announce a show |
| --- | --- |
| ![Dashboard](docs/media/dashboard.jpg) | ![Announcements](docs/media/announcements.jpg) |

The dashboard sits behind a password. Access is available on request.

## Architecture

```
 Fan on Telegram        Fan on web chat
        │ webhook              │ POST /chat/message
        ▼                      ▼
 ┌──────────────────────────────────────────┐
 │ Webhook service (FastAPI)                │
 │   adapters/  parse ─▶ engine ─▶ send     │
 │   core/      flow, rules, store          │
 └────────────────────┬─────────────────────┘
                      │ write
                      ▼
            ┌───────────────────┐   INSERT announcement_requests
            │ Postgres          │◀───────────────┐  (only write)
            └─────────┬─────────┘                │
                      │ read                     │
                      ▼                          │
 ┌──────────────────────────────────────────┐    │
 │ Dashboard (Streamlit, own DB role)       │────┘
 └──────────────────────────────────────────┘

 announcement_requests ─▶ sweeper ─▶ fan-out to consenting fans ─▶ replies ─▶ sender ─▶ Telegram
```

## Channels are plugins

Every channel is one adapter file. An adapter translates the channel's messages to the engine's common format and back. It never imports the flow or the engine.

```python
class Adapter(Protocol):
    channel: str
    capabilities: Capabilities

    def authorized(self, headers: Mapping[str, str]) -> bool: ...
    def parse(self, body: Any, received_at: datetime) -> Inbound | None: ...
    def render(self, reply: Reply) -> dict[str, Any]: ...
    async def send(self, external_user_id: str, reply: Reply) -> None: ...
```

| Channel | Status | Needs |
| --- | --- | --- |
| Telegram | Live | Bot token |
| Web chat | Live (second adapter on the same engine, no core change) | None |
| Discord | Planned | Bot token |
| WhatsApp | Planned | Meta business verification, message templates |
| Instagram | Planned | Meta app review |

Adding a channel changes no engine, flow, database or dashboard code. See [`adapters/base.py`](adapters/base.py).

## Production practices

| Area | What is in place |
| --- | --- |
| Idempotent ingestion | `UNIQUE (channel, external_msg_id)`: a retried webhook never asks a fan twice |
| Concurrency | Per-fan lock: two fast taps never create two fans |
| Reliable delivery | Replies commit with the turn and are sent after commit; a sweeper resends failures; Telegram 429s honour `retry_after` |
| Least privilege | The dashboard connects as its own Postgres role. Supabase `anon` and `authenticated` are revoked and checked by script. The only dashboard write is one `INSERT` on `announcement_requests`, guarded by RLS |
| Consent and privacy | Consent first. `/stop` drops unsent messages, `/delete` erases the fan's data, announcements go only to consenting, non-opted-out real fans |
| Architecture rules enforced | `import-linter` fails CI if a layer imports another; a frozen-core check blocks unplanned changes to `core/` |
| Schema management | Versioned Alembic migrations |
| Testing | Integration tests on real Postgres; one store contract suite runs against both Postgres and the in-memory fake |
| CI gates | ruff, mypy (strict), import-linter, pip-audit (dependency CVEs), detect-secrets, lockfile check, Postgres 16 service container |
| CD | Containerised; Railway deploys the API after CI passes |
| Operations | `/health` and `/ready` probes, secrets only through environment variables, pre-commit hooks |
| Decision log | The main choices are numbered and explained in [`docs/decisions.md`](docs/decisions.md) |

## Measured results

Single machine, Postgres 15 unless noted. Details in [`docs/architecture.md`](docs/architecture.md) §11.

| Metric | Result |
| --- | --- |
| Engine turn p95 (800 turns) | 0.70 ms |
| Dashboard refresh, 20k fans, 12 queries in one round trip | p95 31 ms local; p95 447–601 ms on Supabase from a laptop (network-dominated) |
| Slowest single dashboard query, 20k fans | p95 6 ms local |
| Seed of 20,000 fans through the real engine | 6.4 s |
| New fan visible on the dashboard | 0.55–4.45 s |

**Next (phase 6), not measured yet:** webhook p95 under Locust, 50 msg/s spike, 30-minute soak, chaos tests (duplicates, double taps, crashes, DB outage), a 100,000-fan dashboard run, and a durable inbox so the webhook acknowledges before the engine turn.

## Limits

Only fans who finish the chat are counted, so demand is likely overstated. Stated intent is not purchase. About 20,000 fans are simulated; only about 10 are real testers.

## Stack

| Layer | Technology |
| --- | --- |
| Bot and web chat | Telegram Bot API over httpx |
| Backend | Python 3.12, FastAPI, uvicorn, Pydantic |
| Database | Postgres (Supabase), psycopg 3, Alembic |
| Dashboard | Streamlit, pandas |
| Delivery | Docker, GitHub Actions, Railway |

## Run it

```bash
cp .env.example .env              # fill in the variable names; never commit .env
uv sync --locked
uv run pytest -q --cov=core --cov-fail-under=90     # starts a local Postgres

# bot + web chat (/chat), then the public tunnel and the Telegram webhook
uv run uvicorn api.webhooks:build_app --factory --env-file .env --port 8000
ngrok http 8000 --url=<host of PUBLIC_URL>
uv run python -m scripts.set_webhook

# dashboard: http://localhost:8501
uv run --env-file .env python -m streamlit run dashboard/app.py
```

Seed the simulated fans with `scripts/seed.py`, create the dashboard role with `scripts/dashboard_role.py`, and time things with `scripts/bench_*.py`. Each script says how to run it at the top.

## Docs

| File | Answers |
| --- | --- |
| [`docs/prd.md`](docs/prd.md) | What is built and why |
| [`docs/architecture.md`](docs/architecture.md) | Components, data model, flow, failure handling, measured performance |
| [`docs/decisions.md`](docs/decisions.md) | The choices that shaped it |
| [`docs/design-review.md`](docs/design-review.md) | The tradeoffs behind the main ones |
| [`docs/message-script.md`](docs/message-script.md) | What the bot says; messaging error handling |
| [`testing/`](testing) | Test plan per phase, scenarios, traceability |

## License

MIT
