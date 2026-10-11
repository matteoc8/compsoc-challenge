"""Unlimited-time questions, the submitted-problems queue and featured problems.

0001 builds the schema from the current models, so on a fresh database these already
exist; every step here checks first and only fills in what an older database is missing.

Revision ID: 0002_site_sections
Revises: 0001_initial
Create Date: 2026-10-09
"""

import sqlalchemy as sa
from alembic import op

from app.models import FeaturedProblem, ProblemSubmission

revision = "0002_site_sections"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "unlimited_time" not in {c["name"] for c in insp.get_columns("questions")}:
        with op.batch_alter_table("questions") as batch:
            batch.add_column(sa.Column("unlimited_time", sa.Boolean(), nullable=False, server_default=sa.false()))
    tables = set(insp.get_table_names())
    for model in (ProblemSubmission, FeaturedProblem):  # parent first: featured links to submissions
        if model.__tablename__ not in tables:
            model.__table__.create(bind)


def downgrade() -> None:
    op.drop_table("featured_problems")
    op.drop_table("problem_submissions")
    with op.batch_alter_table("questions") as batch:
        batch.drop_column("unlimited_time")
