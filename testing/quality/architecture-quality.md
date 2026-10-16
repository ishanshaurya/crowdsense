# Architecture and code quality checks

These checks prove the design, not just behaviour. They are automated (pre-commit and CI) except where marked. A check starts in the phase shown and keeps running in every later phase. Tool names are suggestions; swap for equivalents if a tool does not fit.

## Phase 1

| Id | Check | How | Fails when |
|---|---|---|---|
| Q-01 | Lint and format | ruff | Any violation |
| Q-02 | Types | mypy or pyright, strict on `core/` | Any type error in `core/` |
| Q-03 | No secrets in the repo | gitleaks or detect-secrets in pre-commit and CI; `.env` ignored by git | A key, token or connection string is found |
| Q-04 | Config hygiene | Test that every env var read in code is listed in `.env.example`, and that `.env.example` holds placeholders only | An undeclared var, or a real-looking value |
| Q-05 | Dependency direction | import-linter contracts: `core` imports nothing from `adapters`, `api`, `dashboard`; adapters do not import each other, `api` or `dashboard`; `dashboard` imports only the store and insights from `core` | Any forbidden import |
| Q-06 | Pure core | Test runs `decide` with sockets, file access, clock and randomness patched to raise; no `datetime.now`, `random` or `uuid` calls inside `decide` | Any I/O or hidden time/randomness |
| Q-07 | Complexity and size | ruff C901 max 10; files over 400 lines flagged for review | A function over the limit |
| Q-08 | Hygiene | ruff T20 (no `print`), no TODO without an issue id, no commented-out code | Any hit |
| Q-09 | Coverage | `core/` at least 90% line coverage; failing under the gate fails CI | Below the gate |
| Q-10 | Spec consistency | Test parses `docs/decisions.md`: the venue table equals the seeded `venues` rows; option lists in `flow.py` equal decisions 20 to 22; no step asks timing (decision 23); venue names contain no type words (arena, hall, club, stadium); every `@decision(n)` in tests exists in `docs/decisions.md` | Any mismatch |

## Phase 2

| Id | Check | How | Fails when |
|---|---|---|---|
| Q-11 | Adapter protocol | Test checks each adapter implements `parse`, `render`, `send` and `capabilities`, and that adapter files do not import `core.flow` or `core.engine` internals | Missing method, or flow logic in an adapter |
| Q-12 | Webhook security | Test that a missing or wrong secret header is rejected; log scan test shows no token or secret in logs | Request accepted, or secret logged |
| Q-13 | Dependencies | pip-audit clean; lockfile (uv or pip-tools) committed and up to date | Known vulnerability, or lockfile drift |
| Q-14 | Fixture hygiene | Scan of `fixtures/telegram/` for tokens, real user ids, names, usernames | Anything not scrubbed |

## Phase 3

| Id | Check | How | Fails when |
|---|---|---|---|
| Q-15 | Plugin cost | Adding the web sim touches only: one new adapter file, one registry line, tests. A CI check lists changed paths for the phase | Any change in `core/`, `migrations/` |
| Q-16 | Content rules | Scan of user-facing strings and seeds: no timing question, no venue type words, consent text matches the approved wording | A rule is broken |

## Phase 4

| Id | Check | How | Fails when |
|---|---|---|---|
| Q-17 | No logic in the UI | No raw SQL and no recommendation math in `dashboard/`; it calls the store and insights only | SQL or business rules found there |
| Q-18 | Least privilege | Dashboard uses a read-only role; test shows a write is refused | A write succeeds |

## Phase 5

| Id | Check | How | Fails when |
|---|---|---|---|
| Q-19 | Single outbound path | All outbound messages go through the audience function and an adapter `send`; a search test finds no other send call | A direct send exists |
| Q-20 | Docs consistent | README has the limits statement and the simulated-data caveat; architecture diagram present; decision numbers referenced in docs exist | Missing or stale |

## Phase 6

| Id | Check | How | Fails when |
|---|---|---|---|
| Q-21 | Container | Multi-stage, non-root Dockerfile; hadolint and Trivy clean | Root user, or a high severity finding |
| Q-22 | Test strength (optional) | Mutation testing on `core/` (mutmut) | Score under an agreed floor |
| Q-23 | SLO table filled | README "Production readiness" table has a measured value for every target | An empty cell |
| Q-24 | CI gates | Lint, types, tests, coverage, secrets and audit are required checks | A gate is missing |

## Manual design review (once per phase, end of phase)

Answer yes or no, with a note for any no. Use the `review` skill if wanted.
- Could a new channel be added by writing one file plus a registry line?
- Is there any business rule outside `core/`?
- Does any module know about more than it needs to?
- Is every decision in `docs/decisions.md` visible in the code or tests?
- Is anything built that no decision asked for?
