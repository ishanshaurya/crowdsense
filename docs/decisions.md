# Decisions

The choices that shaped Crowdsense. Numbers never change, because code and tests reference them (`@decision(n)`). The product is in `docs/prd.md`, the design in `docs/architecture.md`.

## The big ones

**Channel-agnostic core (#4, #10, #11, #16).** The conversation is data, and the engine is one function: `handle(event) -> list[Reply]`. Telegram is an adapter, and so is the web chat. I built the second adapter on purpose, as the cheapest proof that the first one doesn't leak into the core. Fans and channel identities are separate rows, so one person can arrive on several channels. The rule is enforced: adding a channel may not touch `core/` or `migrations/`, and a test and a CI step check it (#101).

**One language, boring stack (#9, #26, #65).** Python, FastAPI, Postgres on Supabase, and Streamlit. Both services share `core/`. Next.js would have meant a second language and an API layer just for looks. Postgres fits because every dashboard view is a `GROUP BY` or a date bucket. MongoDB would have turned those into aggregation pipelines, and Redis would have been a second system for one row of state per fan.

**One turn, one transaction (#55, #47, #72).** Dedupe, state, answers and replies commit together, and replies are sent after the commit. A resend sweeper picks up anything unsent (`FOR UPDATE SKIP LOCKED`), so delivery is at-least-once. The alternative, sending first, can leave a fan out of step with saved state after a crash. The cost is a `replies` table and a duplicate message in the rare crash between send and mark.

**Telegram is not idempotent, so I made it so (#88, #90, #91, #92, #93).** Updates are deduped on `update_id`. A new fan's identity row is inserted and locked before anything else, so two fast first messages can't create two fans. Taps on old buttons are ignored, and the fan gets a normal chat message instead of a toast. Double taps are told apart from stale taps with a short in-memory window. A 403 (bot blocked) opts the fan out and drops their pending replies instead of retrying forever.

**Engine bugs and outages fail differently (#71).** If the engine hits a bug, the webhook rolls back, returns 200 so Telegram stops retrying, and sends one apology. If the database is down, it returns 5xx, because nothing was saved and a retry is free. Without the split, a crashing bug would repeat its apology on every retry for hours.

**What counts as demand (#31, #49, #51, #52, #70).** Only fans who reached the end count in any number. Once counted, always counted: editing an answer never uncounts a fan, so numbers don't flicker mid-demo. Expected attendance is the sum of group sizes in a city. The suggested venue is the smallest one that fits that figure at 80% fill, or else the city's largest. City priority ranks by expected attendance, with a "growing" badge at 20% week-on-week growth. There is no conversion rate yet, and the README says so.

**Simulated and real data stay apart (#14, #18, #73, #76, #78, #82).** About 20,000 simulated fans run through the real engine in memory and are bulk-copied to Postgres. At 1,500 fans every city got its smallest venue, so the recommendations meant nothing. The dashboard has a Simulated / Real switch and never mixes them. Anyone chatting through the web chat is real. Only the seed script sets `is_simulated`.

**Database permissions, not just app checks (#60, #105, #108, #109, #115).** The dashboard connects as a role that can read and almost nothing else. It can insert an announcement request (city and date only) and nothing more. Supabase's public `anon` and `authenticated` roles are revoked on every table, because by default the public key could read and edit fan data through the REST API. Row-level security is on, and migrations close their own objects.

**Announcements go through the same pipe (#80, #110, #111, #112).** The audience rule lives once, in a SQL function: counted, consented, not opted out, not simulated, Telegram only. The dashboard gets a count, never the rows. The dashboard form writes a request. The webhook service fans it out into `replies`, and the existing sweeper sends it, paced to Telegram's limits. There is one announcement per city and date. I chose that over an idempotency key to keep it simple, and resending a corrected one is not allowed.

**Two stores, one contract suite (#54, #56).** The Postgres store and an in-memory fake run the same tests from phase 1, so the fake can be trusted in fast tests. Time comes from a clock seam, so seeded fans spread over weeks and growth rules are testable. Weeks use IST and timestamps are stored in UTC.

**Inputs are capped in the core (#95, #98, #99).** Text is cut to 1,000 characters, a source tag must match Telegram's deep-link pattern, and `email` and `venue_note` are limited to 200 characters in the database. The web chat is rate limited per IP, and `X-Forwarded-For` is trusted only from the local tunnel agent, and only its last entry, since earlier ones can be forged.

**Cut the question that did nothing (#94).** "Would you actually come?" was removed from the flow, the schema, the edit menu and every filter, because nothing used it. Buttons come first and free text second (#13), so answers stay clean.

## Everything else

Smaller decisions, kept so references in code and tests resolve.

- **#1** Audience is interviewers; they must see a proof of concept and a working MVP
- **#2** ~~Real artist~~ superseded by #18
- **#3** Fans enter by clicking a link (story, bio, poster) that opens the chat app
- **#4** The chat channel is a plugin; conversation logic, storage and dashboard don't depend on it
- **#5** Telegram is the first channel
- **#9** Backend is Python
- **#10** The flow is data and the engine is `handle(event) -> list[Reply]`
- **#11** Fan identity is split from channel identity (`fans` + `identities`)
- **#12** Answers kept as append-only history plus a current snapshot on `fans`
- **#13** Buttons first, free text second
- **#14** Dashboard seeded with synthetic fans run through the real engine, labelled as simulated
- **#15** Outbound "notify fans" is a dashboard button
- **#16** Build a second adapter (web simulator) after Telegram to prove the abstraction
- **#17** The ref repo `Aditya26189/WhatsApp-Bot` is reference only (no license file)
- **#18** The artist is a fictional big Indian pop artist and fans are simulated, as a proof of concept
- **#20** Cities: Mumbai, Delhi NCR, Bengaluru, Hyderabad, Pune, Kolkata, Chennai, Ahmedabad, Jaipur, Indore (Jaipur and Indore are the under-explored ones)
- **#21** Budget bands: under ₹1,500 / ₹1,500–3,000 / ₹3,000–6,000 / ₹6,000+
- **#22** Group size: 1 / 2 / 3–5 / 6+
- **#23** ~~Timing question~~ **Removed**: the bot does not ask for show timing (a number is kept so later references stay stable)
- **#24** Venues are proper-noun names with a capacity, no type words (arena, hall, club)
- **#25** Fan picks a venue by name with buttons, replacing the free-text venue area
- **#26** Supabase (hosted Postgres) is the only database
- **#27** "Other / not listed" venue button stores a free-text note beside the row
- **#28** Dashboard is Streamlit, reading the database directly
- **#30** Two separate services: the Telegram webhook (FastAPI) and the Streamlit dashboard, with the database as the only bridge
- **#31** Recommendation logic, no conversion rate yet: demand per venue, expected attendance, suggested venue at 80% fill, city priority with a growth badge
- **#32** Suggested price band is the most common budget band among counted fans; per city since #79
- **#33** Group bucket to people count: 1→1, 2→2, 3–5→4, 6+→6
- **#36** Consent: a short opening message with Count me in / No thanks; `/stop` is named in it, `/delete` and stored-data info are in `/help` and the README
- **#37** Each channel identity counts as its own fan for now (no cross-channel merge)
- **#38** Message drafts #2 to #15 in `docs/message-script.md` stay as drafts until implementation
- **#39** A `venues` table (id, city, name, capacity) is seeded from the venue table
- **#40** Seed simulated fans with an uneven spread across cities and weeks, all flagged `is_simulated` (about 20,000 since #78)
- **#41** Phase 1 is written with a pure decision core, a store interface (Postgres plus in-memory fake) and a separate insights module
- **#42** Hardening is a later phase 6; load tests use Locust
- **#47** Phase 1 logs inbound events in `events` and each turn's replies in `replies`
- **#49** Expected attendance for the suggested venue is measured per city
- **#50** A tie for the most common budget band picks the lower band (more fans can afford it)
- **#51** "Other / not listed" fans count for the city and price band but not for per-venue demand
- **#52** Only fans who reached the done step count in any number
- **#53** MVP outbound is one "show announced in your city" message
- **#54** The Postgres store and the in-memory fake run one shared contract suite from phase 1
- **#55** One engine turn is one transaction: dedupe, identity lock, state, answers and replies commit together
- **#56** Time comes from a clock seam; weeks use IST and timestamps are stored in UTC
- **#57** `core/demand.py` owns the counted-fan rule (#51, #52) and all SQL aggregates (sync, read-only)
- **#59** `core/outbound.py` owns the audience rule and delivery over the `replies` log
- **#60** The dashboard has a password gate and hides emails by default
- **#62** A reset command wipes simulated fans and reseeds, for repeatable demos
- **#63** Settings come from one validated config module, including `ARTIST_NAME` (replaces hard-coded "Artist X")
- **#65** Stack stays Python, FastAPI, Postgres and Streamlit so both services share `core/`
- **#66** Telegram client is plain `httpx`, not python-telegram-bot or aiogram
- **#67** DB driver is psycopg 3 with raw SQL: async pool for the webhook, sync pool for the dashboard
- **#69** Messages are plain text (no MarkdownV2). Announcements are paced to Telegram limits (about 1 message/s per chat, about 30/s overall)
- **#70** A fan counts from the first time they reach done (`fans.completed_at`, set once, never cleared)
- **#71** An engine bug rolls the turn back, returns 200 and sends one apology; a database outage returns 5xx
- **#72** A resend sweeper runs every 30 s and sends `unsent` replies older than 10 s, so delivery is at-least-once
- **#73** The dashboard has a Simulated / Real switch, Simulated by default, never mixed
- **#75** The announcement is sent from a dashboard form
- **#76** `is_simulated` is set only by the seed script, never by the channel
- **#77** The web chat is served at `/chat` by the webhook service and reached through the same ngrok tunnel, so an interviewer can try it on their own device
- **#78** Seed about 20,000 simulated fans: the engine runs in memory, then rows are bulk-copied to Postgres
- **#79** Price band is per city: most common band among the city's counted fans, shown next to the suggested venue
- **#80** The dashboard role stays read-only plus INSERT on `announcement_requests`
- **#81** `/delete` also removes `replies` and the fan's `events`
- **#82** The engine takes a `simulated=True` option from phase 1
- **#83** Web chat has no stable fan id (refresh = new fan)
- **#84** `fans.furthest_step` (never moves back) drives the funnel
- **#85** Growth badges and the announcement audience use counted fans only (`completed_at` set)
- **#86** The webhook returns 200 first, then sends replies in the background, so the ack target excludes Telegram API time
- **#87** The Done message depends on the channel: push channels promise updates, the web chat just thanks the fan
- **#88** A new fan's identity row is inserted and locked first, so two fast first messages never create two fans
- **#90** Telegram updates are deduped on `update_id`
- **#91** A tap on a button that isn't the fan's current step is stale: no state change, and the fan sees "That question has passed"
- **#92** Every tap is answered at once; buttons become "✓ choice" only if the engine applied the tap, and double taps are told from stale taps by a 60 s in-memory window
- **#93** Send errors: 429 waits `retry_after` and resends; 403 opts the fan out and drops their pending replies
- **#94** The "Would you actually come?" interest question is removed everywhere
- **#95** Input caps live in the core: text is cut to 1,000 characters and source tags must match `^[A-Za-z0-9_-]{1,64}$`
- **#98** `fans.venue_note` and `fans.email` are limited to 200 characters in the database
- **#99** The web chat is rate limited per client IP; `X-Forwarded-For` is trusted only from localhost, last entry only
- **#100** The web chat returns replies in the HTTP response; stale `unsent` ones are expired after 10 minutes
- **#101** A new channel may add an adapter, its routes in `api/` and one wiring line, but `core/` and `migrations/` must not change; a test and a CI step enforce it
- **#102** Seeded fans use the channel `seed`: no adapter, never messaged
- **#104** Funnel per view: Real counts live real fans plus `funnel_counts` (deleted fans); Simulated counts live simulated fans only
- **#105** The dashboard role `crowdsense_dashboard` is made by an idempotent script, not a migration, and can only read
- **#106** The dashboard refreshes every 5 s, running all queries in one read-only snapshot transaction
- **#107** The banner shows the view, counted fans (#52) and started fans
- **#108** Supabase's `anon` and `authenticated` roles get no privileges on our tables (`scripts/lock_public_api.py`)
- **#109** An announcement request holds only `city` and `event_date`; the dashboard role can INSERT those and nothing else
- **#110** The audience is one SQL function, `announcement_audience(city)`; the dashboard only gets a count
- **#111** Announcement fan-out goes into `replies`, so the existing sweeper sends it
- **#112** One announcement per city and date (`UNIQUE (city, event_date)`)
- **#113** No `current_date` CHECK on `event_date`; the date picker starts today and a past-date request fans out to zero recipients
- **#114** `/stop` drops the fan's unsent replies, as a 403 already did (#93), so a queued announcement never reaches a fan who opted out after the fan-out
- **#115** Migration 0004 revokes its new table and functions from `anon` and `authenticated` and enables RLS itself, rather than relying on a script being re-run

## Reference data

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

## Parked

WhatsApp, Instagram and Discord adapters (#7). Merging one fan across channels by email (#37). A price demand curve instead of the most common band (#32). Low-data warnings for tiny cities (#74). A local backup database. Hardening is phase 6.
