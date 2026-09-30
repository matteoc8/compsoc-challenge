"""Team endpoints: Run, Submit, drafts."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import current_team
from ..db import get_session
from ..engine import judging
from ..engine.game import engine
from ..limiter import limiter
from ..models import CodeDraft, Game, Question, Team, utcnow

router = APIRouter(tags=["play"])


class RunIn(BaseModel):
    question_id: str = Field(max_length=40)
    code: str = Field(max_length=10_000)
    stdin: str | None = Field(default=None, max_length=10_000)


class SubmitIn(BaseModel):
    question_id: str = Field(max_length=40)
    code: str = Field(max_length=10_000)


class AnswerIn(BaseModel):
    question_id: str = Field(max_length=40)
    choice: int = Field(ge=0, le=3)


class DraftIn(BaseModel):
    code: str = Field(max_length=10_000)


@router.post("/runs", status_code=202)
@limiter.limit("40/minute")
async def create_run(request: Request, body: RunIn, team: Team = Depends(current_team)):
    return await judging.run(team, body.question_id, body.code, body.stdin)


@router.post("/submissions", status_code=202)
@limiter.limit("20/minute")
async def create_submission(request: Request, body: SubmitIn, team: Team = Depends(current_team)):
    return await judging.submit(team, body.question_id, body.code)


@router.post("/answers")
@limiter.limit("30/minute")
async def create_answer(request: Request, body: AnswerIn, team: Team = Depends(current_team)):
    return await engine.answer(team, body.question_id, body.choice)


async def _draft_question(s: AsyncSession, team: Team, question_id: str) -> uuid.UUID:
    game = await s.get(Game, team.game_id)
    try:
        qid = uuid.UUID(question_id)
    except ValueError:
        raise HTTPException(404, "Unknown question") from None
    q = await s.get(Question, qid)
    if not q or q.quiz_id != game.quiz_id:
        raise HTTPException(404, "Unknown question")
    return qid


@router.put("/drafts/{question_id}")
async def save_draft(question_id: str, body: DraftIn, team: Team = Depends(current_team), s: AsyncSession = Depends(get_session)):
    qid = await _draft_question(s, team, question_id)
    d = await s.get(CodeDraft, (team.game_id, qid, team.id))
    if d:
        d.code = body.code
        d.saved_at = utcnow()
    else:
        s.add(CodeDraft(game_id=team.game_id, question_id=qid, team_id=team.id, code=body.code))
    return {"ok": True, "saved_at": utcnow().isoformat()}


@router.get("/drafts/{question_id}")
async def get_draft(question_id: str, team: Team = Depends(current_team), s: AsyncSession = Depends(get_session)):
    qid = await _draft_question(s, team, question_id)
    d = await s.scalar(
        select(CodeDraft).where(CodeDraft.game_id == team.game_id, CodeDraft.question_id == qid, CodeDraft.team_id == team.id)
    )
    return {"code": d.code if d else None, "saved_at": d.saved_at.isoformat() if d else None}
