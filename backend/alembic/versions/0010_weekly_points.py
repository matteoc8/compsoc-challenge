"""Problem of the week: chosen test points and bonus per week, and a bonus set by hand.

Revision ID: 0010_weekly_points
Revises: 0009_free_run
Create Date: 2026-11-09
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0010_weekly_points"
down_revision = "0009_free_run"
branch_labels = None
depends_on = None

JSON = sa.JSON().with_variant(JSONB(), "postgresql")
TABLES = {
    "weekly_problems": [
        sa.Column("test_points", sa.Integer(), nullable=False, server_default="1000"),
        sa.Column("bonus_points", JSON, nullable=True),
    ],
    "weekly_entries": [
        sa.Column("bonus_override", sa.Integer(), nullable=True),
        sa.Column("bonus_override_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("bonus_note", sa.Text(), nullable=True),
    ],
}


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    for table, cols in TABLES.items():
        have = {c["name"] for c in insp.get_columns(table)}
        missing = [c for c in cols if c.name not in have]
        if missing:
            with op.batch_alter_table(table) as batch:
                for c in missing:
                    batch.add_column(c)


def downgrade() -> None:
    for table, cols in TABLES.items():
        with op.batch_alter_table(table) as batch:
            for c in cols:
                batch.drop_column(c.name)
