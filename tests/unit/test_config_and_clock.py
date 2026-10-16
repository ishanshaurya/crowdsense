from datetime import UTC, datetime, timedelta

import pytest

from core.clock import ScriptedClock, SystemClock
from core.config import DEFAULT_ARTIST_NAME, ConfigError, load_settings
from tests.support import NOW, decision

URL = "postgresql://localhost:5432/db"


@decision(63)
def test_settings_are_validated_at_startup() -> None:
    settings = load_settings({"DATABASE_URL": URL, "ARTIST_NAME": " Rhea "})
    assert (settings.database_url, settings.artist_name) == (URL, "Rhea")
    assert load_settings({"DATABASE_URL": URL}).artist_name == DEFAULT_ARTIST_NAME
    for bad in ({}, {"DATABASE_URL": ""}, {"DATABASE_URL": "mysql://x"}):
        with pytest.raises(ConfigError):
            load_settings(bad)


@decision(56)
def test_scripted_clock_moves_only_when_told() -> None:
    clock = ScriptedClock(NOW)
    assert clock.now() == clock.now() == NOW
    clock.advance(timedelta(days=7))
    assert clock.now() == NOW + timedelta(days=7)
    clock.set(NOW)
    assert clock.now() == NOW


@decision(56)
def test_system_clock_is_timezone_aware_utc() -> None:
    now = SystemClock().now()
    assert now.tzinfo is UTC and now > datetime(2026, 1, 1, tzinfo=UTC)
