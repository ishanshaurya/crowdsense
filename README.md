# Crowdsense

Fans tell a Telegram bot where and how they'd see a show. The artist's dashboard turns that into demand, venue, price and city recommendations.

Proof of concept: a simulated artist, ~20,000 simulated fans and ~10 real testers.

## Docs

| File                     | What is in it                                   |
| ------------------------ | ----------------------------------------------- |
| `docs/prd.md`            | What it does, who it is for, status and roadmap |
| `docs/architecture.md`   | How it is built, plus measured performance      |
| `docs/decisions.md`      | The choices that shaped it                      |
| `docs/design-review.md`  | The tradeoffs behind the main ones              |
| `docs/message-script.md` | What the bot says                               |
| `testing/`               | Test plan per phase, scenarios, traceability    |

## Code

```
adapters/    telegram, web chat
core/        engine, decide, flow, store, demand, insights, outbound, clock, config
api/         webhook service, web chat routes
dashboard/   Streamlit app
migrations/  Alembic schema
scripts/     seed, dashboard role, benchmarks, webhook setup
```

## Status

Phases 1 to 5 are built and tested (tags `phase-2` to `phase-4`, `phase-5a`). Phase 6 (hardening) is next. The roadmap is in `docs/prd.md` §8.

## Limits

- **Self-selection bias.** Only fans who open the bot and finish the chat are counted. They are keener than the average fan, so demand is likely overstated.
- **Stated intent is not purchase.** Budget and "would you go" are answers, not sales. Expect a gap between what fans say and what they buy.
- **Simulated data.** About 20,000 of the fans are generated, and the dashboard defaults to that view. Only the ~10 real testers show in the Real view. Simulated numbers show the system at scale, not real demand.

## Run

Copy `.env.example` to `.env` and fill in the names (never commit `.env`).

```bash
uv sync --locked
uv run pytest -q --cov=core --cov-fail-under=90        # all tests (starts a local Postgres)

# bot + web chat (served at /chat), then the public tunnel and the Telegram webhook
uv run uvicorn api.webhooks:build_app --factory --env-file .env --port 8000
ngrok http 8000 --url=<host of PUBLIC_URL>
uv run python -m scripts.set_webhook

# dashboard: http://localhost:8501, sign in with DASHBOARD_PASSWORD
uv run --env-file .env python -m streamlit run dashboard/app.py
```

Seed the simulated fans with `scripts/seed.py`, create the dashboard role with `scripts/dashboard_role.py`, and time things with `scripts/bench_*.py`. Each script says how to run it at the top.
