"""Leaderboard = SUM(points) over score_events per team (the append-only ledger)."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import ScoreEvent, Team


async def team_totals(s: AsyncSession, game_id: uuid.UUID) -> list[dict]:
    """All non-kicked teams with their total, ranked (ties share a rank)."""
    pts = (
        select(ScoreEvent.team_id, func.coalesce(func.sum(ScoreEvent.points), 0).label("points"))
        .where(ScoreEvent.game_id == game_id)
        .group_by(ScoreEvent.team_id)
        .subquery()
    )
    rows = (
        await s.execute(
            select(Team.id, Team.name, func.coalesce(pts.c.points, 0))
            .outerjoin(pts, pts.c.team_id == Team.id)
            .where(Team.game_id == game_id, Team.kicked.is_(False))
        )
    ).all()
    board = [{"team_id": str(tid), "name": name, "points": int(p)} for tid, name, p in rows]
    board.sort(key=lambda r: (-r["points"], r["name"].lower()))
    rank = 0
    prev_points = None
    for i, r in enumerate(board):
        if r["points"] != prev_points:
            rank = i + 1
            prev_points = r["points"]
        r["rank"] = rank
    return board


def with_previous(board: list[dict], last_board: list[dict]) -> list[dict]:
    prev = {r["team_id"]: r for r in (last_board or [])}
    out = []
    for r in board:
        p = prev.get(r["team_id"])
        out.append(
            {
                **r,
                "prev_rank": p["rank"] if p else None,
                "prev_points": p["points"] if p else 0,
            }
        )
    return out


def slim(board: list[dict]) -> list[dict]:
    return [{"team_id": r["team_id"], "name": r["name"], "points": r["points"], "rank": r["rank"]} for r in board]
