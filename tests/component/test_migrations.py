import psycopg
import pytest

from core.catalog import VENUES
from tests.conftest import migrate
from tests.support import decision, venue_table

TABLES = {
    "venues",
    "fans",
    "identities",
    "sessions",
    "answers",
    "events",
    "replies",
    "funnel_counts",
}


def tables_in(url: str) -> set[str]:
    with psycopg.connect(url) as conn:
        rows = conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
        ).fetchall()
    return {r[0] for r in rows} - {"alembic_version"}


@decision(24, 26, 39)
def test_p1_c09_migrations_go_up_and_down_and_seed_the_venues(pg_url: str) -> None:
    assert tables_in(pg_url) == set()
    migrate(pg_url)
    assert tables_in(pg_url) == TABLES
    with psycopg.connect(pg_url) as conn:
        seeded = conn.execute("SELECT city, name, capacity FROM venues ORDER BY id").fetchall()
    assert len(seeded) == 14
    assert seeded == venue_table()
    assert seeded == [(v.city, v.name, v.capacity) for v in VENUES]
    migrate(pg_url, "base", down=True)
    assert tables_in(pg_url) == set()
    migrate(pg_url)
    assert tables_in(pg_url) == TABLES


@decision(41)
def test_database_constraints_hold_without_the_python_layer(pg_migrated_url: str) -> None:
    with psycopg.connect(pg_migrated_url, autocommit=True) as conn:
        insert = "INSERT INTO fans (created_at, last_seen, {}) VALUES (now(), now(), %s)"
        for column, bad in (("budget_band", "cheap"), ("group_size", "9")):
            with pytest.raises(psycopg.errors.CheckViolation):
                conn.execute(insert.format(column), (bad,))
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            conn.execute(insert.format("venue_id"), (999,))
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute("INSERT INTO venues (id, city, name, capacity) VALUES (99, 'x', 'y', 0)")


@decision(81)
def test_deleting_a_fan_cascades_to_every_dependent_table(pg_migrated_url: str) -> None:
    with psycopg.connect(pg_migrated_url, autocommit=True) as conn:
        fan_id = conn.execute(
            "INSERT INTO fans (created_at, last_seen) VALUES (now(), now()) RETURNING id"
        ).fetchone()[0]  # type: ignore[index]
        conn.execute(
            "INSERT INTO identities (channel, external_user_id, fan_id) VALUES ('t', '1', %s)",
            (fan_id,),
        )
        conn.execute(
            "INSERT INTO sessions (fan_id, flow_id, step_id, updated_at) "
            "VALUES (%s, 'main', 'consent', now())",
            (fan_id,),
        )
        conn.execute(
            "INSERT INTO answers (fan_id, field, value, ts) VALUES (%s, 'city', 'Pune', now())",
            (fan_id,),
        )
        conn.execute(
            "INSERT INTO events (channel, external_msg_id, fan_id, payload, ts) "
            "VALUES ('t', 'm1', %s, '{}', now())",
            (fan_id,),
        )
        conn.execute(
            "INSERT INTO replies (fan_id, channel, external_msg_id, payload, ts) "
            "VALUES (%s, 't', 'm1', '{}', now())",
            (fan_id,),
        )
        conn.execute("DELETE FROM fans WHERE id = %s", (fan_id,))
        for table in ("identities", "sessions", "answers", "events", "replies"):
            count = conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]  # type: ignore[index]
            assert count == 0, table
