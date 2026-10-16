# Telegram fixtures

Real payloads recorded from your own bot during phase 2. Parse tests (P2-U01 to P2-U10) and the contract test (P6-K02) read from here. Do not hand-write payloads.

## What to record

One file per case, named for the case, for example `start_with_tag.json`.

- `/start` with a tag, and `/start` without a tag
- an inline button tap (callback query)
- a plain text message
- `/stop`, `/delete`, `/help`
- an update type the bot does not handle: edited message, photo, sticker, a message from a group (sticker and group are not recorded for now, #96; the tests derive them)

## How to record

1. Run the webhook locally with ngrok and log the raw request body of each update (temporary debug logging, not committed).
2. Send each case from your own Telegram account to your bot.
3. Save the body as JSON, one file per case.

## Scrub before saving (checked by Q-14)

- Replace user ids, chat ids, names and usernames with obvious placeholders (for example `1000001`, `Test User`, `test_user`), keeping the same type and length shape.
- Remove any token or secret. The bot token is not in update bodies, but check any headers you copied.
- Keep message ids and update ids as placeholders that stay unique across files.
- Do not commit the unscrubbed originals.
