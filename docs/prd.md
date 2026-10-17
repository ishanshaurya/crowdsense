# PRD: Crowdsense

What we build and why. How: `docs/architecture.md`. Key choices: `docs/decisions.md`; the tradeoffs behind them: `docs/design-review.md`.

## 1. Problem

Before booking a venue, an artist's team has to guess which city wants a show, how big the room should be, and what a ticket can cost. The usual inputs are social media follows, the last tour, and gut feel. None of them shows that anyone would actually buy, so every booking is a bet.

Crowdsense replaces the guess with a chat bot that asks fans a few structured questions, and a dashboard that turns the answers into demand by city, a suggested venue and a price band.

## 2. Users

**The artist or management team** wants to find the strong and under-explored cities before spending on a venue, estimate attendance, and know what price range fans accept. Today there is no reliable regional data, and marketing money goes out with unclear return.

**Fans** want a simple way to say "I'd come to a show near me" and to hear first when tickets launch. Without that they miss launches or hear about shows late.

## 3. Value

For the artist, fan chats become demand data before any money is spent. For the fan, it is one tap in a chat app, then a message when the show is announced.

## 4. Features

### Bot: intake

Fan clicks a link (story, bio, poster). The chat app opens. The bot asks:

1. Consent to get updates
2. City (10 fixed cities)
3. Venue in that city (or "Other / not listed")
4. Ticket budget band
5. Group size
6. Email (optional)

Fan commands: `/stop`, `/delete`, `/help`.

Returning fans can edit any answer.

### Bot: outbound

- One "show announced in your city" message, sent from a dashboard form: pick a city and a ticket-open date, see a preview and the recipient count, then confirm.
- Goes only to fans who consented and did not opt out.

### Dashboard: insights

- Top cities and top venues
- Price (budget band) distribution
- Group size distribution
- City × venue heatmap
- Response funnel
- Growth per city per week
- Source breakdown (story, bio, poster)

### Dashboard: recommendations

- Suggested venue per city
- Suggested price band
- City priority, with a "growing" badge

Rules: `docs/decisions.md` #31 to #34, #49 to #52.

## 5. MVP scope

The MVP is a proof of concept for interviewers (#1).

In scope:
- Telegram as the only live channel (#5)
- Web chat simulator as a second channel (#16); backup only, Telegram is the main channel (#83)
- Simulated artist and ~20,000 simulated fans, labelled "simulated" (#18, #78)
- Real fans: about 9 to 10 testers on their own Telegram accounts, shown separately from the simulated ones
- Everything above in section 4

Changed from the original idea:

| Original                      | MVP                            | Why                                           |
| ----------------------------- | ------------------------------ | --------------------------------------------- |
| WhatsApp bot                  | Telegram first, WhatsApp later | No Meta verification or templates needed (#5) |
| Real artist                   | Simulated artist               | Proof of concept (#18)                        |
| Free-text venue area          | Venue buttons per city         | Clean data (#25)                              |
| Show timing / preferred dates | Not asked                      | Removed (#23)                                 |

Out of scope (later):
- WhatsApp, Instagram, Discord (#7)
- Early-bird offers, group discounts, reminders (decide in phase 6)
- Campaign conversion metrics (needs ticket sales data)
- Many artists at once (hardening adds campaigns)
- Merging one fan across channels (#37)

## 6. Success

- A real phone completes the flow from a link.
- The answer shows on the dashboard within seconds.
- Each city gets a venue, price band and priority.
- Outbound message reaches opted-in testers only.
- After the MVP (phase 6): measured numbers meet the targets in `docs/architecture.md` §11.

## 7. Known limits

- Fans who reply are self-selected, not a fair sample.
- Stated intent is not a ticket purchase.
- Simulated data shows the system works, not real demand.

## 8. Status and roadmap

Built, tested and tagged:

1. The core: conversation flow as data, the engine, and a Postgres store and in-memory fake that pass the same tests.
2. The Telegram adapter, with a webhook, inline buttons, deep-link source tags and a resend sweeper.
3. A web chat on the same engine, plus a 20,000-fan seed. Its job is to show a channel can plug in without touching `core/`.
4. The dashboard: live funnel, demand, venue, price band and city recommendations, with a Simulated / Real switch.
5. Outbound announcements to the fans in a city, sent from a dashboard form. The app is also hosted on Railway.

Next is phase 6, hardening: an inbox-first webhook (started on branch `phase6a`), load and resilience tests, observability, and a smaller tap latency. Later and not planned: WhatsApp, Instagram and Discord adapters, merging a fan across channels, parsing free-text answers automatically, and deposits or waitlists as a stronger demand signal.
