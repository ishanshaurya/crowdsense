# CrowdSense: Design Decisions

Architecture and stack: [`architecture.md`](architecture.md). Product scope: [`prd.md`](prd.md).

## Summary

| Item | Detail |
| --- | --- |
| Product | Telegram bot collects fan answers; artist dashboard shows city, venue, price recommendations |
| Channels | Telegram, web chat (same engine) |
| Stack | Python, FastAPI, Postgres (Supabase), Streamlit, Railway |
| Reliability | Crash never leaves a fan out of step |
| Security | Leaked public Supabase key reaches no table |
| Data integrity | Duplicate announcement cannot be queued |
| Scale tested | 20,000 simulated fans, about 6 s to seed locally (not a load test) |
| Latency | 1.2 to 1.5 s per tap; engine under 1 ms, rest is network |
| Tests | 289 test functions across unit, component, quality suites |

## Decisions at a glance

| # | Problem | Chose | Rejected | Cost accepted |
| --- | --- | --- | --- | --- |
| 1 | Telegram send fails after state saved | One transaction for state + replies, send after commit, sweeper resends | Send first then save; do nothing | `replies` table; rare duplicate message |
| 2 | Double tap looks identical to stale button | Answer spinner at once, tick after engine applies, 60 s in-process memory | Block until engine finishes | Restart in window shows one extra "That question has passed" |
| 3 | Supabase roles read everything with RLS off | Revoke `anon` and `authenticated` on every object | RLS alone | Script outside migrations, plus per-migration closing |
| 4 | Engine bug makes Telegram retry for hours | Roll back, return 200, one apology; DB outage still 5xx | Always 5xx | One apology instead of retries |
| 5 | Editing an answer dropped fans from counts | `completed_at`, set once, never cleared | Staging copy of old answers | Edit does not make a new fan |
| 6 | Counts by city, week, answer | Postgres | Mongo, Redis | None at this size; `pg_dump` keeps it portable |
| 7 | 1,500 seed fans broke recommendations | 20,000 seed fans | Smaller seed | About 6 s to seed locally |
| 8 | Postgres store and in-memory fake could drift | One contract suite against both | Test each separately | Slightly larger test setup |
| 9 | Same announcement queued twice | Unique `(city, event_date)` | Idempotency key per send | Cannot resend a corrected announcement |

## 1. Saving and sending

- **Problem:** state saved, Telegram send fails, fan sees nothing
- **Decision:** save state and replies in one transaction, send after commit, sweeper resends unsent
- **Why:** only option where a crash cannot leave the fan out of step
- **Rejected:**
  - Send first, save second: breaks on crash in between
  - Do nothing: chat stuck until `/start`
- **Cost:** `replies` table; rare duplicate when crash lands between send and mark
- **Mistake caught:** assumed Telegram retries the webhook; it does not, because we return 200
- **Evidence:** [`api/sweeper.py`](../api/sweeper.py), [`api/sender.py`](../api/sender.py), [`tests/component/test_outbound.py`](../tests/component/test_outbound.py)

## 2. Double taps and stale buttons

- **Problem:** a tap answers once; only the engine knows if it was stale; double tap looks identical to old-button tap
- **Decision:**
  - Adapter answers spinner immediately
  - Button swaps to ✓ after engine applies the tap
  - Webhook remembers confirmed messages for 60 s
- **Why:** fast feedback beats perfect spinner accuracy
- **Cost:** memory is in-process; restart in window shows one extra "That question has passed"
- **Edge case:** 403 means fan blocked the bot; pending replies are dropped, not retried
- **Evidence:** [`api/taps.py`](../api/taps.py), [`api/sender.py`](../api/sender.py)

## 3. Database permissions

- **Problem:** Supabase `anon` and `authenticated` roles get full access with RLS off; public key could read, edit, delete fan data
- **Decision:** revoke both roles on every table, sequence, function
- **How:**
  - Script does the revoking, not a migration (roles only exist on Supabase)
  - Dashboard role can read and insert an announcement request (city, date)
  - Each migration closes its own new objects
- **Why:** safety does not depend on re-running the script
- **Evidence:** [`scripts/lock_public_api.py`](../scripts/lock_public_api.py), [`scripts/dashboard_role.py`](../scripts/dashboard_role.py), [`tests/component/test_lock_public_api.py`](../tests/component/test_lock_public_api.py)

## 4. Bugs versus outages

- **Problem:** Telegram retries a failing webhook for hours; 5xx on a bug repeats the apology every retry
- **Decision:**
  - Bug: roll back the turn, return 200, send one apology
  - DB outage: return 5xx (nothing saved, retry is free)
- **Evidence:** [`api/webhooks.py`](../api/webhooks.py), [`tests/component/test_webhook.py`](../tests/component/test_webhook.py)

## 5. Who counts as a fan

- **Problem:** "counted" meant "on done step"; "Edit city" moved fans back and they vanished from every number
- **Decision:** `completed_at`, set once, never cleared
- **Why:** fan already said they want to come; one edit is not a new person
- **Rejected:** staging copy of old answers (too much for MVP)
- **Evidence:** [`migrations/versions/0001_schema.py`](../migrations/versions/0001_schema.py)

## 6. Database

- **Problem:** dashboard needs counts by city, week, answer
- **Decision:** Postgres, since every view is a `GROUP BY` or date bucket
- **Rejected:**
  - Mongo: aggregation pipelines, second query language, no gain
  - Redis: one row of state per fan, extra system to run
- **Why it fits:**
  - Consent stored per identity in the schema
  - Answers are timestamped history, not overwritten fields
  - Dashboard has no write access
- **Exit path:** `pg_dump` to any Postgres host
- **Evidence:** [`core/store_postgres.py`](../core/store_postgres.py), [`core/demand_queries.py`](../core/demand_queries.py)

## 7. Seed size

- **Problem:** 1,500 fans gave every city its smallest venue; recommendation looked broken
- **Decision:** 20,000 fans, enough spread per city
- **Scope:**
  - Runs through real engine in memory, bulk-copied to Postgres, about 6 s locally
  - Not a load test (skips webhook and network)
  - Dashboard separates simulated from real fans; web chat users count as real
- **Evidence:** [`scripts/seed.py`](../scripts/seed.py), [`tests/component/test_demand_at_scale.py`](../tests/component/test_demand_at_scale.py)

## 8. Testing the store

- **Problem:** Postgres store and in-memory fake, nothing proving they match
- **Decision:** one contract suite runs against both from phase 1
- **Why:** drift is cheap to catch early; keeps fast in-memory tests trustworthy
- **Evidence:** [`tests/component/test_store_contract.py`](../tests/component/test_store_contract.py)

## 9. Duplicate announcements

- **Problem:** two people queue the same announcement for the same show
- **Decision:** unique constraint on `(city, event_date)`; dashboard shows "Already queued"
- **Why:** simplest way to make the duplicate impossible
- **Rejected:** idempotency key per send
- **Cost:** cannot resend a corrected announcement for the same show
- **Evidence:** [`migrations/versions/0004_announcements.py`](../migrations/versions/0004_announcements.py)

## What I measured

| Part | Time |
| --- | --- |
| Full tap to next question | 1.2 to 1.5 s |
| Engine, local Postgres | under 1 ms |
| Supabase round trip from laptop | about 45 ms each |
| Telegram round trip | about 180 ms |

- Time goes on round trips, not compute
- Reordering two calls saves about 360 ms
- Railway in Singapore does not remove the distance to the database
- **Evidence:** [`scripts/bench_turn.py`](../scripts/bench_turn.py), [`scripts/bench_demand.py`](../scripts/bench_demand.py)

## Known limits

| Limit | Impact | Status |
| --- | --- | --- |
| Web chat has no stable fan id | Refresh makes a new fan | Accepted; backup channel only |
| No minimum-sample handling | 3-fan city looks as confident as 3,000-fan city | Not done |
| Stated intent is not a purchase | Demand overstated | Documented in README |
| Only finished chats counted | Demand overstated | Documented in README |
