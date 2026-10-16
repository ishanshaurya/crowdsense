# Manual checklist

One checklist, sections per phase (phases 1 to 5). Tick when done; note anything odd. Phase 6 has no manual section, its tests are automated.

## Phase 1: Core (REPL)

- [ ] Run a dev REPL against the engine and play the whole flow as a new fan.
- [ ] Wording of each message reads clearly and short, in the update-style tone (drafts #2 to #15 refined with the user).
- [ ] "No thanks" ends politely and asks nothing more.
- [ ] `/stop`, `/delete`, `/help` all answer sensibly at any step.
- [ ] Coming back as a returning fan shows the edit menu; edits work.
- [ ] Nothing asks about show timing.

## Phase 2: Telegram (real phone)

- [ ] Bot token and secret only in env; nothing sensitive in the repo.
- [ ] ngrok running and webhook registered.
- [ ] Tap `t.me/<bot>?start=ig_story`: consent appears with two buttons.
- [ ] Finish the whole flow from your phone; buttons render and are tappable.
- [ ] Row appears in Supabase with the right values and the `ig_story` source tag.
- [ ] Send `/start` with a different tag from a second account; source tag stored per identity.
- [ ] Send a photo and a sticker; the bot does not crash.
- [ ] Record fixtures from this session and scrub them (see `fixtures/telegram/README.md`).

## Phase 3: Web sim and seed

- [ ] Chat in the browser; same questions and same rows as Telegram.
- [ ] Run the seed; about 1,500 simulated fans exist, all flagged simulated.
- [ ] Spot-check 5 seeded fans in the DB: values valid, venue belongs to the city.
- [ ] Confirm no seeded fan has an outbound message.

## Phase 4: Dashboard

- [ ] Open every view: top cities, price, group size, heatmap, funnel, weekly growth, source, recommendations.
- [ ] Numbers on screen match a hand check on one city.
- [ ] "Simulated data" badge appears when simulated data is shown.
- [ ] Real vs simulated filter changes the numbers correctly.
- [ ] Complete a new chat on your phone; after a refresh the dashboard shows the new fan.
- [ ] Hero recommendation card reads well in plain language.
- [ ] Jaipur and Indore show as growing.

## Phase 5: Outbound and end-to-end rehearsal

- [ ] Choose a city with at least one real tester; the audience preview shows only eligible fans.
- [ ] Press notify; the message arrives on the phone with the city filled in.
- [ ] Press notify twice quickly; the phone receives it once.
- [ ] Send `/stop`, notify again; no message arrives.
- [ ] Full rehearsal in order: tap link, chat, dashboard updates, notify, receive, stop. Time it.
- [ ] README states limits (self-selection bias, stated intent vs purchase, simulated data).
- [ ] Architecture diagram is current.
