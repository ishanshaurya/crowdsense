"""Migration 0004 (#75, #80, #85): request table, reply priority, and the announcement audience."""

import importlib
from typing import Any

import psycopg
import pytest

from core.catalog import CITIES
from tests.conftest import migrate
from tests.support import decision

Conn = psycopg.Connection[Any]


@pytest.fixture
def db(pg_migrated_url: str) -> Any:
    with psycopg.connect(pg_migrated_url, autocommit=True) as conn:
        yield conn


def add_fan(
    conn: Conn,
    user: str,
    *,
    city: str = "Pune",
    completed: bool = True,
    simulated: bool = False,
    consent: bool | None = True,
    opted_out: bool = False,
    channel: str = "telegram",
) -> int:
    fan_id: int = conn.execute(
        "INSERT INTO fans (city, is_simulated, completed_at, created_at, last_seen) "
        "VALUES (%s, %s, CASE WHEN %s THEN now() END, now(), now()) RETURNING id",
        (city, simulated, completed),
    ).fetchone()[0]  # type: ignore[index]
    conn.execute(
        "INSERT INTO identities (channel, external_user_id, fan_id, consent, opted_out) "
        "VALUES (%s, %s, %s, %s, %s)",
        (channel, user, fan_id, consent, opted_out),
    )
    return fan_id


def audience(conn: Conn, city: str = "Pune") -> list[tuple[Any, ...]]:
    return conn.execute("SELECT * FROM announcement_audience(%s)", (city,)).fetchall()


@decision(75)
def test_migration_cities_match_the_catalog() -> None:
    migration = importlib.import_module("migrations.versions.0004_announcements")
    assert migration.CITIES == CITIES


@decision(75, 80)
def test_0004_goes_down_and_up_again(pg_migrated_url: str) -> None:
    migrate(pg_migrated_url, "0003", down=True)
    with psycopg.connect(pg_migrated_url) as conn:
        gone = conn.execute("SELECT to_regclass('public.announcement_requests')").fetchone()
        columns = conn.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'replies'"
        ).fetchall()
    assert gone == (None,)
    assert {"priority", "announcement_id"}.isdisjoint(c[0] for c in columns)
    migrate(pg_migrated_url)
    with psycopg.connect(pg_migrated_url) as conn:
        back = conn.execute("SELECT to_regclass('public.announcement_requests')").fetchone()
    assert back == ("announcement_requests",)


@decision(75, 112)
def test_one_request_per_city_and_date(db: Conn) -> None:
    insert = "INSERT INTO announcement_requests (city, event_date) VALUES (%s, '2026-12-01')"
    db.execute(insert, ("Pune",))
    with pytest.raises(psycopg.errors.UniqueViolation):
        db.execute(insert, ("Pune",))
    db.execute(insert, ("Mumbai",))  # another city, same date: fine


@decision(75, 109)
def test_request_city_must_be_a_catalog_city(db: Conn) -> None:
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute(
            "INSERT INTO announcement_requests (city, event_date) VALUES ('Atlantis', '2026-12-01')"
        )


@decision(75, 109)
def test_request_id_cannot_be_chosen(db: Conn) -> None:
    with pytest.raises(psycopg.errors.GeneratedAlways):
        db.execute(
            "INSERT INTO announcement_requests (id, city, event_date) "
            "VALUES (7, 'Pune', '2026-12-01')"
        )


@decision(80, 111)
def test_existing_replies_get_chat_priority(db: Conn) -> None:
    fan_id = add_fan(db, "1")
    db.execute(
        "INSERT INTO events (channel, external_msg_id, fan_id, payload, ts) "
        "VALUES ('telegram', 'm1', %s, '{}', now())",
        (fan_id,),
    )
    db.execute(
        "INSERT INTO replies (fan_id, channel, external_msg_id, payload, ts) "
        "VALUES (%s, 'telegram', 'm1', '{}', now())",
        (fan_id,),
    )
    row = db.execute("SELECT priority, announcement_id FROM replies").fetchone()
    assert row == (0, None)


@decision(85, 110)
def test_audience_includes_a_counted_consented_real_telegram_fan(db: Conn) -> None:
    fan_id = add_fan(db, "good")
    assert audience(db) == [(fan_id, "telegram", "good")]
    count = db.execute("SELECT announcement_audience_count('Pune')").fetchone()
    assert count == (1,)


EXCLUDED: dict[str, dict[str, Any]] = {
    "not completed": {"completed": False},
    "consent refused": {"consent": False},
    "consent unanswered": {"consent": None},
    "opted out": {"opted_out": True},
    "simulated": {"simulated": True},
    "web chat cannot push": {"channel": "web_sim"},
    "seeded channel": {"channel": "seed"},
    "other city": {"city": "Mumbai"},
}


@decision(76, 85, 102, 110)
@pytest.mark.parametrize("why", EXCLUDED)
def test_audience_excludes(db: Conn, why: str) -> None:
    add_fan(db, "bad", **EXCLUDED[why])
    assert audience(db) == []
    assert db.execute("SELECT announcement_audience_count('Pune')").fetchone() == (0,)


@decision(85, 110)
def test_count_matches_the_audience(db: Conn) -> None:
    for n in range(3):
        add_fan(db, f"ok{n}")
    for n, why in enumerate(EXCLUDED):
        add_fan(db, f"bad{n}", **EXCLUDED[why])
    rows = audience(db)
    count = db.execute("SELECT announcement_audience_count('Pune')").fetchone()
    assert len(rows) == 3 and count == (3,)


@decision(108, 115)
def test_rls_is_on_and_functions_are_not_public(db: Conn) -> None:
    rls = db.execute(
        "SELECT relrowsecurity FROM pg_class WHERE relname = 'announcement_requests'"
    ).fetchone()
    assert rls == (True,)
    if not db.execute("SELECT 1 FROM pg_roles WHERE rolname = 'stranger'").fetchone():
        db.execute("CREATE ROLE stranger NOLOGIN")  # roles are cluster-wide
    for fn in ("announcement_audience(text)", "announcement_audience_count(text)"):
        can = db.execute("SELECT has_function_privilege('stranger', %s, 'EXECUTE')", (fn,))
        assert can.fetchone() == (False,), fn
