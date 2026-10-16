# Decisions

Why each choice was made. What: `docs/prd.md`. How: `docs/architecture.md`. When: `docs/plan.md`. Issue, options and reasoning behind #54 to #98: `docs/design-review.md`.

**Status key:** **Fixed** = decided by user. **Default** = proposed, applies unless research changes it. **Parked** = decided to do later (section 4). **Open** = needs research (section 5).

Decision numbers never change, so code and tests can reference them (`@decision(n)`).

## Contents

1. [Fixed decisions](#1-fixed-decisions)
2. [Default decisions](#2-default-decisions)
3. [Reference data](#3-reference-data)
4. [Future and parked](#4-future-and-parked)
5. [Research questions](#5-research-questions)

Channel options: `docs/architecture.md` §8. Council input: `docs/design-review.md` §1.

---

## 1. Fixed decisions

### Scope and audience

- **#1** Audience is interviewers; they must see a proof of concept and a working MVP · _(user)_
- **#2** ~~Real artist~~ **Superseded by #18**: artist and fans are simulated · _(user)_
- **#18** The artist is a simulated big artist (fictional Indian pop persona) and fans are simulated, as a proof of concept. Dashboard numbers are labelled "simulated". Real fans are limited to the builder and a few testers through the Telegram link (web chat users are real too, #76) · _(user)_
- **#19** The MVP scope is the full plan, phases 1 to 5 in `docs/plan.md`. No demo date is tracked · _(user)_
- **#43** Product name: **Crowdsense** (project name `crowdsense`; code layout stays as in #8) · _(user)_
- **#48** Spec gaps A1 to A10 in `testing/README.md` accepted as proposed; A8 uses `funnel_counts` (#45) and deletes the fan's `events` too · _(user)_

### Channels and entry

| #   | Decision                                                                                    | Source |
| --- | ------------------------------------------------------------------------------------------- | ------ |
| 3   | Fans enter by clicking a link (story, bio, poster) that opens the chat app                  | user   |
| 4   | Chat channel is a plugin. Conversation logic, storage and dashboard are channel-independent | user   |
| 5   | Telegram is the first channel                                                               | user   |
| 7   | Later adapters: WhatsApp, Instagram, Discord (parked, see `docs/architecture.md` §8)        | user   |

### Architecture and stack

- **#6** Effort goes mainly into backend logic and database architecture · _(user)_
- **#8** Repo structure: `adapters/`, `core/{engine,flow,store}`, `api/webhooks`, `dashboard/` · _(user)_
- **#26** Database: Supabase (hosted Postgres) is the primary and only database for now · _(user)_
- **#28** Dashboard: Streamlit (Python, reads the DB directly; read path refined to `core/demand.py` by #57) · _(user)_
- **#29** Hosting for now is dev only: everything runs on the laptop, Telegram reaches the webhook through ngrok. Cloud hosting for the demo is deferred (see section 4) · _(user)_
- **#30** Two separate services: the Telegram webhook (FastAPI) and the Streamlit dashboard, with the database as the only bridge. ngrok for dev · _(user)_
- **#44** Postgres-backed tests use `pytest-postgresql` on the local Homebrew Postgres (no Docker on the dev machine); CI uses a GitHub Actions Postgres service. Replaces testcontainers-python · _(user)_
- **#65** Stack stays Python + FastAPI + Postgres + Streamlit. One language lets both services share `core/`; Next.js would add a second language and an API layer for looks only · _(user)_
- **#66** Telegram client is plain `httpx` (`setWebhook` with `secret_token` and `allowed_updates`, `sendMessage`, `answerCallbackQuery`, `editMessageReplyMarkup`), not python-telegram-bot or aiogram · _(user)_
- **#67** DB driver is psycopg 3 with raw SQL: async pool for the webhook, sync pool for the dashboard. Transaction pooler (port 6543) needs `prepare_threshold=None`; migrations use the session pooler (port 5432), since the direct connection is IPv6-only on the free tier · _(user)_
- **#68** Dashboard refresh is `st.fragment(run_every=5)` with `st.cache_data(ttl=5)`; aggregation in SQL, small results passed to `insights.py` · _(user)_
- **#69** Messages are plain text (no MarkdownV2). Announcements are paced to Telegram limits (about 1 message/s per chat, about 30/s overall) · _(user)_

### Conversation flow and data

- **#20** Cities: Mumbai, Delhi NCR, Bengaluru, Hyderabad, Pune, Kolkata, Chennai, Ahmedabad, Jaipur, Indore (Jaipur and Indore are the under-explored ones) · _(user ("keep these"))_
- **#21** Budget bands: under ₹1,500 / ₹1,500–3,000 / ₹3,000–6,000 / ₹6,000+ · _(user)_
- **#22** Group size: 1 / 2 / 3–5 / 6+ · _(user)_
- **#23** ~~Timing question~~ **Removed**: the bot does not ask for show timing (a number is kept so later references stay stable) · _(user)_
- **#24** Venues are proper-noun names with a capacity, no type words (arena, hall, club). See the venue table in section 3 · _(user)_
- **#25** Fan picks a venue by name with buttons, replacing the free-text venue area. Confirmed by use in the message script · _(user)_
- **#33** Group bucket to people count: 1→1, 2→2, 3–5→4, 6+→6 · _(user)_
- **#35** ~~Interest is still asked with three buttons and stored, but it affects no calculation yet~~ **Removed by #94** · _(user)_
- **#36** Consent: short update-style opening message with Count me in / No thanks, `/stop` named in it, `/delete` and stored-data info in `/help` and the README. Wording and rules in `docs/message-script.md` (rules: `docs/architecture.md` §6) · _(user)_
- **#37** Each channel identity counts as its own fan for now (no cross-channel merge). Merge by email is parked, see section 4 · _(user)_
- **#38** Message drafts #2 to #15 in `docs/message-script.md` stay as drafts; wording is refined during implementation · _(user)_
- **#45** `/delete` keeps the anonymous funnel count in a `funnel_counts(step_id, count)` table, incremented on delete · _(user (accepted default))_
- **#46** `fans.venue_id` is an FK to `venues.id`; "Other / not listed" leaves it null and fills `venue_note` · _(user (accepted default))_
- **#47** Phase 1 logs inbound events in `events` and each turn's replies in `replies`. Replies are saved with the new state in one transaction and sent after commit; unsent ones are picked up by the resend sweeper (#72). The phase 6 outbox builds on this log (`docs/architecture.md` §10 #3) · _(user)_

### Recommendation logic

- **#31** Recommendation logic, no conversion rate for now: **(a)** Demand per venue = number of fans who picked the venue, ranked as "top venues queried". **(b)** Expected attendance = sum of people (group size) of those fans. **(c)** Suggested venue = smallest venue in the city with capacity ≥ expected attendance ÷ 0.8 (80% target fill), otherwise the city's largest venue. **(d)** City priority = expected attendance per city, with a "growing" badge when last week's signups beat the week before by 20% or more. Price band is in #32 · _(user)_
- **#32** Suggested price band = most common budget band among a venue's counted fans, changed to per city by #79 (Method 1, comes straight from the price range fans select in the bot). Demand-curve method parked in section 4 · _(user)_
- **#34** ~~Interest does not filter any number for now~~ **Removed by #94**. Counted fans (#52, #70) are the only filter · _(user)_
- **#49** Expected attendance for the suggested venue is measured per city: all counted fans in the city. Per-venue demand is for ranking only (clarifies 31c) · _(user)_
- **#50** A tie for the most common budget band picks the lower band (more fans can afford it) · _(user)_
- **#51** Fans who chose "Other / not listed" count in city attendance, city priority and price band, and are excluded from per-venue demand · _(user)_
- **#53** MVP outbound is one "show announced in your city" message. Other types (early-bird, group discount, reminder) are decided in phase 6 · _(user)_
- **#52** Only fans who reached the done step count in any number; partial fans appear only in the funnel · _(user)_
- **#70** A fan counts from the first time they reach done (`fans.completed_at`, set once, never cleared). Editing an answer never uncounts them; a fan re-asked for a venue counts for the city but no venue, like "Other" (#51). Refines #52 · _(user)_

### Design (architecture review)

- **#54** The Postgres store and the in-memory fake run one shared contract suite from phase 1 (not phase 6) · _(user)_
- **#55** One engine turn = one transaction: dedupe, identity lock (#88), state, answers and replies commit together; replies are sent after commit; unsent ones are picked up by the resend sweeper (#72). Inbox-first "ack fast" stays phase 6 · _(user (delegated))_
- **#56** Time comes from a clock seam (real and scripted), so seeded fans spread across weeks and growth rules are testable. Weeks use IST; timestamps stored in UTC · _(user (delegated))_
- **#57** `core/demand.py` owns the counted-fan rule (#51, #52) and all SQL aggregates (sync, read-only); `insights.py` applies rules to aggregates. Aggregates are tested on real Postgres only · _(user (delegated))_
- **#58** The flow holds its own transitions and invalidations (decline ends, "Other" detours, skip email, city clears venue) · _(user (delegated))_
- **#59** Phase 5 builds `core/outbound.py` (audience rule + delivery over the `replies` log, sent directly); the phase 6 outbox replaces the direct send · _(user (delegated))_
- **#60** Dashboard has a password gate and hides emails by default · _(user (delegated))_
- **#61** Failure policy is written in `docs/architecture.md` §5 (engine error, DB down, send failure, duplicate) · _(user (delegated))_
- **#62** A reset command wipes simulated fans and reseeds, for repeatable demos · _(user (delegated))_
- **#63** Settings come from one validated config module, including `ARTIST_NAME` (replaces hard-coded "Artist X") · _(user (delegated))_
- **#64** Deferred: campaign table (phase 6; add column with default then), single writer for answers (covered by #55), regional-language text, CSV export, backup restore drill · _(user (delegated))_
- **#71** On an engine error (a bug) the webhook rolls the turn back, returns 200 so Telegram stops retrying, sends one apology, and logs the error. DB down still returns 5xx so Telegram retries · _(user)_
- **#72** A resend sweeper in the webhook service runs every 30 s, claims `unsent` replies older than 10 s (`FOR UPDATE SKIP LOCKED`), sends them and marks them `sent`. Delivery is at-least-once. The phase 6 outbox replaces it · _(user)_
- **#73** The dashboard has a Simulated / Real switch. Default is Simulated; the two are never mixed. Real = about 9 to 10 testers on their own Telegram accounts. A banner shows the view and its fan count. Refines #18 · _(user)_
- **#74** No minimum-sample handling in the MVP: every number, recommendation and badge is shown as computed, even for tiny cities. The banner (#73) still shows the view's fan count. Low-data warnings are parked · _(user)_
- **#75** The announcement is sent from a dashboard form: city dropdown, date picker (today or later), live preview, "Will send to N fans" and a confirm button. N comes from the same audience rule as #59. Refines #53 · _(user)_
- **#76** `is_simulated` is set only by the seed script, never by the channel. A person chatting through the web simulator is a real fan and appears in the Real view. The web simulator may not support push; announcements skip such fans and show the count (P5-C06). Refines #18 · _(user)_
- **#77** The web chat is served at `/chat` by the webhook service and reached through the same ngrok tunnel, so an interviewer can try it on their own device. The laptop stays on during the demo; a screen recording is the fallback. Cloud hosting stays deferred. Refines #29 · _(user)_
- **#78** Seed about 20,000 simulated fans (was ~1,500, #40): the engine runs in memory, then rows are bulk-copied to Postgres. Reason: 1,500 fans gave every city its smallest venue · _(user)_
- **#79** Price band is per city: most common band among the city's counted fans, shown next to the suggested venue. Refines #32 · _(user)_
- **#80** The dashboard role stays read-only plus INSERT on `announcement_requests`. The webhook service's sweeper sends announcements, paced to Telegram limits. Refines #59, #75 · _(user)_
- **#81** `/delete` also removes `replies` and the fan's `events`. The delete confirmation is sent directly and never stored · _(user)_
- **#82** The engine takes a `simulated=True` option from phase 1; the seed uses it to set `is_simulated`. Phase 3 needs no engine change · _(user)_
- **#83** Web chat has no stable fan id (refresh = new fan). Telegram is the main channel and the web chat only a backup, so this is a known limit, parked · _(user)_
- **#84** `fans.furthest_step` (never moves back) drives the funnel; "completed" = `completed_at` set; `funnel_counts` on `/delete` records the furthest step · _(user (delegated))_
- **#85** Growth badges and the announcement audience use counted fans only (`completed_at` set) · _(user (delegated))_
- **#86** The webhook returns 200 first, then sends replies in the background, so the ack target excludes Telegram API time · _(user (delegated))_
- **#87** The Done message depends on the channel: push channels promise updates; non-push channels (web chat) just thank the fan · _(user (delegated))_
- **#88** A new fan's identity is created with `INSERT … ON CONFLICT DO NOTHING` and then locked (`SELECT … FOR UPDATE`) before anything else, so two fast first messages never create the fan twice or trigger the apology · _(user)_
- **#89** `docs/metrics.md` holds the scale, load, speed and bot-strength metrics with targets, how each is measured, and results filled in after measuring · _(user)_
- **#90** Telegram's dedupe key is `update_id`: unique per bot and present on both text messages and button taps (a tap has no `message_id` of its own) · _(user)_
- **#91** Button data is `<step_id>:<choice_id>` (≤ 64 bytes). A tap whose step is not the fan's current step is stale: ignored, no state change, and the fan sees "That question has passed" as a normal chat message (not a toast, because the tap was already answered, see #92). The buttons are left alone · _(user)_
- **#92** On every Telegram tap the adapter calls `answerCallbackQuery` at once with no text (a tap can be answered only once, and only the engine knows if it is stale). Only if the engine applied the tap are the buttons replaced with "✓ <choice>" via `editMessageReplyMarkup`, so the fan cannot tap twice and a fast tap on another button never shows a wrong ✓. Double tap: the engine cannot tell it from an old-button tap, so the webhook keeps, in process memory for 60 s, the messages it just confirmed with "✓"; a stale tap on one of those is a double tap, and its stale reply is marked sent without being delivered. Older stale taps still get "That question has passed" (#91). After a restart inside that window the worst case is one extra "passed" message · _(user)_
- **#93** Telegram send errors: 429 → wait `retry_after`, then resend; 403 (bot blocked) → in one transaction mark the identity opted out and delete that fan's pending `unsent` replies (so the sweeper never retries them; no `dropped` status and no schema change, because an undeliverable reply is not worth storing, same spirit as #81); log how many were dropped · _(user)_
- **#94** The "Would you actually come?" interest question is removed everywhere: no step, no stored field, no edit-menu entry, no filter. Reason: it served no purpose and nothing used it. Supersedes #34 and #35 · _(user)_
- **#95** Input caps live in the core, so every channel gets them: the engine cuts inbound text to 1,000 characters before it is stored in `events` or reaches `decide`; a `source_tag` is kept only if it matches `^[A-Za-z0-9_-]{1,64}$` (Telegram's deep-link rule), anything else is stored as no tag and the fan still gets in. Postgres length limits on `events` text, `identities.source_tag`, `fans.venue_note` and `fans.email` arrive in a new migration 0003, because 0001 and 0002 are applied to Supabase · _(user)_
- **#96** Sticker and group-chat updates are not recorded as real fixtures for now. The tests build the group and `/help@bot` cases by modifying recorded fixtures, and a sticker takes the same "message with no text" path as the recorded photo. Real recordings are optional later · _(user)_
- **#97** The webhook stays on the Supabase session pooler (port 5432, pool max 5) until the last phase, then moves to the transaction pooler (port 6543). Checked on 2026-10-16: the same code behaves identically on both ports (pool, repeated queries, `FOR UPDATE`, `SKIP LOCKED`, rollback), so the switch is a change of `DATABASE_URL`. Migrations must keep a session or direct URL, so the switch also adds an optional `MIGRATION_DATABASE_URL` that `migrations/env.py` prefers over `DATABASE_URL`. Refines #67 · _(user)_
- **#98** The database limit on `fans.venue_note` and `fans.email` is 200 characters (migration 0003), the same as the flow's own validators. Accepted as a security and scaling measure; reasons in `docs/design-review.md` §15 · _(user)_
- **#99** The web chat's rate limit is per client IP. The webhook service trusts `X-Forwarded-For` only when the request comes from localhost (the ngrok agent), and then only its last entry, which ngrok wrote; earlier entries come from the client and can be forged. Any other request uses the socket address. Limit: 60-request burst, refills 1/s, at most 10,000 IPs held in process memory · _(user)_
- **#100** The web chat returns replies in the HTTP response and marks them sent afterwards. It cannot push and the resend sweeper only claims registered channels, so a reply still `unsent` after 10 minutes (the mark-sent failed) is marked sent by `expire_unsent` (at most once a minute, 500 rows a pass). Nothing piles up; no schema change · _(user)_
- **#101** Plugin cost (Q-15) for a channel that needs its own routes: one adapter file, its transport routes in `api/` (web chat: `api/chat.py`, `api/ratelimit.py`, `api/static/`), one wiring line in `build_app`, plus scripts, tests and docs. `core/` and `migrations/` must not change; a test and a CI step enforce the allowed paths against tag `phase-2`. Refines #16 · _(user)_
- **#102** Seeded fans use the channel `seed`: no adapter, not a push channel. Their bot replies are not copied to Postgres, and the seed never sends `/delete` (so `funnel_counts`, which has no simulated flag, holds real data only). With #76 and the real-fans-only audience (#85), nothing can ever send to a seeded identity (P3-C05). Refines #78 · _(user)_
- **#103** Demo links: the interviewer gets the public ngrok link `<PUBLIC_URL>/chat` (with the Telegram deep link) to try on their own device while the laptop serves it; `localhost:8000/chat` is only for the presenter's own screen. The phone-over-mobile-data check is deferred from phase 3 to the phase 5 rehearsal, so it must pass before any link is shared. Refines #77 · _(user)_
- **#104** Funnel per view: Real = live real fans by `furthest_step` plus `funnel_counts` (deleted fans, which are always real, #102); Simulated = live simulated fans only. "Completed" counts live fans with `completed_at` set; a deleted fan adds only to its furthest step. Refines #84 · _(user)_
- **#105** The dashboard role `crowdsense_dashboard` is made by a one-off idempotent script (`scripts/dashboard_role.py`), not a migration (a role is cluster-wide; migrations stay schema-only). Password from `DASHBOARD_DB_PASSWORD`, never printed. Phase 4 grants SELECT only: `fans`, `venues`, `funnel_counts`, and `identities (fan_id, channel, source_tag)`; every write is refused. Phase 5 creates `announcement_requests` and adds its INSERT grant (#80). The dashboard reads `DASHBOARD_DATABASE_URL` (Supabase transaction pooler, port 6543, user `crowdsense_dashboard.<project-ref>`) and gates on `DASHBOARD_PASSWORD`; both load in `core/config.py` (#63). Refines #80 for phase 4 · _(user)_
- **#106** Live refresh: a Streamlit fragment reruns the data area every 5 s; each refresh runs every query in one `READ ONLY` `REPEATABLE READ` transaction on one pooled connection (pool max 2), so the banner and views share one snapshot. Results are cached for 4 s per view, so many open tabs cost about one batch per 5 s. A new fan appears within about 10 s (#28) · _(user)_
- **#107** The banner shows the view, counted fans (#52) and started fans: "Simulated data · 17,000 counted fans (20,000 started)". Refines #73 · _(user)_
- **#108** Supabase's API roles `anon` and `authenticated` get no privileges on our tables: `scripts/lock_public_api.py` revokes them on every table, sequence and function in `public` and in the owner's default privileges (future tables stay closed), then fails if any privilege is still open. Reason: Supabase grants them everything with row-level security off, so the public anon key could read, edit or delete fan data through the REST API. A script, not a migration, because the roles exist only on Supabase. The dashboard role (#105) and the owner are unaffected · _(user)_

---

## 2. Default decisions

Change only if research says so.

- **#9** Python backend · _Why: the user's structure uses `.py` files_
- **#10** Flow defined as data, engine is `handle(event) -> list[Reply]` · _Why: one engine for all channels, change questions without code_
- **#11** Fan identity split from channel identity (`fans` + `identities`) · _Why: same fan can arrive on several channels_
- **#12** Answers kept as append-only history plus a current snapshot on `fans` · _Why: enables growth-of-demand charts_
- **#13** Buttons first, free text second · _Why: cleaner data, simpler MVP_
- **#14** Dashboard seeded with synthetic fans run through the real engine, labelled as simulated · _Why: structurally real data, honest demo_
- **#15** Outbound "notify fans" is a dashboard button · _Why: shows the retention half of the idea_
- **#16** Build a second adapter (web simulator) after Telegram to prove the abstraction · _Why: cheapest test of the design_
- **#17** The ref repo `Aditya26189/WhatsApp-Bot` is reference only (no license file) · _Why: license unclear_
- **#27** "Other / not listed" venue button stores a free-text note beside the row · _Why: keeps the flow from breaking_
- **#39** A `venues` table (id, city, name, capacity) is seeded from the venue table; recommendations read capacity from it · _Why: keeps venue data out of code_
- **#40** Seed about 1,500 simulated fans with an uneven spread across cities and weeks (some cities growing, Jaipur and Indore rising), all flagged `is_simulated` (raised to ~20,000 by #78) · _Why: gives the dashboard and recommendations something meaningful to show_
- **#41** Phase 1 is written with a pure decision core, a store interface (Postgres plus in-memory fake) and a separate insights module; day-1 tooling is ruff, pytest, pre-commit and GitHub Actions · _Why: keeps the design testable at no feature cost_
- **#42** Hardening is a later phase 6 (see `docs/plan.md`); load tests use Locust unless changed · _Why: production-level story with measured results_

---

## 3. Reference data

### Venue table

Names fictional, capacities in seats.

| City      | Venue               | Capacity |
| --------- | ------------------- | -------- |
| Mumbai    | Mahalaxmi Maidan    | 30,000   |
| Mumbai    | Bandra Waterfront   | 4,000    |
| Delhi NCR | Dwarka Maidan       | 25,000   |
| Delhi NCR | Aerocity Terrace    | 3,500    |
| Bengaluru | Whitefield Commons  | 20,000   |
| Bengaluru | Indiranagar Yard    | 2,000    |
| Hyderabad | Gachibowli Fields   | 18,000   |
| Pune      | Baner Greens        | 12,000   |
| Pune      | Koregaon Park Lawns | 6,000    |
| Kolkata   | Salt Lake Esplanade | 15,000   |
| Chennai   | ECR Seafront        | 12,000   |
| Ahmedabad | Sabarmati Riverside | 10,000   |
| Jaipur    | Jal Mahal Terrace   | 5,000    |
| Indore    | Vijay Nagar Commons | 4,000    |

---

## 4. Future and parked

| Item                                                  | Status                                      | Detail    |
| ----------------------------------------------------- | ------------------------------------------- | --------- |
| Later channel adapters (WhatsApp, Instagram, Discord) | Parked (#7)                                 | Section 4 |
| Local Docker Postgres backup                          | Parked, build after the Supabase path works | Below     |
| Demo hosting                                          | Deferred (#29)                              | Below     |
| Cross-channel fan merge                               | Parked (#37)                                | Below     |
| Price band demand curve                               | Parked (#32)                                | Below     |
| Dashboard swap from Streamlit                         | Possible later (#28)                        | Below     |
| Low-data warnings ("n = 3", greyed out under 10 fans) | Parked (#74)                                | Below     |

### Backup database: local Docker Postgres

Supabase is the primary. A local Docker Postgres is the backup, built after the Supabase path works end to end.

- Why: a network or Supabase outage during the interview would stop the demo, and the free tier pauses idle projects.
- Same schema on both (`fans`, `identities`, `sessions`, `answers`, `events`), kept as migration files so either can be built from scratch.
- Database chosen by one environment variable, so switching needs no code change.
- A seed script loads the simulated fans so the dashboard works offline.
- Connection strings live in `.env`, never in git; placeholder names in `.env.example`.
- Open: sync by periodic dump or by seed script only? Does the backup serve only the dashboard and web simulator (Telegram needs internet anyway)? Add a pre-demo checklist item: wake the Supabase project and test the local backup.

### Demo hosting

Dev only for now (#29). When the demo gets close, choose between:

- **Railway** for the webhook (no idle sleep) and Streamlit Community Cloud (free) for the dashboard, or both on Railway. Pricing checked 2026-10-16: free plan is a 30-day trial with a one-time $5 credit (no card), then $1/month; Hobby includes $5 usage per month; Pro includes $20. Billing is per second (memory $0.00000386 per GB-second, CPU $0.00000772 per vCPU-second). Estimate for both services: about $5 to $7 per month. The pricing page does not say what happens when trial credit runs out, so verify before relying on it.
- **Render** free tier for the webhook: free, but it sleeps after idle and the first message is slow.
- **Fallback:** ngrok on the laptop plus a screen recording of the full flow.
- If Railway: sign up about a week before the interview so the 30-day trial covers the demo, and check both services are running the day before.

### Cross-channel fan merge

#37 counts each channel identity as its own fan. When a second adapter arrives, merge by verified email: if the optional email matches, link both identities to one `fans` row, and list the rest as possible duplicates on the dashboard. The schema already supports this (`fans` is separate from `identities`), so merging is a data task and not a redesign. Other options considered: merge by phone (WhatsApp gives it, Telegram needs the user to share contact), or ask the fan to send their email from the other app.

### Price band: demand curve

#32 uses the most common budget band. A better method for later: for each price (band lower edge), count fans whose budget is at or above it, cap buyers at venue capacity, and mark two suggestions on the curve: max revenue and max fill. Reason: a fan with a high budget also buys at a lower price, so the most common band ignores that. Also parked: a conversion rate from stated intent to purchase.

### Low-data warnings

Not in the MVP (#74). Idea for later: print "n = X" beside each recommendation and grey it out as "low data" when a city has fewer than 10 counted fans. Nothing hidden. Matters most for the Real view (about 10 testers over 10 cities). The PRD limits note (§7) already says results come from self-selected fans.

### Dashboard swap

Streamlit now. The dashboard only reads the database, so Next.js (or another tool) can replace it later without touching the engine or adapters. Streamlit's plain look is handled with a custom theme, a clean layout, a "simulated data" badge and one hero recommendation card.

---

## 5. Research questions

To research with Claude web. Sections 5.1 and 5.2 are for the later WhatsApp adapter, not a blocker. Sections 5.3 to 5.5 feed phase 0 of `docs/plan.md`. Items already settled point to their decision.

**Context to paste first:** fan-demand-intelligence MVP for a simulated big Indian artist. Fans click a link (story, bio) that opens Telegram first (WhatsApp later). A bot collects city, venue, ticket budget, group size, contact. A dashboard shows demand to the artist. Audience: interviewers judging a POC and working MVP. India-based builder.

### 5.1 Message portal (WhatsApp vs Telegram) — settled by #5, #7

1. Compare WhatsApp Cloud API and Telegram Bot API for a 1-week MVP where fans arrive through a link. Time to first working bot, ongoing cost, limits, failure modes.
2. Which would interviewers consider the stronger demo, and what is the honest tradeoff of building on Telegram first and adding WhatsApp later?
3. Where do Indian concert-going fans mostly hear from artists and chat (WhatsApp, Telegram, Instagram DMs)? Any data?
4. Can one conversation engine serve both channels cleanly? What is the minimum adapter design? → #4, #10

### 5.2 WhatsApp Cloud API specifics — open, for the later adapter

1. 2026 limits of the free test number: recipient cap, how recipients are added, token expiry, how to get a permanent system-user token.
2. Can fans who are not whitelisted message the test number through a wa.me link? If not, what is the cheapest path to let real fans in?
3. Business verification for an individual or student in India: documents, time, cost, can it start before the product exists?
4. Message categories and pricing in India: service vs utility vs marketing conversations; what is free; what the 24-hour window and click-to-WhatsApp free entry window allow.
5. Template approval: what is needed for launch notifications, early-bird offers and reminders; typical approval time; example templates.
6. Opt-in rules for collecting a phone number and sending later messages. DPDP Act basics for this use.
7. Webhook details: verification handshake, retry behaviour, deduplication by message ID, signature validation.
8. Interactive messages: buttons and lists, limits on counts and lengths.
9. Account ownership: personal vs business Meta account, how to avoid a messy number migration later.

### 5.3 Telegram specifics — open, phase 0

1. Bot setup via BotFather, deep link `start` parameter for source tags, webhook vs long polling.
2. Inline keyboards for buttons, rate limits, how to message users later (they must start the bot first).
3. Privacy: what user data Telegram gives the bot (no phone number by default; how to request contact).

### 5.4 Tech stack — mostly settled

1. Backend: FastAPI vs Node for a webhook + state machine. → #9, #30 (Python, FastAPI)
2. Database: Supabase vs local Postgres vs SQLite for a demo with live dashboard updates. → #26 (Supabase)
3. Dashboard: Streamlit vs Next.js for a polished 1-week MVP. → #28 (Streamlit)
4. Hosting for a public HTTPS webhook: ngrok vs Render/Railway/Vercel; free-tier limits and cold starts. → #29, section 4 "Demo hosting"
5. Conversation state storage: DB column per fan vs Redis. → DB (`sessions` table, `docs/architecture.md`)
6. LLM for free-text parsing in the MVP, or buttons only? → #13 (buttons first)
7. Reference repo `Aditya26189/WhatsApp-Bot` has no license file: reuse rules, and which parts are worth rewriting. → #17 (reference only)

### 5.5 Product and data — open

1. Typical ticket prices and venue capacities for indie and mid-size artists in target cities.
2. Interest-to-purchase conversion benchmarks for event pre-registration, to make capacity recommendations defensible.
3. How to seed synthetic data and label it honestly next to real fan data in a demo. → partly #14, #40
4. How to check that stated intent predicts purchase (waitlist, deposit, fake-door test).
5. Self-selection bias: how to state it in a pitch without weakening it.

### 5.6 Interview framing — open

1. What do interviewers look for in a "working MVP": live demo, architecture explanation, tradeoff reasoning, metrics?
2. Which two or three numbers should the demo end on (real fans reached, completion rate, recommendation output)?

---
