# Design notes

Nine choices where I weighed real options, with the tradeoff each time. The numbers in brackets point to `docs/decisions.md`.

## 1. Postgres, not Mongo or Redis (#26)

Every dashboard view is a `GROUP BY` or a date bucket. In Mongo that becomes aggregation pipelines, which is a second query language for no gain. Redis would hold one row of state per fan and add a second system to run. At tens of thousands of rows any database copes, so I picked on the data model. If I outgrow Supabase, `pg_dump` moves it to any Postgres host.

What I took from it: consent lives in the schema (per identity), answers are timestamped history rather than overwritten fields, and the dashboard never gets write access.

## 2. Save and send in one transaction (#55, #47, #72)

The question: a fan taps a button, the state is saved, and then the Telegram send fails. They see nothing.

- Send first, then save: a crash in between leaves the fan out of step with what we stored.
- Do nothing special: the chat is stuck until the fan types `/start`.
- **Chosen:** save state and replies together, send after commit, and let a sweeper resend anything unsent.

It costs a `replies` table and, rarely, a duplicate message (a crash between send and mark). I first assumed Telegram would retry the webhook and cover this. It doesn't, because we return 200, so the sweeper had to exist.

## 3. A fake store that has to pass the same tests (#54)

There is a Postgres store and an in-memory fake. Nothing proved they behaved the same, so I run one contract suite against both from phase 1. It's cheap now and expensive to discover drift later. It's also what makes the fast tests trustworthy.

## 4. Once counted, always counted (#70)

"Counted" first meant "is on the done step". A returning fan who tapped "Edit city" moved back a step and vanished from every number, so the dashboard flickered mid-demo. The fix is one column, `completed_at`, set once and never cleared. The fan already said they want to come, and one edit doesn't make them a new person. Keeping a staging copy of old answers would have worked too, but it's far too much for an MVP.

## 5. Bugs and outages get different responses (#71)

Telegram retries a failing webhook for hours. If a bug crashes the engine and we return 5xx, the fan gets the same apology on every retry. So a bug rolls the turn back, returns 200 and sends one apology. A database outage still returns 5xx, because nothing was saved and a retry costs nothing.

## 6. Double taps, stale taps and the lost spinner (#90 to #93)

This took the most thinking. A tap can be answered only once, and only the engine knows whether it was stale, so the adapter answers the spinner at once and swaps the button for a ✓ only after the engine applied it. A real double tap looks identical to a tap on an old button, so the webhook remembers the messages it just confirmed for 60 seconds. That is in memory, so a restart in that window costs one extra "That question has passed" message, which I accepted. A 403 (bot blocked) drops the fan's pending replies instead of retrying them forever.

## 7. 20,000 fans, not 1,500 (#78, #82)

My first seed had 1,500 fans. Every city then got its smallest venue as the suggestion, so the recommendation looked broken. I raised it to 20,000 and ran them through the real engine in memory, then bulk-copied the rows to Postgres. That takes about 6 seconds locally. It proves the logic at that size, but it is not a load test, because it skips the webhook and the network. The dashboard keeps simulated and real fans apart, and anyone who chats through the web chat counts as real.

## 8. Locking the database down, not just the app (#108, #109, #115)

Supabase gives its `anon` and `authenticated` roles access to everything with row-level security off, so the public key could read, edit or delete fan data through the REST API. I revoke those roles on every table, sequence and function. A script does it rather than a migration, because the roles only exist on Supabase. The dashboard uses a role that can read, plus insert an announcement request with a city and a date. A migration also closes its own objects, so safety doesn't depend on someone remembering to re-run the script.

## 9. One announcement per city and date (#112)

I considered an idempotency key per send. Instead there is a unique constraint on `(city, event_date)`. The dashboard shows "Already queued" on a duplicate. The downside is that you can't resend a corrected announcement for the same show. I took that to keep the failure mode impossible rather than handled.

## What I measured

A tap took about 1.2 to 1.5 s to reach the next question. I timed each SQL statement and each Telegram call: the engine itself is under a millisecond on local Postgres, and the time goes on round trips to Supabase (about 45 ms each from my laptop) and to Telegram (about 180 ms). Reordering two calls saves about 360 ms. Hosting on Railway in Singapore doesn't remove the database distance.

## What I'd change

- The web chat has no stable fan id, so a refresh is a new fan (#83). It's only the backup channel.
- No minimum-sample handling: a city with three fans gets a recommendation as confident as one with three thousand (#74).
- Stated intent isn't purchase, and only fans who finish the chat are counted. Both overstate demand. The README says so.
