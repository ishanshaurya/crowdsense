# PRD: Crowdsense

What we build and why. How: `ARCHITECTURE.md`. When: `PLAN.md`. Why each choice: `decisions.md`.

## 1. Problem

Artists and organisers must decide before spending money:

- Which city has real fan demand
- Which venue size fits the expected crowd
- What ticket price fans will pay
- How many shows a region needs
- Whether demand is enough to book a venue at all

Today they guess from:

- Social media likes and follows
- Past tour experience
- Gut feel

None of these show real intent to buy, so booking a venue is a gamble.

**Our answer:** a chat bot collects structured fan intent. A dashboard turns it into demand insights and recommendations.

## 2. Users

### Primary: artist / management team

Goals:
- Find high-demand and under-explored cities
- Measure interest before booking venues
- Estimate attendance
- Know the price range fans accept
- Pick where to launch the next show
- Build a reusable audience list

Pain points:
- No reliable demand data
- High risk in booking venues
- Little insight into regional audiences
- Costly marketing with unclear return

### Secondary: fans

Goals:
- Register interest in a show near them
- Hear first when tickets launch
- Get updates for their city

Pain points:
- Miss ticket launches
- Hear about shows too late
- No simple way to say "I'd come"

## 3. Value

- **Artist:** turn fan chats into demand data before spending money.
- **Fan:** one tap in a chat app to say "I'd come", then get told when it happens.

## 4. Features

### Bot: intake

Fan clicks a link (story, bio, poster). The chat app opens. The bot asks:

1. Consent to get updates
2. City (10 fixed cities)
3. Venue in that city (or "Other / not listed")
4. Ticket budget band
5. Group size
6. Interest level
7. Email (optional)

Fan commands: `/stop`, `/delete`, `/help`.

Returning fans can edit any answer.

### Bot: outbound

- One "show announced in your city" message, sent from the dashboard.
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

Rules: `decisions.md` #31 to #34, #49 to #52.

## 5. MVP scope

The MVP is a proof of concept for interviewers (#1).

In scope:
- Telegram as the only live channel (#5)
- Web chat simulator as a second channel (#16)
- Simulated artist and ~1,500 simulated fans, labelled "simulated" (#18, #40)
- Real fans: builder plus a few testers
- Everything above in section 4

Changed from the original idea:

| Original | MVP | Why |
|---|---|---|
| WhatsApp bot | Telegram first, WhatsApp later | No Meta verification or templates needed (#5) |
| Real artist | Simulated artist | Proof of concept (#18) |
| Free-text venue area | Venue buttons per city | Clean data (#25) |
| Show timing / preferred dates | Not asked | Removed (#23) |

Out of scope (later):
- WhatsApp, Instagram, Discord (#7)
- Early-bird offers, group discounts, reminders (decide in phase 6)
- Campaign conversion metrics (needs ticket sales data)
- Many artists at once (hardening adds campaigns)
- Merging one fan across channels (#37)
- Using interest level in the numbers (#34)

## 6. Success

- A real phone completes the flow from a link.
- The answer shows on the dashboard within seconds.
- Each city gets a venue, price band and priority.
- Outbound message reaches opted-in testers only.
- Measured numbers meet the targets in `PLAN.md`.

## 7. Known limits

- Fans who reply are self-selected, not a fair sample.
- Stated intent is not a ticket purchase.
- Simulated data shows the system works, not real demand.
