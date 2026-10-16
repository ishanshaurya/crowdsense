# Phase 4: Dashboard

Status: **done.** 456 tests pass (the 371 from phases 1 to 3 are all still green), `core/` coverage 98.74%. ruff, ruff format, mypy strict (now incl. `dashboard/`), import-linter (4 contracts), detect-secrets, pip-audit and `uv lock --check` are clean. Supabase: dashboard role created (#105), public API roles revoked (#108), timings measured; manual checklist 6/7 (phone chat skipped). Committed as `phase 4`, tag `phase-4`.

## Baseline (before any phase 4 change, 2026-10-16)

- 371 tests pass; `core/` coverage 98.51%; every check clean.
- Probe: a dashboard module importing `core.insights` broke the dashboard contract (indirect `core.flow`). Fixed by `allow_indirect_imports` on that contract only (Q5); a test now checks the dashboard's direct `core.*` imports instead (P4-C04).

## Build checklist

- [x] A. Baseline recorded
- [x] §2 Decisions #104 to #107; doc drift D1 to D8 applied (README #1–#107)
- [x] B. `core/demand.py` + P4-U01 to U10 on Postgres
- [x] C. `scripts/dashboard_role.py` + P4-C02 / Q-18; settings in `core/config.py`
- [x] D. `dashboard/` + P4-U09, U11, C03 to C06, Q-17
- [x] E. P4-C01, P4-C07 at 20k; EXPLAIN ANALYZE numbers; no index needed (no migration)
- [x] F. Supabase: role created 2026-10-16 on the ap-south-1 pooler; role check passed (reads as allowed, every write and hidden read refused); timings recorded
- [x] F2. Supabase `anon` / `authenticated` had full access to `fans`, `identities`, `answers`, `events` with RLS off. Revoked 2026-10-16 (#108, `scripts/lock_public_api.py`, run by the user): all 7 checked tables now select=False, write=False for both roles
- [x] Notes, traceability, metrics (Supabase rows pending)
- [x] Manual checklist Phase 4: 6 of 7 checked on Supabase data (2026-10-16, see below); phone chat skipped by the user

## Overview

```
Postgres (fans, venues, funnel_counts, identities.source_tag)
   ▲  role crowdsense_dashboard: SELECT only, read-only default, 5 s timeout (#105)
   │  one READ ONLY REPEATABLE READ transaction, 12 queries pipelined = 1 round trip (#106)
core/demand.py   ── SQL aggregates; `counted` CTE = view filter + counted rule, written once (#57)
   │  rows → dataclasses; people per group passed in from insights as arrays
   ▼
core/insights.py ── rules: suggested_venue, price_band, city_priority, growth_badge (unchanged)
   │  DemandReport (banner, views, recommendations)
   ▼
dashboard/app.py ── gate (hmac) → sidebar (view, email toggle) → @st.fragment(run_every=5 s)
   │  st.cache_data(ttl=4 s) per (view, emails): all tabs share ~1 batch / 5 s
   ▼
dashboard/views.py + text.py ── draw and label only (Q-17)
```

## Files and responsibilities

| File | Job |
|---|---|
| `core/demand.py` | 12 SQL constants (`QUERIES`), `params`, `fetch` / `fetch_all` (pipeline), one parser per view, `recommendations` (insights rules over aggregates), `build_report`, `DemandReader` (sync pool, read-only, repeatable read, `StoreUnavailable`) |
| `core/config.py` | + `DashboardSettings` (both fields `repr=False`), `load_dashboard_settings` (URL must log in as the dashboard role; gate password ≥ 12) |
| `scripts/dashboard_role.py` | Idempotent role + grants; password hashed by libpq (`encrypt_password`) on this machine; `--print-sql` (redacted), `--allow-remote` |
| `scripts/bench_demand.py` | Per query: EXPLAIN ANALYZE server time + wall time p50/p95, plan top node; whole report p50/p95. Read-only connection |
| `dashboard/app.py` | Settings, gate, sidebar, live fragment, caches (`on_release` closes the pool) |
| `dashboard/views.py` | One draw function per view; empty views show a caption; latest fans via `st.table` (no download button) |
| `dashboard/text.py` | Labels (bands, groups, steps, views, badges), banner, hero sentence, IST time format |
| `.streamlit/config.toml` | Bind `localhost`, no usage stats, minimal toolbar, no error details to the browser |
| `tests/component/conftest.py` | Session fixtures `full_rows` / `small_rows` (moved from `test_seed.py`, shared with phase 4) |

## Queries (all take the view; Simulated and Real never mix)

| Query | Counts |
|---|---|
| `totals` | Started = live fans in the view; counted = `completed_at` set (banner, #107) |
| `cities` | Counted fans and people per city, people from `PEOPLE_PER_GROUP`; ordered by people |
| `venues` | Counted fans and people per venue; "Other" / no venue excluded (#51) |
| `budget` | `GROUPING SETS`: band counts overall and per city (price band input, #79) |
| `groups` | Counted fans per group bucket |
| `heatmap` | Counted fans per city × venue; venue NULL = "Other / not listed" column (#27) |
| `funnel` | All live fans by `furthest_step`; Real also adds `funnel_counts` (#84, #104) |
| `weekly` | Counted fans per city per IST week (Monday), last 6 weeks (#56) |
| `growth` | Per city: counted in the last 7 days vs the 7 before (same windows as insights, #85) |
| `sources` | Counted fans per source tag, NULL = "no tag" (#3); one identity per fan (#37) |
| `latest` | 50 newest counted fans; email selected only when the toggle is on (#60) |
| `venue_list` | Reference data for names, capacities, suggested venue |

## Safety rules

- **Least privilege (#105, Q-18).** `crowdsense_dashboard`: SELECT on `fans`, `venues`, `funnel_counts`, `identities (fan_id, channel, source_tag)` only. Tests switch the role's read-only default off and still see 18 kinds of write refused, plus reads of answers, events, replies, sessions, Telegram user ids and `alembic_version`. The whole dashboard read path runs as the role in tests.
- **Password handling.** Role password hashed to a SCRAM verifier by libpq before it is sent (never plain in server logs); never printed. Gate: `hmac.compare_digest`, 1 s delay after a wrong try. Settings errors name the variable only.
- **Emails (#60).** Not selected unless the session's toggle is on; shown with `st.table` (no CSV download); never logged; cached only in process memory for 4 s.
- **Never mixed (#73).** Every fan query filters `is_simulated = %(simulated)s` (scanned by a test); `funnel_counts` only when Real; adding real fans leaves the Simulated report identical (P4-U09).
- **No logic in the UI (Q-17).** Tests scan `dashboard/` for SQL words, psycopg imports, arithmetic operators, `+=`, and calls like `sum`/`len`/`sorted`, and forbid importing insights functions (types only). A probe file with SQL and `sum()+1` made both tests fail.
- **Local only.** Streamlit binds `localhost`; usage stats off.

## Test id → file

| Id | File |
|---|---|
| P4-U01 to P4-U08, P4-U10 (data) | `tests/component/test_demand.py` |
| P4-U09 | `test_demand.py` (data) + `test_dashboard_app.py` (switch, banner) |
| P4-U10 (UI) | `test_dashboard_app.py` |
| P4-U11 | `tests/unit/test_dashboard_text.py` + `test_dashboard_app.py` |
| P4-C01, P4-C07 | `tests/component/test_demand_at_scale.py` |
| P4-C02, Q-18 | `tests/component/test_dashboard_role.py` |
| P4-C03, P4-C05, P4-C06 | `tests/component/test_dashboard_app.py` |
| P4-C04, Q-17 | `tests/quality/test_phase4_quality.py` (+ import-linter, Q-05) |

## Measured (2026-10-16, laptop, local Postgres 15, 20,000 seeded fans)

| What | Result |
|---|---|
| Each query, as the role, 30 runs | server p95 ≤ 6.0 ms (slowest `growth`); wall p95 ≤ 5.5 ms; plans: seq scan + hash aggregate / sort on 20k rows |
| Whole refresh (12 queries, pipelined) | p50 30.1 ms, p95 31.1 ms |
| P4-C07 in the suite | every query < 1 s (max of 5 runs), whole report < 1 s |
| New fan visible (engine commit → browser DOM) | 0.67, 3.77, 2.14, 0.55, 4.45, 3.12 s; design worst case ≈ 9 s |
| Role password check | Local pg_hba set to `scram-sha-256` for the role: wrong password refused, right one accepted |
| Supabase, as the role, 20 runs | server p95 < 23 ms per query; wall p95 up to 617 ms (`budget`, network jitter); whole refresh (12 queries pipelined, warm connection), two 40-run benches: p50 306–313 ms, p95 447–601 ms, max 600–962 ms; first (cold) connect 650–970 ms. Pipelined vs one query at a time, same data: p50 324–362 ms vs 978–1,478 ms (~3–4× faster). Intermittent multi-second outliers (p95 3.3–5.4 s in two 20-run comparisons, both modes) come from the network/pooler, not the queries |

EXPLAIN's server time is above wall time because ANALYZE adds timing overhead. No index: 20k rows is ~3 MB; at 100k (phase 6) a partial index on `(is_simulated, completed_at) WHERE completed_at IS NOT NULL` is the first thing to try.

## Manual checklist (Supabase data, 2026-10-16, checked in Chrome)

| Item | Result |
|---|---|
| Every view opens | Pass: banner, hero, 10 views; no errors |
| Hand check one city | Pass: Mumbai 3,447 fans = Mahalaxmi 2,001 + Bandra 1,280 + Other 166 (heatmap matches); people 9,828 = 5,691 + 3,663 + 474; row sums match for Bengaluru, Delhi NCR, Chennai, Hyderabad, Pune. Suggested venue rule checked by hand for all 10 cities |
| Simulated badge | Pass: orange "Simulated data" on Simulated, green "Real" on Real |
| Switch; Real = test accounts only | Pass: Real shows 2 counted fans (Pune, Delhi NCR) |
| New fan from the phone | Skipped (user, 2026-10-16); same path measured locally: 0.55–4.45 s |
| Hero card wording | Pass: "Play Mumbai first, at Mahalaxmi Maidan. About 9,828 people want to come (the venue holds 30,000). Price tickets at ₹3,000–6,000: most fans picked it." |
| Jaipur and Indore growing | Pass: both "📈 Growing" (recommendations + growth caption) |
| Email toggle (#60) | Pass: column absent until toggled; 13 of 50 with `@example.com`, 37 blank; email table has no toolbar (no CSV) |

## Decisions added

- **#104** Funnel per view; Real adds `funnel_counts`.
- **#105** Role `crowdsense_dashboard` by script, SELECT only (fans, venues, funnel_counts, identities source columns); env names in `.env.example` (dashboard URL, gate secret, role secret); settings in `core/config.py`.
- **#106** Fragment refresh every 5 s; one read-only snapshot per refresh; 4 s cache per view; pool max 2.
- **#107** Banner: view, counted and started fans.
- **#108** Revoke Supabase `anon` / `authenticated` on our tables (`scripts/lock_public_api.py`), incl. default privileges.

## Gotchas

- **import-linter checks indirect imports by default.** `core.insights` and `core.store_postgres` import `core.flow`, so "dashboard must not import flow" broke on a harmless `import core.insights`.
- **pandas has no type stubs**, so with mypy strict the dashboard passes plain dicts/lists to Streamlit.
- **`st.dataframe` has a CSV download button**; the email table uses `st.table`.
- **`st.cache_resource` keeps the pool alive across tests** that use different databases; `on_release=DemandReader.close` plus clearing caches around each AppTest fixes it.
- **Run Streamlit as `python -m streamlit`** so the repo root is on `sys.path` (`core`, `dashboard` imports).
- **Badge + bold label said "Simulated data" twice**; the badge now carries the view label and the bold text the counts.
- **Empty views drew blank charts with a "0.000000" axis**; empty views now show a caption.
- **Heatmap as a table printed "None"** in every empty cell (venues belong to one city, so the matrix is sparse). Now a Vega-Lite rect heatmap with counts, "Other / not listed" last.
- **The current week looked like a crash.** The last IST week is partial, so every city's line dropped while the badges said "growing". `demand.weekly` now flags `in_progress` and the chart labels it "(so far)". Labels stay ISO dates, because "05 Oct" / "07 Sep" sort alphabetically on a nominal axis.
- **Bench the warm path.** `DemandReader` opens its connection lazily (TLS + SCRAM, ~0.7–1 s to Supabase); the first `bench_demand` run timed that as a refresh and pushed p95 to 822 ms. The bench now reports the cold connect separately; the live dashboard keeps the connection warm.
- **Real funnel vs banner:** the funnel's "started" includes deleted fans from `funnel_counts` (#104), the banner counts live fans only, so Real can show 3 vs 2. Correct, worth one sentence in the demo.
- `pytest-postgresql` uses trust auth, so suite tests prove grants, not the password check (checked once by hand, above).
- `Settings.database_url` (phase 1) has no `repr=False`. Out of scope; flagged.

## How to run

```bash
uv run pytest -q --cov=core --cov-fail-under=90
DATABASE_URL=<owner url> DASHBOARD_DB_PASSWORD=<secret> uv run python -m scripts.dashboard_role [--allow-remote]
uv run python -m scripts.dashboard_role --print-sql
uv run --env-file .env python -m scripts.bench_demand --runs 20
uv run --env-file .env python -m streamlit run dashboard/app.py      # http://localhost:8501
```

## Likely interview Q&A

**Why SQL in demand.py and rules in insights.py?** Counting 20,000 rows is the database's job; doing it in Python means shipping every row over the network each refresh. Rules (people per group, 80% fill, price-band tie-break, +20% growth) are business decisions, so they live once in pure, unit-tested functions. `demand.py` feeds aggregates into those same functions, and a test proves the result equals the Python-only path on the same rows (P4-U08, P4-C01).

**How do you keep simulated and real apart?** `is_simulated` is set only by the seed; every dashboard query takes the view as a parameter and filters on it, and a test scans every query for that filter. `funnel_counts` has no flag but only real fans can `/delete`, so it is added to the Real funnel only. Adding real fans leaves the Simulated report identical (P4-U09).

**Why a read-only role?** The dashboard is the part most exposed to people (a browser, a password). If it is compromised or buggy, the worst case is reading aggregates and emails, never changing or deleting data. The grants enforce it, not the app: tests switch the read-only default off and every write is still refused.

**How does it stay live?** A Streamlit fragment reruns the data area every 5 s; each rerun is one read-only transaction with all 12 queries pipelined (one round trip, one consistent snapshot). A 4 s shared cache means ten open tabs still cost about one query batch per 5 s, which matters on Supabase's small pooler. Measured: a new fan appears in 0.5 to 4.5 s.

**Is it fast at 20k / 100k?** At 20k the slowest query is 6 ms and a whole refresh 31 ms locally, so the budget is network, which pipelining reduces to one round trip. Queries are linear scans of a narrow table; 100k is about 5× (tens of ms). Past that: a partial index, then materialized views refreshed per minute (`docs/metrics.md`).
