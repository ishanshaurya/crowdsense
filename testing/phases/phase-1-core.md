# Phase 1: Core (no network)

## Build

1. Repo skeleton and day-1 tooling (ruff, pytest, pre-commit with a secret scanner, GitHub Actions).
2. `core/flow.py`: steps as data (consent, city, venue, venue_note, budget, group, email, done).
3. Pure `decide(state, event) -> (new_state, replies, writes)`. Clock and randomness are passed in.
4. Store interface plus an in-memory fake, then the Postgres implementation with Alembic migrations.
5. `venues` table seeded from the venue table in `docs/decisions.md`.
6. Engine shell, one transaction: dedupe, find or create identity, lock, `decide`, save state, answers and replies; send after returning 200 (decisions 55, 86). Option `simulated=True` (decision 82).
7. `core/insights.py`: decisions 31 to 33 as pure functions.

## Unit tests (no I/O)

| Id | What | Expected | Decision |
|---|---|---|---|
| P1-U01 | Consent "Count me in" | Next step is city; consent true | 36 |
| P1-U02 | Consent "No thanks" | Decline reply; nothing saved except that they declined | 36 |
| P1-U03 | Text sent where consent button is expected | Consent re-asked; no questions asked | 36 |
| P1-U04 | Valid city | Venue step shows only that city's venues plus "Other / not listed" | 24, 25 |
| P1-U05 | Venue "Other / not listed" | Free-text step; text stored as `venue_note`; `venue` stays empty | 27 |
| P1-U06 | Choice not in the current options | "Tap one of the options"; same step; nothing saved | 13 |
| P1-U07 | Group buckets | 1, 2, 3–5, 6+ store codes and map to 1, 2, 4, 6 people | 33 |
| P1-U09 | Email: skip, invalid, valid | Skip moves on; invalid re-asks; valid stored | 36 |
| P1-U10 | `/stop` at every step | Identity opted out; one confirmation; no further questions | 36 |
| P1-U11 | `/delete` and `/help` | Delete write emitted; help text returned | 36 |
| P1-U12 | Flow is complete | No step asks timing or interest (decisions 23, 94); every step reachable; every field exists in the schema; option lists match decisions 20 to 22 | 23 |
| P1-U13 | Determinism | Same state and event give identical output | 41 |
| P1-U14 | Returning fan edit menu | Done fan sees edit options; editing one field returns to done | 36 |
| P1-U15 | Edit city (A7) | Venue cleared and re-asked | 25 |

### Insights unit tests (`scenarios/insights_cases.yaml`)

| Id | What | Expected | Decision |
|---|---|---|---|
| P1-U20 | Attendance sums people, not fans | 1+2+4+6 = 13 | 31, 33 |
| P1-U21 | Suggested venue is the smallest fit at 80% fill | 13 people in Pune gives Koregaon Park Lawns | 31 |
| P1-U22 | Boundary | 3,200 people in Mumbai gives Bandra Waterfront (4,000 ≥ 3,200 ÷ 0.8) | 31 |
| P1-U23 | Demand above every venue | 25,000 people in Mumbai gives the largest venue, Mahalaxmi Maidan | 31 |
| P1-U24 | Most common budget band | The mode wins; tie gives the lower band (A2) | 32 |
| P1-U25 | City priority order | Sorted by attendance, descending | 31 |
| P1-U26 | Growth badge | Fires at +20% and above, not at +19%; "new" when the prior week is 0 (A5); counts counted fans by `completed_at` | 31, 85 |
| P1-U27 | Only completed fans count (A4) | A partial fan changes no number | 31 |
| P1-U29 | "Other" venue fans (A3) | In city attendance and price band, not in per-venue demand | 31 |
| P1-U30 | Empty data | Returns empty results, no error | 31 |
| P1-U31 | Completed fan starts an edit | Stays counted; `completed_at` unchanged | 70 |
| P1-U32 | Completed fan changes city, venue not yet re-picked | Counted for the new city, for no venue | 51, 70 |
| P1-U33 | Furthest step | Never moves back when a fan edits; funnel counts by it | 84 |
| P1-U34 | Stale tap | `choice_step` differs from the current step → no state change; stale reply returned | 91 |

## Component tests (engine + store)

Run each against the in-memory fake, then the same tests against real Postgres (pytest-postgresql, decision 44).

| Id | What | Expected | Decision |
|---|---|---|---|
| P1-C01 | Scenario `happy_path_pune` | Rows in `fans`, `identities`, `sessions`, `answers`, `events` match `final_db` | 4, 11, 12 |
| P1-C02 | Scenario `duplicate_message` | One processed event; no duplicate rows or replies | 41 |
| P1-C03 | Same external id on two channels | Two independent identities | 11, 37 |
| P1-C04 | Source tag | Stored on the identity at first contact only | 3 |
| P1-C05 | Restart mid-flow | New engine instance resumes at the saved step | 12 |
| P1-C06 | Edit an answer | New `answers` row; `fans` snapshot updated; latest `answers` equals `fans` | 12 |
| P1-C07 | `/delete` (A8) | Fan rows, `events` and `replies` gone; funnel count kept for the furthest step; confirmation sent, not stored | 36, 81, 84 |
| P1-C08 | Opted-out then `/start` (A9) | Re-subscribed; resumes at saved step | 36 |
| P1-C09 | Migrations | Up and down on an empty DB; `venues` seed has 14 rows matching `docs/decisions.md` capacities | 24, 39 |
| P1-C10 | DB constraints | Bad `budget_band` or missing FK rejected | 41 |
| P1-C11 | Store contract | The same suite passes on the fake and on Postgres | 41 |
| P1-C12 | Insights on DB | `insights` over seeded rows returns the same result as over in-memory rows | 41 |
| P1-C14 | Engine run with `simulated=True` | Fan stored with `is_simulated = true`; no other difference | 82 |
| P1-C13 | Scenarios `decline_consent`, `stop_command`, `delete_command`, `bad_input_then_ok`, `other_venue`, `returning_fan_edit`, `email_validation` | All match `final_db` | 13, 27, 36 |

## Store contract tests (decisions 54, 55, 56)

One suite, run against the in-memory fake and real Postgres. Both must pass identically.

| Id | What | Expected | Decision |
|---|---|---|---|
| P1-S01 | Insert the same `(channel, external_msg_id)` twice | Second insert reports duplicate; one row | 41 |
| P1-S02 | Two turns for one fan at once | Serialised by the identity lock; both applied in order | 55, 88 |
| P1-S03 | Turn fails after writing the answer | Nothing saved: no answer, no reply, step unchanged | 55 |
| P1-S04 | Commit, then restart before send | `unsent` replies still there and returned for resend | 47, 55 |
| P1-S05 | Duplicate event with `unsent` replies | Replies sent once, then marked `sent` | 55 |
| P1-S06 | Scripted clock | `created_at` and `ts` use the scripted time | 56 |
| P1-S07 | Two claimers ask for stale `unsent` replies at once | Disjoint sets (`SKIP LOCKED`); each reply claimed once | 72 |
| P1-S08 | Brand-new fan sends two messages at the same moment | One identity, one fan; both messages handled in order; no apology sent | 88 |

## Manual (see `manual/manual-checklist.md`, Phase 1)

Run a dev REPL against the engine and read the whole conversation for tone and clarity.

## Exit (final output)

- All unit and component tests above pass on the fake and on Postgres.
- Coverage on `core/` at least 90% (Q-09).
- Quality checks `Q-01` to `Q-10` pass (`quality/architecture-quality.md`).
- The REPL manual item is signed off.
