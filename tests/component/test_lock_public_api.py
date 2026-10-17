"""#108: Supabase's `anon` / `authenticated` lose every privilege on our tables, now and later.

Plain Postgres has no such roles, so the test creates stand-ins and grants them what Supabase does
(all privileges plus default privileges) before running the script.
"""

from typing import Any

import psycopg
import pytest

from scripts import dashboard_role, lock_public_api
from tests.component.test_dashboard_role import PASSWORD
from tests.conftest import migrate
from tests.support import decision

SUPABASE_LIKE = [
    "GRANT USAGE ON SCHEMA public TO anon, authenticated",
    "GRANT ALL ON ALL TABLES IN SCHEMA public TO anon, authenticated",
    "GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO anon, authenticated",
    "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO anon, authenticated",
]


@pytest.fixture
def admin(pg_migrated_url: str) -> Any:
    with psycopg.connect(pg_migrated_url, autocommit=True) as conn:
        for role in lock_public_api.API_ROLES:
            if not conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,)).fetchone():
                conn.execute(f"CREATE ROLE {role} NOLOGIN")
        for statement in SUPABASE_LIKE:
            conn.execute(statement)
        yield conn


@decision(108)
def test_lock_closes_every_table_for_the_api_roles(admin: psycopg.Connection[Any]) -> None:
    before = lock_public_api.privileges(admin, lock_public_api.API_ROLES)
    assert before and all(select and write for _, _, select, write in before)
    after = lock_public_api.lock(admin)
    assert len(after) == len(lock_public_api.API_ROLES) * len(lock_public_api.CHECKED_TABLES)
    assert not any(select or write for _, _, select, write in after)
    assert lock_public_api.lock(admin) == after  # idempotent


@decision(108)
def test_tables_created_later_stay_closed(admin: psycopg.Connection[Any]) -> None:
    lock_public_api.lock(admin)
    admin.execute("CREATE TABLE public.announcement_requests_probe (id int)")
    open_ = admin.execute(
        "SELECT has_table_privilege('anon', 'public.announcement_requests_probe', 'SELECT')"
    ).fetchone()
    assert open_ == (False,)


@decision(105, 108)
def test_lock_leaves_the_dashboard_role_alone(admin: psycopg.Connection[Any]) -> None:
    dashboard_role.apply(admin, PASSWORD)
    lock_public_api.lock(admin)
    can_read = admin.execute(
        "SELECT has_table_privilege('crowdsense_dashboard', 'public.fans', 'SELECT')"
    ).fetchone()
    assert can_read == (True,)


def test_print_sql_needs_no_database(capsys: pytest.CaptureFixture[str]) -> None:
    lock_public_api.main(["--print-sql"])
    out = capsys.readouterr().out
    assert 'REVOKE ALL ON ALL TABLES IN SCHEMA public FROM "anon", "authenticated";' in out
    assert out.count("ALTER DEFAULT PRIVILEGES") == 3


FUNCTIONS = (
    "announcement_audience(text)",
    "announcement_audience_count(text)",
    "announcement_history()",
)


@decision(80, 108, 115)
def test_migration_0004_closes_its_own_objects_without_the_script(pg_url: str) -> None:
    """Supabase-like roles and default grants already exist when 0004 runs; nothing else is run."""
    migrate(pg_url, "0003")
    with psycopg.connect(pg_url, autocommit=True) as conn:
        for role in lock_public_api.API_ROLES:
            if not conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,)).fetchone():
                conn.execute(f"CREATE ROLE {role} NOLOGIN")
        for statement in SUPABASE_LIKE:
            conn.execute(statement)
        conn.execute(
            "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
            "GRANT ALL ON FUNCTIONS TO anon, authenticated"
        )
    migrate(pg_url)
    with psycopg.connect(pg_url, autocommit=True) as conn:
        for role in lock_public_api.API_ROLES:
            table = conn.execute(
                "SELECT count(*) FROM information_schema.role_table_grants "
                "WHERE grantee = %s AND table_name = 'announcement_requests'",
                (role,),
            ).fetchone()
            assert table == (0,), role
            for fn in FUNCTIONS:
                can = conn.execute(
                    "SELECT has_function_privilege(%s, %s, 'EXECUTE')", (role, fn)
                ).fetchone()
                assert can == (False,), (role, fn)
        rls = conn.execute(
            "SELECT relrowsecurity FROM pg_class WHERE relname = 'announcement_requests'"
        ).fetchone()
        assert rls == (True,)


@decision(108, 115)
def test_after_the_lock_api_roles_hold_no_table_grant_at_all(
    admin: psycopg.Connection[Any],
) -> None:
    lock_public_api.lock(admin)
    for role in lock_public_api.API_ROLES:
        rows = admin.execute(
            "SELECT table_name FROM information_schema.role_table_grants "
            "WHERE grantee = %s AND table_schema = 'public'",
            (role,),
        ).fetchall()
        assert rows == [], role
    assert "announcement_requests" in lock_public_api.CHECKED_TABLES
