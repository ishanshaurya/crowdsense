# Message script

What the bot says, and what the fan sees when messaging goes wrong. Structure and rules: `docs/architecture.md`. Terms: `docs/CONTEXT.md`.

## 1. Bot texts

Text lives in `core/flow.py` as data. Only #1 is approved; the rest are drafts (#38).

- **#1** Consent · _Bot text: Hi! Get updates when Artist X plays near you. Answer a few quick questions so we can plan the right shows. Reply /stop any time to opt out._ · _Buttons: Count me in · No thanks_ · _Status: Approved_
- **#2** Declined · _Bot text: No problem. Message me any time._ · _Buttons: —_ · _Status: Draft_
- **#3** City · _Bot text: Which city are you in?_ · _Buttons: 10 cities_ · _Status: Draft_
- **#4** Venue · _Bot text: Where would you want to see the show?_ · _Buttons: city's venues + Other / not listed_ · _Status: Draft_
- **#5** Other venue · _Bot text: Tell us the place._ · _Buttons: free text → `venue_note`_ · _Status: Draft_
- **#6** Budget · _Bot text: What ticket price feels comfortable?_ · _Buttons: 4 bands_ · _Status: Draft_
- **#7** Group · _Bot text: How many people are coming?_ · _Buttons: 1 · 2 · 3–5 · 6+_ · _Status: Draft_
- **#8** ~~Timing~~ · _Bot text: not asked (#23)_ · _Buttons: —_ · _Status: Removed_
- **#9** ~~Interest~~ · _Bot text: not asked (#94)_ · _Buttons: —_ · _Status: Removed_
- **#10** Email · _Bot text: Shows near you can sell out fast. Drop your email and we'll tell you the moment Artist X tickets open. Or tap Skip._ · _Buttons: Skip_ · _Status: Draft_
- **#11** Done · _Bot text: You're in! We'll message you when Artist X announces a show near you. · Channels that cannot push (web chat): "You're in! Thanks for telling us." (#87)_ · _Buttons: —_ · _Status: Draft_
- **#12** Returning fan · _Bot text: Welcome back! Want to update anything?_ · _Buttons: City · Venue · Budget · Group · All good_ · _Status: Draft_
- **#13** Invalid input · _Bot text: Please tap one of the options._ · _Buttons: repeats options_ · _Status: Draft_
- **#14** /stop · /delete · /help · _Bot text: You're unsubscribed. · Your data is deleted. · short help_ · _Buttons: —_ · _Status: Draft_
- **#15** Outbound · _Bot text: Artist X is coming to {city}. Tickets open {date}._ · _Buttons: —_ · _Status: Draft_
- **#16** Stale tap (chat message, not a toast) · _Bot text: That question has passed._ · _Buttons: —_ · _Status: Draft_
- **#17** Tap confirmation · _Bot text: ✓ {choice} (replaces the buttons)_ · _Buttons: —_ · _Status: Draft_

## 2. Messaging error cheat sheet

What the fan sees and what the system does when messaging goes wrong.

- **Fan taps a button**
  - Fan sees: Spinner stops at once; buttons become "✓ Pune"
  - System does: `answerCallbackQuery` (no text), then `editMessageReplyMarkup` once the tap is applied
  - Decision: #92
- **Fan double-taps before buttons disappear**
  - Fan sees: Nothing extra
  - System does: Second tap is stale (step moved on) → ignored; buttons untouched; the webhook hides the stale reply for 60 s after a confirmed tap
  - Decision: #91, #92
- **Telegram delivers the same update twice**
  - Fan sees: Nothing extra
  - System does: Same `update_id` → skipped; unsent replies resent
  - Decision: #90, #55
- **Two messages from a brand-new fan at once**
  - Fan sees: Normal replies, in order
  - System does: Identity lock; second waits
  - Decision: #88
- **Fan taps an old button from earlier in the chat**
  - Fan sees: "That question has passed" (chat message)
  - System does: Ignored; no state change; buttons untouched
  - Decision: #91
- **Fan types text where a tap is expected (or the reverse)**
  - Fan sees: "Please tap one of the options" + buttons again
  - System does: Same step re-asked
  - Decision: A10
- **Tap value not in the current options**
  - Fan sees: "Please tap one of the options"
  - System does: Same step; nothing saved
  - Decision: #13
- **Bug in the engine**
  - Fan sees: "Something went wrong, please tap again" (once)
  - System does: Rolled back; 200 returned; error logged
  - Decision: #71
- **Database down**
  - Fan sees: Nothing yet; reply arrives after recovery
  - System does: 5xx; Telegram retries
  - Decision: #71
- **Our send to Telegram fails**
  - Fan sees: Reply arrives within about 40 s
  - System does: Reply stays `unsent`; sweeper resends
  - Decision: #72
- **Telegram says "too many requests" (429)**
  - Fan sees: Reply slightly delayed
  - System does: Wait `retry_after` seconds, then resend
  - Decision: #69, #93
- **Fan has blocked the bot (403)**
  - Fan sees: —
  - System does: Mark the identity opted out and delete that fan's pending unsent replies (one transaction); stop sending
  - Decision: #93
- **Fan sent `/stop`**
  - Fan sees: "You're unsubscribed."
  - System does: No more messages, announcements skip them
  - Decision: #36
- **Fan sent `/delete`**
  - Fan sees: "Your data is deleted."
  - System does: All fan rows removed; confirmation not stored
  - Decision: #81
- **Web chat page refreshed**
  - Fan sees: Chat starts over
  - System does: Known limit: new fan created
  - Decision: #83
