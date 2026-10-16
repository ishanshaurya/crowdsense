"""P4-C02, Q-18: the dashboard role can read what the dashboard needs and write nothing (#80, #105).

Writes are tried with `default_transaction_read_only` switched off first, so the grants are what
refuses them, not the role's default (which any session could change).
"""

import io
from collections.abc import Iterator
from typing import Any
from urllib.parse import urlsplit

import psycopg
import pytest

from core import demand
from core.config import DASHBOARD_ROLE, ConfigError, load_dashboard_settings
from scripts import dashboard_role
from tests.component.test_demand import SIM, add_real, insert
from tests.conftest import url_of
from tests.support import NOW, decision

PASSWORD = "dash-test-password"  # pragma: allowlist secret
POOLER = "postgresql://{user}:pw@pooler.example.com:6543/postgres"  # pragma: allowlist secret

WRITES = [
    "INSERT INTO fans (is_simulated, created_at, last_seen) VALUES (false, now(), now())",
    "UPDATE fans SET city = 'Pune'",
    "DELETE FROM fans",
    "TRUNCATE fans",
    "INSERT INTO venues VALUES (99, 'Pune', 'X', 10)",
    "UPDATE venues SET capacity = 1",
    "INSERT INTO funnel_counts VALUES ('city', 1)",
    "UPDATE identities SET source_tag = 'x'",
    "DELETE FROM identities",
    "INSERT INTO answers (fan_id, field, value, ts) VALUES (1, 'city', 'Pune', now())",
    "DELETE FROM replies",
    "UPDATE sessions SET step_id = 'done'",
    "CREATE TABLE public.sneaky (id int)",
    "ALTER TABLE fans ADD COLUMN sneaky int",
    "DROP TABLE fans",
    "CREATE INDEX sneaky_idx ON fans (city)",
    "GRANT SELECT ON answers TO PUBLIC",
    "CREATE ROLE sneaky",
]
HIDDEN_READS = [
    "SELECT * FROM answers",
    "SELECT * FROM events",
    "SELECT * FROM replies",
    "SELECT * FROM sessions",
    "SELECT external_user_id FROM identities",
    "SELECT version_num FROM alembic_version",
]


@pytest.fixture
def role_url(pg_migrated_url: str) -> str:
    with psycopg.connect(pg_migrated_url, autocommit=True) as admin:
        insert(admin, SIM, simulated=True)
        add_real(admin)
        dashboard_role.apply(admin, PASSWORD)
    parts = urlsplit(pg_migrated_url)
    return url_of(
        parts.hostname or "", parts.port or 5432, DASHBOARD_ROLE, PASSWORD, parts.path.lstrip("/")
    )


@pytest.fixture
def as_role(role_url: str) -> Iterator[psycopg.Connection[Any]]:
    with psycopg.connect(role_url, autocommit=True) as conn:
        conn.execute("SET default_transaction_read_only = off")
        yield conn


@decision(41, 80, 105)
@pytest.mark.parametrize("statement", WRITES)
def test_p4_c02_q18_every_write_is_refused(as_role, statement: str) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        as_role.execute(statement)


@decision(60, 105)
@pytest.mark.parametrize("query", HIDDEN_READS)
def test_q18_role_cannot_read_what_the_dashboard_does_not_need(as_role, query: str) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        as_role.execute(query)


@decision(105)
def test_q18_role_defaults_to_read_only(role_url: str) -> None:
    with psycopg.connect(role_url, autocommit=True) as conn:
        settings = conn.execute(
            "SELECT current_setting('default_transaction_read_only'), "
            "current_setting('statement_timeout')"
        ).fetchone()
        assert settings == ("on", "5s")
        with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
            conn.execute("DELETE FROM fans")


@decision(57, 105)
def test_the_whole_dashboard_read_path_runs_as_the_role(
    role_url: str, pg_migrated_url: str
) -> None:
    as_owner, as_dashboard = demand.DemandReader(pg_migrated_url), demand.DemandReader(role_url)
    for view in demand.VIEWS:
        got = as_dashboard.report(view, NOW, with_email=True)
        assert got == as_owner.report(view, NOW, with_email=True)
        assert got.counted > 0
    as_owner.close()
    as_dashboard.close()


@decision(105)
def test_role_script_is_idempotent_and_resets_grants(pg_migrated_url: str, role_url: str) -> None:
    with psycopg.connect(pg_migrated_url, autocommit=True) as admin:
        admin.execute(f"GRANT INSERT ON fans TO {DASHBOARD_ROLE}")
        assert dashboard_role.apply(admin, PASSWORD) is False  # exists: updated, not created
        granted = admin.execute(
            "SELECT table_name, privilege_type FROM information_schema.role_table_grants "
            "WHERE grantee = %s ORDER BY 1, 2",
            (DASHBOARD_ROLE,),
        ).fetchall()
        stored = admin.execute(
            "SELECT rolpassword FROM pg_authid WHERE rolname = %s", (DASHBOARD_ROLE,)
        ).fetchone()
    assert granted == [("fans", "SELECT"), ("funnel_counts", "SELECT"), ("venues", "SELECT")]
    assert stored is not None and stored[0].startswith("SCRAM-SHA-256$")


@decision(105)
def test_role_script_never_prints_the_password(pg_migrated_url: str, monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("DATABASE_URL", pg_migrated_url)
    monkeypatch.setenv("DASHBOARD_DB_PASSWORD", PASSWORD)
    dashboard_role.main([])
    dashboard_role.main(["--print-sql"])
    out = capsys.readouterr().out
    assert PASSWORD not in out and "SCRAM-SHA-256$" not in out
    assert f"role {DASHBOARD_ROLE} " in out and "<SCRAM verifier>" in out
    buffer = io.StringIO()
    dashboard_role.print_sql(buffer)
    assert 'GRANT SELECT ("fan_id", "channel", "source_tag") ON identities' in buffer.getvalue()


def test_role_script_refuses_short_password_and_remote_host(pg_migrated_url: str) -> None:
    with psycopg.connect(pg_migrated_url, autocommit=True) as admin, pytest.raises(SystemExit):
        dashboard_role.apply(admin, "short")
    with pytest.raises(SystemExit):
        dashboard_role.guard_host("postgresql://u@db.example.com/x", allow_remote=False)


@decision(60, 63, 105)
def test_dashboard_settings_hide_secrets_and_demand_the_role() -> None:
    url = POOLER.format(user="crowdsense_dashboard.abcref")
    settings = load_dashboard_settings(
        {"DASHBOARD_DATABASE_URL": url, "DASHBOARD_PASSWORD": "x" * 12}
    )
    assert url not in repr(settings) and "x" * 12 not in repr(settings)
    owner = POOLER.format(user="postgres.abcref")
    bad = [
        {"DASHBOARD_PASSWORD": "x" * 12},
        {"DASHBOARD_DATABASE_URL": owner, "DASHBOARD_PASSWORD": "x" * 12},
        {"DASHBOARD_DATABASE_URL": url, "DASHBOARD_PASSWORD": "x" * 11},
    ]
    for environ in bad:
        with pytest.raises(ConfigError) as error:
            load_dashboard_settings(environ)
        assert "pw@" not in str(error.value)
