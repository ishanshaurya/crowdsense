# Phase 1 notes: Core (no network)

Goal: a whole chat runs in tests and leaves correct rows in `fans`, `identities`, `sessions`, `answers`, `events`, `replies`, on an in-memory fake and on real Postgres.

Status at end of phase: **142 tests pass** (73 unit, 69 component runs; the component suite runs on both backends), `core/` coverage **98.4%**, ruff, mypy strict, import-linter, detect-secrets all clean. Manual REPL sign-off is the one open item (yours).

## Build checklist

- [x] 1. Tooling (ruff, mypy strict, import-linter, detect-secrets, pre-commit, CI, markers, coverage gate)
- [x] 2. `core/flow.py` + `core/catalog.py` (steps as data)
- [x] 3. `core/types.py`
- [x] 4. `core/decide.py` (pure)
- [x] 5. Store: protocol, fake, Postgres, Alembic migrations + venue seed
- [x] 6. `core/engine.py`
- [x] 7. `core/insights.py`
- [x] 8. `scripts/repl.py`
- [x] 9. Tests (unit, component x2 backends, Q-04..Q-10 as tests; Q-01..Q-03, Q-09 as tools)
- [ ] 10. Manual: play the REPL (`uv run python -m scripts.repl`), read the whole chat for tone (`testing/manual/manual-checklist.md`, Phase 1)

## Overview

One engine turn = one DB transaction. The pure function `decide(state, event, now)` holds all conversation rules and does no I/O. The engine loads state from the store, calls `decide`, applies the returned writes and logs the replies, then commits. Channels (Telegram later) only translate messages into `InboundEvent` and `Reply`.

```
InboundEvent -> Engine.handle
   1 dedupe        record_event(channel, msg_id)      duplicate -> return its unsent replies
   2 identity lock lock_identity (INSERT ON CONFLICT DO NOTHING, then SELECT FOR UPDATE)   #88
   3 fan + session create_fan if the identity has none
   4 decide()      (FanState, event, now) -> Decision(state, replies, writes)   pure
   5 apply         record_answer / set_consent / set_opted_out / mark_completed / save_progress
                   add_reply (status unsent)   |  delete path: funnel +1, delete_fan
   6 commit        caller sends replies, then engine.mark_sent(...)   #86
```

## Files and responsibilities

| File | Job |
|---|---|
| `core/types.py` | Adapter contract (`InboundEvent`, `Reply`, `Option`), `FanState`, the write commands (`SaveAnswer`, `SetConsent`, `SetOptedOut`, `MarkCompleted`, `DeleteFan`), `Decision`. All frozen dataclasses |
| `core/catalog.py` | Reference data: 10 cities, 14 venues with fixed ids 1..14, budget / group options with canonical codes |
| `core/flow.py` | The conversation as data: `Step` (id, prompt, expects, field, options, next, edit_next, branches, clears, null_choice, validate) + message texts + edit-menu text. Options come from `catalog`, not from logic |
| `core/decide.py` | Pure decision core. Handles start, stop, delete, help, stale taps, consent, each question step, edit menu, completion |
| `core/store.py` | `Store` and `Tx` protocols, row dataclasses, `IntegrityViolation`, JSON helpers |
| `core/store_memory.py` | In-memory fake: undo-log rollback, per-identity `asyncio.Lock`, reply claim set (behaves like `FOR UPDATE` / `SKIP LOCKED`) |
| `core/store_postgres.py` | psycopg 3 store. Every query is a `LiteralString`, so mypy rejects SQL built from data. One connection per transaction, `prepare_threshold=None` (#67) |
| `core/engine.py` | `Engine.handle(event) -> TurnResult`, `mark_sent`. Option `simulated=True` (#82) |
| `core/insights.py` | Recommendation rules as pure functions over `FanRow` + `Venue` |
| `core/clock.py` | `Clock` protocol, `SystemClock`, `ScriptedClock` (#56) |
| `core/config.py` | `load_settings(environ)`: `DATABASE_URL` required, `ARTIST_NAME` default "Artist X" (#63) |
| `migrations/` | Alembic: `0001_schema` (tables, CHECKs, FKs, indexes), `0002_seed_venues` (14 rows). `env.py` reads `DATABASE_URL` from the environment only |
| `scripts/repl.py` | Dev REPL on the in-memory store. Never touches a database |
| `tests/` | `unit/`, `component/`, `quality/`, plus `support.py` (event builders, `@decision`, YAML loader), `scenario_runner.py` |

Why `decide.py` and three store files, when `docs/architecture.md` lists `engine/flow/store`: `decide` is the pure core the doc asks for (§9) and gets its own file; the store is split so no file passes the 400-line check (Q-07).

## Data model

Tables (all created in `0001_schema`): `venues`, `fans`, `identities`, `sessions`, `answers`, `events`, `replies`, `funnel_counts`. `announcement_requests` is phase 5.

- `fans` is the current snapshot (fast reads). `answers` is append-only history (trends, growth). `fans.venue_id` is an FK to `venues`; "Other" leaves it null and fills `venue_note` (#46).
- CHECK constraints in the DB: `budget_band` in `lt_1500|1500_3000|3000_6000|gte_6000`, `group_size` in `1|2|3_5|6_plus`, `answers.field` in the 6 answer fields, `status` in `unsent|sent`, `venues.capacity > 0`, `funnel_counts.count >= 0`.
- Every fan-owned table has `ON DELETE CASCADE` to `fans`, so `/delete` is one `DELETE FROM fans`. Identities, sessions, answers, events and replies disappear with it. `replies` also cascades from `events`.
- Consent and opt-out live on `identities` (per channel). `consent` is nullable: NULL = not asked yet, false = declined.
- `events` PK `(channel, external_msg_id)` is the dedupe key. Telegram's `update_id` will fill it (#90).
- `completed_at` is set once (`COALESCE(completed_at, new)`), never cleared (#70). `furthest_step` never moves back (#84).
- All timestamps are passed in by the caller. No `DEFAULT now()` is used for tracked columns, so the scripted clock drives every `created_at` / `ts` (#56).
- Canonical stored values: city = the city name; venue answer = venue id as text; everything else = option code. Typed email is stored stripped.

## Flow and decide()

Order: consent -> city -> venue -> (venue_note if Other) -> budget -> group -> email -> done. Plus session-only states `declined` and `edit_menu`. No timing step (#23), no interest step (#94: removed everywhere; migration 0001 was edited in place because it had never been applied).

Rules worth knowing:

- **Input resolution.** A tap must carry a choice id from the current options. Typed text is matched to an option label (case-insensitive), so text-only channels work and the scenario `bad_input_then_ok` (types "Pune") passes. Anything else re-asks the step with `is_error=True` and saves nothing (#13, A10).
- **Stale tap (#91).** A choice whose `choice_step` differs from the current step changes nothing and gets "That question has passed."
- **Stop / start / delete.** `/stop` sets opted out and gets one confirmation; later messages get no reply at all. `/start` re-subscribes and resumes at the saved step (A9). `/start` after "No thanks" asks consent again. `/delete` and `/help` work even when opted out.
- **Edit mode = fan is completed.** A completed fan's `/start` or any text shows the edit menu. After an edit, the step uses `edit_next` instead of `next`, so it returns to done. No extra `editing` column is needed.
- **City edit (A7).** Changing the city clears venue and venue_note (clearing writes an `answers` row with NULL value, so "latest answers equals fans" holds) and re-asks the venue. Picking the same city changes nothing and returns to done.
- **Same value = no write.** Re-answering with the current value appends no `answers` row.
- **Done message (#87)** depends on `can_push` (engine: `push_channels`, default `{"telegram"}`).
- **Determinism.** `decide` takes `now` only to stamp `MarkCompleted`. Artist name is a parameter (#63). A test patches sockets, files, random, uuid and time to raise while running a full flow, and an AST test forbids `now()` calls and impure imports in the pure modules.

Contract changes versus `docs/architecture.md` §3 (all forced by the specs, flag if you disagree):

- `Reply` gained `step_id` (scenarios assert `expect: {step: ...}`) and `is_error` (scenarios assert `error: true`).
- `InboundEvent.kind` gained `delete` and `help` (like `stop`, adapters parse the commands).
- `decide(state, event, now, *, artist, can_push)` has two extra keyword arguments.

## Store and Alembic

- **Protocol.** `Store.transaction()` yields a `Tx` with 17 methods; `Store` also has read methods (`fans()`, `answers()`, ...) used by tests and later by the dashboard.
- **One suite, two backends (#54).** `tests/component/test_store_contract.py` and the engine and scenario tests are parametrised over `memory` and `postgres` through the `store` fixture. A meta-test (P1-C11) checks every contract test really ran on both.
- **Identity lock (#88).** `INSERT ... ON CONFLICT DO NOTHING` then `SELECT ... FOR UPDATE`. A second message from a brand-new fan blocks on the insert until the first commits, then sees the fan. The fake holds a per-identity asyncio lock until the transaction ends.
- **Reply claim (#72).** `claim_unsent` uses `FOR UPDATE SKIP LOCKED`; the fake keeps a claim set that is released when the transaction ends. Two claimers get disjoint rows.
- **Parameterised SQL.** Snapshot updates use one literal `UPDATE` per field (a dict of `LiteralString`), never a formatted column name.
- **Migrations.** Run with `DATABASE_URL=... uv run alembic upgrade head` / `downgrade base`. Tested up, down, up on an empty DB (pytest and the CLI on a throwaway local cluster). The seed is a literal copy of the venue table inside the migration (old migrations must not import app code); Q-10 asserts it equals `docs/decisions.md` and `core/catalog.py`.
- **Test DB.** `pytest-postgresql` starts the Homebrew server (found with `which pg_ctl`); when the `CI` env var is set it uses the CI Postgres service instead (#44). Each test gets a fresh database; an autouse fixture deletes `DATABASE_URL`, so tests can never reach Supabase.

## Insights

Pure functions in `core/insights.py`, all over counted fans (`completed_at` set, #52, #70):

| Function | Rule | Decision |
|---|---|---|
| `city_attendance` | sum of people per city; 1->1, 2->2, 3-5->4, 6+->6 | 31, 33, 34, 49 |
| `venue_demand` | fans and people per venue id; fans with no venue ("Other", re-asked after a city change) skipped | 31, 51 |
| `suggested_venue` | smallest venue with `capacity * 4 >= attendance * 5` (80% fill, integer math, no float); else the city's largest; no demand -> None | 31 |
| `price_band` / `price_band_by_city` | mode; tie -> lower band | 32, 50, 79 |
| `city_priority` | by attendance descending (ties by name) | 31 |
| `growth_badge` | `this * 5 >= prior * 6` -> "growing"; prior 0 and this > 0 -> "new"; else none | 31 (A5) |
| `growth_by_city` | rolling 7 days vs the 7 days before, by `completed_at` | 85 |
| `funnel` | started, completed, fans by furthest step | 84 |
| `recommend` | composes the above per city, ordered by priority | 31 |

`insights_cases.yaml` drives P1-U20..U30. P1-C12 seeds the same fans through the engine on the fake and on Postgres and asserts identical `recommend`, `venue_demand` and `funnel` results.

## Testing

- **Layout.** `tests/unit` (no I/O), `tests/component` (engine + store, both backends), `tests/quality` (Q checks). Markers `unit` and `component` are applied by folder in `conftest.py`; `--strict-markers` is on.
- **Spec ids.** Test function names contain the spec id (`test_p1_u22_...`). A test parses `testing/phases/phase-1-core.md` and fails if any `P1-*` id has no test. `@decision(n)` tags feed Q-10, which checks every number exists in `docs/decisions.md` (scenario YAML `decisions:` lists too).
- **Scenarios.** `tests/scenario_runner.py` plays each YAML file: maps button labels to choice ids, tracks the last keyboard for `choice_step`, marks replies sent after each turn (so duplicates return nothing), and checks `final_db`. A custom YAML loader keeps `1500_3000` and `3_5` as strings (plain YAML reads them as integers).
- **Fake vs Postgres.** Same assertions on both. The only intended difference: the fake can show uncommitted data to a concurrent transaction (no isolation), which no contract test depends on.
- **Q checks.** Q-04 env vars vs `.env.example` placeholders, Q-05 import-linter (also run inside pytest), Q-06 purity, Q-07 files <= 400 lines and functions <= 40 lines, Q-08 no TODO without an issue id (ruff ERA001 and T20 cover commented code and print), Q-10 spec consistency. Q-01 ruff, Q-02 mypy, Q-03 detect-secrets run in pre-commit and CI; Q-09 is `--cov-fail-under=90`.

## Tooling and CI

- Dependencies added with `uv add`: alembic (runtime), pyyaml, mypy, import-linter, detect-secrets, pytest-cov, pytest-asyncio, types-PyYAML (dev). `uv.lock` updated.
- `pyproject.toml`: ruff (E, F, I, B, UP, C90 max 10, T20, ERA, SIM, RUF), mypy strict on `core`, pytest markers and asyncio auto mode, coverage on `core`, three import-linter contracts.
- `.pre-commit-config.yaml`: five local hooks (`ruff check`, `ruff format --check`, `mypy core`, `lint-imports`, `detect-secrets-hook` with `.secrets.baseline`). Local hooks use the versions pinned in `uv.lock`, so no revision was guessed. Run `pre-commit install` once if you want it on every commit.
- `.github/workflows/ci.yml`: Postgres 16 service (trust auth, so no password sits in the file), `uv sync --locked`, the same checks, pytest with the coverage gate. **Not run yet**: there is no GitHub repo, and the action versions (`checkout@v4`, `setup-uv@v6`) were written from memory.
- `.env.example` gained `ARTIST_NAME`.

## Decisions touched

1, 3, 4, 11, 12, 13, 20-22, 23, 24, 25, 26, 27, 31-35, 36, 37, 39, 41, 44, 45, 46, 47, 48, 50, 51, 52, 54, 55, 56, 57 (boundary only), 63, 67, 70, 72 (store side), 79, 81, 82, 84, 85, 87, 88, 91. Spec gaps A1-A10 are all implemented (A6 follows #85: growth by `completed_at`, not `created_at`).

## Likely interview Q&A

**Why a pure `decide` plus an engine?** All rules live in one I/O-free function, so tests are fast and deterministic (same input, same output), and the engine is a thin transaction wrapper. A test proves purity by making sockets, files, clock and randomness raise.

**How do you stop a duplicate Telegram delivery from double counting?** `events` has primary key `(channel, external_msg_id)`. The first thing a turn does is insert the event; a conflict means duplicate, so the turn stops and only returns any replies that were never marked sent (at-least-once delivery).

**What if the same new user sends two messages at once?** The identity row is inserted with `ON CONFLICT DO NOTHING` and then locked with `FOR UPDATE`. The second transaction waits, then sees the fan the first created. One identity, one fan, no apology. Tested with five concurrent new users on both backends.

**Why a fake store as well as Postgres?** Fast tests without a DB, and a second implementation that proves the interface. One contract suite runs on both; a meta-test makes sure none is skipped on either backend.

**What is saved when something fails mid-turn?** Nothing. Dedupe, state, answers and reply log commit together; an exception rolls back all of it (P1-S03, on both backends).

**How is `/delete` privacy-safe but the funnel still right?** Delete cascades from `fans` to identities, sessions, answers, events (which hold the raw text) and replies. Before deleting, the engine bumps `funnel_counts` for the fan's furthest step, an anonymous number. The confirmation is returned but never stored.

**Why is a fan "counted" from `completed_at`?** Set the first time they reach done and never cleared, so editing an answer never makes someone vanish from demand (#70). A fan who changes city and has not re-picked a venue counts for the city, for no venue.

**Why integer math in `suggested_venue`?** `capacity * 4 >= attendance * 5` is exactly `capacity >= attendance / 0.8` with no float rounding, so the 3,200 -> Bandra Waterfront boundary is exact.

**How does the flow stay data instead of code?** Each `Step` names its prompt, options, field, next step, edit-next step, branches (Other -> venue note) and what it clears. `decide` interprets steps; adding a question means adding a `Step`.

**How do you prove migrations are safe?** Up, down and up again on an empty database, a seed check against the decisions table, DB-level CHECK and FK tests with raw SQL, and a cascade test.

**How do you keep SQL injection impossible?** All queries are string literals with `%s` parameters, and the query parameter is typed `LiteralString`, so mypy fails the build if anyone formats data into SQL. Column choice for updates uses a fixed dict of literal statements.

**Why an in-memory REPL instead of Postgres?** It lets you read the whole conversation and test tone with no network and no risk to real data.

## Gotchas

- **Docs moved mid-session.** `PRD.md`, `ARCHITECTURE.md`, `PLAN.md`, `decisions.md`, `design-review.md`, `METRICS.md` were reorganised into `docs/` (and `docs/message-script.md` was split out) while this phase ran, with `PRD.md` staged as deleted. That was not part of this build; code and tests now point at `docs/decisions.md`. `docs/`, `CONTEXT.md` and `README.md` are still untracked.
- **Scenario inconsistency.** `decline_consent.yaml` checks `fans: {consent: false}` but every other spec puts consent on `identities`. The harness exposes the fan's identity consent as `fans.consent` instead of editing the spec file. Worth fixing in the YAML later.
- **YAML underscores.** `1500_3000` and `3_5` load as integers in plain YAML. `tests/support.py` has a loader that keeps them as strings. Quote them or keep the loader.
- **Typed labels are accepted** as taps (needed by `bad_input_then_ok`). Numbered-text mapping (docs §3 "no buttons: numbered text") is not built: a typed `4` at the group step would be ambiguous with a group size. Decide when the web chat (phase 3) needs it.
- **Event ids in tests.** Reusing a message id deduplicates, so test helpers use a global counter. A repeated id in a test looks like "the engine ignored my message".
- **`/delete` redelivery.** The delete event is removed with the fan, so a redelivered `/delete` is processed again: it creates and instantly deletes an empty fan and bumps nothing. Harmless but visible in logs.
- **Fan row is created at first contact**, including for "No thanks" and for `/stop` as a first message, because scenarios expect a fan row with null fields. `furthest_step` is NULL until a question is asked.
- **Clearing a field writes an `answers` row with NULL value.** Keeps "latest answers equals snapshot" true after a city change.
- **Unused column.** `identities.can_message_until` exists (data model) but nothing sets it until a channel needs it.
- **`mark_sent` is a separate transaction** after the commit. A crash between send and mark means a resend (at-least-once, #72).
- **Fake isolation.** The fake mutates shared tables immediately and undoes on rollback, so a concurrent transaction can see uncommitted rows (a Postgres one cannot).
- **Coverage gate is 90%** (your prompt and Q-09). `testing/phases/phase-1-core.md` and `docs/plan.md` still say 85%.
- **Function length limit.** Your prompt's "Functions <= ..." was cut off; Q-07 uses 40 lines (longest function in `core/` is under it).
- **Security reminders.** The Supabase DB password and bot token were pasted in chat earlier: rotate both before the demo. This phase never read `.env` and never ran a migration against Supabase.
- **Before commit.** No commit was made. `git status` shows your own doc changes (`testing/*`, staged `D PRD.md`) mixed with the new code; stage by path when you say commit. `docs/`, `CONTEXT.md`, `README.md` are untracked and the plan says to keep the planning docs out of commits.
