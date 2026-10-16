# Design review log

Why we decided what we decided. Use it to answer "why did you do it this way?"

- Each entry: **Issue** → **Options** → **Chosen** → **Why**.
- Decision numbers (#n) point to `docs/decisions.md`.
- Terms: `CONTEXT.md`.
- Date: 2026-10-16.

## Contents

1. [Database choice](#1-database-choice)
2. [Architecture review findings](#2-architecture-review-findings)
3. [Questions and answers](#3-questions-and-answers)
4. [Stack notes review](#4-stack-notes-review)
5. [Scope decided from the review](#5-scope-decided-from-the-review)
6. [Likely interview questions](#6-likely-interview-questions)
7. [Deferred and still open](#7-deferred-and-still-open)
8. [Full doc scan](#8-full-doc-scan)
9. [Double taps: lessons from established bots](#9-double-taps-lessons-from-established-bots)
10. [Interest question removed](#10-interest-question-removed)
11. [Stale tap: chat message, not a toast](#11-stale-tap-chat-message-not-a-toast)
12. [Blocked bot: delete pending replies](#12-blocked-bot-delete-pending-replies)
13. [Double tap vs stale tap](#13-double-tap-vs-stale-tap)
14. [Phase 2 wrap-up decisions](#14-phase-2-wrap-up-decisions)
15. [Input caps: what and why](#15-input-caps-what-and-why)

---

## 1. Database choice

**Issue:** which database for the MVP (decision #26).

**Options:** Supabase (Postgres), MongoDB, Redis, local Postgres.

**Chosen:** Supabase (Postgres). The 5-advisor council voted 5–0.

**Why:**
- Every dashboard view is a `GROUP BY` or a date bucket. That is relational work.
- MongoDB would turn those into aggregation pipelines: a second codebase.
- Conversation state is one row per fan. Redis adds a second system for no gain.
- At this size (tens of thousands of rows) any database works. The data model matters more than the engine.
- Moving later is easy: `pg_dump` to any Postgres host.

**Warnings the council raised (all handled):**
- Consent is part of the schema → `consent` and `opted_out` per identity (#36).
- Keep answers as timestamped events, not overwritten fields → `answers` table (#12).
- Row-level security leaks are common → bot writes stay server-side, dashboard uses a read-only role.
- Free tier pauses idle projects → local backup DB parked (`docs/decisions.md` §4).

**Council input (reference, not binding):**

- The dashboard is the product; the bot is the intake pipe.
- Unofficial WhatsApp libraries carry ban and terms-of-service risk.
- Before WhatsApp: check if non-whitelisted fans can reach the test number through a link, and start business verification early.
- Consent and opt-out are needed on every channel.

---

## 2. Architecture review findings

Report: `architecture-review-*.html` (temp folder). Seven candidates:

|     | Finding                                                                                          | Verdict                  | Decision      |
| --- | ------------------------------------------------------------------------------------------------ | ------------------------ | ------------- |
| A   | Turn has no defined transaction; locking and inbox come in phase 6                               | **Do now**               | #55, #47, #54 |
| B   | "Counted fan" rules would live in both SQL and Python; 100k fans in Python breaks the 1 s target | **Do now**               | #57           |
| C   | "Steps are data" cannot express branches or "city clears venue"                                  | **Do now**               | #58           |
| D   | Phase 5 sends directly, phase 6 adds an outbox: a rewrite                                        | **Do now** (module only) | #59           |
| E   | Seeding through the real engine gives every fan the same timestamp                               | **Do now**               | #56           |
| F   | Campaigns touch four tables in phase 6                                                           | **Defer**                | #64           |
| G   | `fans` snapshot and `answers` can drift                                                          | **Covered by A**         | #55, #64      |

Missing, not module-shaped:

| Gap                                                      | Verdict | Decision     |
| -------------------------------------------------------- | ------- | ------------ |
| Dashboard access control                                 | Do now  | #60          |
| Glossary                                                 | Do now  | `CONTEXT.md` |
| Failure policy                                           | Do now  | #61, #71     |
| Demo reset command                                       | Do now  | #62          |
| Config module                                            | Do now  | #63          |
| Store contract tests in phase 1                          | Do now  | #54          |
| Timezone (IST)                                           | Do now  | #56          |
| Regional-language text, CSV export, backup restore drill | Defer   | #64          |

---

## 3. Questions and answers

### Q1 · Send fails after the state is saved → #55, #47

- **Issue:** fan taps a button. State is saved. Telegram send fails. Fan sees nothing.
- **Options:**
  1. Save state and replies in one transaction; send after commit; a resend sweeper sends unsent replies (see Q6).
  2. Send first, then save.
  3. Do nothing special.
- **Chosen:** 1.
- **Why:**
  - No lost reply and nothing counted twice.
  - Option 2: a crash between send and save leaves the fan out of step with the saved state.
  - Option 3: the chat is stuck until the fan types `/start`.
- **Cost:** a `replies` table in phase 1. Changes #47 (it used to say inbound events only).
- **Correction (see Q6):** I first said unsent replies go out "on Telegram's retry". That was wrong: our webhook returns 200, so Telegram never retries. The sweeper in #72 fixes it.

### Q2 · Contract tests: phase 1 or phase 6? → #54

- **Issue:** two stores exist (Postgres and an in-memory fake). Nothing proved they behave the same.
- **Chosen:** one shared suite, run on both, from phase 1 (`P1-S01` to `P1-S06`).
- **Why:** it makes the fake a trustworthy second adapter. Cheap now, expensive to find drift later.

### Q3 · Record the stack notes → #65 to #69

- **Issue:** stack choices were only in chat; PLAN still said "SQLAlchemy or psycopg3".
- **Chosen:** record all five.
- **Why:** keeps PLAN and ARCHITECTURE from contradicting each other.
- **Details:** see section 4.

### Q4 · Is an editing fan still counted? → #70

- **Issue:** "counted = reached the done step". A returning fan who taps "Edit city" moves back a step and drops out of every number. Changing city also clears the venue.
- **Options:**
  1. `completed_at` set once; edits never uncount. Venue being re-asked counts for the city only.
  2. Keep "step = done"; numbers dip mid-edit.
  3. Keep old answers counted via a staging copy.
- **Chosen:** 1.
- **Why:**
  - The fan already said they want to come; one edit does not make them a new person.
  - Option 2 makes counts flicker during a demo.
  - Option 3 is too much work for an MVP.
- **Cost:** one nullable column. The counted-fan rule becomes `completed_at IS NOT NULL`.

### Q5 · What happens on an engine error? → #71

- **Issue:** Telegram retries failed webhooks for hours. A crashing bug could send the same apology on every retry.
- **Options:**
  1. Return 200, send one apology, log the error.
  2. Return 5xx so Telegram retries.
  3. Split by cause: DB down = 5xx, bug = 200.
- **Chosen:** 1 for engine errors. DB down still returns 5xx, because there is nothing to save and a retry costs nothing.
- **Why:**
  - Never spams a fan.
  - Errors are visible in logs with a correlation id.
  - The fan simply taps again.
- **Trade-off I flagged:** on a bug, that one tap is lost. Option 3 would have retried it after a short DB blip; you picked the simpler rule.

### Q6 · Who retries an unsent reply? → #72

- **Issue:** Q1 said unsent replies go out on Telegram's retry. But when a send fails, our webhook already returned 200, so Telegram does not retry. The reply would stay `unsent` forever.
- **Options:**
  1. A resend sweeper in the webhook service (every 30 s, resends `unsent` replies older than 10 s).
  2. Retry only when the same fan messages again.
  3. Wait for the phase 6 outbox; until then a failed send is lost.
- **Chosen:** 1.
- **Why:**
  - Makes #55's promise true: no lost replies.
  - About 15 lines, no new infrastructure.
  - Option 2: a fan with a failed reply may wait forever.
  - Option 3: loses replies in phases 2 to 5.
- **Details:**
  - Claims rows with `FOR UPDATE SKIP LOCKED`, so two workers never take the same reply.
  - The 10 s wait avoids racing a send that is still in progress.
  - **Trade-off:** delivery is at-least-once. If the server crashes after Telegram accepts the message but before we mark it `sent`, the fan may get that one reply twice. Accepted: a duplicate is better than a lost reply.
  - The phase 6 outbox replaces the sweeper.
- **Tests:** `P1-S07`, `P2-C07`, `P2-C08`.

### Q7 · What does the dashboard show by default? → #73

- **Issue:** about 1,500 simulated fans but only about 9 to 10 real testers. Mixed together, the real ones vanish. Real only looks empty.
- **Options:**
  1. Everything together, with a "92% simulated" banner and a toggle.
  2. Simulated by default, real in a separate view.
  3. Real by default.
- **Chosen:** your variant of 2. Default **Simulated**, a switch to **Real**, never mixed.
- **Why:**
  - Honest: nobody mistakes made-up fans for real ones.
  - The simulated view has enough data to show every chart and recommendation.
  - The real view proves the live path: your testers' own Telegram taps appear on the dashboard.
- **Details:** a banner always shows the view and its fan count. Your 9 to 10 testers use their own Telegram accounts; one person with two accounts counts twice (#37).

### Q8 · Tiny data in the Real view → #74

- **Issue:** about 10 testers across 10 cities means most cities have 0 or 1 fans. A recommendation or "growing" badge from one person means little.
- **Options:**
  1. Show everything, add "n = X" and grey out "low data" under 10 fans.
  2. Hide recommendations below 10 fans.
  3. No special handling.
- **Chosen:** 3. Show the numbers as computed.
- **Why:** this is a proof of concept. The goal is to show the pipeline working end to end, and hiding or greying numbers would make the live test look empty.
- **Kept:** the banner still shows the view's fan count (#73), and the PRD limits note says results come from self-selected fans.
- **Parked:** low-data warnings (`docs/decisions.md` §4).

### Q9 · How does the artist send the announcement? → #75

- **Issue:** the text is "Artist X is coming to {city}. Tickets open {date}." Something has to supply the city and the date.
- **Options:**
  1. Form: city dropdown, date picker, live preview, recipient count, confirm button.
  2. One fixed "Notify fans" button per city.
  3. Free-text box.
- **Chosen:** 1.
- **Why:**
  - Preview and count make the demo clear.
  - The count shows opt-out and the real/simulated rules at work (same audience rule as #59).
  - Option 2 cannot show choosing a date. Option 3 skips the template and could say anything.
- **Tests:** `P5-U07` to `P5-U09`.

### Q10 · Is a web-chat fan real or simulated? → #76

- **Issue:** the web chat creates the 1,500 made-up fans and is also the backup demo. An interviewer typing into it is a real person.
- **Options:**
  1. Only the seed script marks fans simulated.
  2. Everything on the web chat is simulated.
  3. Ask "Is this a test?" at the start.
- **Chosen:** 1.
- **Why:**
  - "Simulated" means made-up people, not a type of chat window.
  - A live interviewer shows up in the Real view.
  - The web chat works as a true backup for the Telegram flow.
  - Option 3 adds a question that people answer inconsistently.
- **Side effect:** the web chat may not support push, so announcements skip those fans and show how many (`P5-C06`).
- **Test:** `P3-C08`.

### Q11 · Where does the web chat run in the demo? → #77

- **Issue:** everything runs on the laptop (#29). An interviewer who wants to try the web chat on their own phone needs a public link.
- **Options:**
  1. Serve `/chat` from the webhook service and share the same ngrok link.
  2. Laptop only; you type, they watch.
  3. Deploy to Railway or Render first.
- **Chosen:** 1.
- **Why:**
  - Nothing new to host; the ngrok tunnel already exists for Telegram.
  - The interviewer can try it themselves.
  - Option 3 costs about $5 to $7 a month and adds setup that #29 deferred.
- **Costs:**
  - The laptop must stay on and online. Fallback: screen recording.
  - A public link needs a per-IP rate limit.
- **Test:** `phase-3` manual check on a second device.

---

## 4. Stack notes review

Decisions #65 to #69. Your notes were mostly right; these are the catches.

- **Sync vs async**
  - Issue: FastAPI is async, Streamlit is sync; one async store breaks "share `core/`"
  - Fix: Async conversation store for the webhook; sync read-only `demand.py` for the dashboard
  - Decision: #57, #67
- **In-memory fake cannot run SQL aggregates**
  - Issue: Counted-fan rules would be written twice and drift
  - Fix: Test aggregates on real Postgres only; the fake covers the conversation turn
  - Decision: #57
- **Supabase direct connection is IPv6-only on the free tier**
  - Issue: Migrations fail on a laptop without IPv6
  - Fix: Session pooler (port 5432) for migrations
  - Decision: #67
- **Transaction pooler and prepared statements**
  - Issue: Errors with psycopg defaults
  - Fix: `prepare_threshold=None`
  - Decision: #67
- **One DB layer**
  - Issue: PLAN said "SQLAlchemy 2.0 or psycopg3"
  - Fix: psycopg 3 with raw SQL
  - Decision: #67
- **Webhook secret**
  - Issue: Not wired in
  - Fix: `secret_token` on `setWebhook`; check the header
  - Decision: #66
- **Telegram rate limits**
  - Issue: Announcements could be throttled
  - Fix: Pace to ~1 msg/s per chat, ~30/s overall
  - Decision: #69
- **Message formatting**
  - Issue: MarkdownV2 needs heavy escaping
  - Fix: Plain text
  - Decision: #69

Why plain `httpx` instead of a Telegram framework (#66): frameworks own the update loop and routing, which works against the adapter design. We need four API calls: `setWebhook`, `sendMessage`, `answerCallbackQuery`, `editMessageReplyMarkup`.

Why no Next.js (#65): a second language and an API layer just for looks. Backend depth is what gets judged (#6).

---

## 5. Scope decided from the review

| #   | Decision                                                                   | Issue it fixes                             | Why                                           |
| --- | -------------------------------------------------------------------------- | ------------------------------------------ | --------------------------------------------- |
| 54  | Contract tests from phase 1                                                | Two stores, no proof they agree            | Fake becomes trustworthy                      |
| 55  | One transaction per turn                                                   | Half-saved turns, double taps              | Locality: retries and races in one place      |
| 56  | Clock seam; IST weeks                                                      | Seed fans all have one timestamp           | Growth story producible and testable          |
| 57  | `demand.py` owns counted-fan rule + SQL aggregates                         | Rules in two places; slow at 100k          | One definition; dashboard stays fast          |
| 58  | Flow holds transitions and invalidations                                   | Rules hide in engine code                  | Flow versioning covers them                   |
| 59  | `outbound.py` in phase 5                                                   | Direct send then outbox = rewrite          | Phase 6 swaps the drain, not the callers      |
| 60  | Dashboard password; emails hidden                                          | Fan emails visible to anyone with the link | Basic privacy                                 |
| 61  | Failure policy in docs/architecture.md §5                                  | Unclear behaviour on errors                | One written rule per failure                  |
| 62  | Reset command                                                              | Demos must be repeatable                   | Safe wipe of simulated fans                   |
| 63  | Config module, `ARTIST_NAME`                                               | Hard-coded "Artist X"                      | Fail fast; one place                          |
| 64  | Deferred: campaigns, single answer writer, localisation, CSV, backup drill | Not needed for MVP                         | Adding a column with a default later is cheap |
| 70  | `completed_at`, edits never uncount                                        | Numbers dip during edits                   | Q4                                            |
| 71  | Engine error → 200 + one apology                                           | Retry spam                                 | Q5                                            |
| 72  | Resend sweeper for `unsent` replies                                        | Telegram never retries after our 200       | Q6                                            |
| 73  | Simulated / Real switch, never mixed                                       | 1,500 simulated would drown 10 real        | Q7                                            |
| 74  | No minimum-sample handling                                                 | PoC; keep the live test visible            | Q8                                            |
| 75  | Announcement form with preview and recipient count                         | Date and city must come from somewhere     | Q9                                            |
| 76  | `is_simulated` set only by the seed script                                 | Web chat used by both seed and humans      | Q10                                           |
| 77  | `/chat` via the same ngrok link                                            | Interviewer may want to try it             | Q11                                           |

---

## 6. Likely interview questions

**Why Telegram and not WhatsApp?**
- Telegram needs no business verification or paid templates.
- The channel is a plugin (#4); a web simulator proves it (#16).
- WhatsApp is parked with its blockers listed (`docs/architecture.md` §8, `docs/decisions.md` §5).

**Why Postgres, not MongoDB?**
- Every view is an aggregate over fixed fields. See section 1.

**What if the same message arrives twice?**
- Unique key on `(channel, external_msg_id)`; duplicate is skipped; unsent replies are still sent (#55).

**What if the server crashes mid-turn?**
- The turn is one transaction: all saved or nothing (#55).

**What if Telegram is down when we reply?**
- Reply stays `unsent`; the resend sweeper sends it within about 40 s. At-least-once, so rarely a duplicate (#55, #72).

**What if there is a bug in the engine?**
- Rolled back, one apology, error logged, no retry loop (#71).

**How do you know your numbers are right?**
- Counted-fan rule lives in one module (#57); fan edits never uncount (#70); seeded test cases in `testing/scenarios/insights_cases.yaml`.

**How do you handle privacy?**
- Consent first, `/stop`, `/delete` (keeps only an anonymous funnel count), no phone numbers, dashboard password (#36, #45, #60).

**Is the data real?**
- No. Simulated fans are flagged and never messaged. Self-selection bias and intent ≠ purchase are stated limits (`docs/prd.md` §7).

**How would it scale?**
- `docs/metrics.md` "Scale path": indexes and views, worker pool, read replica, row-level security, partitions.

**How do you test it?**
- Unit, component, contract (both stores), property, load, chaos. See `testing/`.

---

## 7. Deferred and still open

Deferred (#64):
- Campaign table (phase 6)
- Regional-language message text
- CSV export
- Backup restore drill

Still open:
- Extra announcement types (early-bird, group discount, reminder): decide in phase 6 (#53).
- Backup database: sync by dump or by seed only (`docs/decisions.md` §4).
- Low-data warnings (#74)
- Price-band demand curve (`docs/decisions.md` §4).
- Research questions 5.2 to 5.6 (`docs/decisions.md` §5).

---

## 8. Full doc scan

Scanned every doc, test phase and scenario on 2026-10-16. Decisions #78 to #87.

### Must-fix issues

- **#M1** 1,500 fans ≈ 3,800 people over 10 cities, so every city got its smallest venue at 2–20% fill. Recommendations never varied · _Fix: Seed ~20,000 fans: engine in memory, then bulk copy_ · _Decision: #78_
- **#M2** #32 said price band per venue; #51 and the test data needed per city · _Fix: Per city_ · _Decision: #79_
- **#M3** Dashboard was read-only but had to send announcements · _Fix: Dashboard inserts an `announcement_requests` row; webhook service sends_ · _Decision: #80_
- **#M4** `/delete` left `replies`; the delete confirmation would be saved against a deleted fan · _Fix: Delete `replies`; send the confirmation without saving it_ · _Decision: #81_
- **#M5** New-fan race: two quick taps both create the identity · _Fix: Create identity with `ON CONFLICT DO NOTHING`, then lock it; the second message waits_ · _Decision: #88_
- **#M6** Seed had no way to mark fans simulated without an engine change in phase 3 · _Fix: Engine option `simulated=True` from phase 1_ · _Decision: #82_
- **#M7** Web chat has no stable fan id; refresh = new fan · _Fix: Known limit, parked: Telegram is the main channel_ · _Decision: #83_
- **#M8** Funnel used the current step, so an editing fan looked unfinished · _Fix: `furthest_step`; completed = `completed_at`_ · _Decision: #84_

### Contradictions fixed

- `delete_command.yaml` kept events → now deleted (#81).
- `happy_path_pune.yaml` had consent on `fans` → moved to `identities`.
- `P1-C13` named a missing `skip_email` scenario → `email_validation`.
- Growth counted unfinished fans → counted fans by `completed_at` (#85).
- Announcement audience included unfinished fans → counted fans only (#85).
- Replies were sent inside the request → return 200 first, then send (#86).
- Done message promised updates to web chat fans → text depends on channel (#87).

### Stale text fixed

- #28, phase 4 build step 1: dashboard reads through `demand.py`.
- docs/architecture.md §10 #7: secret check is already phase 2.
- Phase 1 build step 6 and exit rows.
- Coverage: 85% everywhere.
- `traceability.md`: rows for #47 to #85; A1–A10 marked confirmed.
- NFR availability: applies only once cloud hosted.
- PRD success: phase 6 numbers are after the MVP.
- #18: web chat users are real too.
- Practical: run the reset on demo day, since seeded dates are relative to seed time.

### Is 20,000 seeded fans too bulky?

- Rough size: 20,000 fans × ~7 answers ≈ 140,000 `answers` rows and as many `events`. About 60–100 MB with indexes. Supabase free tier allows 500 MB. Fits.
- Seeded fans are never messaged, so they add no `replies`.
- Dashboard target is p95 < 1 s at 100k fans, so 20k is well inside.

### Does seeding 20,000 prove we can handle that many requests?

- **No.** The seed runs the engine in memory and bulk-copies rows. It skips the webhook, the network and per-message database transactions.
- It proves the **logic** handles 20,000 conversations correctly and the **dashboard** stays fast with that much data.
- Proving **request handling** is the phase 6 load test: Locust sends fake Telegram updates to the real webhook (spike 50 msg/s, soak 10 msg/s).

### M6 in simple terms

- Seeded fans must be marked "made-up". Only the seed script may set that mark (#76).
- But fans are created inside the engine, and the engine had no way to be told "this one is made-up".
- Phase 3 forbids changing the engine (that phase proves the design is finished).
- So the engine gets a switch, `simulated=True`, from day one. The seed turns it on; Telegram and the web chat never do.

### M5 in simple terms

- A brand-new person taps two buttons very fast; two messages arrive at almost the same moment.
- Both ask "do I know this person?", both get "no", both try to create them. The database allows only one, so the second failed and the fan saw "Something went wrong".
- Cause: the "one at a time" lock was taken after the person was created, too late.
- Fix (#88): the first message creates the person and locks them; the second sees they exist and waits its turn. Both are handled in order, no error. Test `P1-S08`.

### Metrics file

- Load, scale and bot-strength numbers live in `docs/metrics.md` (#89): what each proof shows, targets, how measured, results after measuring, and interview one-liners.
- Key distinction kept there: the 20k seed proves **logic correctness** and **dashboard speed**; the phase 6 Locust run proves **requests per second**.

---

## 9. Double taps: lessons from established bots

Researched 2026-10-16. Decisions #90 to #93. Fan-facing rules: `docs/message-script.md` §2.

### What others do

| Platform                | Approach                                                                                     | We match it with                                    |
| ----------------------- | -------------------------------------------------------------------------------------------- | --------------------------------------------------- |
| Rasa                    | One lock per conversation; messages handled in order; shared lock across servers             | Identity row lock in Postgres (#88)                 |
| Slack                   | Dedupe on `event_id`; ack within 3 s, process in background                                  | `(channel, external_msg_id)` (#55); ack first (#86) |
| WhatsApp                | At-least-once delivery; dedupe on message id; ack first                                      | Same as above                                       |
| Stripe                  | Idempotency key: first result stored and replayed; concurrent repeat → 409                   | Duplicate skipped, unsent replies resent (#55)      |
| Microsoft Bot Framework | Optimistic locking (ETag, 412 → re-read and retry)                                           | We lock instead (simpler at our scale)              |
| Telegram                | Spinner shows until `answerCallbackQuery`; slow bots get repeat taps; button data ≤ 64 bytes | #92, #91                                            |

### What we added, in simple terms

- **L1 · Receipt number (#90).** Every Telegram message and tap gets an `update_id`, never reused. A repeat with the same number is ignored. Before, button taps had no reliable id.
- **L2 · Buttons know their question (#91).** A button carries "city:Pune", not just "Pune". If the fan taps a button from an older question, the bot sends a chat message (not a toast, see §11) saying "That question has passed" and changes nothing.
- **L3 · Buttons vanish after a tap (#92).** The spinner stops at once and the buttons become "✓ Pune", so there is nothing left to tap twice.
- **Extra · Telegram errors (#93).** 429 "too many requests" → wait the time Telegram gives, then resend. 403 "bot blocked" → stop messaging that fan.

### Four layers, outside in

1. Buttons disappear after a tap (#92) → the fan can't tap twice.
2. Same `update_id` skipped (#90) → Telegram's duplicate deliveries.
3. One message at a time per fan (#88) → two messages at the same instant.
4. Step tag check (#91) → old buttons from earlier in the chat.

Interview line: "Four layers stop double taps: the UI removes buttons, the platform id dedupes, a per-fan lock serialises, and a step tag rejects stale taps."

### Sources

- Rasa lock stores: https://rasa.com/docs/rasa/lock-stores
- Slack retries: https://hookdeck.com/webhooks/skills/slack-webhooks
- WhatsApp idempotency: https://www.ycloud.com/blog/whatsapp-webhook-reliability-retries-idempotency
- Stripe idempotent requests: https://docs.stripe.com/api/idempotent_requests
- Bot Framework concurrency: https://learn.microsoft.com/en-us/answers/questions/5637145/step-repeating-in-bot-on-randomly-production-not-e
- Telegram callback queries: https://docs.aiogram.dev/uk-ua/latest/api/methods/answer_callback_query.html

---

## 10. Interest question removed

Decision #94. Supersedes #34 and #35.

- **Issue:** the bot asked "Would you actually come?" (Definitely / Probably / Just curious). The answer was stored but no number used it.
- **Options:**
  1. Keep it and add an interest split chart to the dashboard.
  2. Keep it parked for a future filter.
  3. Remove it everywhere.
- **Chosen:** 3.
- **Why:**
  - It serves no purpose today and one fewer question means one fewer tap per fan.
  - Collecting data nothing uses is hard to defend under DPDP-style data-minimisation.
  - The "excluding low-interest fans" filter was never built and is dropped.
- **Numbers kept:** #34 and #35 stay in `decisions.md`, struck through, because code and tests cite them. Message script row #9 is marked removed, like timing (#8).
- **Still to do (code, not docs):** remove the step, field and tests; drop the `interest` column. See "Interest removal" steps in the conversation plan: `core/catalog.py`, `flow.py`, `types.py`, `store*.py`, `migrations/0001`, the `tests/` files and the YAML scenarios `happy_path_pune`, `returning_fan_edit`, `insights_cases`.
- **Left alone:** the English word "interest" in the PRD ("measure interest before booking venues").

---

## 11. Stale tap: chat message, not a toast

Raised by the phase 2 build chat on 2026-10-16. Clarifies #91 and #92 in place (no new number).

- **Issue:** `P2-C10` said a stale tap shows a "That question has passed" toast, but #92 says answer the tap first. A tap can be answered only once, and only the engine knows a tap is stale, so both could not hold.
- **Options:**
  1. Answer first with no text; the stale reply is a normal chat message.
  2. Run the engine first, then answer with the toast text.
- **Chosen:** 1.
- **Why:**
  - Keeps the spinner stopping at once, which is what stops fans double-tapping (#92).
  - Option 2 makes the spinner wait for the whole turn (about 50 to 300 ms, more over Supabase).
  - Cost: one extra line in the chat for a stale tap.
- **Also decided:** the buttons become "✓ <choice>" only when the engine applied the tap. A stale tap leaves them alone, so a fast tap on a different button never shows a wrong ✓.
- **Docs updated:** #91, #92, `docs/architecture.md` §3 and §5, `docs/message-script.md` (row #16 and the cheat sheet), tests `P2-C09`, `P2-C10`, `P2-C11`.

---

## 12. Blocked bot: delete pending replies

Raised by the phase 2 build chat on 2026-10-16. Clarifies #93 in place (no new number).

- **Issue:** when a fan blocks the bot, Telegram answers every send with 403. Their pending `unsent` replies would be retried by the sweeper forever.
- **Options:**
  1. Delete those rows in the same transaction that marks the identity opted out.
  2. Add a `dropped` status (needs `0003` to widen the status CHECK) and mark them.
- **Chosen:** 1.
- **Why:**
  - An undeliverable reply is not worth storing (same reasoning as #81).
  - No extra schema change in migration `0003`.
  - The fact is still recorded: the opted-out flag, plus a log line with the number of replies dropped.
- **Cost:** no audit trail of dropped replies. The "lost replies = 0" metric means lost by a bug, so a deliberate drop does not break it.
- **Docs updated:** #93, `docs/architecture.md` §5 failures, `docs/message-script.md` cheat sheet, test `P2-C13`.

---

## 13. Double tap vs stale tap

Raised by the phase 2 build chat on 2026-10-16. Clarifies #92 in place (no new number).

- **Issue:** the engine treats the second tap of a double tap as a stale tap and replies "That question has passed", which is right for an old button (`P2-C10`) but not for a double tap (`P2-C09` wants nothing extra). The core cannot tell them apart.
- **Options:**
  1. The webhook remembers, in process memory for 60 s, the messages it just confirmed with "✓". A stale tap on one of them is a double tap; its stale reply is marked sent and not delivered. About 20 lines, no core change.
  2. Accept the extra message and relax `P2-C09`.
- **Chosen:** 1.
- **Why:**
  - A confirmed message has no buttons left, so any tap on it in that window is a repeat.
  - A clean double tap is the point of #91 and #92.
  - Single process on a laptop, so in-memory state is enough.
- **Cost:** after a restart inside the 60 s window, one extra "passed" message. Accepted.
- **Docs updated:** #92, `docs/architecture.md` §3 and §5, `docs/message-script.md` cheat sheet, tests `P2-C09` and new `P2-C17`.

---

## 14. Phase 2 wrap-up decisions

From the phase 2 build report, 2026-10-16.

- **Missing recordings (#96):** sticker and group updates were never recorded. Decision: leave them. A sticker takes the same "no text" path as the photo; the group and `/help@bot` cases are derived from recorded fixtures.
- **Database port (#97):** the webhook uses the session pooler (5432) for now; move to the transaction pooler (6543) in the last phase.
  - **Is it safe to switch later?** Checked on Supabase with every write rolled back. On both ports: the pool opens, 8 repeated queries work (`prepare_threshold=None`), `FOR UPDATE SKIP LOCKED` skips a row held by another transaction, and `INSERT ... ON CONFLICT` plus `SELECT ... FOR UPDATE` works in one transaction. The code uses no session-level features (no advisory locks, `SET`, `LISTEN`, temp tables).
  - **What the switch needs:** change `DATABASE_URL`, and keep migrations on 5432 through an optional `MIGRATION_DATABASE_URL` (Alembic does DDL and must not go through the transaction pooler).
- **Latency numbers:** the Supabase per-turn estimate (about 180 ms) stays an estimate until measured live. Test later.
- **Open:** the 200-character cap on `venue_note` and `email` (see the conversation) and the 503 that Telegram reported on a real message.

---

## 15. Input caps: what and why

Decisions #95 and #98. A security and scaling measure.

**What we limit:**

- **Message text: 1,000 characters.** Cut by the engine before it is saved or decided on.
- **`source_tag`: 64 characters, letters, digits, `_` and `-` only.** Anything else is stored as "no tag" and the fan still gets in.
- **`venue_note` and `email`: 200 characters.** Enforced by the database (migration 0003), as a last line of defence.

**Why (security):**

- Anyone can type anything. Telegram allows 4,096 characters per message, and the phase 3 web chat has no limit at all.
- The source tag is shown on the dashboard. The strict alphabet keeps `<script>` or junk out of it.
- The database limit still holds if a code bug lets long text through.

**Why (scaling):**

- Unlimited text lets one person bloat the database and slow every dashboard query.
- With caps, row sizes are bounded, so storage and query cost per fan stay predictable. About 20,000 fans fit the free tier (see `docs/metrics.md`).

**Why in the core and the database, not in each channel:**

- Every channel gets the same limits, including the web chat in phase 3.
- Phase 3 may not change `core/` or the schema (Q-15), so the caps had to land in phase 2.

**Why 200 for `venue_note` and `email` (#98):**

- Real emails are under 100 characters. The technical maximum is 254.
- 200 matches the flow's own validators, so the database never rejects something the flow accepted.
- Raising email to 254 would need another migration and protects almost nobody.

**Tests:** `P2-C14` (oversized message), `P2-C15` (database limits), `P2-C16` (the migration on a database with rows), `P2-U12` (source tag).

