"""Announcement history for the dashboard (#80, #108): a function, never the table.

The dashboard role can insert a request but cannot read the table (#80). Its Announcements page
lists what was queued, so this adds one SECURITY DEFINER function returning only city, date,
status, recipient count and time, newest first and capped. Like the audience functions in 0004
it is revoked from PUBLIC and the Supabase API roles; `scripts/dashboard_role.py` grants EXECUTE
to the dashboard role.

Revision ID: 0005
Revises: 0004
"""

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

STATEMENTS = [
    """
    CREATE FUNCTION announcement_history()
    RETURNS TABLE (
        city text, event_date date, status text, recipients integer, created_at timestamptz
    )
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path = public, pg_temp
    AS $$
        SELECT r.city, r.event_date, r.status, r.recipients, r.created_at
        FROM announcement_requests r
        ORDER BY r.created_at DESC, r.id DESC
        LIMIT 50
    $$
    """,
    "REVOKE EXECUTE ON FUNCTION announcement_history() FROM PUBLIC",
    """
    DO $$
    DECLARE r text;
    BEGIN
        FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
                EXECUTE format('REVOKE ALL ON FUNCTION announcement_history() FROM %I', r);
            END IF;
        END LOOP;
    END $$
    """,
]


def upgrade() -> None:
    for statement in STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    op.execute("DROP FUNCTION announcement_history()")
