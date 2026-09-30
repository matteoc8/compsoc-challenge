import re

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import current_team, new_device_token, token_hash
from ..db import get_session
from ..engine.game import engine, sha256
from ..engine.judging import PRACTICE
from ..engine.views import now
from ..limiter import limiter
from ..models import Game, GameState, Team
from ..runtime import rt

router = APIRouter(tags=["join"])

NAME_RE = re.compile(r"^[A-Za-z0-9 _-]{2,24}$")
# A small list; the teacher can still rename or kick. Extend as needed.
# Blocked anywhere in the name, even with separators removed ("f_u_c_k"):
BLOCKED_ANYWHERE = {
    "fuck", "shit", "cunt", "bitch", "wank", "twat", "slut", "whore", "nigger", "nigga",
    "faggot", "retard", "asshole", "bollock", "tosser", "porn", "penis", "vagina",
}
# Blocked only as whole words, so "Sussex", "Peacock" or "Grapes" are fine:
BLOCKED_WORDS = {"sex", "dick", "cock", "fag", "rape", "arse", "prick", "nazi", "hitler", "bastard", "pussy", "tits"}
ALLOWED_ANYWAY = {"scunthorpe"}
LEET = str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "@": "a", "$": "s"})


def validate_team_name(name: str) -> str:
    clean = " ".join(name.split())
    if not NAME_RE.fullmatch(clean):
        raise HTTPException(400, "Team names are 2–24 characters: letters, numbers, spaces, _ and -")
    lowered = clean.lower().translate(LEET)
    for ok in ALLOWED_ANYWAY:
        lowered = lowered.replace(ok, " ")
    letters = re.sub(r"[^a-z]", "", lowered)
    words = set(re.split(r"[^a-z]+", lowered))
    if any(w in letters for w in BLOCKED_ANYWHERE) or words & BLOCKED_WORDS:
        raise HTTPException(400, "Please choose a different team name")
    return clean


class JoinIn(BaseModel):
    code: str | None = Field(default=None, max_length=12)
    team_name: str | None = Field(default=None, max_length=60)
    rejoin_code: str | None = Field(default=None, max_length=12)


@router.post("/join")
@limiter.limit("30/minute")
async def join(request: Request, body: JoinIn, s: AsyncSession = Depends(get_session)):
    token = new_device_token()
    if body.rejoin_code:
        code = body.rejoin_code.strip().upper()
        team = await s.scalar(select(Team).where(Team.rejoin_code_hash == sha256(code)))
        if not team or team.kicked or not team.rejoin_expires_at or team.rejoin_expires_at < now():
            raise HTTPException(400, "That rejoin code is wrong or has expired")
        team.session_token_hash = token_hash(token)
        team.rejoin_code_hash = None
        team.rejoin_expires_at = None
        await s.flush()
        rt.hub.kick_team(str(team.game_id), str(team.id), "Your team was opened on another device.")
        return {"token": token, "team_id": str(team.id), "game_id": str(team.game_id), "name": team.name}

    if not body.code or not body.team_name:
        raise HTTPException(400, "Enter the game code and a team name")
    game = await s.scalar(select(Game).where(Game.join_code == body.code.strip().upper()))
    if not game or game.state == GameState.finished:
        raise HTTPException(404, "No game with that code is running")
    name = validate_team_name(body.team_name)
    if await s.scalar(select(Team.id).where(Team.game_id == game.id, func.lower(Team.name) == name.lower())):
        raise HTTPException(409, "That team name is taken in this game")
    team = Team(game_id=game.id, name=name, session_token_hash=token_hash(token))
    s.add(team)
    await s.flush()
    gid = str(game.id)
    await s.commit()
    await engine.broadcast(gid)
    return {"token": token, "team_id": str(team.id), "game_id": gid, "name": team.name}


@router.get("/team/me")
async def team_me(team: Team = Depends(current_team)):
    return {"team_id": str(team.id), "game_id": str(team.game_id), "name": team.name}


@router.get("/practice")
async def practice():
    return PRACTICE
