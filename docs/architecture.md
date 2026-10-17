# Architecture

How Crowdsense is built. What and why: `docs/prd.md`. Bot texts and messaging errors: `docs/message-script.md`.

**Principle:** channels are plugins.
- Adapters only translate messages.
- The core owns the conversation, the data and the rules.

## 1. Overview

```
  ┌──────────────┐        ┌──────────────┐
  │ Fan on       │        │ Fan on       │
  │ Telegram     │        │ web chat     │
  └──────┬───────┘        └──────┬───────┘
         │ webhook                │ POST /chat/message
         ▼                        ▼
  ┌─────────────────────────────────────────┐
  │ Webhook service (FastAPI, via ngrok)    │
  │   adapters/  parse ─▶ engine ─▶ send    │
  │   core/      flow + rules + store       │
  └────────────────────┬────────────────────┘
                       │ write
                       ▼
          ┌─────────────────────────┐
          │ Postgres (Supabase)     │◀──────────────┐
          │ backup: local Docker    │               │
          └────────────┬────────────┘               │
                       │ read                       │ INSERT announcement_requests
                       ▼                            │ (city, date; only write)
  ┌─────────────────────────────────────────┐       │
  │ Dashboard (Streamlit)                   │───────┘
  │   demand, recommendations, Sim / Real,  │
  │   "Announce a show" form                │
  └─────────────────────────────────────────┘

  Outbound (phase 5), inside the webhook service:

  announcement_requests ─▶ sweeper (every 30 s) ─▶ core/outbound.py fan-out
        (request table)      fans out first        eligible fans only (consent, not /stop)
                                                          │ one reply per fan, priority 1
                                                          ▼
                                    replies (unsent) ─▶ sender (Telegram limits) ─▶ Telegram ─▶ fan
```

| Layer    | Stack                                                                 |
| -------- | --------------------------------------------------------------------- |
| Frontend | Telegram bot, web chat (plain HTML/JS/CSS), Streamlit dashboard       |
| Backend  | Python 3, FastAPI + uvicorn, httpx (Telegram Bot API)                 |
| Database | Postgres on Supabase, psycopg 3, Alembic                              |
| Tools    | uv, ngrok, pytest, ruff, mypy, import-linter, pre-commit, detect-secrets, pip-audit, GitHub Actions |

## 2. Code layout

```
adapters/
  base.py           contract every channel adapter implements: parse, render, send
  telegram.py       Telegram Bot API adapter over plain httpx
  web_sim.py        web chat adapter; proves a second channel needs no core change
api/
  webhooks.py       /hook/{channel}: parse -> engine -> 200, then send replies
  chat.py           web chat routes: serves /chat page, handles /chat/message
  sender.py         sends replies under Telegram limits (429 wait, 403 opt-out)
  sweeper.py        every 30 s resends replies still unsent after 10 s
  taps.py           tells a double tap from a tap on an old question
  ratelimit.py      per-IP token bucket for the public web chat
  logs.py           logging setup that never prints the bot token
  static/           web chat page (chat.html, app.js, app.css)
core/
  engine.py         one turn = one transaction: lock, dedupe, decide, write
  decide.py         pure decision: (state, event, now) -> what to write and reply
  flow.py           the conversation as data: steps, options, next step, what clears
  catalog.py        reference data (cities, venues, budgets, group sizes)
  types.py          shared types: InboundEvent, Reply, decision values
  store.py          store interface shared by both implementations
  store_postgres.py Postgres store, parameterised SQL only
  store_memory.py   in-memory fake with the same behaviour, for tests
  insights.py       recommendation rules as pure functions
  clock.py          real clock + scripted clock for seed and tests
  config.py         validated settings from env; errors never show values
  demand.py         counted-fan rule + SQL aggregates for the dashboard
  outbound.py       announcement audience + delivery                      phase 5
dashboard/
  app.py            password gate, view switch, 5 s live refresh
  views.py          one draw function per view
  text.py           labels and the recommendation sentence
migrations/         Alembic: schema, venue seed, input caps
scripts/
  repl.py           play the conversation in the terminal on the in-memory store
  set_webhook.py    register the Telegram webhook with its secret
  record_updates.py record raw Telegram updates as test fixtures
  bench_turn.py     time engine turns against a local Postgres
  seed.py           seed ~20,000 simulated fans (engine in memory, then COPY)
  seed_plan.py      the deterministic plan the seed follows
  dashboard_role.py create the read-only dashboard role and its grants
  lock_public_api.py revoke Supabase's anon/authenticated roles on our tables
  bench_demand.py   time every dashboard query
```

## 4. Data model

```
venues ◀── fans ──▶ identities   (one per channel account)
             │
             ├──▶ sessions       (where the fan is in the flow)
             ├──▶ answers        (every answer, history)
             ├──▶ events ──▶ replies
             └── funnel_counts   (counts only, no fan link)
```

| Table                   | One row is                            | Key                           | Main columns                                                                                  |
| ----------------------- | ------------------------------------- | ----------------------------- | --------------------------------------------------------------------------------------------- |
| `venues`                | a venue the artist could play         | `id`                          | city, name, capacity                                                                          |
| `fans`                  | a fan's current answers (snapshot)    | `id`                          | city, venue_id, venue_note, budget_band, group_size, email, is_simulated, completed_at, furthest_step, created_at, last_seen |
| `identities`            | one channel account of a fan          | `(channel, external_user_id)` | fan_id, source_tag, consent, opted_out, can_message_until                                     |
| `sessions`              | where a fan is in the conversation    | `fan_id`                      | flow_id, step_id, updated_at                                                                  |
| `answers`               | one answer, never edited (history)    | `id`                          | fan_id, field, value, ts                                                                      |
| `events`                | one inbound message                   | `(channel, external_msg_id)`  | fan_id, direction, payload, ts                                                                |
| `replies`               | one bot reply to an event             | `id`                          | fan_id, event key, payload, status (`unsent` / `sent`), ts                                    |
| `announcement_requests` | a show announcement from the dashboard (phase 5) | `id`                         | city, show_date, status (`pending` / `sending` / `done`), sent_count, created_at              |
| `funnel_counts`         | fans whose furthest step is this step | `step_id`                     | count (kept after `/delete`)                                                                  |

## 5. Conversation flow

Steps are data: id, question, input type, options, target field, validation.
A step also names its next step and what its answer clears (e.g. city clears venue).

Order: consent → city → venue → budget → group → email → done.

Options come from `docs/decisions.md` #20 to #25.

### Engine: one core, any channel

Every social app talks to the same engine. An adapter only translates the app's message into a common `InboundEvent`, and the engine's `Reply` back into the app's format. The engine never knows which app it is talking to.

```
 Telegram ──▶ telegram.py ──┐                          ┌──▶ telegram.py ──▶ Telegram
 Web chat ──▶ web_sim.py  ──┤                          ├──▶ web_sim.py  ──▶ Web chat
 WhatsApp ──▶ whatsapp.py ──┤  InboundEvent            │  Reply           (later)
 Instagram ─▶ instagram.py ─┘       │                  │
                                    ▼                  │
                      ┌───────────────────────────┐    │
                      │ Engine (core/)            │    │
                      │ flow, rules, store, DB    │────┘
                      └───────────────────────────┘
```

| Step | What the engine does on each message                         | Why                                       |
| ---- | ------------------------------------------------------------ | ----------------------------------------- |
| 1    | Skip the message if already seen (`channel`, `message id`)   | Apps resend; a fan is never asked twice   |
| 2    | Find or create the fan, and lock them                        | Two fast messages never create two fans   |
| 3    | Check the answer, save it, move to the next question         | Same flow for every app                   |
| 4    | Save the replies as `unsent`, commit everything at once       | Nothing is half saved                     |
| 5    | Adapter sends the replies, marks them `sent`                 | Sending happens outside the database work |

**Adding a new app = one new adapter file.** No change to the engine, flow, database or dashboard. `web_sim.py` proves this: the web chat runs on the same engine as Telegram.

**Failures:**

| Failure                    | Reason                                                       | What happens                                                           |
| -------------------------- | ------------------------------------------------------------ | ---------------------------------------------------------------------- |
| Engine error               | A bug in our code during a turn                              | Turn rolled back; fan gets "Something went wrong, please tap again"; error logged (#71) |
| Database down              | Supabase unreachable or paused                               | Webhook returns 5xx, so Telegram retries later                         |
| Send fails                 | Telegram or network error while sending a reply              | Reply stays `unsent`; resend sweeper sends it within about 40 s (#72)  |
| 429 Too Many Requests      | We hit Telegram's rate limit                                 | Wait the `retry_after` time, then resend (#69)                         |
| 403 Forbidden              | Fan blocked the bot                                          | Fan marked opted out; their unsent replies deleted (#93)               |
| Reply sent twice           | Crash after Telegram accepted the reply, before it was marked `sent` | Accepted: one duplicate is better than a lost reply (#72)      |

**Edge cases:**

| Edge case                                          | What happens                                                                 |
| -------------------------------------------------- | ---------------------------------------------------------------------------- |
| Telegram sends the same message twice              | Second copy skipped by the message id; no double answer (#90)                |
| New fan sends two messages very fast               | Second waits on the fan lock; only one fan is created (#88)                  |
| Fan types text where buttons are expected, or the reverse | Same question asked again (A10)                                       |
| Fan taps a button on an old question               | Nothing changes; bot says "That question has passed" (#91)                   |
| Fan double-taps the same button                    | Second tap ignored silently (#92)                                            |
| Fan types an invalid email                         | Asked again, with a Skip option                                              |
| Fan picks "Other" venue                            | Venue left empty, their note saved; counts for the city only (#46, #51)      |
| Returning fan                                      | Sees their answers and can edit one; history kept in `answers`               |
| Returning fan changes city                         | Venue cleared and asked again, since venues belong to a city (A7)            |
| Fan sends `/start` after `/stop`                   | Subscribed again; resumes at their saved question (A9)                       |
| Very long message                                  | Cut to 1,000 characters (#95)                                                |
| Same person on Telegram and web chat               | Counted as two fans for now (#37)                                            |

## 6. Consent and privacy

| Limit                         | Value                                   |
| ----------------------------- | --------------------------------------- |
| Inbound message text          | Cut to 1,000 characters                 |
| `venue_note` and `email`      | At most 200 characters                  |
| `source_tag` from the link    | Kept only if `^[A-Za-z0-9_-]{1,64}$`    |

| Command   | What it does                                                                                       |
| --------- | -------------------------------------------------------------------------------------------------- |
| `/stop`   | Sets `opted_out = true`. Fan gets no more messages; their answers stay                             |
| `/delete` | Removes the fan's `fans`, `answers`, `identities`, `sessions`, `replies` and `events` rows (#81)    |

After `/delete`:
- Fan gets "Your data is deleted". This message is sent directly and never stored (#81).
- `funnel_counts` goes up by 1 for the furthest step the fan reached, so funnel totals stay right (#45, #84).
- If the same person messages again, they start over as a brand-new fan.

## 7. Dashboard

- Reads `fans`, `venues`, `funnel_counts`, and `identities` (source tag only).
- Uses a read-only DB role (`crowdsense_dashboard`, SELECT only, #105). Phase 5 adds INSERT on `announcement_requests` only (#80). Supabase's public API roles are closed out of our tables (#108).
- Phase 5: announcement form: city dropdown, date picker (today or later), live preview, "Will send to N fans", confirm (#75). Confirm inserts an `announcement_requests` row; the webhook service's sweeper sends it through `core/outbound.py`, paced to Telegram limits (#80, #69).
- Reads through `core/demand.py` (sync). Aggregation in SQL; rules in `insights.py`.
- Password gate (`DASHBOARD_PASSWORD`). Emails hidden unless toggled on.
- Refreshes every 5 s, one read-only snapshot per refresh, so new fans appear live (#106).
- Switch: Simulated (default) / Real. The two are never mixed (#73).
- Banner always shows the view, counted and started fans ("Simulated data · 17,000 counted fans (20,000 started)" / "Real · 9 counted fans (11 started)", #107).

Views:
- Top cities, top venues
- Budget band distribution
- Group size distribution
- City × venue heatmap
- Response funnel (by furthest step reached; completed = `completed_at` set, #84)
- Growth per city per IST week (last 6 weeks); badge from the rolling 7 days (#85)
- Source breakdown
- Recommendations card
- Latest fans (50 newest counted fans; email column hidden until toggled, #60)

Recommendation rules (`core/insights.py`):
- Counted fan = `completed_at` is set (first time the fan reaches done). Edits never uncount (#70, #52).
- A fan re-asked for a venue counts for the city, not for any venue, like "Other" (#51).
- People per fan: 1→1, 2→2, 3–5→4, 6+→6 (#33).
- Suggested venue: smallest with capacity ≥ city attendance ÷ 0.8; else largest (#31c, #49).
- Price band: per city, most common band among counted fans; tie → lower band (#79, #50).
- "Other" fans: count for city, not for any venue (#51).
- Growing: counted fans by `completed_at`; last 7 days ≥ 1.2 × the 7 days before; 0 before → "new" (A5, A6, #85).

## 9. Built-in from phase 1

Written this way from day one; retrofitting costs a rewrite.

| Item                     | What                                                                 | Why                                                   |
| ------------------------ | -------------------------------------------------------------------- | ----------------------------------------------------- |
| Pure core                | `decide(state, event) -> (state, replies, writes)`, no I/O           | Fast, deterministic tests                             |
| Store interface          | Postgres + in-memory fake                                            | Tests without a DB; backup DB drops in                |
| Insights module          | Rules as pure functions                                              | Testable; Streamlit only draws                        |
| One transaction per turn | Dedupe, identity lock (#88), state, answers, replies commit together | No half-saved turns; double taps serialised           |
| Clock seam               | Engine and seed get time from `clock.py`                             | Seed spreads fans across weeks; growth rules testable |
| Store contract tests     | One suite runs on Postgres and the in-memory fake                    | The fake is a trustworthy second adapter              |
| Config module            | Settings validated at startup (`ARTIST_NAME`, URLs, secrets)         | Fail fast; no hard-coded "Artist X"                   |
