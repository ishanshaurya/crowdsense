"""Webhook service parts: Telegram settings, pacing, retries, double taps, redaction."""

import logging

import pytest

from adapters.base import RetryAfter, Tap
from api.logs import REDACTED, RedactSecrets
from api.sender import Outcome, Pacer, Sender
from api.taps import RecentTaps
from core.config import ConfigError, load_telegram_settings
from core.types import Reply
from tests.component.telegram_fake import SECRET, TOKEN
from tests.support import decision

GOOD = {
    "TELEGRAM_BOT_TOKEN": TOKEN,
    "TELEGRAM_WEBHOOK_SECRET": SECRET,
    "PUBLIC_URL": "https://a.b.dev/",
}


@decision(63, 66)
def test_telegram_settings_load_and_hide_secrets_from_repr() -> None:
    settings = load_telegram_settings(GOOD)
    assert settings.webhook_url == "https://a.b.dev/hook/telegram"
    assert TOKEN not in repr(settings) and SECRET not in repr(settings)


@decision(63)
@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("TELEGRAM_BOT_TOKEN", ""),
        ("TELEGRAM_BOT_TOKEN", "not-a-token"),
        ("TELEGRAM_WEBHOOK_SECRET", "short"),
        ("TELEGRAM_WEBHOOK_SECRET", "has spaces in it, sixteen+"),
        ("PUBLIC_URL", "http://a.b.dev"),
        ("PUBLIC_URL", "https://a.b.dev/path"),
    ],
)
def test_bad_telegram_settings_raise_a_config_error_without_the_value(
    name: str, value: str
) -> None:
    with pytest.raises(ConfigError, match=name) as error:
        load_telegram_settings({**GOOD, name: value})
    assert TOKEN not in str(error.value) and SECRET not in str(error.value)


class FakeTime:
    def __init__(self) -> None:
        self.now = 100.0
        self.waits: list[float] = []

    def clock(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.waits.append(round(seconds, 3))
        self.now += seconds


@decision(69)
async def test_pacer_spaces_one_chat_by_a_second_and_all_chats_by_a_thirtieth() -> None:
    t = FakeTime()
    pacer = Pacer(clock=t.clock, sleep=t.sleep)
    for chat in ("a", "a", "b", "c"):
        await pacer.wait(chat)
    assert t.waits == [1.0, 0.033, 0.033]


class AlwaysLimited:
    channel = "telegram"

    async def send(self, user: str, reply: Reply) -> None:
        raise RetryAfter(3)


@decision(93)
async def test_sender_gives_up_after_its_attempts_and_leaves_the_reply_unsent() -> None:
    t = FakeTime()
    sender = Sender(None, Pacer(per_chat=0, overall=0), sleep=t.sleep, attempts=3)  # type: ignore[arg-type]
    outcome = await sender.send(AlwaysLimited(), "1", Reply("hi", "x"))  # type: ignore[arg-type]
    assert outcome is Outcome.FAILED and t.waits == [3.0, 3.0, 3.0]


@decision(91, 92)
def test_recent_taps_expire() -> None:
    t = FakeTime()
    taps = RecentTaps(ttl=60, clock=t.clock)
    tap = Tap("q1", "1", 7, "Pune")
    assert not taps.is_double(tap)
    taps.remember(tap)
    assert taps.is_double(Tap("q2", "1", 7, "Delhi"))
    assert not taps.is_double(Tap("q3", "1", 8, "Pune"))
    t.now += 61
    assert not taps.is_double(tap)


def test_redact_filter_replaces_known_secrets() -> None:
    record = logging.LogRecord("x", logging.INFO, "f", 1, "url /bot%s/send", (TOKEN,), None)
    RedactSecrets([TOKEN, ""]).filter(record)
    assert record.getMessage() == f"url /bot{REDACTED}/send"
