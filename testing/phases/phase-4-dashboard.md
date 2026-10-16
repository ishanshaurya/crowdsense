# Phase 4: Dashboard

All phase 1 to 3 tests must still pass. Business rules stay in `core/insights.py`; Streamlit only draws.

## Build

1. `dashboard/` Streamlit app reading through `core/demand.py` (SQL aggregates) and `core/insights.py`, using a read-only DB role with INSERT on `announcement_requests` only (decisions 57, 80).
2. Views: top cities, price distribution, group size distribution, city × venue heatmap, response funnel, weekly growth per city, source breakdown, recommendations (venue, price band, city priority).
3. Simulated / Real switch (default Simulated, never mixed), "simulated data" badge, live refresh, one hero recommendation card.
4. Emails hidden by default; a toggle shows them for the current session only. Emails never appear in logs or in any export (decision 60). Behind the password gate.

## Unit tests (data layer, no UI)

Each query runs on a small hand-built fixture with known answers, loaded into real Postgres (aggregates are tested on Postgres only, #57).

| Id | What | Expected | Decision |
|---|---|---|---|
| P4-U01 | Top cities | Ordered by attendance, with counts | 31 |
| P4-U02 | Price distribution | Counts per band; completed fans only; suggested band per city | 32, 79 |
| P4-U03 | Group size distribution | Counts per bucket | 22 |
| P4-U04 | Heatmap | city × venue counts; "Other" shown separately | 27 |
| P4-U05 | Funnel | Counts by furthest step reached; completed = `completed_at` set; an editing fan stays completed; Real adds `funnel_counts` | 4, 84, 104 |
| P4-U06 | Weekly growth | Rolling 7-day comparison on counted fans by `completed_at`; growth badge rule | 31, 85 |
| P4-U07 | Source breakdown | Fans per source tag, including "no tag" | 3 |
| P4-U08 | Recommendations | Match `insights` cases | 31 to 33 |
| P4-U09 | Simulated / Real switch | Each view counts only its own fans; default is Simulated; no view mixes them; banner shows counted and started fans | 18, 73, 107 |
| P4-U10 | Empty database | Every query returns an empty result; no error | 31 |
| P4-U11 | Email column | Hidden by default; shown only after the toggle; fans without an email show blank | 60 |

## Component tests

| Id | What | Expected | Decision |
|---|---|---|---|
| P4-C01 | Queries on real Postgres with the seeded dataset | Same results as on the fixture for the overlapping slice | 26, 40 |
| P4-C02 | Read-only role | Every write is refused (`announcement_requests` and its INSERT grant arrive in phase 5) | 41, 80, 105 |
| P4-C03 | New fan appears | A fan added through the engine shows up after a refresh | 28, 106 |
| P4-C04 | Dashboard does not import adapters or the webhook | Import boundary check (see `Q-05`) | 30 |
| P4-C05 | Smoke render | The app starts and each view renders without exceptions | 28 |
| P4-C06 | Simulated badge | Shown whenever simulated data is included | 18 |
| P4-C07 | Query smoke timing | Every query returns in under 1 s on about 20,000 fans (not a load test) | 42 |

## Manual (see `manual/manual-checklist.md`, Phase 4)

Walk every view in the browser; check the badge, filter, refresh and the hero card.

## Exit (final output)

- All new tests pass, and all earlier tests are still green.
- Every view and recommendation is produced from seeded plus real data.
- Dashboard imports only `core` store, demand, insights, config and catalog.
- Quality checks through `Q-18` pass.
