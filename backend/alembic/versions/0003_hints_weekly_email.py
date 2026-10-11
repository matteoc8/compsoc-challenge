"""Per-test results, hints, submitter emails and problem of the week.

Like 0002, every step checks first: 0001 builds a fresh database from the current models.

Revision ID: 0003_hints_weekly_email
Revises: 0002_site_sections
Create Date: 2026-10-10
"""

import sqlalchemy as sa
from alembic import op

from app.models import HintGiven, WeeklyEntry, WeeklyProblem

revision = "0003_hints_weekly_email"
down_revision = "0002_site_sections"
branch_labels = None
depends_on = None

NEW_COLUMNS = {
    "submissions": [sa.Column("test_results", sa.JSON(), nullable=True)],
    "problem_submissions": [
        sa.Column("email", sa.Text(), nullable=True),
        sa.Column("emailed_at", sa.DateTime(timezone=True), nullable=True),
    ],
}


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    for table, cols in NEW_COLUMNS.items():
        have = {c["name"] for c in insp.get_columns(table)}
        missing = [c for c in cols if c.name not in have]
        if missing:
            with op.batch_alter_table(table) as batch:
                for c in missing:
                    batch.add_column(c)
    tables = set(insp.get_table_names())
    for model in (HintGiven, WeeklyProblem, WeeklyEntry):  # parents first
        if model.__tablename__ not in tables:
            model.__table__.create(bind)


def downgrade() -> None:
    op.drop_table("weekly_entries")
    op.drop_table("weekly_problems")
    op.drop_table("hints_given")
    for table, cols in NEW_COLUMNS.items():
        with op.batch_alter_table(table) as batch:
            for c in cols:
                batch.drop_column(c.name)
