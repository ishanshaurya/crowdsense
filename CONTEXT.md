# Crowdsense

Measures fan demand for live shows before an artist books venues. Fans answer a few questions in a chat app; the artist sees demand and recommendations.

## Language

**Fan**:
A person who started a chat with the bot. Each channel identity counts as its own fan for now.
_Avoid_: user, lead, subscriber

**Simulated fan**:
A made-up fan created by the seed script for the demo. Always labelled, never messaged. A real person using the web chat is not simulated.
_Avoid_: fake fan, dummy, test fan

**Counted fan**:
A fan who has finished the flow at least once. Only counted fans appear in demand numbers; the rest appear only in the funnel. Editing an answer later never uncounts them.
_Avoid_: valid fan, completed fan

**Artist**:
The performer fans sign up for. In the MVP a fictional big Indian pop artist.
_Avoid_: act, band

**Channel**:
The chat app a fan uses to talk to the bot (Telegram first, WhatsApp later).
_Avoid_: platform, portal

**Identity**:
A fan's presence on one channel.
_Avoid_: account, handle

**Source tag**:
Label in the entry link (story, bio, poster) that says where the fan came from.
_Avoid_: UTM, referrer

**Flow**:
The ordered questions asked to a fan, with the rules for what comes next.
_Avoid_: script, survey, form

**Step**:
One question in the flow.
_Avoid_: screen, stage

**Consent**:
The fan's "yes" to getting updates. Asked first; without it no questions follow.
_Avoid_: agreement, subscription

**Opt-out**:
A fan has asked to stop (`/stop`). No more messages are sent to them.
_Avoid_: unsubscribe, block

**Venue**:
A named place with a seat capacity in one city. Names carry no type words (no arena, hall, club).
_Avoid_: hall, arena, stadium

**Budget band**:
One of four ticket-price ranges a fan picks from.
_Avoid_: price range, tier

**Demand**:
How many counted fans want a given city or venue.
_Avoid_: popularity, traffic

**Expected attendance**:
The number of people counted fans would bring to a city, using group size.
_Avoid_: turnout, headcount

**Recommendation**:
A suggestion shown to the artist: venue, price band or city priority.
_Avoid_: prediction, forecast

**Growing city**:
A city whose new counted fans in the last 7 days beat the 7 days before by at least 20%.
_Avoid_: trending, hot

**Announcement**:
The one message the artist sends from the dashboard to counted, consenting, real fans in a city.
_Avoid_: broadcast, blast, notification

**Campaign**:
One artist's effort to measure demand for a show. Not modelled yet (decision 64).
_Avoid_: tour, event
