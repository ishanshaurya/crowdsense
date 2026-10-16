"""Input caps in the database (#95): length limits on events text, source tag, venue note, email.

0001 and 0002 are applied to Supabase, so the limits arrive here instead of editing them.
The engine already cuts text to 1,000 characters and drops bad tags; `venue_note` and `email`
are validated to 200 characters in `core/flow.py`.

Revision ID: 0003
Revises: 0002
"""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

CHECKS = [
    ("events", "events_text_len", "char_length(payload ->> 'text') <= 1000"),
    ("identities", "identities_source_tag_len", "char_length(source_tag) <= 64"),
    ("fans", "fans_venue_note_len", "char_length(venue_note) <= 200"),
    ("fans", "fans_email_len", "char_length(email) <= 200"),
]


def upgrade() -> None:
    for table, name, condition in CHECKS:
        op.execute(f"ALTER TABLE {table} ADD CONSTRAINT {name} CHECK ({condition})")


def downgrade() -> None:
    for table, name, _ in reversed(CHECKS):
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT {name}")
