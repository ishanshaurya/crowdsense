# Phase 3: Prove the plugin design (web chat + seed)

Status: **built and green.** 371 tests pass (the 257 from phases 1 and 2 are all still green), `core/` coverage 98.5%. ruff, ruff format, mypy strict, import-linter (4 contracts), detect-secrets, pip-audit and `uv lock --check` are clean. `git diff phase-2 -- core migrations` is empty: **no core or schema change**. **Open:** commit + tag `phase-3`, and phase 2's checkpoint C (live Telegram run). Phone check deferred to phase 5 (#103).

## Baseline (before any phase 3 change)

- 257 tests pass; every check clean; no diff in `core/` or `migrations/` since tag `phase-2`.
- Already in the tree, uncommitted, untested: `adapters/web_sim.py`, `api/chat.py`, `api/ratelimit.py`, `api/static/`, the `mount_chat` line in `api/webhooks.py`.

## Build checklist

- [x] A. Baseline recorded
- [x] §2 Doc drift: #99 to #102 added (README #1–#102); seed size lines → 20,000 (#78); Q-15 → #101. Phase 2 checkpoint C still open (user)
- [x] B. Web chat tests (P3-U01, P3-U02, routes, rate limit, XFF, expiry); one bug fixed (below)
- [x] C. Parity (P3-C01, P3-C02, P3-C08)
- [x] D. No-core-change check (P3-C03, Q-15) as tests and a CI step
- [x] E. Seed (P3-U03, P3-U04, P3-C04, P3-C05, P3-C07, Q-16)
- [x] F. Reset (#62, P3-C06)
- [x] Notes, traceability, metrics
- [x] Supabase seed (2026-10-16): 20,000 simulated fans, copy 19.8 s over the network, DB 71 MB; 0 replies; 1 real fan untouched
- [x] Manual checklist Phase 3: browser chat passed (fan 20004: web_sim, real, completed, 8 replies sent); seed spot-check passed. Phone check deferred to phase 5 (#103)

## Overview

```
Web chat (any browser, through the same ngrok URL, #77)
  GET /chat, /chat/app.js, /chat/app.css   ── rate-limited per IP (#99), CSP + nosniff + no-referrer
  POST /chat/message {user, msg_id, kind, ...}
     │ 429 (Retry-After) │ 413 > 4 KB │ 400 bad body
     ▼
  WebSimAdapter.parse ──▶ InboundEvent(channel="web_sim")   same type as Telegram (P3-U01)
     ▼
  engine.handle(event)  ── the SAME engine, one transaction (#55)
     │ StoreUnavailable → 503 │ bug → 200 + apology, nothing saved (#71)
     ▼
  200 {replies:[{text, step_id, expects, options:[{id,label}]}]}   replies go back IN the response
     └─ background: mark_sent; once a minute expire_unsent (> 10 min old → sent, #100)

Seed (scripts/seed.py, #78, #82, #102)
  plan_fans(20,000, seed=42, now)  ── pure, deterministic (scripts/seed_plan.py)
     ▼
  Engine(InMemoryStore, ScriptedClock, simulated=True), channel "seed": every fan really chats
     ▼
  rows: fans, identities, sessions, answers, events   (replies NOT copied)
     ▼
  check_rows: all simulated, all channel "seed"   else refuse
     ▼
  ONE Postgres transaction: [--reset: DELETE FROM fans WHERE is_simulated → cascades]
                            reserve ids with nextval(...) → COPY each table
```

## Files and responsibilities

| File | Job |
|---|---|
| `adapters/web_sim.py` | `parse_body` (every field checked, `None` on anything odd, client clock ignored), typed commands → same kinds as Telegram, `render_reply` (core option ids), `WebSimAdapter` (`can_push_anytime=False`, `send` raises) |
| `api/chat.py` | `WebChat`: static files with security headers, `POST /chat/message` (cap body, parse, engine, reply in response, mark sent after), `expire_unsent`; `mount_chat` / `add_chat_routes` |
| `api/ratelimit.py` | `RateLimiter` token bucket per key, bounded memory; `client_ip` (#99) |
| `api/static/` | `chat.html`, `app.js` (textContent only, new id per page load #83, retry with the same `msg_id`), `app.css` |
| `api/webhooks.py` | One line: `mount_chat(app, engine, store, clock)` in `build_app` |
| `scripts/seed_plan.py` | Approved shares and rates; `plan_fans` → `FanPlan` (user, city, week, start, tag, moves) |
| `scripts/seed.py` | `run_engine`, `rows_of`, `check_rows`, `copy_rows` (reset + COPY in one transaction), `guard_host`, CLI |
| `tests/unit/test_web_sim_adapter.py` | P3-U01, P3-U02, bad bodies, limiter, `client_ip` |
| `tests/component/web_fake.py` | `build_web_rig` (Telegram webhook app + chat routes, like production), `WebFan` |
| `tests/component/test_web_chat.py` | P3-C01, P3-C02, P3-C08, headers, 400/413/429/503, apology, sweeper vs expiry |
| `tests/unit/test_seed_plan.py` | P3-U03 (incl. across processes), P3-U04, rates, dates, Q-16 |
| `tests/component/test_seed.py` | P3-C04 to P3-C07, refusals, host guard (Postgres only: COPY) |
| `tests/quality/test_phase3_quality.py` | P3-C03, Q-15 (#101 paths, wiring line only), Q-11 for the web chat, every P3 id has a test |
| `.github/workflows/ci.yml` | `fetch-depth: 0` + a step that fails on any `core/` or `migrations/` diff since `phase-2` |

## Seed shape (approved 2026-10-16)

- 20,000 fans, channel `seed`, users `seed-000000…`, 6 weeks before seed time, `--seed 42`.
- City share: Mumbai 20, Delhi NCR 18, Bengaluru 16, Hyderabad 9, Pune 9, Kolkata 7, Chennai 7, Ahmedabad 5, Jaipur 5, Indore 4.
- Weeks: a fixed quota per city and week, then shuffled. Jaipur and Indore weight 1.35^week; others flat. (Random weeks were noisy: Indore once went 54, 81, 71…)
- 5% decline consent, 10% drop at a random question, 85% finish. 5% pick "Other" + a short note. Venue: bigger venue 3:2. Budget: metros 10/35/35/20, others 25/45/22/8. Group 20/40/30/10. 30% leave `fanNNNNNN@example.com`. Tags ig_story 40, ig_bio 25, poster 20, yt 15.
- Turns 40 s apart; the clock is set to each fan's start.

## Safety rules

- **Simulated isolation (#76, #102).** Only the seed sets `is_simulated` (engine `simulated=True`). Seeded fans live on channel `seed`: no adapter, not in `push_channels`, never claimed by the sweeper (it claims registered channels only). Their replies are never copied, so there is nothing to send even by mistake. Phase 5's audience is real fans only (#85).
- **`funnel_counts` has no simulated flag**, so the seed never sends `/delete` and never copies it.
- **Reset (#62).** `DELETE FROM fans WHERE is_simulated` (identities, sessions, answers, events, replies cascade) + `DELETE FROM identities WHERE channel = 'seed'` (orphan guard), then COPY, all in one transaction. A failure rolls everything back. Without `--reset` the script refuses if simulated fans exist. Real fans never touched (P3-C06).
- **Hosts.** Non-local host refused without `--allow-remote`; only the host is printed, never the URL. `DATABASE_URL` missing → stops before the engine run.
- **Rate limit (#99).** 60 burst, 1/s refill, per IP, 10,000 keys max (idle ones pruned first). Behind ngrok the socket peer is localhost, so the IP is the **last** `X-Forwarded-For` entry (ngrok's); earlier entries are client-written and ignored. A non-local peer's XFF is ignored.
- **Web chat input.** Body ≤ 4 KB (header and streamed), user id `[A-Za-z0-9-]{8,64}`, msg id `[A-Za-z0-9_-]{1,64}`, step/choice ≤ 64; text cap 1,000 is the core's (#95). The page renders text with `textContent` (the edit menu echoes saved answers).

## Test id → file

| Id | File |
|---|---|
| P3-U01, P3-U02 | `tests/unit/test_web_sim_adapter.py` |
| P3-U03, P3-U04, Q-16 | `tests/unit/test_seed_plan.py` |
| P3-C01, P3-C02, P3-C08 | `tests/component/test_web_chat.py` |
| P3-C03, Q-15 | `tests/quality/test_phase3_quality.py` + CI step |
| P3-C04 to P3-C07 | `tests/component/test_seed.py` |

## Measured (2026-10-16, laptop, local Postgres 16)

| What | Result |
|---|---|
| Seed engine run, 20,000 fans | 4.9 s (in memory) |
| COPY to Postgres | 1.4 s; whole command 6.4 s; `--reset` + reseed 7.1 s |
| Rows | fans 20,000 · identities 20,000 · sessions 20,000 · answers 76,800 · events 129,575 · replies 0 |
| Database size with the seed | 63 MB (events 38 MB, answers 10 MB) of Supabase's 500 MB |
| Web chat turn over ASGI, in-memory store | p50 0.20 ms, p95 0.25 ms (1,400 turns; no network, no DB) |

Answers are 3.8 per fan, not the ~7 estimated in `docs/metrics.md` (5 questions, fewer for drop-offs and declines); the doc now holds the measured number.

## Decisions added

- **#99** Rate limit per IP; XFF trusted only from localhost, last entry.
- **#100** Web chat replies return in the response; unsent > 10 min → marked sent by `expire_unsent`.
- **#101** Plugin cost = adapter file + its `api/` routes + one wiring line (+ scripts, tests, docs); core/migrations frozen; enforced by test + CI.
- **#102** Seeded fans on channel `seed`, replies not copied, no `/delete`.
- **#103** Interviewer gets the public ngrok `/chat` link (plus the Telegram deep link); localhost is presenter-only; phone check moved to the phase 5 rehearsal.

## Gotchas

- **`limiter or RateLimiter()`** dropped an injected limiter: `RateLimiter` has `__len__`, so an empty one is falsy. Now `is not None`. Same trap for any container-like object with a default.
- **A `set` of strings iterates in hash order**, which changes per process (`PYTHONHASHSEED`). The seed quota loop uses `sorted(set(...))`; a test runs the plan in two processes with different hash seeds. And `hash()` of a str is itself randomised, so the test compares `repr`.
- **Parity needs normalising.** Telegram text events carry Telegram's message `date`; the web chat uses receive time (the client clock is untrusted). Payloads also contain the user id. Both are dropped before comparing; the Done text differs on purpose (#87).
- **COPY into `GENERATED ALWAYS` identity columns works** (COPY does not need `OVERRIDING SYSTEM VALUE`). Ids are reserved with `nextval(pg_get_serial_sequence(...))` first, so real inserts during the copy never collide.
- **Retry after a lost response.** `app.js` resends with the same `msg_id`; if the server had already marked the replies sent, the duplicate returns no replies and the buttons vanish (the fan can still type). Rare; fixing it needs either the page keeping stale buttons or a core change. Left as is.
- **Homebrew `pg_ctl` needs `LC_ALL`** set, or the postmaster fails with "became multithreaded during startup". Plus `initdb -E UTF8` (phase 2).
- **Q-15 before vs after the tag.** Until tag `phase-3` exists the check diffs `phase-2` → working tree (untracked too); after, `phase-2` → `phase-3`, so phase 4 may change `core/` again. Tag `phase-3` when committing.
- **detect-secrets flags hex-looking test ids**; tests use `web-fan-0001`.

## How to run

```bash
uv run pytest -q --cov=core --cov-fail-under=90
uv run python -m scripts.seed --dry-run                                  # memory only
DATABASE_URL=postgresql://localhost:5432/dev uv run python -m scripts.seed --reset
uv run --env-file .env python -m scripts.seed --allow-remote [--reset]  # Supabase: demo day, after "go"
uv run uvicorn api.webhooks:build_app --factory --env-file .env --port 8000   # /chat is served here
```

## Likely interview Q&A

**How do you know the plugin design works?** A second channel was added with zero change to `core/` or `migrations/`, proven by a test and a CI step that diff against the `phase-2` tag (P3-C03). Every conversation scenario runs through the web chat with the same final rows (P3-C01), and the same flow on Telegram and the web chat writes identical rows except channel, ids and the Done text (P3-C02).

**Why is the web chat more than one file?** A web page needs its own routes, static files and abuse controls (rate limit). Those live in `api/`; the adapter itself is one file that only translates. #101 sets the allowed paths and a test enforces them.

**Why bulk-copy instead of 20k live turns?** The point of the seed is data that went through the real engine, not a load test. In memory it takes 5 s; 160k turns over the network to Supabase at ~180 ms each would take hours. COPY is one transaction and 1.4 s locally. Load is measured separately in phase 6.

**How do you stop messages to fake fans?** Three independent guards: seeded fans live on a channel no adapter serves, none of their replies is stored in Postgres, and the outbound audience is real fans only. A test asks the sweeper's own query for unsent replies on every channel and gets none (P3-C05).

**How do you keep simulated and real data apart?** `is_simulated` set only by the seed; reset deletes only simulated fans; the test makes a real fan, reseeds twice and compares the real rows byte for byte (P3-C06). `funnel_counts` has no flag, so the seed never touches it.

**Why is the seed deterministic?** Same seed → same fans, so a demo is repeatable and a bug is reproducible. Weeks use fixed quotas, so "Jaipur and Indore rising" is a guarantee, not luck.

**How is the public chat protected?** Per-IP token bucket with bounded memory, XFF trusted only from the local ngrok agent, 4 KB body cap, strict field patterns, CSP `default-src 'self'`, `textContent` only, no push, no admin routes.

**What doesn't the web chat do?** No stable identity (refresh = new fan, #83), no push (announcements skip these fans, #76), and the laptop must stay on (#77).
