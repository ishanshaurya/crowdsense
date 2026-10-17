"""Create or update the dashboard's read-only role (#105, Q-18). Idempotent; run once per database.

    DATABASE_URL=postgresql://localhost:5432/dev DASHBOARD_DB_PASSWORD=... \\
        uv run python -m scripts.dashboard_role
    uv run --env-file .env python -m scripts.dashboard_role --allow-remote   # Supabase, after "go"
    uv run python -m scripts.dashboard_role --print-sql                      # no database

Connects with the owner's `DATABASE_URL`. The password is turned into a SCRAM verifier by libpq on
this machine, so the plain password never reaches the server or its logs; it is never printed.
Every grant is revoked first, then SELECT is granted on `fans`, `venues`, `funnel_counts` and three
columns of `identities`. The role also defaults to read-only transactions with a statement
timeout, but the grants are the real guard. Phase 5 (#80): INSERT on two columns of
`announcement_requests` (city, event_date) plus the RLS policy that lets that insert through,
and EXECUTE on the count-only `announcement_audience_count` and the history function
`announcement_history` (#80); never the audience rows or the table.
"""

import argparse
import os
import sys
from collections.abc import Sequence
from typing import Any

import psycopg
from psycopg import sql

from core.config import DASHBOARD_ROLE, MIN_DASHBOARD_PASSWORD
from scripts.seed import guard_host

READ_TABLES = ("fans", "venues", "funnel_counts")
IDENTITY_COLUMNS = ("fan_id", "channel", "source_tag")
REQUEST_COLUMNS = ("city", "event_date")
FUNCTIONS = ("announcement_audience_count(text)", "announcement_history()")
CONNECTION_LIMIT = 5
REDACTED = sql.Literal("<SCRAM verifier>")


def grant_statements(role: str = DASHBOARD_ROLE) -> list[sql.Composed]:
    name = sql.Identifier(role)
    tables = sql.SQL(", ").join(sql.Identifier(t) for t in READ_TABLES)
    columns = sql.SQL(", ").join(sql.Identifier(c) for c in IDENTITY_COLUMNS)
    request_columns = sql.SQL(", ").join(sql.Identifier(c) for c in REQUEST_COLUMNS)
    statements = [
        "ALTER ROLE {r} SET default_transaction_read_only = on",
        "ALTER ROLE {r} SET statement_timeout = '5s'",
        "ALTER ROLE {r} SET idle_in_transaction_session_timeout = '30s'",
        "REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {r}",
        "REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM {r}",
        "REVOKE CREATE ON SCHEMA public FROM {r}",
        "GRANT USAGE ON SCHEMA public TO {r}",
        "GRANT SELECT ON {tables} TO {r}",
        "GRANT SELECT ({columns}) ON identities TO {r}",
        "GRANT INSERT ({request_columns}) ON announcement_requests TO {r}",
        "DROP POLICY IF EXISTS dashboard_insert ON announcement_requests",
        "CREATE POLICY dashboard_insert ON announcement_requests FOR INSERT TO {r} "
        "WITH CHECK (true)",
        *["GRANT EXECUTE ON FUNCTION " + f + " TO {r}" for f in FUNCTIONS],
    ]
    return [
        sql.SQL(s).format(
            r=name,
            tables=tables,
            columns=columns,
            request_columns=request_columns,
        )
        for s in statements
    ]


def login_statement(exists: bool, verifier: sql.Composable, role: str = DASHBOARD_ROLE) -> Any:
    verb = "ALTER ROLE {r} WITH LOGIN" if exists else "CREATE ROLE {r} WITH LOGIN NOINHERIT"
    return sql.SQL(verb + " CONNECTION LIMIT {limit} PASSWORD {p}").format(
        r=sql.Identifier(role), limit=sql.Literal(CONNECTION_LIMIT), p=verifier
    )


def apply(conn: psycopg.Connection[Any], password: str, role: str = DASHBOARD_ROLE) -> bool:
    """Create or update the role and reset its grants in one transaction. True if created."""
    if len(password) < MIN_DASHBOARD_PASSWORD:
        raise SystemExit(f"DASHBOARD_DB_PASSWORD must be at least {MIN_DASHBOARD_PASSWORD} chars")
    verifier = conn.pgconn.encrypt_password(password.encode(), role.encode(), b"scram-sha-256")
    with conn.transaction():
        exists = conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,)).fetchone()
        conn.execute(login_statement(bool(exists), sql.Literal(verifier.decode()), role))
        for statement in grant_statements(role):
            conn.execute(statement)
    return not exists


def print_sql(out: Any) -> None:
    for exists in (False, True):
        label = "-- existing role:" if exists else "-- new role:"
        out.write(f"{label}\n{login_statement(exists, REDACTED).as_string()};\n")
    for statement in grant_statements():
        out.write(f"{statement.as_string()};\n")


def _args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="scripts.dashboard_role")
    parser.add_argument("--allow-remote", action="store_true", help="allow a non-local host")
    parser.add_argument("--print-sql", action="store_true", help="print the SQL; no database")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    args = _args(argv)
    if args.print_sql:
        print_sql(sys.stdout)
        return
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        raise SystemExit("DATABASE_URL is not set")
    password = os.environ.get("DASHBOARD_DB_PASSWORD", "")
    host = guard_host(url, args.allow_remote)
    with psycopg.connect(url, prepare_threshold=None) as conn:
        created = apply(conn, password)
    tables = ", ".join(READ_TABLES) + f", identities ({', '.join(IDENTITY_COLUMNS)})"
    inserts = f"announcement_requests ({', '.join(REQUEST_COLUMNS)})"
    action = "created" if created else "updated"
    sys.stdout.write(
        f"host {host}: role {DASHBOARD_ROLE} {action}; SELECT on {tables}; "
        f"INSERT on {inserts}; EXECUTE on {', '.join(FUNCTIONS)}\n"
    )


if __name__ == "__main__":
    main()
