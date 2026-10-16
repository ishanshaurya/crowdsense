# Traceability: decision to tests

Every decision in `docs/decisions.md` that has behaviour should map to at least one test. A test file also marks its tests with `@decision(n)`, and `Q-10` checks that the numbers exist.

| Decision | Behaviour | Tests |
|---|---|---|
| 3 | Link carries a source tag | P1-C04, P2-U01, P2-U02, P4-U07 |
| 4 | Channel is a plugin; core is channel-free | P1-C01, P2-C01, P3-C01, P3-C02, P3-C03, P3-U01, Q-05, Q-11, Q-15, P6-K01 |
| 5 | Telegram first | P2-U01 to U10, P2-C01 to C06 |
| 11 | Fan separate from identity | P1-C01, P1-C03 |
| 12 | Answers history plus snapshot | P1-C01, P1-C05, P1-C06, P6-R03, P6-C06 |
| 13 | Buttons first | P1-U06, P2-U03, P2-U07 |
| 14 | Seeded simulated fans, labelled | P3-C04, P3-C05, P5-U03, P6-R04 |
| 15 | Notify button | P5-U01, P5-U04, P5-U05, P5-C01 to C04 |
| 16 | Second adapter proves the design | P3-C01, P3-C03 |
| 18 | Simulated artist and fans | P3-C06, P4-U09, P4-C06 |
| 20 | Ten cities | P1-U12, P2-U07, Q-10 |
| 21 | Budget bands | P1-U12, P1-U24, Q-10 |
| 22 | Group buckets | P1-U07, P4-U03, Q-10 |
| 23 | Timing removed | P1-U12, Q-10, Q-16 |
| 24 | Venue names and capacities | P1-C09, P1-U04, Q-10, Q-16 |
| 25 | Venue chosen by name with buttons | P1-U04, P1-U15 |
| 26 | Supabase Postgres | P1-C09, P1-C11, P2-C06, P4-C01, P5-C07 |
| 27 | "Other / not listed" note | P1-U05, P1-U29, P4-U04 |
| 28 | Streamlit dashboard | P4-C03, P4-C05 |
| 30 | Two services, DB as bridge | P4-C04, Q-05, Q-17 |
| 31 | Venue demand, attendance, suggested venue, city priority, growth badge | P1-U20 to U27, U29, U30, P4-U01, P4-U06, P4-U08 |
| 32 | Price band is the most common band | P1-U24, P4-U02 |
| 33 | Group to people mapping | P1-U07, P1-U20 |
| 36 | Consent, `/stop`, `/delete`, `/help` | P1-U01 to U03, U09 to U11, P1-C07, P1-C08, P2-U05, P5-U02, P5-C05, P6-R04, Q-16 |
| 37 | Each channel identity is its own fan | P1-C03 |
| 39 | `venues` table | P1-C09, P1-C12, Q-10 |
| 40 | About 1,500 seeded fans | P3-U03, P3-U04, P3-C04, P3-C07 |
| 41 | Pure core, store interface, insights module | P1-U13, P1-C10, P1-C11, Q-02, Q-06, P6-R05 |
| 42 | Hardening and measured results | Phase 6 tests, Q-21 to Q-24 |
| 47 | Replies logged per turn | P1-S04, P1-S05 |
| 54 | Store contract suite from phase 1 | P1-S01 to S07 |
| 55 | One transaction per turn | P1-S02, P1-S03, P1-S05 |
| 56 | Clock seam | P1-S06 |
| 57 | Demand module, SQL aggregates | P4-C01, P4-U08 |
| 70 | Counted from first completion | P1-U31, P1-U32 |
| 71 | Engine error returns 200 + one apology | P2-C04 |
| 72 | Resend sweeper | P1-S07, P2-C07, P2-C08, P5-C02 |
| 73 | Simulated / Real switch | P4-U09 |
| 75 | Announcement form | P5-U07, P5-U08, P5-U09 |
| 76 | Web chat users are real | P3-C08 |
| 78 | ~20,000 seeded fans | P3-C04, P4-C07 |
| 79 | Price band per city | P1-U24, P4-U02 |
| 80 | Dashboard inserts announcement requests only | P4-C02 |
| 81 | `/delete` removes replies and events | P1-C07 |
| 82 | Engine `simulated=True` | P1-C14 |
| 84 | Funnel by furthest step | P1-U33, P1-C07, P4-U05 |
| 85 | Growth and audience use counted fans | P1-U26, P4-U06, P5-U01 |
| 88 | Identity lock for new fans | P1-S02, P1-S08 |
| 90 | Telegram dedupe on `update_id` | P2-U09, P2-U11, P2-C03 |
| 91 | Stale taps ignored | P1-U34, P2-U11, P2-C09, P2-C10 |
| 92 | Answer tap at once, replace buttons | P2-C11 |
| 93 | 429 and 403 handling | P2-C12, P2-C13 |
| 94 | Interest question removed | P1-U12 |
| 95 | Input caps: text 1,000 chars, source tag pattern, DB length limits (pending in `docs/decisions.md`) | P2-U12, P2-C14, P2-C15, P2-C16 |
| 60 | Password gate; emails hidden by default | P4-U11, P6-C08 |

## Gaps to watch

- Decisions 38 (message wording) and 29 (dev only hosting) have no tests: wording is refined by hand (manual checklist), hosting is not code.
- Spec gaps A1 to A10 are confirmed (decision 48).
- Decisions 62, 83 and 87 have no automated test yet; cover them in the manual checklist.
