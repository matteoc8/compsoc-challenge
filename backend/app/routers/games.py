"""Teacher game controls. Every transition goes through the engine."""

import secrets
import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .. import analytics
from ..auth import current_teacher
from ..db import get_session, session_scope
from ..engine.game import engine, new_join_code
from ..engine.views import quiz_questions
from ..models import Game, Quiz, Teacher

router = APIRouter(prefix="/games", tags=["games"])


class NewGameIn(BaseModel):
    quiz_id: str


class ExpectIn(BaseModel):
    expect_state: str | None = None


class StartIn(ExpectIn):
    force: bool = False  # start even with no teams


class AdjustTimeIn(BaseModel):
    delta_s: float | None = Field(default=None, ge=-3600, le=3600)
    set_remaining_s: float | None = Field(default=None, ge=1, le=3600)

    @model_validator(mode="after")
    def _one(self):
        if (self.delta_s is None) == (self.set_remaining_s is None):
            raise ValueError("Give exactly one of delta_s or set_remaining_s")
        return self


class PointsIn(BaseModel):
    points: int = Field(ge=-100_000, le=100_000)
    note: str | None = Field(default=None, max_length=120)


class RenameIn(BaseModel):
    name: str = Field(max_length=60)


class SettingsIn(BaseModel):
    allow_negative_totals: bool | None = None
    show_reasons: bool | None = None
    sounds: bool | None = None


class OverrideIn(BaseModel):
    team_id: str
    class_label: str | None = Field(default=None, max_length=40)
    points: int | None = Field(default=None, ge=0, le=100_000)


async def own_game(s: AsyncSession, game_id: str, t: Teacher) -> Game:
    try:
        g = await s.get(Game, uuid.UUID(game_id))
    except ValueError:
        g = None
    if not g or g.owner_id != t.id:
        raise HTTPException(404, "Game not found")
    return g


async def check_owner(game_id: str, t: Teacher) -> None:
    async with session_scope() as s:
        await own_game(s, game_id, t)


def game_summary(g: Game, quiz_title: str | None = None) -> dict:
    return {
        "id": str(g.id),
        "quiz_id": str(g.quiz_id),
        "quiz_title": quiz_title,
        "join_code": g.join_code,
        "state": g.state.value,
        "created_at": g.created_at.isoformat(),
        "screen_token": g.screen_token,
    }


@router.post("")
async def create_game(body: NewGameIn, t: Teacher = Depends(current_teacher)):
    async with session_scope() as s:
        try:
            quiz = await s.get(Quiz, uuid.UUID(body.quiz_id))
        except ValueError:
            quiz = None
        if not quiz or quiz.owner_id != t.id:
            raise HTTPException(404, "Quiz not found")
        qs = await quiz_questions(s, quiz.id)
        if not qs:
            raise HTTPException(409, "Add at least one question first")
        unverified = [q.title for q in qs if not q.verified_at]
        if unverified:
            raise HTTPException(409, "Verify every question first. Not verified: " + ", ".join(unverified))
        quiz_title, quiz_id, settings = quiz.title, quiz.id, dict(quiz.settings or {})
    for _ in range(10):  # retry on the (unlikely) join code collision
        try:
            async with session_scope() as s:
                g = Game(
                    quiz_id=quiz_id,
                    owner_id=t.id,
                    join_code=new_join_code(),
                    screen_token=secrets.token_urlsafe(24),
                    settings={"show_reasons": True, "sounds": True, **settings},
                )
                s.add(g)
                await s.flush()
                return game_summary(g, quiz_title)
        except IntegrityError:
            continue
    raise HTTPException(500, "Could not allocate a join code")


@router.get("")
async def list_games(t: Teacher = Depends(current_teacher), s: AsyncSession = Depends(get_session)):
    rows = (
        await s.execute(
            select(Game, Quiz.title).join(Quiz, Quiz.id == Game.quiz_id).where(Game.owner_id == t.id).order_by(Game.created_at.desc())
        )
    ).all()
    return [game_summary(g, title) for g, title in rows]


@router.get("/{game_id}")
async def get_game(game_id: str, t: Teacher = Depends(current_teacher), s: AsyncSession = Depends(get_session)):
    g = await own_game(s, game_id, t)
    quiz = await s.get(Quiz, g.quiz_id)
    return game_summary(g, quiz.title if quiz else None)


@router.post("/{game_id}/start")
async def start(game_id: str, body: StartIn, t: Teacher = Depends(current_teacher)):
    await check_owner(game_id, t)
    await engine.start(game_id, force=body.force, expect_state=body.expect_state)
    return {"ok": True}


@router.post("/{game_id}/next")
async def next_(game_id: str, body: ExpectIn, t: Teacher = Depends(current_teacher)):
    await check_owner(game_id, t)
    await engine.next(game_id, expect_state=body.expect_state)
    return {"ok": True}


@router.post("/{game_id}/pause")
async def pause(game_id: str, t: Teacher = Depends(current_teacher)):
    await check_owner(game_id, t)
    await engine.pause(game_id)
    return {"ok": True}


@router.post("/{game_id}/resume")
async def resume(game_id: str, t: Teacher = Depends(current_teacher)):
    await check_owner(game_id, t)
    await engine.resume(game_id)
    return {"ok": True}


@router.post("/{game_id}/adjust-time")
async def adjust_time(game_id: str, body: AdjustTimeIn, t: Teacher = Depends(current_teacher)):
    await check_owner(game_id, t)
    await engine.adjust_time(game_id, delta_s=body.delta_s, set_remaining_s=body.set_remaining_s)
    return {"ok": True}


@router.post("/{game_id}/end-now")
async def end_now(game_id: str, t: Teacher = Depends(current_teacher)):
    await check_owner(game_id, t)
    await engine.end_now(game_id)
    return {"ok": True}


@router.post("/{game_id}/results")
async def results(game_id: str, t: Teacher = Depends(current_teacher)):
    await check_owner(game_id, t)
    await engine.goto(game_id, "results")
    return {"ok": True}


@router.post("/{game_id}/leaderboard")
async def leaderboard(game_id: str, t: Teacher = Depends(current_teacher)):
    await check_owner(game_id, t)
    await engine.goto(game_id, "leaderboard")
    return {"ok": True}


@router.post("/{game_id}/podium")
async def podium(game_id: str, t: Teacher = Depends(current_teacher)):
    await check_owner(game_id, t)
    await engine.goto(game_id, "podium")
    return {"ok": True}


@router.post("/{game_id}/results/override")
async def override(game_id: str, body: OverrideIn, t: Teacher = Depends(current_teacher)):
    await check_owner(game_id, t)
    await engine.override_result(game_id, body.team_id, body.class_label, body.points)
    return {"ok": True}


@router.post("/{game_id}/questions/{question_id}/rescore")
async def rescore(game_id: str, question_id: str, t: Teacher = Depends(current_teacher)):
    await check_owner(game_id, t)
    await engine.rescore(game_id, question_id)
    return {"ok": True}


@router.post("/{game_id}/teams/{team_id}/points")
async def points(game_id: str, team_id: str, body: PointsIn, t: Teacher = Depends(current_teacher)):
    await check_owner(game_id, t)
    if body.points == 0:
        raise HTTPException(400, "Enter a non-zero amount")
    await engine.adjust_points(game_id, team_id, body.points, body.note, t.id)
    return {"ok": True}


@router.post("/{game_id}/score-events/{event_id}/undo")
async def undo(game_id: str, event_id: int, t: Teacher = Depends(current_teacher)):
    await check_owner(game_id, t)
    await engine.undo(game_id, event_id, t.id)
    return {"ok": True}


@router.post("/{game_id}/teams/{team_id}/kick")
async def kick(game_id: str, team_id: str, t: Teacher = Depends(current_teacher)):
    await check_owner(game_id, t)
    await engine.kick(game_id, team_id)
    return {"ok": True}


@router.post("/{game_id}/teams/{team_id}/rename")
async def rename(game_id: str, team_id: str, body: RenameIn, t: Teacher = Depends(current_teacher)):
    await check_owner(game_id, t)
    await engine.rename(game_id, team_id, body.name)
    return {"ok": True}


@router.post("/{game_id}/teams/{team_id}/reissue")
async def reissue(game_id: str, team_id: str, t: Teacher = Depends(current_teacher)):
    await check_owner(game_id, t)
    code = await engine.reissue(game_id, team_id)
    return {"rejoin_code": code, "expires_in_s": 900}


@router.post("/{game_id}/settings")
async def settings(game_id: str, body: SettingsIn, t: Teacher = Depends(current_teacher)):
    await check_owner(game_id, t)
    await engine.update_settings(game_id, body.model_dump(exclude_none=True))
    return {"ok": True}


@router.get("/{game_id}/analytics")
async def get_analytics(game_id: str, t: Teacher = Depends(current_teacher), s: AsyncSession = Depends(get_session)):
    g = await own_game(s, game_id, t)
    return await analytics.stats(s, g)


@router.get("/{game_id}/analytics.csv")
async def get_analytics_csv(game_id: str, kind: str = "teams", t: Teacher = Depends(current_teacher), s: AsyncSession = Depends(get_session)):
    g = await own_game(s, game_id, t)
    if kind not in ("teams", "submissions"):
        raise HTTPException(400, "kind is 'teams' or 'submissions'")
    body = await (analytics.teams_csv(s, g) if kind == "teams" else analytics.submissions_csv(s, g))
    return Response(
        body,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="compsoc-{g.join_code}-{kind}.csv"'},
    )

