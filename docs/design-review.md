# Design review

Nine places where I had real options and had to pick one. Each section starts with the problem, then the decision with the plainest reason I have, then the details.

## 1. Database

The dashboard needs counts by city, by week, by answer.

**Decision:** Postgres, because every view is a `GROUP BY` or a date bucket and SQL does that natively.

Mongo would turn the same views into aggregation pipelines, a second query language for no gain. Redis would hold one row of state per fan and add another system to run. At tens of thousands of rows any of them copes, so I picked on the data model. Consent lives in the schema per identity, answers are timestamped history instead of overwritten fields, and the dashboard never gets write access. If Supabase stops fitting, `pg_dump` moves everything to any Postgres host.

## 2. Saving and sending

A fan taps a button, the state is saved, and the Telegram send fails. They see nothing.

**Decision:** save the state and the replies in one transaction, send after commit, and let a sweeper resend anything unsent. It's the only option where a crash can't leave the fan out of step.

Sending first and saving second breaks on a crash in between. Doing nothing leaves the chat stuck until the fan types `/start`. The price is a `replies` table and, rarely, a duplicate message when a crash lands between send and mark. I first assumed Telegram would retry the webhook and cover this. It doesn't, because we return 200, so the sweeper had to exist.

## 3. Testing the store

There is a Postgres store and an in-memory fake, and nothing proved they behave the same.

**Decision:** one contract suite runs against both from phase 1, because drift is cheap to catch early and painful to find late.

It also makes the fast in-memory tests worth trusting.

## 4. Who counts as a fan

"Counted" first meant "is on the done step". A returning fan who tapped "Edit city" moved back a step and vanished from every number, so the dashboard flickered mid-demo.

**Decision:** one column, `completed_at`, set once and never cleared. The fan already said they want to come, and one edit doesn't make them a new person.

I could have kept a staging copy of old answers. It would work, but it's far too much for an MVP.

## 5. Bugs versus outages

Telegram retries a failing webhook for hours. If a bug crashes the engine and we return 5xx, the fan gets the same apology on every retry.

**Decision:** a bug rolls the turn back, returns 200 and sends one apology. A database outage still returns 5xx, since nothing was saved and a retry costs nothing.

## 6. Double taps and stale buttons

This took the most thinking. A tap can be answered only once, and only the engine knows whether it was stale.

**Decision:** the adapter answers the spinner immediately, then swaps the button for a ✓ after the engine applied the tap. Fast feedback matters more than perfect accuracy on the spinner.

A real double tap looks identical to a tap on an old button, so the webhook remembers the messages it just confirmed for 60 seconds. That memory lives in the process. A restart inside the window costs one extra "That question has passed" message, which I accepted. A 403 means the fan blocked the bot, so their pending replies get dropped instead of retried forever.

## 7. Seed size

My first seed had 1,500 fans, and every city got its smallest venue as the suggestion. The recommendation looked broken.

**Decision:** 20,000 fans, because that's enough for each city to have a real spread.

They run through the real engine in memory and get bulk-copied to Postgres, about 6 seconds locally. It proves the logic at that size but it isn't a load test, since it skips the webhook and the network. The dashboard keeps simulated and real fans apart, and anyone who chats through the web chat counts as real.

## 8. Database permissions

Supabase gives its `anon` and `authenticated` roles access to everything when row-level security is off. The public key could read, edit or delete fan data through the REST API.

**Decision:** revoke both roles on every table, sequence and function, so a leaked public key reaches nothing.

A script does the revoking, not a migration, because those roles only exist on Supabase. The dashboard connects as a role that can read and insert an announcement request (a city and a date). Each migration also closes its own new objects, so safety doesn't hang on someone remembering to re-run the script.

## 9. Duplicate announcements

Two people could queue the same announcement for the same show.

**Decision:** a unique constraint on `(city, event_date)`. It's the simplest way to make the duplicate impossible.

I considered an idempotency key per send. The dashboard shows "Already queued" on a duplicate. The downside is that you can't resend a corrected announcement for the same show, and I took that to keep the failure from ever happening.

## What I measured

A tap took about 1.2 to 1.5 s to reach the next question. I timed each SQL statement and each Telegram call. The engine itself runs under a millisecond on local Postgres. The time goes on round trips to Supabase (about 45 ms each from my laptop) and to Telegram (about 180 ms). Reordering two calls saves roughly 360 ms. Hosting on Railway in Singapore doesn't remove the distance to the database.

## What I'd change

The web chat has no stable fan id, so a refresh makes a new fan. It's only the backup channel, so it stayed.

A city with three fans gets a recommendation as confident as one with three thousand. There is no minimum-sample handling yet.

Stated intent isn't a purchase, and only fans who finish the chat are counted. Both overstate demand, and the README says so.
