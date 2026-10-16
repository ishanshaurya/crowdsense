# Phase 2 notes: Telegram adapter + webhook service

Goal: a real phone taps `t.me/crowdsense_live_bot?start=ig_story`, finishes the flow over Telegram, and the rows land in Supabase. Along the way: input caps in core (#95), a pooled Postgres store, the resend sweeper (#72) and the Telegram failure rules (#71, #93).

Status: **built and green.** 256 tests pass (phase 1's 142 are all still green), `core/` coverage 98.5%. ruff, ruff format, mypy strict (now `core`, `adapters`, `api`), import-linter (4 contracts), detect-secrets, pip-audit and `uv lock --check` are all clean. Migration 0003 is applied to Supabase. Checkpoint C (live phone runs) done, user confirmed 2026-10-16.

## Build checklist

- [x] 0. Baseline recorded; decision #95 added (`docs/decisions.md`, README count, traceability)
- [x] 1a. Input caps in the engine + migration 0003 (length CHECKs, reversible)
- [x] 1b. `ReplyRow.external_user_id` (join identities) in `claim_unsent`, `unsent_replies`, `replies()`
- [x] 1c. `Engine.opt_out_blocked` + `Tx.drop_unsent` (403, #93)
- [x] 1d. Async pool + fewer round trips; measured (below)
- [x] 1e. `load_telegram_settings` (token, secret, PUBLIC_URL), `.env.example` already had the names
- [x] 2. `adapters/base.py`, `adapters/telegram.py`, recorder, `set_webhook`; fixtures recorded and scrubbed
- [x] 3. Webhook, sender (429/403/pacing), sweeper, `/health`, `/ready`, double-tap guard
- [x] 4. Tests P2-U01..U12, P2-C01..C17, Q-11..Q-14
- [x] 5a. Checkpoint B: 0003 applied to Supabase and verified
- [x] 5b. Checkpoint C: real phone flow, rows checked in Supabase, manual checklist (user confirmed, 2026-10-16)
- [x] 6. These notes, `docs/metrics.md` results

## Overview

```
Telegram ──POST /hook/telegram──▶ api/webhooks.py  (secret header, hmac.compare_digest)
                                     │
                          adapter.parse(update) ──▶ None? → 200, nothing else
                                     │
                          tap? → answerCallbackQuery (no text) ── spinner stops (#92)
                                     │
                          engine.handle(event)  ── one DB transaction (#55)
                            │ StoreUnavailable → 503 (Telegram retries)
                            │ any other error  → log cid, apology (not stored), 200
                            ▼
                         200 returned FIRST (#86)
                            │ background:
                            ├─ tap applied → editMessageReplyMarkup "✓ <choice>"
                            └─ sender.deliver(replies) → mark_sent each success
                                     │ 429 wait retry_after │ 403 opt out + drop │ else leave unsent
                                     ▼
api/sweeper.py (lifespan task): every 30 s claim unsent > 10 s old (SKIP LOCKED) → send → mark sent
```

## Files and responsibilities

| File | Job |
|---|---|
| `adapters/base.py` | `Adapter` protocol (parse, render, send, capabilities, authorized, answer_tap, confirm_tap), `Capabilities`, `Tap`, `Inbound`, `SendError` / `RetryAfter` / `Blocked` |
| `adapters/telegram.py` | Pure `parse_update` and `render_reply`, keyboard layout, 64-byte callback check, `TelegramAdapter` (plain `httpx`, #66). Never logs a URL |
| `api/webhooks.py` | FastAPI app: `/hook/{channel}`, `/health`, `/ready`; `Webhook` (the turn and failure policy), `create_app` (lifespan runs the sweeper), `build_app` (production wiring from env) |
| `api/sender.py` | `Pacer` (~1 msg/s per chat, ~30/s overall, #69), `Sender.send` (429 retries), `Sender.deliver` (in order, mark sent, stop at first failure), `block` (403 → opt out, log count) |
| `api/sweeper.py` | `Sweeper.sweep_once` / `run` (#72) |
| `api/taps.py` | `RecentTaps`: messages confirmed in the last 60 s, to hide the double-tap "passed" reply |
| `api/logs.py` | `configure_logging`: httpx/httpcore at WARNING, `RedactSecrets` filter on root handlers |
| `core/engine.py` | + `cap_inbound` (#95), identity lock before dedupe, `TurnResult.applied`, `opt_out_blocked` |
| `core/store*.py` | + `record_event(..., fan_id)`, `load_state`, `claim_unsent(..., channels)`, `drop_unsent`, `ping`, `close`, `StoreUnavailable`; Postgres store pooled with CTEs |
| `core/config.py` | + `TelegramSettings` (secrets `repr=False`), `load_telegram_settings` |
| `core/flow.py` | + `APOLOGY_TEXT` (phase 3's web chat needs it too, and core is frozen then) |
| `migrations/versions/0003_input_caps.py` | 4 CHECKs: events text ≤ 1,000, source_tag ≤ 64, venue_note ≤ 200, email ≤ 200 |
| `scripts/set_webhook.py` | `setWebhook` with `secret_token` + `allowed_updates`; `--record` adds `edited_message`; `--info` |
| `scripts/record_updates.py` | Real webhook on the in-memory store that saves raw bodies to `.recordings/` (gitignored) |
| `scripts/bench_turn.py` | Engine-turn timing + round-trip count; refuses non-local hosts |
| `testing/fixtures/telegram/*.json` | 11 scrubbed recorded updates |
| `tests/component/telegram_fake.py` | Fake Bot API (`httpx.MockTransport`), `Rig`, `Fan` (taps buttons by label over ASGI) |

## Rules worth knowing

**Failure policy (#71).** Engine bug → the transaction rolls back (nothing saved), `log.exception("cid=<12 hex> ...")`, one apology "Something went wrong, please tap again" sent directly (never stored), HTTP 200. Database unreachable (`psycopg.OperationalError`, including `PoolTimeout`) → the store raises `StoreUnavailable` → HTTP 503 and no apology, so Telegram's retry gets a real answer. It is the only 5xx. Wrong or missing secret → 401, nothing parsed. Unknown channel → 404. Body that is not JSON → 400.

**Order on a tap (#92, design-review §13).** `answerCallbackQuery` with no text first, then the engine. The buttons become "✓ <label>" (callback `noop`) only if `TurnResult.applied`, which is true when the turn wrote something or moved the step. A stale tap gets "That question has passed" as a chat message, and its buttons stay as they are. Exception, the double tap: a stale tap on a message we confirmed less than 60 s ago gets its reply marked sent without delivery. A `noop` tap is answered and never reaches the engine.

**Sending.** 429 → sleep `retry_after`, resend, up to 3 attempts; the reply stays `unsent` while waiting. 403 → `opt_out_blocked`, which in one transaction sets `opted_out` and deletes that fan's unsent replies (count logged). Any other error → the reply stays unsent; `deliver` stops, so later replies keep their order. Pacing: one chat ~1 msg/s, all chats ~30/s.

**Sweeper (#72).** Started in the FastAPI lifespan and cancelled on shutdown (a cancelled transaction rolls back and frees its claims). Every 30 s: `claim_unsent(now - 10 s, 50, channels=registered adapters)` → send → `mark_sent` in the same transaction. It never touches replies younger than 10 s (P2-C08). Once one of a fan's replies fails, it skips the rest of that fan's replies in the batch. A block found by the sweeper is applied **after** the commit; doing it inside would make the delete wait on the sweeper's own row locks forever. Delivery is at-least-once: a crash after the send but before the commit sends the reply again, and so does a 429 wait longer than 10 s.

**Duplicates (#55, #90).** `external_msg_id = str(update_id)` for text and taps. Same update twice → the engine returns its still-unsent replies, the webhook sends them, nothing new is stored.

**Input caps (#95).** `cap_inbound` cuts `text` to 1,000 characters before `record_event` and `decide`, and keeps `source_tag` only if `fullmatch(r"[A-Za-z0-9_-]{1,64}")` (fullmatch: with `re.match` + `$`, `ig_story\n` would pass). The DB backs this up with migration 0003. `venue_note` and `email` use 200, the same as the flow validators. An existing oversized row blocks the upgrade (tested) instead of being cut silently.

**Parse rules.** Private chats only. Commands `/start [tag]`, `/stop`, `/delete`, `/help`, also with `@botname`. Unknown `/foo` is plain text. Callback data `<step>:<choice>`; anything malformed is answered and dropped. Edited messages, photos, stickers, groups, channel posts, member updates and odd JSON → `None` → 200, no exception. `external_user_id` = chat id. A tap carries no date, so its `ts` is the receive time.

**Render.** Plain text, no `parse_mode` (#69). Text over 4,096 is cut with "…". Rows: 4 per row if every label is ≤ 4 characters (group sizes), 2 if ≤ 14 (cities, budget, consent, edit menu), else 1 (venues).

## Latency (1d)

Round trips cut by: pool instead of a connection per transaction; skip the identity INSERT for known fans (SELECT … FOR UPDATE first, #88 kept for new fans); event inserted with its `fan_id` (`link_event` only for new fans); fan + session loaded in one JOIN; `record_answer`, `save_progress`, `create_fan` each one statement via CTEs. Not folded into the lock query on purpose: a `FOR UPDATE` that waited re-reads only the locked row, so joined fan/session columns could be stale (READ COMMITTED EvalPlanQual). The state read is a separate statement after the lock.

| Measured 2026-10-16 | Phase 1 code | Phase 2 code |
|---|---|---|
| Engine turn, local Postgres, 800 turns | p50 2.92 ms, p95 3.45 ms | p50 0.48 ms, p95 0.70 ms |
| Round trips per turn (BEGIN/COMMIT included) | 12.6 (new fan 14) | 8.1 (new fan 10, known fan 7.9) |
| Connections opened | 1,600 (one per transaction) | 2 (pool) |
| Supabase (Mumbai) network | connect 136-155 ms, query p50 22 ms | same |
| Estimated DB time per turn on Supabase | ~150 + 12.6 × 22 ≈ 430 ms | ~8 × 22 ≈ 180 ms |

`mark_sent` (3 round trips) runs after the 200, so it is not in the ack time.

## How to run

```bash
# tests (Homebrew Postgres is started by pytest-postgresql)
uv run pytest -q --cov=core --cov-fail-under=90
uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run lint-imports
uv run pip-audit --skip-editable && uv lock --check

# live
uv run uvicorn api.webhooks:build_app --factory --env-file .env --port 8000
ngrok http 8000 --url=https://<host of PUBLIC_URL>          # ngrok 3.37: --url
uv run python -m scripts.set_webhook                        # --info to check, --record for fixtures

# re-record fixtures (in-memory store, never Supabase)
uv run python -m scripts.set_webhook --record
uv run uvicorn scripts.record_updates:build_app --factory --env-file .env --port 8000
# then scrub (testing/fixtures/telegram/README.md), delete .recordings/, run set_webhook again

# migration
set -a; source .env; set +a; uv run alembic upgrade head      # downgrade: alembic downgrade 0002
DATABASE_URL=postgresql://localhost:5432/bench uv run python -m scripts.bench_turn 100
```

## Testing

- **Fixtures.** Recorded from the real bot: `start_with_tag`, `start_no_tag`, `button_tap` (consent), `tap_city`, `tap_noop`, `text`, `help`, `stop`, `delete`, `edited_message`, `photo`. Scrubbed: ids → same-length placeholders (`1000000001`), names → Test User, username → test_user (bot name kept), file ids → `FILE…`, update ids `100000001…`, message ids `101…`. The originals are deleted. No sticker, group or `/help@bot` update was recorded: tests derive the group case from `text.json` (chat moved to a group) and `@botname` from `help.json` / `start_with_tag.json` (text swapped). Flagged in the gaps.
- **Component tests** go through the real ASGI app (`httpx.ASGITransport`) with a fake Bot API (`httpx.MockTransport`), parametrised over the in-memory store and Postgres. P2-C06 is a meta-test that every webhook test ran on both. Component updates are built from the fixtures, never by hand.
- **Q checks.** Q-11: protocol members + AST import check + import-linter contract (adapters may not import flow/engine/decide/store). Q-12: 401 cases + a log scan over a run with failures (500, 429, 400) and redaction off; no token, secret or `api.telegram.org` in any record; httpx loggers ≥ WARNING. Q-13: `uv lock --check` in pytest, pip-audit in pre-commit and CI. Q-14: fixture scan (placeholder ids, names, usernames, file ids, no token shape, no headers, unique update ids). A test fails if any `P2-*` id in the spec has no test.

## Gotchas

- **Telegram drops `/start` payloads** if you pick `/start` from the command menu or the chat already exists. The source tag is stored only on first contact (P1-C04), so the first message must carry it.
- **`allowed_updates` filters at Telegram.** With `message` + `callback_query` Telegram never sends edited messages. Recording them needs `--record`.
- **FastAPI hangs background tasks on the Response you return.** A module-level `Response` would collect every request's tasks; build a fresh one each time.
- **httpx exception text and INFO logs contain the full URL, and so the token.** The adapter raises `SendError(f"{method}: {ExcType}") from None` and never calls `raise_for_status`.
- **Starlette `TestClient` is deprecated with httpx**; tests use `httpx.ASGITransport`, which also runs background tasks before the call returns (deterministic).
- **Blocking from inside the sweeper's transaction deadlocks on Postgres** (the delete waits on our own `FOR UPDATE` locks; the in-memory store would not show it). Covered by a test on both backends.
- **`_exec_command` in psycopg is a generator, not a coroutine.** It matters only for the bench's round-trip counter.
- **initdb with `--locale=C` defaults to SQL_ASCII**, and SQLAlchemy then fails to parse `version()`. Use `-E UTF8`.
- **DATABASE_URL uses port 5432 (session pooler).** #67 wants the transaction pooler (6543) for the webhook. Both work (`prepare_threshold=None` is set); the pool is capped at 5 for the session pooler's small limit.
- **detect-secrets flags** the header-name constant and the fake test secret; they carry `# pragma: allowlist secret`.

## Carried into phase 3

- Web chat adapter: done in phase 3 (one adapter file, its routes in `api/`, one registry line, #101). The sweeper filters by registered channels, so web chat replies never block Telegram resends.
- Numbered-text choices (phase 1 gotcha) were not built; the web chat uses buttons, so nothing needs them.
- `RecentTaps` is per process; fine for one laptop process.

## Likely interview Q&A

**Why return 200 before sending?** Telegram waits for the ack and retries slow or failed webhooks. The turn is committed first, so the reply is safe in `replies`; sending is best-effort and the sweeper covers failures (#86).

**Why is DB-down the only 5xx?** A 5xx makes Telegram retry. That helps when the database is down (the retry can succeed). It hurts for a bug (it would fail the same way, again and again), so a bug gets 200 + one apology.

**How do you stop the sweeper racing an in-flight send?** It only claims replies older than 10 s; the webhook sends within milliseconds. `SKIP LOCKED` keeps two sweepers apart.

**What if the bot is blocked?** 403 → in one transaction: `opted_out = true`, unsent replies deleted (nothing to retry), count logged. Unblock + `/start` re-subscribes (A9).

**429?** Wait `retry_after`, resend (3 attempts), reply unsent meanwhile; pacing keeps us near Telegram's limits so it should be rare.

**How is the webhook authenticated?** `setWebhook(secret_token=...)`; Telegram sends it in `X-Telegram-Bot-Api-Secret-Token`; `hmac.compare_digest` (constant time). Wrong → 401 before parsing.

**How do you keep the token out of logs?** httpx/httpcore at WARNING, adapter errors never include the URL, settings hide secrets in `repr`, a redaction filter as a second guard, and a test that scans logs from a run full of failures.

**Double tap vs old button?** Core sees both as stale. The webhook remembers messages it confirmed in the last 60 s; a stale tap on one of those is a double tap and stays silent; others get "That question has passed".

**Why answer the callback before the engine?** The spinner stops at once, and a callback can be answered only once. Only the engine knows if the tap was stale, so the toast can't say "passed"; that goes out as a chat message.

**Why caps in core, not the adapter?** Every channel gets them; phase 3's public web chat has no Telegram limits and core is frozen then.

**Why a new migration instead of editing 0001?** 0001/0002 are applied to Supabase; Alembic would never re-run them. 0003 is additive, reversible, and refuses to apply over bad rows.

**What did pooling buy?** A fresh TLS connect to Supabase is ~140-250 ms; the pool pays it once. CTEs cut a known-fan turn from 12.6 to 8 round trips: ~430 ms → ~180 ms of DB time on Supabase, and 3.5 → 0.7 ms p95 locally.

**Why not fold the fan/session read into the lock query?** In READ COMMITTED, a `FOR UPDATE` that waited re-reads only the locked row; joined columns can be stale, which would break the double-tap serialisation.

**How do you test without hitting Telegram?** `httpx.MockTransport` fakes the Bot API (scripted 429/403/500), `ASGITransport` drives the real app, and updates are built from real recorded payloads.
