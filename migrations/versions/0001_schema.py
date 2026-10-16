"""Conversation schema: venues, fans, identities, sessions, answers, events, replies, funnel_counts.

Revision ID: 0001
Revises:
"""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

STATEMENTS = [
    """
    CREATE TABLE venues (
        id integer PRIMARY KEY,
        city text NOT NULL,
        name text NOT NULL UNIQUE,
        capacity integer NOT NULL CHECK (capacity > 0)
    )
    """,
    """
    CREATE TABLE fans (
        id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        city text,
        venue_id integer REFERENCES venues (id),
        venue_note text,
        budget_band text CHECK (budget_band IN ('lt_1500', '1500_3000', '3000_6000', 'gte_6000')),
        group_size text CHECK (group_size IN ('1', '2', '3_5', '6_plus')),
        email text,
        is_simulated boolean NOT NULL DEFAULT false,
        completed_at timestamptz,
        furthest_step text,
        created_at timestamptz NOT NULL,
        last_seen timestamptz NOT NULL
    )
    """,
    """
    CREATE TABLE identities (
        channel text NOT NULL,
        external_user_id text NOT NULL,
        fan_id bigint REFERENCES fans (id) ON DELETE CASCADE,
        source_tag text,
        consent boolean,
        opted_out boolean NOT NULL DEFAULT false,
        can_message_until timestamptz,
        PRIMARY KEY (channel, external_user_id)
    )
    """,
    "CREATE INDEX identities_fan_id_idx ON identities (fan_id)",
    """
    CREATE TABLE sessions (
        fan_id bigint PRIMARY KEY REFERENCES fans (id) ON DELETE CASCADE,
        flow_id text NOT NULL,
        step_id text NOT NULL,
        updated_at timestamptz NOT NULL
    )
    """,
    """
    CREATE TABLE answers (
        id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        fan_id bigint NOT NULL REFERENCES fans (id) ON DELETE CASCADE,
        field text NOT NULL CHECK (
            field IN ('city', 'venue', 'venue_note', 'budget_band', 'group_size', 'email')
        ),
        value text,
        ts timestamptz NOT NULL
    )
    """,
    "CREATE INDEX answers_fan_field_idx ON answers (fan_id, field, id)",
    """
    CREATE TABLE events (
        channel text NOT NULL,
        external_msg_id text NOT NULL,
        fan_id bigint REFERENCES fans (id) ON DELETE CASCADE,
        direction text NOT NULL DEFAULT 'in' CHECK (direction IN ('in', 'out')),
        payload jsonb NOT NULL,
        ts timestamptz NOT NULL,
        PRIMARY KEY (channel, external_msg_id)
    )
    """,
    "CREATE INDEX events_fan_id_idx ON events (fan_id)",
    """
    CREATE TABLE replies (
        id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        fan_id bigint NOT NULL REFERENCES fans (id) ON DELETE CASCADE,
        channel text NOT NULL,
        external_msg_id text NOT NULL,
        payload jsonb NOT NULL,
        status text NOT NULL DEFAULT 'unsent' CHECK (status IN ('unsent', 'sent')),
        ts timestamptz NOT NULL,
        FOREIGN KEY (channel, external_msg_id) REFERENCES events (channel, external_msg_id)
            ON DELETE CASCADE
    )
    """,
    "CREATE INDEX replies_unsent_idx ON replies (ts) WHERE status = 'unsent'",
    "CREATE INDEX replies_event_idx ON replies (channel, external_msg_id)",
    """
    CREATE TABLE funnel_counts (
        step_id text PRIMARY KEY,
        count bigint NOT NULL DEFAULT 0 CHECK (count >= 0)
    )
    """,
]

DROPS = [
    "DROP TABLE funnel_counts",
    "DROP TABLE replies",
    "DROP TABLE events",
    "DROP TABLE answers",
    "DROP TABLE sessions",
    "DROP TABLE identities",
    "DROP TABLE fans",
    "DROP TABLE venues",
]


def upgrade() -> None:
    for statement in STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    for statement in DROPS:
        op.execute(statement)
