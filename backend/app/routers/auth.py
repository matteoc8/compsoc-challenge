from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import COOKIE, any_teacher, hash_password, make_session, set_session_cookie, verify_password
from ..db import get_session
from ..limiter import limiter
from ..models import Teacher

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=200)


class ChangePasswordIn(BaseModel):
    current_password: str = Field(max_length=200)
    new_password: str = Field(min_length=10, max_length=200)


def me(t: Teacher) -> dict:
    return {"id": str(t.id), "username": t.username, "must_change_password": t.must_change_password}


@router.post("/login")
@limiter.limit("20/minute")
async def login(request: Request, body: LoginIn, response: Response, s: AsyncSession = Depends(get_session)):
    t = await s.scalar(select(Teacher).where(Teacher.username == body.username))
    if not t or not verify_password(t.password_hash, body.password):
        raise HTTPException(401, "Wrong username or password")
    set_session_cookie(response, make_session(t.id))
    return me(t)


@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


@router.get("/me")
async def whoami(t: Teacher = Depends(any_teacher)):
    return me(t)


@router.post("/change-password")
async def change_password(body: ChangePasswordIn, t: Teacher = Depends(any_teacher), s: AsyncSession = Depends(get_session)):
    if not verify_password(t.password_hash, body.current_password):
        raise HTTPException(400, "Current password is wrong")
    if body.new_password == body.current_password:
        raise HTTPException(400, "Choose a different password")
    t = await s.get(Teacher, t.id)
    t.password_hash = hash_password(body.new_password)
    t.must_change_password = False
    return me(t)
