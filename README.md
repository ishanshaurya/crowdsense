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
| `docs/decisions.md`      | Every decision, numbered (#1–#98)                |
| `docs/design-review.md`  | Why each decision was made; interview Q&A        |
| `CONTEXT.md`             | Glossary                                         |
| `testing/`               | Test plan per phase, scenarios, traceability     |

Rule: each fact lives in one file. Others point to it by decision number (`#n`).

## Code

```
adapters/   telegram, web chat
core/       engine, flow, store, demand, insights, outbound, clock, config
api/        webhook service
dashboard/  Streamlit
```

## Run

Not built yet. Phase 1 is next (`docs/plan.md`).
