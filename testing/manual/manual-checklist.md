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

- [x] Bot token and secret only in env; nothing sensitive in the repo.
- [x] ngrok running and webhook registered.
- [x] Tap `t.me/<bot>?start=ig_story`: consent appears with two buttons.
- [x] Finish the whole flow from your phone; buttons render and are tappable.
- [x] Row appears in Supabase with the right values and the `ig_story` source tag.
- [x] Send `/start` with a different tag from a second account; source tag stored per identity.
- [x] Send a photo and a sticker; the bot does not crash.
- [x] Record fixtures from this session and scrub them (see `fixtures/telegram/README.md`).

## Phase 3: Web sim and seed

- [x] Chat in the browser; same questions and same rows as Telegram. (2026-10-16: fan 20004, web_sim, real, completed, 8 replies sent)
- [x] Run the seed; about 20,000 simulated fans exist, all flagged simulated (#78). (Supabase 2026-10-16: 20,000, copy 19.8 s, 71 MB)
- [x] Spot-check 5 seeded fans in the DB: values valid, venue belongs to the city.
- [x] Confirm no seeded fan has an outbound message. (0 replies)

## Phase 4: Dashboard

- [x] Open every view: top cities, price, group size, heatmap, funnel, weekly growth, source, recommendations. (Supabase 2026-10-16: all 10 views and the hero card render)
- [x] Numbers on screen match a hand check on one city. (Mumbai 3,447 = 2,001 + 1,280 + 166 Other)
- [x] "Simulated data" badge appears when simulated data is shown.
- [x] Simulated / Real switch changes the numbers; Real shows only the test accounts. (Real: 2 counted fans)
- [x] Complete a new chat on your phone; after a refresh the dashboard shows the new fan. (2026-10-17: web chat on the phone; Real went 2 → 3 counted fans, new Kolkata fan in Latest fans. Same path measured by script: 0.55 to 4.45 s.)
- [x] Hero recommendation card reads well in plain language.
- [x] Jaipur and Indore show as growing.

## Phase 5: Outbound and end-to-end rehearsal

- [x] Choose a city with at least one real tester; the audience preview shows only eligible fans. (2026-10-17: Delhi NCR, 1 real Telegram tester; web_sim fans in Pune and Kolkata not counted.)
- [x] Press notify; the message arrives on the phone with the city filled in. (2026-10-17: requests for 17, 18 and 19 Oct all arrived; fan-out to sent takes up to about 70 s: 30 s sweep, 10 s message age, 30 s sweep.)
- [ ] Press notify twice quickly; the phone receives it once.
- [x] Send `/stop`, notify again; no message arrives. (2026-10-17: after `/stop` the Delhi NCR count is 0, no new request was queued, no reply created; checked in the DB.)
- [ ] Full rehearsal in order: tap link, chat, dashboard updates, notify, receive, stop. Time it.
- [x] Open `<PUBLIC_URL>/chat` on a phone over mobile data through ngrok and finish the flow; only then share the link with an interviewer (#103, deferred from phase 3). (2026-10-17: done by the user from the phone; server log: 7 `/chat/message` posts, all 200, no errors; one new completed fan in the Real view. Mobile data itself is the user's word, not visible in the log.)
- [x] README states limits (self-selection bias, stated intent vs purchase, simulated data). (2026-10-17: "Limits" section added.)
- [ ] Architecture diagram is current.
