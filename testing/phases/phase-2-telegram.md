# Phase 2: Telegram adapter

All phase 1 tests must still pass.

## Build

1. Create the bot with BotFather; store the token in env only.
2. `adapters/telegram.py`: parse, render, send. No flow logic.
3. `api/webhooks.py`: `/hook/{channel}` calls `adapter.parse`, the engine, then `adapter.send`. Checks the Telegram secret-token header.
4. Deep link `t.me/<bot>?start=<source_tag>`.
5. **Record real payloads** from your own bot into `fixtures/telegram/` (see its README), then write the parse tests against them.
6. Resend sweeper in the webhook service: every 30 s, claim `unsent` replies older than 10 s, send, mark `sent` (decision 72).
7. Run locally with ngrok; register the webhook.
8. Input caps in core, so every channel gets them (decision 95). The engine cuts inbound text to 1,000 characters before it is stored in `events` or reaches `decide`. A `source_tag` is kept only if it matches `^[A-Za-z0-9_-]{1,64}$` (Telegram's own deep-link rule); anything else is stored as no tag and the fan still gets in. Postgres length limits on `events` text, `identities.source_tag`, `fans.venue_note` and `fans.email` arrive in a new migration (0001 and 0002 are applied to Supabase in this phase, so they are not edited). Must land here: phase 3 allows no engine or schema change, and its public web chat has no Telegram limits.

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
| P2-U12 | Source tag check | `ig_story` kept; 65 characters, spaces, emoji or `<script>` → no tag; consent still asked | 3, 95 |
| P2-U11 | Tap parse | `callback_data` `city:pune` → `choice_step = city`, `choice_id = pune`; `external_msg_id` = `update_id` | 90, 91 |

## Component tests (webhook with a fake Telegram sender)

| Id | What | Expected | Decision |
|---|---|---|---|
| P2-C01 | Replay scenario `happy_path_pune` as Telegram updates | Same `final_db` as the phase 1 core run | 4, 5 |
| P2-C02 | Wrong or missing secret header | Rejected; engine not called | 41 |
| P2-C03 | Same update delivered twice (Telegram retry) | One set of rows; one outgoing message | 41 |
| P2-C04 | Engine raises an error | Webhook returns 200; nothing saved; one apology message sent; error logged with a correlation id | 41, 71 |
| P2-C05 | Outgoing message shape | Text and inline keyboard match what `Reply` asked for | 5 |
| P2-C06 | Webhook against real Postgres | All of the above also pass | 26 |
| P2-C07 | Telegram send fails, then recovers | Reply stays `unsent`; sweeper sends it once it is older than 10 s; then `sent` | 55, 72 |
| P2-C08 | Sweeper sees a fresh `unsent` reply (under 10 s) | Not sent yet, so it cannot race the in-flight send | 72 |
| P2-C09 | Fan taps one button twice fast | First tap applied and its buttons become "✓ <choice>"; second is stale, ignored, no second edit; exactly one reply reaches the fan and no "That question has passed" message is delivered | 91, 92 |
| P2-C10 | Fan taps a button from an earlier question | No state change; `answerCallbackQuery` sent with no text; "That question has passed" arrives as a normal chat message; the buttons are left unchanged | 91, 92 |
| P2-C11 | Any tap | `answerCallbackQuery` (no text) called before the engine runs; buttons replaced with "✓ <choice>" only when the engine applied the tap | 92 |
| P2-C12 | Telegram returns 429 with `retry_after` | Resend waits at least `retry_after` seconds | 93 |
| P2-C13 | Telegram returns 403 (bot blocked) | Identity marked opted out and that fan's `unsent` replies deleted in one transaction; the sweeper never retries them; no further sends; the count dropped is logged | 93 |
| P2-C14 | Oversized message (5,000 characters), on the fake and on Postgres | Stored and decided as its first 1,000 characters; no error | 95 |
| P2-C15 | DB length limits | Oversized `source_tag`, `venue_note` or `email` written straight to Postgres is rejected | 41, 95 |
| P2-C16 | Caps migration | Up and down on a database already at 0002 with rows in it | 95 |
| P2-C17 | Stale tap on a message confirmed more than 60 s ago, and on a message the webhook never confirmed | The fan gets "That question has passed" as a chat message | 91, 92 |

## Manual (see `manual/manual-checklist.md`, Phase 2)

Real phone, real ngrok URL, real Supabase: tap the link, finish the flow, see the row.

## Exit (final output)

- All new tests pass, and all phase 1 tests are still green.
- Recorded payload fixtures committed (no real user data or token inside).
- One real phone completes the flow and the row appears in Supabase.
- Quality checks `Q-01` to `Q-14` pass.
