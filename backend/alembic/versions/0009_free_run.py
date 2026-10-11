"""Game mode: live (one question at a time) or free_run (all at once, one clock).

Revision ID: 0009_free_run
Revises: 0008_weekly_credit
Create Date: 2026-10-11
"""

import sqlalchemy as sa
from alembic import op

revision = "0009_free_run"
down_revision = "0008_weekly_credit"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "mode" not in {c["name"] for c in sa.inspect(op.get_bind()).get_columns("games")}:
        with op.batch_alter_table("games") as batch:
            batch.add_column(sa.Column("mode", sa.Text(), nullable=False, server_default="live"))


def downgrade() -> None:
    with op.batch_alter_table("games") as batch:
        batch.drop_column("mode")
