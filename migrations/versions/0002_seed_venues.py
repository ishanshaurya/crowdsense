"""Seed the 14 venues from the docs/decisions.md venue table (#24, #39).

Revision ID: 0002
Revises: 0001
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

VENUES = [
    (1, "Mumbai", "Mahalaxmi Maidan", 30000),
    (2, "Mumbai", "Bandra Waterfront", 4000),
    (3, "Delhi NCR", "Dwarka Maidan", 25000),
    (4, "Delhi NCR", "Aerocity Terrace", 3500),
    (5, "Bengaluru", "Whitefield Commons", 20000),
    (6, "Bengaluru", "Indiranagar Yard", 2000),
    (7, "Hyderabad", "Gachibowli Fields", 18000),
    (8, "Pune", "Baner Greens", 12000),
    (9, "Pune", "Koregaon Park Lawns", 6000),
    (10, "Kolkata", "Salt Lake Esplanade", 15000),
    (11, "Chennai", "ECR Seafront", 12000),
    (12, "Ahmedabad", "Sabarmati Riverside", 10000),
    (13, "Jaipur", "Jal Mahal Terrace", 5000),
    (14, "Indore", "Vijay Nagar Commons", 4000),
]


def upgrade() -> None:
    connection = op.get_bind()
    for venue in VENUES:
        connection.exec_driver_sql(
            "INSERT INTO venues (id, city, name, capacity) VALUES (%s, %s, %s, %s)", venue
        )


def downgrade() -> None:
    op.execute("DELETE FROM venues")
