# Phase 5: Outbound and polish

All phase 1 to 4 tests must still pass.

## Build

1. Dashboard "notify fans" action: choose a city, preview the audience, send.
2. Audience rule: consented, not opted out, not simulated, the channel can push, in the chosen city.
3. Send through the adapter; record each outbound as an `events` row.
4. Demo script, README (with limits: self-selection bias, stated intent vs purchase), architecture diagram.

## Unit tests

| Id | What | Expected | Decision |
|---|---|---|---|
| P5-U01 | Audience selection | Only fans meeting every rule above | 15, 36 |
| P5-U02 | Opted-out fan | Never in the audience | 36 |
| P5-U03 | Simulated fan | Never in the audience | 14 |
| P5-U04 | Other-city fan | Not in the audience | 15 |
| P5-U05 | Message render | `{city}` and other placeholders filled; no raw braces left | 15 |
| P5-U06 | Idempotency key | Same send request gives the same key; a new request gives a new one | 41 |

## Component tests

| Id | What | Expected | Decision |
|---|---|---|---|
| P5-C01 | Send to a city with a fake adapter | One message per eligible fan; one outbound `events` row each | 15 |
| P5-C02 | One send fails | The others still go out; the failure is recorded | 15 |
| P5-C03 | Double click on send | Messages sent once, not twice | 41 |
| P5-C04 | Empty audience | Send is disabled or returns "nobody to notify"; nothing sent | 15 |
| P5-C05 | `/stop` after a send | Next send skips that fan | 36 |
| P5-C06 | Capability check | A channel that cannot push is skipped, with a count shown | 4 |
| P5-C07 | Real Postgres | All of the above also pass | 26 |

## Manual (see `manual/manual-checklist.md`, Phase 5)

End-to-end rehearsal: tap the link, chat, watch the dashboard update, press notify, receive the message on the phone, send `/stop`, send again, confirm no message.

## Exit (final output)

- All new tests pass, and all earlier tests are still green.
- Rehearsal checklist signed off start to finish.
- README states limits and the "simulated data" caveat.
- Quality checks through `Q-20` pass.
