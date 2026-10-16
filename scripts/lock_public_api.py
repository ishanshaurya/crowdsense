"""Close Supabase's public API roles out of our tables (#108). Idempotent; run once per database.

    uv run python -m scripts.lock_public_api --print-sql                    # no database
    uv run --env-file .env python -m scripts.lock_public_api --allow-remote  # Supabase, after "go"

Supabase grants `anon` and `authenticated` (the roles behind its REST API and the public anon key)
every privilege on tables in `public`, with row-level security off. This revokes them on every
existing table, sequence and function, and in the owner's default privileges, so tables added by
later migrations stay closed too. Roles that do not exist (plain Postgres) are skipped. The
dashboard role (#105) and the owner are untouched. Prints only privilege flags, never data.
"""

import argparse
import os
import sys
from collections.abc import Sequence
from typing import Any

import psycopg
from psycopg import sql

from scripts.seed import guard_host

API_ROLES = ("anon", "authenticated")
CHECKED_TABLES = (
    "fans",
    "identities",
    "answers",
    "events",
    "replies",
    "sessions",
    "venues",
    "announcement_requests",
)
OBJECTS = ("TABLES", "SEQUENCES", "FUNCTIONS")


def lock_statements(roles: Sequence[str] = API_ROLES) -> list[sql.Composed]:
    names = sql.SQL(", ").join(sql.Identifier(r) for r in roles)
    revoke = "REVOKE ALL ON ALL {kind} IN SCHEMA public FROM {roles}"
    default = "ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON {kind} FROM {roles}"
    return [
        sql.SQL(template).format(kind=sql.SQL(kind), roles=names)
        for template in (revoke, default)
        for kind in OBJECTS
    ]


def existing_roles(conn: psycopg.Connection[Any]) -> list[str]:
    rows = conn.execute(
        "SELECT rolname FROM pg_roles WHERE rolname = ANY(%s) ORDER BY rolname", (list(API_ROLES),)
    ).fetchall()
    return [row[0] for row in rows]


def privileges(conn: psycopg.Connection[Any], roles: Sequence[str]) -> list[tuple[Any, ...]]:
    """(role, table, can_select, can_write) for every checked table that exists."""
    return conn.execute(
        "SELECT r, t, has_table_privilege(r, 'public.' || t, 'SELECT'), "
        "has_table_privilege(r, 'public.' || t, 'INSERT, UPDATE, DELETE, TRUNCATE') "
        "FROM unnest(%s::text[]) r CROSS JOIN unnest(%s::text[]) t "
        "WHERE to_regclass('public.' || t) IS NOT NULL ORDER BY r, t",
        (list(roles), list(CHECKED_TABLES)),
    ).fetchall()


def lock(conn: psycopg.Connection[Any]) -> list[tuple[Any, ...]]:
    """Revoke in one transaction; return the privileges left afterwards (all should be False)."""
    with conn.transaction():
        roles = existing_roles(conn)
        if roles:
            for statement in lock_statements(roles):
                conn.execute(statement)
    return privileges(conn, roles)


def _args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="scripts.lock_public_api")
    parser.add_argument("--allow-remote", action="store_true", help="allow a non-local host")
    parser.add_argument("--print-sql", action="store_true", help="print the SQL; no database")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    args = _args(argv)
    if args.print_sql:
        sys.stdout.writelines(f"{s.as_string()};\n" for s in lock_statements())
        return
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        raise SystemExit("DATABASE_URL is not set")
    host = guard_host(url, args.allow_remote)
    with psycopg.connect(url, prepare_threshold=None) as conn:
        left = lock(conn)
    sys.stdout.write(f"host {host}: revoked from {', '.join(API_ROLES)} where present\n")
    for role, table, select, write in left:
        sys.stdout.write(f"  {role:<13} {table:<10} select={select} write={write}\n")
    if any(select or write for _, _, select, write in left):
        raise SystemExit("some privilege is still open: check grants made by other roles")


if __name__ == "__main__":
    main()
