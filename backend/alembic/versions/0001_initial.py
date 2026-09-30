"""Initial schema: nine tables from the build plan, the runs log and the leaderboard view.

Revision ID: 0001_initial
Revises:
Create Date: 2026-09-29
"""

from alembic import op

from app.models import LEADERBOARD_VIEW_SQL, Base

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    # The first migration builds the schema straight from the models so the two can't
    # drift; later migrations should use explicit op.* calls (alembic revision --autogenerate).
    Base.metadata.create_all(bind)
    op.execute(LEADERBOARD_VIEW_SQL)


def downgrade() -> None:
    op.execute("drop view if exists leaderboard")
    Base.metadata.drop_all(op.get_bind())
