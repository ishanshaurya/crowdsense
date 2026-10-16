# Testing

Tests are the living spec. Each phase in `docs/plan.md` has a test file here that says what to build, how it is proven, and what must still pass from earlier phases. No code exists yet; this folder is written first and the build follows it.

## Folder map

```
testing/
  README.md                       this file: approach, conventions, spec gaps
  traceability.md                 decision number -> test ids
  phases/
    phase-1-core.md               build steps + unit + component + exit
    phase-2-telegram.md
    phase-3-plugin-and-seed.md
    phase-4-dashboard.md
    phase-5-outbound.md
    phase-6-hardening.md          contract, property, load, resilience
  quality/
    architecture-quality.md       design, architecture, code quality checks (all phases)
  manual/
    manual-checklist.md           one manual checklist, sections per phase
  scenarios/                      conversation scenarios and insights cases (YAML)
  fixtures/telegram/              real Telegram payloads recorded in phase 2
```

## Approach

1. **Scenarios are data.** A conversation is written once as YAML and run at every level: core (phase 1), Telegram adapter (phase 2), web sim (phase 3), seed traffic (phase 3) and load (phase 6). Python tests with pytest read the YAML. No Gherkin tooling.
2. **Phases 1 to 5 use three layers only:** unit, component, and one manual checklist. Contract, property and load tests belong to phase 6.
3. **Cumulative gate.** A phase is done only when its own tests pass and every earlier phase's tests still pass. CI runs everything; older tests are never deleted or loosened to make a new phase pass.
4. **Build, then prove.** Each phase file lists build steps first and ends with the test exit, which is the final output of the phase.
5. **Quality checks run from day 1** and grow as modules appear: see `quality/architecture-quality.md`.

## Test ids and markers

- Id format: `P<phase>-<layer><nn>`. Layers: `U` unit, `C` component, `M` manual, `K` contract, `R` property, `L` load, `X` resilience. Example `P1-U03`. Quality checks use `Q-<nn>`.
- Proposed pytest markers: `unit`, `component`, `contract`, `property`, `load`, `manual`. Each test is also tagged with the decision numbers it proves, for example `@decision(31)`, which feeds `traceability.md`.
- Layer meaning:
  - **Unit:** no I/O. `decide`, validators, insights, flow validation.
  - **Component:** engine with the in-memory store, then the same tests against real Postgres (pytest-postgresql, decision 44). Webhook with a fake Telegram sender.
  - **Manual:** a human with a real phone or browser, from `manual/manual-checklist.md`.

## Scenario format

Files in `scenarios/`. One file is one conversation.

```yaml
id: happy_path_pune
description: one line
decisions: [20, 21, 24, 25]
steps:
  - send: {kind: start, source_tag: ig_story}   # kind: start | choice | text | command
    expect: {step: consent, options: ["Count me in", "No thanks"]}
  - send: {kind: choice, value: "Count me in"}
    expect: {step: city, options_count: 10}
final_db:                                       # state after the last step
  fans: {city: Pune, venue: Baner Greens}
  identities: {opted_out: false}
```

- Optional keys: `setup: {scenario: <id>, stop_before: <step>}` starts from the state another scenario leaves (or stops just before a step); `msg_id` on a send fixes the message id (for duplicate tests); `expect: {no_reply: true}`, `{error: true}` and `{duplicate: true}` check silent, rejected and deduplicated turns; `final_db` values of `none` mean the rows must not exist.
- `expect` checks the step id and options, never exact wording (message drafts change, decision 38). Use `text_contains` only for the approved consent message.
- Stored values use canonical codes so tests do not depend on labels: `budget_band` in `lt_1500 | 1500_3000 | 3000_6000 | gte_6000`, `group_size` in `1 | 2 | 3_5 | 6_plus`.
- `insights_cases.yaml` is a separate format: given fans and venues, expected recommendations.

## Spec gaps found while drafting (close before the related tests are final)

All of A1 to A10 are accepted (decision 48); A1 to A4 were also confirmed individually (decisions 49 to 52).

| # | Gap | Answer used in tests |
|---|---|---|
| A1 | Decision 31(c): is "expected attendance" for suggested venue measured per venue or per city? | Per city (all counted fans in the city). Per-venue demand is for ranking only | (confirmed, decision 49) |
| A2 | Tie in the most common budget band | Pick the lower band (more fans can afford it) | (confirmed, decision 50) |
| A3 | Fans who chose "Other / not listed" | Count in city attendance, city priority and price band; excluded from per-venue demand | (confirmed, decision 51) |
| A4 | Which fans "count" | Fans who reached the done step at least once (`completed_at` set). Partial fans appear only in the funnel; a later edit does not uncount (decision 70) | (confirmed, decision 52) |
| A5 | Growth badge when last week had 0 signups | Show "new" instead of a percentage; no division by zero |
| A6 | Week boundary for growth | Rolling 7 days vs the 7 days before, by `created_at` |
| A7 | Returning fan changes city | Venue is cleared and asked again, because venues belong to a city |
| A8 | `/delete` | Removes `fans`, `answers`, `identities`, `sessions` and the fan's `events`; increments `funnel_counts` for the step the fan was on (decisions 45, 48) |
| A9 | Opted-out fan sends `/start` again | Re-subscribes, sets `opted_out = false`, resumes at their saved step |
| A10 | Free-text step receives a button tap, or the reverse | Re-ask the current step |

## Running (proposed, once code exists)

```
pytest -m unit
pytest -m "unit or component"       # phases 1 to 5 gate
pytest                               # everything; CI default
```
