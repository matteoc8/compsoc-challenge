"""The public problems section: anyone can suggest a problem (it lands in the teacher's
review queue), and the teacher publishes featured problems whose solutions students can
reveal on the site if they want to."""

import re
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import mailer
from ..auth import current_teacher
from ..db import get_session
from ..limiter import limiter
from ..models import FeaturedProblem, ProblemGroup, ProblemSubmission, Question, QuestionType, Teacher, utcnow
from ..schemas.question import IOCase, QuestionIn
from .quizzes import _apply, own_question, own_quiz

router = APIRouter(tags=["problems"])

MAX_PENDING = 500  # the public form stops taking new problems once the queue is this long
Difficulty = Literal["easy", "medium", "hard"]
Status = Literal["pending", "accepted", "rejected"]
Use = Literal["challenge", "weekly", "either"]
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def clean_email(v: str) -> str:
    v = v.strip()
    if not EMAIL_RE.match(v):
        raise ValueError("Enter a valid email address")
    return v.lower()


def _uuid(raw: str) -> uuid.UUID:
    try:
        return uuid.UUID(raw)
    except ValueError:
        raise HTTPException(404, "Not found") from None


# ------------------------------------------------------------------ public


class ProblemSubmitIn(BaseModel):
    author_name: str = Field(min_length=1, max_length=60)
    email: str = Field(max_length=200)  # so the teacher can reply; never shown publicly
    title: str = Field(min_length=3, max_length=120)
    intended_use: Use = "either"  # what they'd like it used for
    description_md: str = Field(min_length=10, max_length=10_000)
    examples: list[IOCase] = Field(default_factory=list, max_length=5)
    solution: str = Field(default="", max_length=10_000)
    notes: str = Field(default="", max_length=2_000)
    website: str = Field(default="", max_length=200)  # honeypot: people leave it empty, bots fill it in

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        return clean_email(v)


def public_featured(p: FeaturedProblem) -> dict:
    return {
        "id": str(p.id),
        "title": p.title,
        "difficulty": p.difficulty,
        "credit": p.credit,
        "group_id": str(p.group_id) if p.group_id else None,
        "created_at": p.created_at.isoformat(),
    }


def group_out(g: ProblemGroup) -> dict:
    return {"id": str(g.id), "name": g.name, "description": g.description, "position": g.position}


@router.post("/problems/submit")
@limiter.limit("20/hour")
async def submit_problem(request: Request, body: ProblemSubmitIn, s: AsyncSession = Depends(get_session)):
    if body.website.strip():
        return {"ok": True}  # quietly drop bot submissions
    pending = await s.scalar(select(func.count()).where(ProblemSubmission.status == "pending"))
    if pending >= MAX_PENDING:
        raise HTTPException(503, "The review queue is full right now. Please try again in a few days.")
    s.add(
        ProblemSubmission(
            author_name=body.author_name.strip(),
            email=body.email,
            title=body.title.strip(),
            intended_use=body.intended_use,
            description_md=body.description_md,
            examples=[e.model_dump() for e in body.examples],
            solution=body.solution,
            notes=body.notes,
        )
    )
    return {"ok": True}


async def _sync_past_weeks(s: AsyncSession) -> None:
    from .weekly import feature_past_weeks  # weekly imports this module

    await feature_past_weeks(s)


@router.get("/problems")
async def list_problems(s: AsyncSession = Depends(get_session)):
    await _sync_past_weeks(s)
    rows = (await s.scalars(select(FeaturedProblem).where(FeaturedProblem.published.is_(True)).order_by(FeaturedProblem.created_at.desc()))).all()
    return [public_featured(p) for p in rows]


@router.get("/problems/groups")
async def list_groups(s: AsyncSession = Depends(get_session)):
    """The page's sections in order; the page leaves out any with no published problems."""
    await _sync_past_weeks(s)
    rows = (await s.scalars(select(ProblemGroup).order_by(ProblemGroup.position, ProblemGroup.created_at))).all()
    return [group_out(g) for g in rows]


async def _published(s: AsyncSession, problem_id: str) -> FeaturedProblem:
    p = await s.get(FeaturedProblem, _uuid(problem_id))
    if not p or not p.published:
        raise HTTPException(404, "Problem not found")
    return p


@router.get("/problems/{problem_id}")
async def get_problem(problem_id: str, s: AsyncSession = Depends(get_session)):
    """The problem without its solution, so the page never holds the answer until asked."""
    p = await _published(s, problem_id)
    return {
        **public_featured(p),
        "description_md": p.description_md,
        "examples": p.examples or [],
        "has_solution": bool(p.solution_code.strip() or p.solution_md.strip()),
    }


@router.get("/problems/{problem_id}/solution")
async def get_solution(problem_id: str, s: AsyncSession = Depends(get_session)):
    p = await _published(s, problem_id)
    return {"solution_code": p.solution_code, "solution_md": p.solution_md}


# ------------------------------------------------------------------ teacher: review queue


class ReviewIn(BaseModel):
    status: Status
    teacher_note: str | None = Field(default=None, max_length=500)


class ToQuizIn(BaseModel):
    quiz_id: str
    type: QuestionType = QuestionType.super_fast


def submission_full(p: ProblemSubmission) -> dict:
    return {
        "id": str(p.id),
        "author_name": p.author_name,
        "email": p.email,
        "title": p.title,
        "intended_use": p.intended_use or "either",
        "description_md": p.description_md,
        "examples": p.examples or [],
        "solution": p.solution,
        "notes": p.notes,
        "status": p.status,
        "teacher_note": p.teacher_note,
        "created_at": p.created_at.isoformat(),
        "reviewed_at": p.reviewed_at.isoformat() if p.reviewed_at else None,
        "emailed_at": p.emailed_at.isoformat() if p.emailed_at else None,
    }


async def _submission(s: AsyncSession, submission_id: str) -> ProblemSubmission:
    p = await s.get(ProblemSubmission, _uuid(submission_id))
    if not p:
        raise HTTPException(404, "Submitted problem not found")
    return p


@router.get("/problem-submissions")
async def list_submissions(
    status: Status | None = None, t: Teacher = Depends(current_teacher), s: AsyncSession = Depends(get_session)
):
    q = select(ProblemSubmission).order_by(ProblemSubmission.created_at)
    if status:
        q = q.where(ProblemSubmission.status == status)
    counts = dict((await s.execute(select(ProblemSubmission.status, func.count()).group_by(ProblemSubmission.status))).all())
    return {
        "items": [submission_full(p) for p in (await s.scalars(q)).all()],
        "counts": {k: int(counts.get(k, 0)) for k in ("pending", "accepted", "rejected")},
    }


@router.put("/problem-submissions/{submission_id}")
async def review_submission(
    submission_id: str, body: ReviewIn, t: Teacher = Depends(current_teacher), s: AsyncSession = Depends(get_session)
):
    p = await _submission(s, submission_id)
    p.status = body.status
    p.teacher_note = body.teacher_note
    p.reviewed_at = None if body.status == "pending" else utcnow()
    return submission_full(p)


class EmailIn(BaseModel):
    subject: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=10_000)


@router.get("/email/status")
async def email_status(t: Teacher = Depends(current_teacher)):
    return {"configured": mailer.configured(), "from": mailer.sender() if mailer.configured() else None}


@router.post("/problem-submissions/{submission_id}/email")
async def email_submitter(
    submission_id: str, body: EmailIn, t: Teacher = Depends(current_teacher), s: AsyncSession = Depends(get_session)
):
    """Reply to whoever submitted the problem, from the teacher's own account (SMTP)."""
    p = await _submission(s, submission_id)
    if not p.email:
        raise HTTPException(400, "This problem was submitted without an email address")
    try:
        await mailer.send(p.email, body.subject, body.body)
    except mailer.MailError as e:
        raise HTTPException(503, str(e)) from e
    p.emailed_at = utcnow()
    return submission_full(p)


@router.post("/problem-submissions/{submission_id}/emailed")
async def mark_emailed(submission_id: str, t: Teacher = Depends(current_teacher), s: AsyncSession = Depends(get_session)):
    """The teacher replied from their own mail app (mailto); just record it."""
    p = await _submission(s, submission_id)
    p.emailed_at = utcnow()
    return submission_full(p)


@router.delete("/problem-submissions/{submission_id}")
async def delete_submission(submission_id: str, t: Teacher = Depends(current_teacher), s: AsyncSession = Depends(get_session)):
    await s.delete(await _submission(s, submission_id))
    return {"ok": True}


@router.post("/problem-submissions/{submission_id}/feature")
async def feature_submission(submission_id: str, t: Teacher = Depends(current_teacher), s: AsyncSession = Depends(get_session)):
    """Accept it and start an unpublished featured problem from it, for the teacher to polish."""
    p = await _submission(s, submission_id)
    f = FeaturedProblem(
        owner_id=t.id,
        title=p.title[:120],
        description_md=p.description_md,
        examples=p.examples or [],
        solution_code=p.solution,
        credit=f"Submitted by {p.author_name}"[:80],
        published=False,
        source_submission_id=p.id,
    )
    s.add(f)
    p.status, p.reviewed_at = "accepted", utcnow()
    await s.flush()
    return featured_full(f)


@router.post("/problem-submissions/{submission_id}/to-quiz")
async def submission_to_quiz(
    submission_id: str, body: ToQuizIn, t: Teacher = Depends(current_teacher), s: AsyncSession = Depends(get_session)
):
    """Accept it and add it to a quiz as a coding question (unverified: the teacher still
    adds hidden tests and checks the reference solution)."""
    if body.type == QuestionType.multiple_choice:
        raise HTTPException(400, "Submitted problems become coding questions")
    p = await _submission(s, submission_id)
    quiz = await own_quiz(s, body.quiz_id, t)
    pos = await s.scalar(select(func.coalesce(func.max(Question.position), -1)).where(Question.quiz_id == quiz.id))
    q = Question(quiz_id=quiz.id, position=pos + 1)
    _apply(
        q,
        QuestionIn(
            round_name=f"Round {pos + 2}",
            type=body.type,
            title=p.title[:120],
            description_md=p.description_md + f"\n\n*Submitted by {p.author_name}*",
            reference_solution=p.solution,
            config={"examples": (p.examples or [])[:10], "tests": []},
        ),
    )
    s.add(q)
    quiz.updated_at = utcnow()
    p.status, p.reviewed_at = "accepted", utcnow()
    await s.flush()
    return {"question_id": str(q.id), "quiz_id": str(quiz.id)}


# ------------------------------------------------------------------ teacher: featured problems


class FeaturedIn(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    difficulty: Difficulty = "medium"
    description_md: str = Field(default="", max_length=20_000)
    examples: list[IOCase] = Field(default_factory=list, max_length=10)
    solution_code: str = Field(default="", max_length=10_000)
    solution_md: str = Field(default="", max_length=20_000)
    credit: str | None = Field(default=None, max_length=80)
    published: bool = False
    group_id: str | None = None


def featured_full(p: FeaturedProblem) -> dict:
    return {
        **public_featured(p),
        "description_md": p.description_md,
        "examples": p.examples or [],
        "solution_code": p.solution_code,
        "solution_md": p.solution_md,
        "published": p.published,
        "source_submission_id": str(p.source_submission_id) if p.source_submission_id else None,
        "updated_at": p.updated_at.isoformat(),
    }


async def _own_featured(s: AsyncSession, problem_id: str, t: Teacher) -> FeaturedProblem:
    p = await s.get(FeaturedProblem, _uuid(problem_id))
    if not p or p.owner_id != t.id:
        raise HTTPException(404, "Featured problem not found")
    return p


async def _own_group(s: AsyncSession, group_id: str | None, t: Teacher) -> ProblemGroup | None:
    if not group_id:
        return None
    g = await s.get(ProblemGroup, _uuid(group_id))
    if not g or g.owner_id != t.id:
        raise HTTPException(404, "Group not found")
    return g


async def _apply_featured(s: AsyncSession, p: FeaturedProblem, body: FeaturedIn, t: Teacher) -> None:
    g = await _own_group(s, body.group_id, t)
    for k, v in body.model_dump(exclude={"group_id"}).items():
        setattr(p, k, v)
    p.group_id = g.id if g else None
    p.credit = (body.credit or "").strip() or None
    p.updated_at = utcnow()


@router.get("/featured")
async def list_featured(t: Teacher = Depends(current_teacher), s: AsyncSession = Depends(get_session)):
    await _sync_past_weeks(s)
    rows = (await s.scalars(select(FeaturedProblem).where(FeaturedProblem.owner_id == t.id).order_by(FeaturedProblem.created_at.desc()))).all()
    return [featured_full(p) for p in rows]


@router.post("/featured")
async def create_featured(body: FeaturedIn, t: Teacher = Depends(current_teacher), s: AsyncSession = Depends(get_session)):
    p = FeaturedProblem(owner_id=t.id)
    await _apply_featured(s, p, body, t)
    s.add(p)
    await s.flush()
    return featured_full(p)


@router.get("/featured/{problem_id}")
async def get_featured(problem_id: str, t: Teacher = Depends(current_teacher), s: AsyncSession = Depends(get_session)):
    return featured_full(await _own_featured(s, problem_id, t))


@router.put("/featured/{problem_id}")
async def edit_featured(problem_id: str, body: FeaturedIn, t: Teacher = Depends(current_teacher), s: AsyncSession = Depends(get_session)):
    p = await _own_featured(s, problem_id, t)
    await _apply_featured(s, p, body, t)
    return featured_full(p)


@router.delete("/featured/{problem_id}")
async def delete_featured(problem_id: str, t: Teacher = Depends(current_teacher), s: AsyncSession = Depends(get_session)):
    await s.delete(await _own_featured(s, problem_id, t))
    return {"ok": True}


class FeatureIn(BaseModel):
    group_id: str | None = None
    published: bool = False


def _from_question(q: Question, t: Teacher, g: ProblemGroup | None, published: bool) -> FeaturedProblem:
    return FeaturedProblem(
        owner_id=t.id,
        title=q.title,
        description_md=q.description_md,
        examples=(q.config or {}).get("examples", []),
        solution_code=q.reference_solution,
        published=published,
        group_id=g.id if g else None,
    )


@router.post("/questions/{question_id}/feature")
async def feature_question(
    question_id: str, body: FeatureIn | None = None, t: Teacher = Depends(current_teacher), s: AsyncSession = Depends(get_session)
):
    """A featured problem from a quiz's coding question (e.g. after the event, or a past problem
    of the week). Unpublished unless asked, so it can be polished first."""
    body = body or FeatureIn()
    q, _ = await own_question(s, question_id, t)
    if q.type == QuestionType.multiple_choice:
        raise HTTPException(400, "Only coding questions can be featured")
    p = _from_question(q, t, await _own_group(s, body.group_id, t), body.published)
    s.add(p)
    await s.flush()
    return featured_full(p)


@router.post("/quizzes/{quiz_id}/feature")
async def feature_quiz(quiz_id: str, body: FeatureIn, t: Teacher = Depends(current_teacher), s: AsyncSession = Depends(get_session)):
    """Every coding question in a quiz becomes a featured problem, e.g. all of one event's problems in its group."""
    quiz = await own_quiz(s, quiz_id, t)
    g = await _own_group(s, body.group_id, t)
    qs = (await s.scalars(select(Question).where(Question.quiz_id == quiz.id).order_by(Question.position))).all()
    made = [_from_question(q, t, g, body.published) for q in qs if q.type != QuestionType.multiple_choice]
    if not made:
        raise HTTPException(400, "This quiz has no coding questions")
    s.add_all(made)
    await s.flush()
    return {"created": len(made)}


# ------------------------------------------------------------------ admin: groups


class GroupIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    description: str = Field(default="", max_length=500)


class GroupOrderIn(BaseModel):
    group_ids: list[str] = Field(max_length=200)


async def _owned_groups(s: AsyncSession, t: Teacher) -> list[ProblemGroup]:
    q = select(ProblemGroup).where(ProblemGroup.owner_id == t.id).order_by(ProblemGroup.position, ProblemGroup.created_at)
    return list((await s.scalars(q)).all())


@router.get("/featured-groups")
async def admin_groups(t: Teacher = Depends(current_teacher), s: AsyncSession = Depends(get_session)):
    await _sync_past_weeks(s)
    return [group_out(g) for g in await _owned_groups(s, t)]


@router.post("/featured-groups")
async def create_group(body: GroupIn, t: Teacher = Depends(current_teacher), s: AsyncSession = Depends(get_session)):
    pos = await s.scalar(select(func.coalesce(func.max(ProblemGroup.position), -1)).where(ProblemGroup.owner_id == t.id))
    g = ProblemGroup(owner_id=t.id, name=body.name.strip(), description=body.description.strip(), position=pos + 1)
    s.add(g)
    await s.flush()
    return group_out(g)


@router.put("/featured-groups/order")
async def order_groups(body: GroupOrderIn, t: Teacher = Depends(current_teacher), s: AsyncSession = Depends(get_session)):
    groups = {str(g.id): g for g in await _owned_groups(s, t)}
    if sorted(body.group_ids) != sorted(groups):
        raise HTTPException(400, "The order must list every group once")
    for i, gid in enumerate(body.group_ids):
        groups[gid].position = i
    return [group_out(groups[gid]) for gid in body.group_ids]


@router.put("/featured-groups/{group_id}")
async def edit_group(group_id: str, body: GroupIn, t: Teacher = Depends(current_teacher), s: AsyncSession = Depends(get_session)):
    g = await _own_group(s, group_id, t)
    g.name, g.description = body.name.strip(), body.description.strip()
    return group_out(g)


@router.delete("/featured-groups/{group_id}")
async def delete_group(group_id: str, t: Teacher = Depends(current_teacher), s: AsyncSession = Depends(get_session)):
    """Its problems stay, just without a group."""
    g = await _own_group(s, group_id, t)
    for p in (await s.scalars(select(FeaturedProblem).where(FeaturedProblem.group_id == g.id))).all():
        p.group_id = None
    await s.delete(g)
    return {"ok": True}
