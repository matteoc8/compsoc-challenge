"""What a submitted problem is meant for: the CompSoc Challenge, a weekly problem, or either.

Revision ID: 0005_problem_use
Revises: 0004_problem_groups
Create Date: 2026-10-10
"""

import sqlalchemy as sa
from alembic import op

revision = "0005_problem_use"
down_revision = "0004_problem_groups"
branch_labels = None
depends_on = None


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if "intended_use" not in {c["name"] for c in insp.get_columns("problem_submissions")}:
        with op.batch_alter_table("problem_submissions") as batch:
            batch.add_column(sa.Column("intended_use", sa.Text(), nullable=False, server_default="either"))


def downgrade() -> None:
    with op.batch_alter_table("problem_submissions") as batch:
        batch.drop_column("intended_use")
