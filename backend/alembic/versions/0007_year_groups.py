"""Year group (4th, 5th, 6th, L8th, U8th) for problem of the week people.

Revision ID: 0007_year_groups
Revises: 0006_weekly_people
Create Date: 2026-10-11
"""

import sqlalchemy as sa
from alembic import op

revision = "0007_year_groups"
down_revision = "0006_weekly_people"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "year_group" not in {c["name"] for c in sa.inspect(op.get_bind()).get_columns("weekly_people")}:
        with op.batch_alter_table("weekly_people") as batch:
            batch.add_column(sa.Column("year_group", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("weekly_people") as batch:
        batch.drop_column("year_group")
