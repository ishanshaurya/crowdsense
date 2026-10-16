# Phase 6: Hardening

Adds the layers deferred from phases 1 to 5: contract, property, load and resilience. All earlier tests stay green. Items come from `ARCHITECTURE.md` §11; tools and NFR targets from `PLAN.md`. Targets are proposed; set them after measuring.

## Build

Inbox-first idempotent webhook with row locking, campaigns, outbox for outbound, flow versioning, adapter conformance suite, projection rebuild, observability, load tests (Locust), README "Production readiness" table.

## Contract tests (`K`)

| Id | What | Expected |
|---|---|---|
| P6-K01 | Adapter conformance suite: parse, render options, degrade to numbered text, capabilities, event id stability | Telegram and web sim both pass the same suite |
| P6-K02 | Telegram payload contract | Every recorded fixture parses; a fixture with an unknown field still parses |
| P6-K03 | Store contract | Fake and Postgres pass the same suite (extends P1-C11) |
| P6-K04 | Reply contract | Every step in the flow yields a valid `Reply` (text present, options within channel limits) |

## Property tests (`R`, Hypothesis)

| Id | Invariant |
|---|---|
| P6-R01 | Any sequence of random valid and invalid inputs never leaves a session in an unknown step |
| P6-R02 | Duplicate message ids never create duplicate rows or replies |
| P6-R03 | `fans` always equals the latest values in `answers` (and rebuilds identically from `answers`) |
| P6-R04 | An opted-out or simulated fan never receives an outbound message |
| P6-R05 | `decide` is deterministic and performs no I/O |
| P6-R06 | Insights output is invariant to row order and to interest values |
| P6-R07 | Suggested venue capacity is never below attendance ÷ 0.8 unless the largest venue is chosen |

## Component tests for new architecture items

| Id | What | Expected |
|---|---|---|
| P6-C01 | Double tap (concurrent events for one fan) | Processed one at a time; final state correct; no lost update |
| P6-C02 | Inbox-first: crash after saving the event, before processing | On restart the event is processed once |
| P6-C03 | Campaigns | Two campaigns with different flows and venues stay isolated |
| P6-C04 | Flow versioning | A fan mid-flow on v1 finishes on v1 after v2 is released |
| P6-C05 | Outbox | Failed send retries with backoff; opt-out checked at send time; each message sent once |
| P6-C06 | Projection rebuild command | Rebuilds `fans` from `answers`; result equals the snapshot |
| P6-C07 | `/health` and `/ready` | Health ok when the process is up; ready fails when the DB is unreachable |
| P6-C08 | Logs | Every request has a correlation id; no user ids or emails appear in logs |

## Resilience tests (`X`)

| Id | What | Expected |
|---|---|---|
| P6-X01 | Duplicate webhook delivery | One result |
| P6-X02 | Out-of-order messages | Session stays valid; the late message is handled or ignored |
| P6-X03 | DB down during a webhook | Returns a retryable response; no partial rows; recovers when the DB returns |
| P6-X04 | DB latency injected (toxiproxy) | Webhook still acknowledges within the target or times out cleanly |
| P6-X05 | Telegram send fails or times out | Retried by the outbox; the conversation state is not corrupted |
| P6-X06 | Malformed or oversized payload | Rejected without a crash |

## Load tests (`L`, Locust with fake Telegram updates)

| Id | What | Measure | Proposed target |
|---|---|---|---|
| P6-L01 | Steady load on the webhook | p50/p95/p99, errors, throughput | ack p95 under 300 ms (our time only) |
| P6-L02 | Engine turn alone | p95 | under 100 ms |
| P6-L03 | Spike | Error rate and recovery time | no errors, recovers in seconds |
| P6-L04 | Soak (about 30 minutes) | Memory and latency drift | flat |
| P6-L05 | Dashboard queries at 100k seeded fans | p95 per query, with `EXPLAIN ANALYZE` | under 1 s |
| P6-L06 | Latency split | Ours vs Telegram API vs ngrok reported separately | reported |

## Exit (final output)

- All new tests pass, and every earlier phase's tests are still green.
- Measured results against the targets in the README "Production readiness" table.
- CI is green with the coverage gate and the security checks.
- All quality checks `Q-01` onward pass.
