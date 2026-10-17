"""Dashboard sign-in tokens (#60): random, expiring, revocable, bounded."""

from datetime import UTC, datetime, timedelta

from core.clock import ScriptedClock
from core.sessions import MAX_TOKENS, SessionTokens
from tests.support import decision

START = datetime(2026, 10, 17, 9, 0, tzinfo=UTC)


@decision(60)
def test_a_token_is_valid_until_it_expires() -> None:
    clock = ScriptedClock(START)
    tokens = SessionTokens(clock, timedelta(hours=1))
    token = tokens.issue()
    assert tokens.valid(token)
    clock.advance(timedelta(minutes=59))
    assert tokens.valid(token)
    clock.advance(timedelta(minutes=2))
    assert not tokens.valid(token)


@decision(60)
def test_unknown_empty_and_revoked_tokens_are_refused() -> None:
    tokens = SessionTokens(ScriptedClock(START))
    token = tokens.issue()
    assert not tokens.valid("forged") and not tokens.valid("") and not tokens.valid(None)
    tokens.revoke(token)
    assert not tokens.valid(token)
    assert tokens.issue() != tokens.issue()


@decision(60)
def test_the_store_stays_bounded() -> None:
    tokens = SessionTokens(ScriptedClock(START))
    first = tokens.issue()
    for _ in range(MAX_TOKENS):
        tokens.issue()
    assert not tokens.valid(first)
