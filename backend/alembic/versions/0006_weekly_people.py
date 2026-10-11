"""Problem of the week people: one row per school email, with the name they entered under.

Existing entries are carried over: each email keeps the name from its latest entry.

Revision ID: 0006_weekly_people
Revises: 0005_problem_use
Create Date: 2026-10-11
"""

import sqlalchemy as sa
from alembic import op

from app.models import WeeklyEntry, WeeklyPerson

revision = "0006_weekly_people"
down_revision = "0005_problem_use"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if WeeklyPerson.__tablename__ in sa.inspect(bind).get_table_names():
        return
    WeeklyPerson.__table__.create(bind)
    e = WeeklyEntry.__table__.c
    rows = bind.execute(sa.select(e.email, e.name, e.submitted_at).order_by(e.id)).all()
    people: dict[str, list] = {}
    for email, name, at in rows:
        people.setdefault(email, [name, at])[0] = name  # latest name, first entry's date
    if people:
        op.bulk_insert(
            WeeklyPerson.__table__,
            [{"email": e, "name": n, "banned": False, "created_at": at} for e, (n, at) in people.items()],
        )


def downgrade() -> None:
    op.drop_table("weekly_people")
