"""Problem groups (sections of the public problems page), and the seeded account becomes 'admin'.

Like 0002, every step checks first: 0001 builds a fresh database from the current models.

Revision ID: 0004_problem_groups
Revises: 0003_hints_weekly_email
Create Date: 2026-10-10
"""

import sqlalchemy as sa
from alembic import op

from app.models import ProblemGroup

revision = "0004_problem_groups"
down_revision = "0003_hints_weekly_email"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "problem_groups" not in insp.get_table_names():
        ProblemGroup.__table__.create(bind)
    if "group_id" not in {c["name"] for c in insp.get_columns("featured_problems")}:
        with op.batch_alter_table("featured_problems") as batch:
            batch.add_column(sa.Column("group_id", sa.Uuid(), nullable=True))
            batch.create_foreign_key("fk_featured_group", "problem_groups", ["group_id"], ["id"], ondelete="SET NULL")
    # the old default login name; only when it wouldn't clash
    if not bind.execute(sa.text("select 1 from teachers where username = 'admin'")).first():
        bind.execute(sa.text("update teachers set username = 'admin' where username = 'teacher'"))


def downgrade() -> None:
    with op.batch_alter_table("featured_problems") as batch:
        batch.drop_column("group_id")
    op.drop_table("problem_groups")
