import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import get_settings
from .db import get_session
from .models import Team, Teacher

COOKIE = "cc_session"
_ph = PasswordHasher()  # argon2id


def hash_password(pw: str) -> str:
    return _ph.hash(pw)


def verify_password(hash_: str, pw: str) -> bool:
    try:
        return _ph.verify(hash_, pw)
    except (VerificationError, InvalidHashError):
        return False


def make_session(teacher_id: uuid.UUID) -> str:
    s = get_settings()
    exp = datetime.now(timezone.utc) + timedelta(hours=s.session_hours)
    return jwt.encode({"sub": str(teacher_id), "exp": exp, "typ": "teacher"}, s.secret_key, algorithm="HS256")


def read_session(token: str | None) -> uuid.UUID | None:
    if not token:
        return None
    try:
        data = jwt.decode(token, get_settings().secret_key, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None
    if data.get("typ") != "teacher":
        return None
    try:
        return uuid.UUID(data["sub"])
    except (KeyError, ValueError):
        return None


def set_session_cookie(response, token: str) -> None:
    s = get_settings()
    response.set_cookie(
        COOKIE,
        token,
        max_age=s.session_hours * 3600,
        httponly=True,
        samesite="strict",
        secure=s.cookie_secure,
        path="/",
    )


async def teacher_from_cookie(session: AsyncSession, token: str | None) -> Teacher | None:
    tid = read_session(token)
    return await session.get(Teacher, tid) if tid else None


async def any_teacher(request: Request, session: AsyncSession = Depends(get_session)) -> Teacher:
    """Logged-in teacher, even one who still has to change the seeded password."""
    t = await teacher_from_cookie(session, request.cookies.get(COOKIE))
    if not t:
        raise HTTPException(401, "Not logged in")
    return t


async def current_teacher(teacher: Teacher = Depends(any_teacher)) -> Teacher:
    if teacher.must_change_password:
        raise HTTPException(403, "password_change_required")
    return teacher


def new_device_token() -> str:
    return secrets.token_urlsafe(32)  # 32 random bytes


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def team_from_token(session: AsyncSession, token: str | None) -> Team | None:
    if not token:
        return None
    team = await session.scalar(select(Team).where(Team.session_token_hash == token_hash(token)))
    if not team or team.kicked:
        return None
    return team


async def current_team(request: Request, session: AsyncSession = Depends(get_session)) -> Team:
    auth = request.headers.get("authorization", "")
    token = auth[7:] if auth.lower().startswith("bearer ") else None
    team = await team_from_token(session, token)
    if not team:
        raise HTTPException(401, "Unknown or expired team token")
    return team
