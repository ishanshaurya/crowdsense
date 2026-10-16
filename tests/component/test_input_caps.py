"""Input caps (#95) through the engine on both backends, and the 0003 limits in Postgres."""

import psycopg
import pytest

from core.engine import Engine
from core.store import Store
from tests.component.helpers import talk
from tests.conftest import migrate
from tests.support import decision, event


@decision(95)
async def test_p2_c14_oversized_message_is_stored_and_decided_as_its_first_1000_chars(
    engine: Engine, store: Store
) -> None:
    await talk(engine, "u1", [("start", ""), ("choice", "yes")])
    padded = "Pune" + " " * 996 + "Mumbai" * 800  # only the first 1,000 characters say Pune
    assert len(padded) > 5000
    result = await engine.handle(event("text", text=padded, msg_id="big1"))
    assert result.replies[-1].reply.step_id == "venue"
    assert [f.city for f in await store.fans()] == ["Pune"]
    stored = {e.external_msg_id: e.payload["text"] for e in await store.events()}
    assert stored["big1"] == padded[:1000]
    noise = await engine.handle(event("text", text="x" * 5000, msg_id="big2"))
    assert noise.replies[-1].reply.is_error
    assert len({e.external_msg_id: e for e in await store.events()}["big2"].payload["text"]) == 1000


INSERT_FAN = "INSERT INTO fans (created_at, last_seen, {}) VALUES (now(), now(), %s)"


@decision(41, 95)
def test_p2_c15_database_rejects_oversized_values(pg_migrated_url: str) -> None:
    with psycopg.connect(pg_migrated_url, autocommit=True) as conn:
        for column, limit in (("venue_note", 200), ("email", 200)):
            conn.execute(INSERT_FAN.format(column), ("x" * limit,))
            with pytest.raises(psycopg.errors.CheckViolation):
                conn.execute(INSERT_FAN.format(column), ("x" * (limit + 1),))
        tag = "INSERT INTO identities (channel, external_user_id, source_tag) VALUES ('t', %s, %s)"
        conn.execute(tag, ("ok", "x" * 64))
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute(tag, ("long", "x" * 65))
        ev = (
            "INSERT INTO events (channel, external_msg_id, payload, ts) VALUES ('t', %s, %s, now())"
        )
        conn.execute(ev, ("ok", psycopg.types.json.Jsonb({"text": "x" * 1000})))
        conn.execute(ev, ("tap", psycopg.types.json.Jsonb({"text": None})))
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute(ev, ("long", psycopg.types.json.Jsonb({"text": "x" * 1001})))


def _constraints(conn: psycopg.Connection) -> set[str]:  # type: ignore[type-arg]
    rows = conn.execute("SELECT conname FROM pg_constraint WHERE conname LIKE '%\\_len'").fetchall()
    return {r[0] for r in rows}


@decision(95)
def test_p2_c16_caps_migration_up_and_down_on_a_database_at_0002_with_rows(pg_url: str) -> None:
    migrate(pg_url, "0002")
    with psycopg.connect(pg_url, autocommit=True) as conn:
        fan_id = conn.execute(
            "INSERT INTO fans (created_at, last_seen, venue_note, email) "
            "VALUES (now(), now(), 'near the station', 'a@b.co') RETURNING id"
        ).fetchone()[0]  # type: ignore[index]
        conn.execute(
            "INSERT INTO identities (channel, external_user_id, fan_id, source_tag) "
            "VALUES ('telegram', '1', %s, 'ig_story')",
            (fan_id,),
        )
        conn.execute(
            "INSERT INTO events (channel, external_msg_id, fan_id, payload, ts) "
            "VALUES ('telegram', '1', %s, '{\"text\": \"hi\"}', now())",
            (fan_id,),
        )
        assert _constraints(conn) == set()
    migrate(pg_url, "0003")
    with psycopg.connect(pg_url) as conn:
        assert len(_constraints(conn)) == 4
    migrate(pg_url, "0002", down=True)
    with psycopg.connect(pg_url) as conn:
        assert _constraints(conn) == set()
        conn.execute(INSERT_FAN.format("email"), ("x" * 300,))  # limit gone after downgrade
    with pytest.raises(Exception, match="fans_email_len"):
        migrate(pg_url, "0003")  # an oversized row blocks the upgrade instead of being cut
    with psycopg.connect(pg_url) as conn:
        conn.execute("DELETE FROM fans WHERE char_length(email) > 200")
    migrate(pg_url, "0003")
    with psycopg.connect(pg_url) as conn:
        assert conn.execute("SELECT count(*) FROM identities").fetchone() == (1,)
