# Metrics

What Crowdsense can handle, how many users it works with, and how we prove it.
Use this for the demo and interview questions on load, scale and bot quality.

- **Target** = what we aim for. **Result** = filled in after measuring.
- Targets are proposed. Measure first, then lock them. Decisions: `docs/decisions.md`. Phases: `docs/plan.md`.
- Final numbers also go into the README "Production readiness" table (phase 6).

## 1. Scale we work with

| What                                               | Number                                | Source         |
| -------------------------------------------------- | ------------------------------------- | -------------- |
| Simulated fans (seeded)                            | ~20,000                               | #78            |
| Real fans (testers on their own Telegram accounts) | ~9 to 10                              | #73            |
| Cities                                             | 10                                    | #20            |
| Venues                                             | 14 (2,000 to 30,000 seats)            | #24            |
| Answer rows from the seed                          | 76,800 measured (3.8 per fan; was estimated at 7) | #78   |
| Database size with the seed                        | 63 MB measured (events 38 MB, answers 10 MB) of the 500 MB free tier | #78 |
| Dashboard scale target                             | 100,000 fans, 1,000,000 answers       | `docs/plan.md` |

## 2. What each proof shows

Different tests prove different things. Do not mix them up in the interview.

| Proof                                       | What it shows                                                       | What it does **not** show                     | Phase |
| ------------------------------------------- | ------------------------------------------------------------------- | --------------------------------------------- | ----- |
| Seeding 20,000 fans through the real engine | **The bot logic handles 20,000 conversations correctly**            | How many requests per second the server takes | 3     |
| Dashboard on the 20,000-fan dataset         | **The dashboard stays fast with that much data**                    | Speed at 100k (that is a phase 6 test)        | 4     |
| Dashboard on 100,000 seeded fans            | Queries scale past the demo size                                    | Live traffic                                  | 6     |
| Load test (Locust → real webhook)           | **Requests per second and latency under load**                      | Real Telegram network speed                   | 6     |
| Soak test                                   | No memory leak or slowdown over time                                | Peak load                                     | 6     |
| Chaos tests                                 | Duplicates, double taps, crashes and DB outages do not corrupt data | Speed                                         | 6     |
| Real testers on Telegram                    | The full live path works end to end                                 | Scale                                         | 2, 5  |

Why the seed is not a load test: it runs the engine in memory and bulk-copies rows. It skips the webhook, the network and per-message database transactions (#78).

## 3. Load and speed

| Metric                           | Target                                        | How measured                              | Tool              | Phase | Result |
| -------------------------------- | --------------------------------------------- | ----------------------------------------- | ----------------- | ----- | ------ |
| Webhook ack p95 (our code only)  | < 300 ms                                      | Fake Telegram updates to the real webhook | Locust            | 6     | —      |
| Engine turn p95                  | < 100 ms                                      | Engine alone, timed                       | pytest + timer    | 6     | 0.70 ms on local Postgres (p50 0.48 ms, 800 turns, 8.1 round trips/turn); phase 1 code: 3.45 ms, 12.6 round trips |
| Dashboard query p95 at 20k fans  | < 1 s                                         | Each query on the seeded DB               | `EXPLAIN ANALYZE` | 4     | Local Postgres 15, as the dashboard role, 30 runs: slowest query p95 6.0 ms server / 5.5 ms wall (`growth`); whole refresh (12 queries, one pipelined round trip) p50 30.1 ms, p95 31.1 ms. Supabase (laptop → ap-south-1 transaction pooler, as the dashboard role, 20 runs): server p95 < 23 ms per query; wall p95 per query up to 617 ms (`budget`; spikes are network jitter, not query time); whole refresh (12 queries pipelined, warm connection), two 40-run benches: p50 306–313 ms, p95 447–601 ms, max 600–962 ms; first (cold) connect 650–970 ms. Pipelined vs one query at a time, same data: p50 324–362 ms vs 978–1,478 ms (~3–4× faster). Intermittent multi-second outliers (p95 3.3–5.4 s in two 20-run comparisons, both modes) come from the network/pooler, not the queries |
| Dashboard query p95 at 100k fans | < 1 s                                         | Same, larger seed                         | `EXPLAIN ANALYZE` | 6     | —      |
| Launch spike                     | 50 msg/s, no errors, recovers in seconds      | Spike run                                 | Locust            | 6     | —      |
| Soak                             | 10 msg/s for ~30 min, memory and latency flat | Soak run                                  | Locust            | 6     | —      |
| Seed run time (20k fans)         | Measure and report                            | Time the seed command                     | stopwatch         | 3     | 6.4 s local (engine 4.9 s, COPY 1.4 s); `--reset` + reseed 7.1 s |
| New fan visible on dashboard     | ≤ 10 s                                        | Tap in Telegram, watch dashboard          | manual            | 4     | Engine commit → browser DOM change, real Streamlit server, 6 samples: 0.55–4.45 s (max 4.45 s); worst case by design ≈ 9 s (5 s refresh + 4 s cache). Phone check: manual checklist |

Report our time, Telegram API time and ngrok time separately, so the numbers are honest.

Database network time, measured separately (2026-10-16, laptop to Supabase Mumbai, session pooler port 5432): fresh connect 136 to 155 ms, one query p50 22 ms (20.7 to 48.6 ms). A known-fan turn is about 8 round trips on a pooled connection, so about 180 ms of database network time per turn (phase 1: a new connection plus about 12.6 round trips, about 430 ms). The phase 1 audit measured 250 ms connect and 35 ms per query on another day; network time varies.

### How many users that means

Derived from the targets, not measured yet:

- A fan needs about 8 messages to finish the flow.
- At 50 msg/s → about 6 fans finish per second → **about 22,000 fans per hour**.
- At 10 msg/s sustained → about 4,500 fans per hour.
- Replace these with measured numbers after phase 6.

## 4. Bot strength (correctness and reliability)

| Metric                               | Target                                                 | How measured           | Phase | Result |
| ------------------------------------ | ------------------------------------------------------ | ---------------------- | ----- | ------ |
| Duplicate messages handled           | 100% skipped, no double counting                       | Contract + chaos tests | 1, 6  | —      |
| Double taps by a brand-new fan       | One fan, no error                                      | `P1-S08` (#88)         | 1     | Pass, both backends |
| Half-saved turns after a crash       | 0                                                      | `P1-S03` (#55)         | 1     | 0, both backends |
| Same tap delivered twice by Telegram | Skipped by `update_id`                                 | `P2-C03` (#90)         | 2     | Pass, both backends |
| Taps on old buttons                  | 100% ignored, no state change                          | `P2-C10` (#91)         | 2     | Pass, both backends (+ `P2-C17`) |
| Fan double-taps one button           | One answer, one reply                                  | `P2-C09` (#91, #92)    | 2     | Pass, both backends (concurrent taps) |
| Fans blocked → messages still sent   | 0                                                      | `P2-C13` (#93)         | 2     | 0, both backends |
| Lost replies                         | 0 (sweeper resends)                                    | `P2-C07` (#72)         | 2     | 0 in `P2-C07`, both backends |
| Duplicate replies                    | Rare; only crash between send and mark (at-least-once) | Chaos test             | 6     | —      |
| Engine errors shown to fan           | One apology, no retry storm                            | `P2-C04` (#71)         | 2     | Pass, both backends |
| Opted-out fans messaged              | 0                                                      | `P5-C05`               | 5     | —      |
| Simulated fans messaged              | 0                                                      | `P3-C05`               | 3     | 0: no seeded replies stored, nothing claimable (#102) |
| `/delete` leaves fan data            | 0 rows                                                 | `P1-C07` (#81)         | 1     | 0 rows, both backends |
| Coverage on `core/`                  | ≥ 90%                                                  | CI                     | 1     | 98.74% (phase 4) |

## 5. Other non-functional requirements

### Reliability

- No lost messages: event saved before ack.
- No double counting: dedupe on `(channel, external_msg_id)`.
- No race on double taps, even for a brand-new fan: identity row lock (#88).
- Outbound retries with backoff; failures visible in `outbox`.
- DB down → webhook returns error; Telegram retries; no corruption.
- Availability target once cloud hosted (#29): 99.5% (≈ 3.6 h/month). Laptop demo: no target.

### Data integrity

- FK, CHECK and enum constraints in the DB, not only in code.
- Migrations up and down tested.
- `fans` snapshot can be rebuilt from `answers`.

### Security

- Webhook secret header checked on every call.
- Secrets only in `.env` / host secrets; `.env.example` has names only.
- Dashboard uses a read-only DB role.
- Rate limit per identity and per IP.
- Input length caps: message text 1,000 characters, `source_tag` 64 characters from a safe alphabet, `venue_note` and `email` 200 characters (#95, #98). Why: `docs/design-review.md` §15.
- Dependency, secret and image scans in CI.

### Privacy (DPDP-minded)

- Consent before any question.
- `/stop` and `/delete` work and are tested.
- No phone numbers stored for Telegram.
- PII redacted in logs.
- Simulated data clearly flagged; never messaged.

### Observability

- JSON logs with a correlation id per message.
- Metrics: request rate, errors, latency (p50/p95/p99), funnel drop-off.
- Traces across webhook → engine → DB.
- `/health` (alive) and `/ready` (DB reachable).
- Uptime check on `/health`.

### Maintainability

- Type-checked (strict), linted, formatted.
- Coverage gate in CI (90% on `core/`).
- Every behaviour decision mapped to a test (`testing/traceability.md`).
- New channel = one adapter file + passing conformance suite.

### Cost

- Demo hosting ≤ ~$7/month (see `docs/decisions.md` §4 "Demo hosting").
- No paid services needed for development.

---

## 6. Scale path (beyond this project)

What changes as load grows. Not built now; shows the next step.

| Load                  | Bottleneck                  | Next step                                                              |
| --------------------- | --------------------------- | ---------------------------------------------------------------------- |
| ~10k fans             | None                        | Current design                                                         |
| ~100k fans            | Dashboard queries           | Indexes, materialized views refreshed per minute                       |
| ~1M fans / big launch | Webhook spikes, DB writes   | Inbox table → worker pool; Supabase pooler; read replica for dashboard |
| Many artists          | Data isolation              | `campaigns` + Postgres row-level security                              |
| Many channels         | Outbound limits per channel | Per-channel rate limits in the outbox sender                           |
| ~10M answers          | `answers` / `events` size   | Partition by month; archive old events                                 |

---

## 7. Funnel and product metrics (shown on the dashboard)

| Metric              | Meaning                                      | Where                                    |
| ------------------- | -------------------------------------------- | ---------------------------------------- |
| Completion rate     | Counted fans ÷ fans who started              | Funnel view (#84)                        |
| Drop-off per step   | Fans whose furthest step is X                | Funnel view (#84)                        |
| Invalid-input rate  | Re-asks ÷ total answers                      | Logs                                     |
| Fans per source tag | Story vs bio vs poster                       | Source breakdown                         |
| Announcement reach  | Messages sent ÷ eligible fans                | `announcement_requests.sent_count` (#80) |
| Announcement time   | Time to send to N fans (Telegram caps ~30/s) | Sweeper logs (#69)                       |

## 8. Interview one-liners

- "Bot logic verified on 20,000 seeded conversations."
- "Dashboard queries under 1 s on 20,000 fans; target holds at 100,000."
- "Webhook handles N msg/s at p95 M ms" (fill in after the Locust run).
- "Zero lost replies, zero double counting, verified by tests."
- "Real users: about 10 testers on Telegram, kept separate from simulated data."

## 9. Honest limits

- Seed ≠ load test (section 2).
- Laptop + ngrok numbers are slower than a cloud host would be.
- Outbound speed is capped by Telegram (~30 msg/s overall, ~1/s per chat).
- Simulated data shows the system works, not real demand.
