# Phase 5: Outbound (announcements)

Status: **security-first slice done, not committed.** 523 tests pass (457 before the slice), `core/` coverage 99%. ruff, ruff format, mypy strict, import-linter (4 contracts) clean. Supabase migrated to 0004 on 2026-10-17 with grants checked before and after. Still open in phase 5: manual phone rehearsal, demo script, README limits, architecture diagram.

## Baseline (2026-10-17, before any phase 5 change)

- 457 tests pass (456 from phase 4 plus `test_settings_repr_never_shows_the_database_url`).
- Supabase at revision 0003: 20,004 fans, 29 replies (0 unsent). Dashboard role: SELECT on `fans`, `venues`, `funnel_counts`, `identities (fan_id, channel, source_tag)`. `anon` / `authenticated`: nothing. No RLS policies.

## Build checklist

- [x] 0. Facts check: `/stop` did not drop unsent replies (only a 403 did); `claim_unsent` finds the push target through the `identities` join; cities from `core.catalog.CITIES`
- [x] 1. Migration 0004: `announcement_requests`, `replies.priority` + `announcement_id`, revokes, RLS
- [x] 2. `announcement_audience` + `announcement_audience_count` (in 0004, your choice)
- [x] 3. `scripts/dashboard_role.py`: INSERT on two columns, RLS policy, EXECUTE on the count function
- [x] 4. Public API test: 0004 closes its own objects even with Supabase-like default grants
- [x] 5. `core/outbound.py` fan-out, sweeper wiring, chat-first ordering, `/stop` drops unsent
- [x] 6. Dashboard "Announce a show" form
- [x] 7. Supabase: migrate, role script, lock script, before/after diff, live role probe
- [x] 8. Decisions #109 to #115, these notes
- [ ] Manual rehearsal on a phone (link → chat → dashboard → send → receive → `/stop` → send again → nothing)
- [ ] Demo script, README limits (self-selection, intent ≠ purchase, simulated data), architecture diagram

## Overview

```
dashboard (role crowdsense_dashboard, read-only by default)
  form: city + date ── preview = announcement_reply()  (same function as the sent text)
     │  count  = announcement_audience_count(city)      SECURITY DEFINER, count only (#110)
     │  confirm: SET TRANSACTION READ WRITE; INSERT (city, event_date)  (savepoint; dup -> False)
     ▼
announcement_requests  (UNIQUE city+date, RLS on, policy dashboard_insert, #109 #112)
     │
webhook service sweeper, every 30 s (owner role)
  Outbound.fan_out_next(): one transaction (#111)
     claim oldest pending  FOR UPDATE SKIP LOCKED
     past date? -> fanned_out, 0 recipients, log (#113)
     INSERT events  (direction 'out', 'ann-<req>-<fan>')      FROM announcement_audience(city)
     INSERT replies (priority 1, announcement_id)  ON CONFLICT (announcement_id, fan_id) DO NOTHING
     UPDATE request: fanned_out, recipients, fanned_out_at
  then claim_unsent ORDER BY priority, id  -> chat replies first -> Telegram, paced (#69, #72)
```

## Files and responsibilities

| File | What changed |
|---|---|
| `migrations/versions/0004_announcements.py` | Table, constraints, reply columns + partial unique index, both functions, revokes (PUBLIC, `anon`, `authenticated`), RLS. Cities frozen in the file like 0002 freezes venues; a test keeps them equal to the catalog |
| `core/outbound.py` | Template (#15), `announcement_reply`, `today_ist`, `Outbound.fan_out_next`; dashboard side `audience_count`, `request_announcement` |
| `core/store.py` | `AnnouncementRow`, `ReplyRow.priority`, Tx: `claim_announcement`, `fan_out`, `finish_announcement` |
| `core/store_postgres.py` / `core/store_memory.py` | Both implementations; memory mirrors the SQL audience rule |
| `core/engine.py` | `/stop` (`SetOptedOut(True)`) also calls `drop_unsent` (#114) |
| `core/config.py` | `DashboardSettings.artist_name` so the preview matches the sent text |
| `api/sweeper.py`, `api/webhooks.py` | Sweeper fans out pending requests first; `build_app` wires `Outbound` |
| `dashboard/app.py`, `dashboard/text.py` | "Announce a show" expander; send runs in an `on_click` callback |
| `scripts/dashboard_role.py` | Adds the INSERT grant, RLS policy, EXECUTE grant; existing grants untouched |
| `scripts/lock_public_api.py` | `CHECKED_TABLES` includes `announcement_requests` |
| `tests/quality/test_phase4_quality.py` | Dashboard may import `core.outbound` (preview = sent text, P5-U07) |

## Security (the six risks and what holds each)

| Risk | Fix | Enforced by |
|---|---|---|
| Spam: dashboard creds send anything to everyone | Row holds city + date only; text and audience built server-side | Column-level INSERT grant, city CHECK, RLS policy (#109) |
| Duplicate sends | Claim with SKIP LOCKED; unique (announcement, fan); one transaction | Partial unique index + `ON CONFLICT DO NOTHING` (#111) |
| Audience leaks | One SQL function, Telegram allowlist; dashboard sees the count only | `SECURITY DEFINER` count, EXECUTE revoked from PUBLIC (#110) |
| Opt-out between fan-out and send | `/stop` drops unsent replies | Engine write (#114) |
| Public API exposure | Migration revokes and enables RLS itself | 0004 + lock script check (#115) |
| Double submit | UNIQUE (city, event_date); button locks | Database, not the UI (#112) |

Rule of thumb: **the dashboard only asks, the server decides; constraints, not the UI, enforce both rules.**

## Test id → file

| Id | Test |
|---|---|
| P5-U01 to U04, C06 | `test_outbound.py::test_p5_u01_u04_c06_both_stores_skip_the_same_fans` (8 cases × 2 stores); SQL side in `test_announcements_schema.py::test_audience_excludes` |
| P5-U05, U07 | `test_outbound.py::test_p5_u05_u07_the_text_is_the_template_filled_in`; `test_dashboard_app.py::test_p5_u07_u08_preview_and_count_then_queue` |
| P5-U06 | Replaced by UNIQUE (city, event_date) (#112): `test_announcements_schema.py::test_one_request_per_city_and_date` |
| P5-U08 | `test_dashboard_app.py::test_p5_u07_u08_preview_and_count_then_queue`, `test_announcements_schema.py::test_count_matches_the_audience` |
| P5-U09 | `test_outbound.py::test_p5_u09_a_past_date_queues_nothing`; `test_dashboard_app.py::test_p5_u09_past_date_never_reaches_the_form` |
| P5-C01 | `test_outbound.py::test_p5_c01_…`, `test_the_sweeper_sends_the_announcement_on_telegram` |
| P5-C02 | Existing sweeper resend tests (phase 2) cover a failed send; announcement replies are ordinary unsent replies |
| P5-C03 | `test_outbound.py::test_p5_c03_…`, `test_two_sweepers_at_once_…`; `test_dashboard_app.py::test_p5_c03_double_click_is_refused_twice` |
| P5-C04 | `test_dashboard_app.py::test_p5_c04_nobody_to_notify_disables_the_button` |
| P5-C05 | `test_outbound.py::test_p5_c05_stop_after_fan_out_drops_the_announcement` |
| P5-C07 | Every `test_outbound.py` test runs on memory and Postgres |
| Grants | `test_dashboard_role.py` (allowed insert, 7 refused statements, read-only default, column grants + policy); `test_lock_public_api.py` (0004 closes itself, zero table grants after lock) |

## Supabase run (2026-10-17, ap-south-1 pooler)

1. `alembic upgrade head`: 0003 → 0004 in one transaction; webhook not running.
2. `scripts.dashboard_role --allow-remote`: role updated.
3. `scripts.lock_public_api --allow-remote`: 8 tables × 2 roles, all select=False write=False.
4. Before/after diff: table grants unchanged; added only INSERT on `announcement_requests (city, event_date)`, EXECUTE on the count function, RLS on that table, policy `dashboard_insert`; role settings unchanged; every row count unchanged; 0 unsent replies.
5. Live probe as the dashboard role (rolled back): insert works; SELECT on requests, audience rows, UPDATE, DELETE refused. Pune audience = 0 (no real completed fans yet).

## Gotchas

- **RLS with no policy blocks everyone but the owner,** including the dashboard role. The policy lives in the role script because migrations never create that role (#105).
- **Functions are executable by PUBLIC by default,** and Supabase exposes functions over its API. Revoke explicitly.
- **The dashboard role defaults to read-only transactions,** so its one insert opens with `SET TRANSACTION READ WRITE`. No `RETURNING` (needs SELECT).
- **`replies` has a foreign key to `events`,** so each announcement reply needs an outbound event row first (`direction 'out'`).
- **A Streamlit button's `disabled` is computed before the click is known.** Do the send in `on_click` so the button is already locked when the page redraws (a test caught this).
- **Streamlit drops a date below `min_value`** and resets to the default, so the past-date path is guarded in the fan-out, not only the form.
- **Quality gates:** `demand.py` must stay ≤ 400 lines and the dashboard may not import psycopg or contain SQL, so the dashboard-side SQL lives in `core/outbound.py`.
- **Restart the webhook service after deploying,** or pending requests stay pending.

## How to run

```
uv run pytest -q                                              # 523 tests
uv run --env-file .env python -m streamlit run dashboard/app.py
uv run uvicorn api.webhooks:build_app --factory --env-file .env --port 8000
uv run python -m scripts.dashboard_role --print-sql           # grants, no database
```

## Likely interview Q&A

**How do you stop the dashboard being used to spam fans?** The dashboard can only insert a city and a date; the database refuses any other column, any read, any update. The message is a fixed template in server code and the audience is a SQL function the dashboard can't call. So a stolen password triggers at most one legitimate announcement per city and date.

**What if the sweeper crashes halfway?** Fan-out is one transaction: either every reply and the "fanned out" mark commit together, or nothing does and the request is still pending for the next pass. Two sweepers can't take the same request (`SKIP LOCKED`), and a unique index on (announcement, fan) makes a rerun add nothing. The only duplicate left is a crash after Telegram accepted a message but before we marked it sent: at-least-once, accepted and stated.

**Why reuse `replies` instead of a new sender?** The sweeper already handles pacing, 429 waits, 403 blocks and resends, and it is tested. Announcements are priority 1 so a big send never delays someone mid-chat.

**How does the preview count match what's sent?** Both come from `announcement_audience`: the dashboard calls a count-only wrapper, the fan-out selects from the function itself. The memory fake mirrors the rule and the same tests run on both stores.

**What if a fan opts out after the fan-out?** `/stop` now deletes that fan's unsent replies in the same transaction that opts them out, so the queued announcement is gone before the sweeper reaches it.

**Can you resend a corrected announcement?** Not for the same city and date: that's the unique constraint doing its job against double-submits. A deliberate tradeoff; a correction flow would need its own request type.
