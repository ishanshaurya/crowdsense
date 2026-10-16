# Crowdsense

Fans tell a Telegram bot where and how they'd see a show. The artist's dashboard turns that into demand, venue, price and city recommendations.

Proof of concept: a simulated artist, ~20,000 simulated fans and ~10 real testers.

## Docs

Read in this order:

| File                     | Answers                                          |
| ------------------------ | ------------------------------------------------ |
| `docs/prd.md`            | What we build and why                            |
| `docs/architecture.md`   | How it's built                                   |
| `docs/message-script.md` | What the bot says; messaging error handling      |
| `docs/plan.md`           | Order of work (phases 0–6)                       |
| `docs/metrics.md`        | Load, scale and bot-strength targets and results |
| `docs/decisions.md`      | Every decision, numbered (#1–#115)                |
| `docs/design-review.md`  | Why each decision was made; interview Q&A        |
| `CONTEXT.md`             | Glossary                                         |
| `testing/`               | Test plan per phase, scenarios, traceability     |
| `notes/`                 | Per-phase build notes, measured numbers, interview Q&A |

Rule: each fact lives in one file. Others point to it by decision number (`#n`).

## Code

```
adapters/    telegram, web chat
core/        engine, decide, flow, store, demand, insights, clock, config   (outbound: phase 5)
api/         webhook service, web chat routes
dashboard/   Streamlit app
migrations/  Alembic schema
scripts/     seed, dashboard role, benchmarks, webhook setup
notes/       per-phase build notes
```

## Status

Phases 1 to 4 are built and tested (tags `phase-2` to `phase-4`). Phase 5 (outbound announcements) is next, then phase 6 (hardening). See `docs/plan.md`.

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

Seed, dashboard role and benchmarks: "How to run" in `notes/phase-3.md` and `notes/phase-4.md`.
