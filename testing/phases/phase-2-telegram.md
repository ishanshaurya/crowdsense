# Phase 2: Telegram adapter

All phase 1 tests must still pass.

## Build

1. Create the bot with BotFather; store the token in env only.
2. `adapters/telegram.py`: parse, render, send. No flow logic.
3. `api/webhooks.py`: `/hook/{channel}` calls `adapter.parse`, the engine, then `adapter.send`. Checks the Telegram secret-token header.
4. Deep link `t.me/<bot>?start=<source_tag>`.
5. **Record real payloads** from your own bot into `fixtures/telegram/` (see its README), then write the parse tests against them.
6. Run locally with ngrok; register the webhook.

## Unit tests (adapter, no network)

Parse tests read recorded payloads from `fixtures/telegram/`.

| Id | What | Expected | Decision |
|---|---|---|---|
| P2-U01 | `/start <tag>` payload | `InboundEvent` kind start with `source_tag` | 3 |
| P2-U02 | `/start` with no tag | `source_tag` is empty | 3 |
| P2-U03 | Inline button tap (callback query) | kind choice with the right value | 13 |
| P2-U04 | Plain text message | kind text | 13 |
| P2-U05 | `/stop`, `/delete`, `/help` | kind command | 36 |
| P2-U06 | Update types we do not handle (edited message, photo, sticker, group) | Ignored safely; no exception | 5 |
| P2-U07 | Render options to an inline keyboard | Buttons laid out in rows; 10 cities fit | 20 |
| P2-U08 | Callback data length | Every callback value is at most 64 bytes | 5 |
| P2-U09 | Event ids | `external_msg_id` is stable for the same update and distinct for different ones | 41 |
| P2-U10 | Capabilities | Adapter reports buttons, `has_phone` false, `can_push_anytime` after start | 4 |

## Component tests (webhook with a fake Telegram sender)

| Id | What | Expected | Decision |
|---|---|---|---|
| P2-C01 | Replay scenario `happy_path_pune` as Telegram updates | Same `final_db` as the phase 1 core run | 4, 5 |
| P2-C02 | Wrong or missing secret header | Rejected; engine not called | 41 |
| P2-C03 | Same update delivered twice (Telegram retry) | One set of rows; one outgoing message | 41 |
| P2-C04 | Engine raises an error | Webhook still returns success to Telegram; error logged with a correlation id | 41 |
| P2-C05 | Outgoing message shape | Text and inline keyboard match what `Reply` asked for | 5 |
| P2-C06 | Webhook against real Postgres | All of the above also pass | 26 |

## Manual (see `manual/manual-checklist.md`, Phase 2)

Real phone, real ngrok URL, real Supabase: tap the link, finish the flow, see the row.

## Exit (final output)

- All new tests pass, and all phase 1 tests are still green.
- Recorded payload fixtures committed (no real user data or token inside).
- One real phone completes the flow and the row appears in Supabase.
- Quality checks `Q-01` to `Q-14` pass.
