"""Announcements (#75, #80, #85): request table, reply priority, audience functions.

The dashboard only asks: a request row holds a city and a date, nothing else it can set. The
webhook service decides the text and the audience. `UNIQUE (city, event_date)` stops a double
submit; a corrected resend for the same show is not allowed, by choice. No `current_date` CHECK
(Postgres never re-checks it as days pass); a past date is refused in code.

Supabase's API roles get nothing here (#108), and RLS is on with no policy; the dashboard role's
INSERT policy is added by `scripts/dashboard_role.py`, since migrations never create that role
(#105). Functions are executable by PUBLIC by default, so that is revoked too.

Revision ID: 0004
Revises: 0003
"""

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

CITIES = (  # core/catalog.py CITIES when this was written; a test keeps them equal
    "Mumbai",
    "Delhi NCR",
    "Bengaluru",
    "Hyderabad",
    "Pune",
    "Kolkata",
    "Chennai",
    "Ahmedabad",
    "Jaipur",
    "Indore",
)
_CITY_LIST = ", ".join("'" + c.replace("'", "''") + "'" for c in CITIES)

STATEMENTS = [
    f"""
    CREATE TABLE announcement_requests (
        id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        city text NOT NULL CHECK (city IN ({_CITY_LIST})),
        event_date date NOT NULL,
        status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'fanned_out')),
        recipients integer,
        created_at timestamptz NOT NULL DEFAULT now(),
        fanned_out_at timestamptz,
        UNIQUE (city, event_date)
    )
    """,
    """
    ALTER TABLE replies
        ADD COLUMN priority smallint NOT NULL DEFAULT 0,
        ADD COLUMN announcement_id bigint
            REFERENCES announcement_requests (id) ON DELETE CASCADE
    """,
    "CREATE UNIQUE INDEX replies_announcement_fan_uq ON replies (announcement_id, fan_id) "
    "WHERE announcement_id IS NOT NULL",
    """
    CREATE FUNCTION announcement_audience(p_city text)
    RETURNS TABLE (fan_id bigint, channel text, external_user_id text)
    LANGUAGE sql STABLE
    SET search_path = public, pg_temp
    AS $$
        SELECT f.id, i.channel, i.external_user_id
        FROM fans f JOIN identities i ON i.fan_id = f.id
        WHERE f.city = p_city
          AND f.completed_at IS NOT NULL
          AND NOT f.is_simulated
          AND i.consent IS TRUE
          AND NOT i.opted_out
          AND i.channel = 'telegram'
    $$
    """,
    """
    CREATE FUNCTION announcement_audience_count(p_city text)
    RETURNS integer
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path = public, pg_temp
    AS $$ SELECT count(*)::integer FROM announcement_audience(p_city) $$
    """,
    "REVOKE EXECUTE ON FUNCTION announcement_audience(text) FROM PUBLIC",
    "REVOKE EXECUTE ON FUNCTION announcement_audience_count(text) FROM PUBLIC",
    """
    DO $$
    DECLARE r text;
    BEGIN
        FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
                EXECUTE format('REVOKE ALL ON announcement_requests FROM %I', r);
                EXECUTE format(
                    'REVOKE ALL ON FUNCTION announcement_audience(text) FROM %I', r);
                EXECUTE format(
                    'REVOKE ALL ON FUNCTION announcement_audience_count(text) FROM %I', r);
            END IF;
        END LOOP;
    END $$
    """,
    "ALTER TABLE announcement_requests ENABLE ROW LEVEL SECURITY",
]

DROPS = [
    "DROP FUNCTION announcement_audience_count(text)",
    "DROP FUNCTION announcement_audience(text)",
    "DROP INDEX replies_announcement_fan_uq",
    "ALTER TABLE replies DROP COLUMN announcement_id, DROP COLUMN priority",
    "DROP TABLE announcement_requests",
]


def upgrade() -> None:
    for statement in STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    for statement in DROPS:
        op.execute(statement)
