# Phase 3: Prove the plugin design and seed data

All phase 1 and 2 tests must still pass. The point of this phase: adding a channel must not change the core.

## Build

1. `adapters/web_sim.py`: a small web chat on the same engine.
2. Seed script that drives the engine through the web sim to create about 1,500 simulated fans (decision 40).
3. Parity check that proves `core/` and the schema did not change in this phase.

## Unit tests

| Id | What | Expected | Decision |
|---|---|---|---|
| P3-U01 | Web sim parse and render | Same `InboundEvent` and `Reply` types as Telegram | 4 |
| P3-U02 | Web sim capabilities | Reports buttons supported | 4 |
| P3-U03 | Seed generator is deterministic | Same random seed gives the same fans | 40 |
| P3-U04 | Seed distribution rules | Every city present; Mumbai, Delhi NCR and Bengaluru lead; Jaipur and Indore rise week over week | 40 |

## Component tests

| Id | What | Expected | Decision |
|---|---|---|---|
| P3-C01 | Every scenario in `scenarios/` through the web sim | Same `final_db` as the core run | 4, 16 |
| P3-C02 | Parity: Telegram vs web sim | Same scenario gives identical rows except `channel` | 4 |
| P3-C03 | No core change | A CI check shows no diff in `core/` or `migrations/` since the phase 2 tag; if there is one, the contract is fixed first and recorded | 4, 16 |
| P3-C04 | Seed run | 1,400 to 1,600 fans, all `is_simulated = true`, all with `events` rows (went through the engine) | 14, 40 |
| P3-C05 | Seed never messages | No outbound event for any simulated fan | 14, 36 |
| P3-C06 | Seed and real coexist | Real tester rows are not touched by re-seeding | 18 |
| P3-C07 | Insights over the seeded data | Returns a venue, price band and city priority for every seeded city | 31 to 33 |

## Manual (see `manual/manual-checklist.md`, Phase 3)

Chat in the browser and see the same flow and rows as Telegram.

## Exit (final output)

- All new tests pass, and all earlier tests are still green.
- Parity test passes with no `core/` change.
- Seeded dataset loaded in the dev DB and flagged simulated.
- Quality checks through `Q-16` pass.
