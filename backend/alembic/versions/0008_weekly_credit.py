"""Problem of the week: who submitted it, and when it was copied to Past Weekly Problems.

Revision ID: 0008_weekly_credit
Revises: 0007_year_groups
Create Date: 2026-10-11
"""

import sqlalchemy as sa
from alembic import op

revision = "0008_weekly_credit"
down_revision = "0007_year_groups"
branch_labels = None
depends_on = None

COLUMNS = [sa.Column("credit", sa.Text(), nullable=True), sa.Column("featured_at", sa.DateTime(timezone=True), nullable=True)]


def upgrade() -> None:
    have = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("weekly_problems")}
    missing = [c for c in COLUMNS if c.name not in have]
    if missing:
        with op.batch_alter_table("weekly_problems") as batch:
            for c in missing:
                batch.add_column(c)


def downgrade() -> None:
    with op.batch_alter_table("weekly_problems") as batch:
        for c in COLUMNS:
            batch.drop_column(c.name)
