"""Quiz and question editing (teacher only)."""

import io
import json
import uuid
import zipfile
from datetime import datetime

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import Response

from ..auth import current_teacher
from ..config import get_settings
from ..db import get_session
from ..engine import judging
from ..engine.serialize import serialize_question_full
from ..media import BadImage, process_image, store
from ..models import Game, Media, Question, Quiz, Submission, Teacher, utcnow
from ..schemas.question import QuestionIn

router = APIRouter(tags=["quizzes"])


class QuizIn(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    settings: dict | None = None


class OrderIn(BaseModel):
    question_ids: list[str]


ALLOWED_SETTINGS = {"allow_negative_totals", "sounds", "show_reasons"}


async def own_quiz(s: AsyncSession, quiz_id: str, teacher: Teacher) -> Quiz:
    try:
        quiz = await s.get(Quiz, uuid.UUID(quiz_id))
    except ValueError:
        quiz = None
    if not quiz or quiz.owner_id != teacher.id:
        raise HTTPException(404, "Quiz not found")
    return quiz


async def own_question(s: AsyncSession, question_id: str, teacher: Teacher) -> tuple[Question, Quiz]:
    try:
        q = await s.get(Question, uuid.UUID(question_id))
    except ValueError:
        q = None
    if not q:
        raise HTTPException(404, "Question not found")
    quiz = await own_quiz(s, str(q.quiz_id), teacher)
    return q, quiz


async def questions_of(s: AsyncSession, quiz_id) -> list[Question]:
    return list((await s.scalars(select(Question).where(Question.quiz_id == quiz_id).order_by(Question.position))).all())


def quiz_summary(quiz: Quiz, questions: list[Question]) -> dict:
    return {
        "id": str(quiz.id),
        "title": quiz.title,
        "settings": quiz.settings or {},
        "updated_at": quiz.updated_at.isoformat(),
        "question_count": len(questions),
        "all_verified": bool(questions) and all(q.verified_at for q in questions),
    }


@router.get("/quizzes")
async def list_quizzes(t: Teacher = Depends(current_teacher), s: AsyncSession = Depends(get_session)):
    quizzes = (await s.scalars(select(Quiz).where(Quiz.owner_id == t.id).order_by(Quiz.updated_at.desc()))).all()
    return [quiz_summary(q, await questions_of(s, q.id)) for q in quizzes]


@router.post("/quizzes")
async def create_quiz(body: QuizIn, t: Teacher = Depends(current_teacher), s: AsyncSession = Depends(get_session)):
    quiz = Quiz(owner_id=t.id, title=body.title, settings={k: v for k, v in (body.settings or {}).items() if k in ALLOWED_SETTINGS})
    s.add(quiz)
    await s.flush()
    return quiz_summary(quiz, [])


@router.get("/quizzes/{quiz_id}")
async def get_quiz(quiz_id: str, t: Teacher = Depends(current_teacher), s: AsyncSession = Depends(get_session)):
    quiz = await own_quiz(s, quiz_id, t)
    qs = await questions_of(s, quiz.id)
    return {**quiz_summary(quiz, qs), "questions": [serialize_question_full(q) for q in qs]}


@router.put("/quizzes/{quiz_id}")
async def update_quiz(quiz_id: str, body: QuizIn, t: Teacher = Depends(current_teacher), s: AsyncSession = Depends(get_session)):
    quiz = await own_quiz(s, quiz_id, t)
    quiz.title = body.title
    if body.settings is not None:
        quiz.settings = {k: v for k, v in body.settings.items() if k in ALLOWED_SETTINGS}
    quiz.updated_at = utcnow()
    return quiz_summary(quiz, await questions_of(s, quiz.id))


@router.delete("/quizzes/{quiz_id}")
async def delete_quiz(quiz_id: str, t: Teacher = Depends(current_teacher), s: AsyncSession = Depends(get_session)):
    quiz = await own_quiz(s, quiz_id, t)
    if await s.scalar(select(func.count()).where(Game.quiz_id == quiz.id)):
        raise HTTPException(409, "This quiz has been used in a game, so it can't be deleted (duplicate it instead)")
    await s.delete(quiz)
    return {"ok": True}


@router.put("/quizzes/{quiz_id}/order")
async def reorder(quiz_id: str, body: OrderIn, t: Teacher = Depends(current_teacher), s: AsyncSession = Depends(get_session)):
    quiz = await own_quiz(s, quiz_id, t)
    qs = {str(q.id): q for q in await questions_of(s, quiz.id)}
    if sorted(body.question_ids) != sorted(qs):
        raise HTTPException(400, "The list must contain every question of this quiz exactly once")
    # Two passes keep the (quiz_id, position) unique constraint happy.
    await s.execute(update(Question).where(Question.quiz_id == quiz.id).values(position=Question.position + 10_000))
    await s.flush()
    for i, qid in enumerate(body.question_ids):
        await s.execute(update(Question).where(Question.id == uuid.UUID(qid)).values(position=i))
    quiz.updated_at = utcnow()
    return {"ok": True}


# ------------------------------------------------------------------ questions


def _apply(q: Question, body: QuestionIn) -> bool:
    """Copy fields; returns True if anything that affects judging changed."""
    new_cfg = body.config.model_dump()
    judged_changed = (
        q.reference_solution != body.reference_solution
        or (q.config or {}) != new_cfg
        or q.type != body.type
    )
    q.round_name = body.round_name
    q.type = body.type
    q.title = body.title
    q.description_md = body.description_md
    q.image_media_id = uuid.UUID(body.image_media_id) if body.image_media_id else None
    q.image_alt = body.image_alt
    q.starter_code = body.starter_code
    q.reference_solution = body.reference_solution
    q.config = new_cfg
    q.time_limit_s = body.time_limit_s
    q.auto_end = body.auto_end.model_dump()
    q.scoring = body.scoring.model_dump()
    q.updated_at = utcnow()
    return judged_changed


async def _check_media(s: AsyncSession, body: QuestionIn, t: Teacher) -> None:
    if body.image_media_id:
        try:
            m = await s.get(Media, uuid.UUID(body.image_media_id))
        except ValueError:
            m = None
        if not m or m.owner_id != t.id:
            raise HTTPException(400, "Unknown image")


@router.post("/quizzes/{quiz_id}/questions")
async def add_question(quiz_id: str, body: QuestionIn, t: Teacher = Depends(current_teacher), s: AsyncSession = Depends(get_session)):
    quiz = await own_quiz(s, quiz_id, t)
    await _check_media(s, body, t)
    pos = await s.scalar(select(func.coalesce(func.max(Question.position), -1)).where(Question.quiz_id == quiz.id))
    q = Question(quiz_id=quiz.id, position=pos + 1)
    _apply(q, body)
    s.add(q)
    quiz.updated_at = utcnow()
    await s.flush()
    return serialize_question_full(q)


@router.get("/questions/{question_id}")
async def get_question(question_id: str, t: Teacher = Depends(current_teacher), s: AsyncSession = Depends(get_session)):
    q, _ = await own_question(s, question_id, t)
    return serialize_question_full(q)


@router.put("/questions/{question_id}")
async def edit_question(question_id: str, body: QuestionIn, t: Teacher = Depends(current_teacher), s: AsyncSession = Depends(get_session)):
    q, quiz = await own_question(s, question_id, t)
    if body.expected_updated_at and q.updated_at and datetime.fromisoformat(body.expected_updated_at) != q.updated_at:
        raise HTTPException(409, {"message": "This question was changed elsewhere", "current": serialize_question_full(q)})
    await _check_media(s, body, t)
    if _apply(q, body):
        q.verified_at = None
    quiz.updated_at = utcnow()
    await s.flush()
    return serialize_question_full(q)


@router.delete("/questions/{question_id}")
async def delete_question(question_id: str, t: Teacher = Depends(current_teacher), s: AsyncSession = Depends(get_session)):
    q, quiz = await own_question(s, question_id, t)
    if await s.scalar(select(func.count()).where(Submission.question_id == q.id)):
        raise HTTPException(409, "Teams have submitted to this question in a game, so it can't be deleted")
    if await s.scalar(select(func.count()).where(Game.current_question_id == q.id)):
        raise HTTPException(409, "This question is in use by a game")
    await s.delete(q)
    await s.flush()
    rest = await questions_of(s, quiz.id)
    await s.execute(update(Question).where(Question.quiz_id == quiz.id).values(position=Question.position + 10_000))
    await s.flush()
    for i, other in enumerate(rest):
        await s.execute(update(Question).where(Question.id == other.id).values(position=i))
    quiz.updated_at = utcnow()
    return {"ok": True}


@router.post("/questions/{question_id}/duplicate")
async def duplicate_question(question_id: str, t: Teacher = Depends(current_teacher), s: AsyncSession = Depends(get_session)):
    q, quiz = await own_question(s, question_id, t)
    pos = await s.scalar(select(func.coalesce(func.max(Question.position), -1)).where(Question.quiz_id == quiz.id))
    copy = Question(
        quiz_id=quiz.id,
        position=pos + 1,
        round_name=q.round_name,
        type=q.type,
        title=(q.title + " (copy)")[:120],
        description_md=q.description_md,
        image_media_id=q.image_media_id,
        image_alt=q.image_alt,
        starter_code=q.starter_code,
        reference_solution=q.reference_solution,
        config=q.config,
        time_limit_s=q.time_limit_s,
        auto_end=q.auto_end,
        scoring=q.scoring,
        verified_at=q.verified_at,
    )
    s.add(copy)
    await s.flush()
    return serialize_question_full(copy)


@router.post("/questions/{question_id}/verify")
async def verify(question_id: str, t: Teacher = Depends(current_teacher), s: AsyncSession = Depends(get_session)):
    q, _ = await own_question(s, question_id, t)
    report = await judging.verify_question(q)
    q.verified_at = utcnow() if report["ok"] else None
    await s.flush()
    return {**report, "question": serialize_question_full(q)}


@router.post("/questions/{question_id}/generate-outputs")
async def generate_outputs(question_id: str, t: Teacher = Depends(current_teacher), s: AsyncSession = Depends(get_session)):
    q, _ = await own_question(s, question_id, t)
    if not q.reference_solution.strip():
        raise HTTPException(400, "Add a reference solution first")
    out = await judging.generate_outputs(q)
    q.config = out["config"]
    q.verified_at = None
    q.updated_at = utcnow()
    await s.flush()
    return {"failures": out["failures"], "question": serialize_question_full(q)}


# ------------------------------------------------------------------ import / export


@router.get("/quizzes/{quiz_id}/export.zip")
async def export_quiz(quiz_id: str, t: Teacher = Depends(current_teacher), s: AsyncSession = Depends(get_session)):
    quiz = await own_quiz(s, quiz_id, t)
    qs = await questions_of(s, quiz.id)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        items = []
        for q in qs:
            d = serialize_question_full(q)
            for k in ("id", "quiz_id", "image_url", "verified_at", "updated_at", "position"):
                d.pop(k, None)
            if q.image_media_id:
                m = await s.get(Media, q.image_media_id)
                if m:
                    name = f"images/{m.id}.webp"
                    with open(m.path, "rb") as f:
                        z.writestr(name, f.read())
                    d["image_file"] = name
            d.pop("image_media_id", None)
            items.append(d)
        z.writestr("quiz.json", json.dumps({"version": 1, "title": quiz.title, "settings": quiz.settings, "questions": items}, indent=2))
    safe = "".join(c if c.isalnum() else "-" for c in quiz.title)[:40] or "quiz"
    return Response(
        buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{safe}.zip"'},
    )


@router.post("/quizzes/import")
async def import_quiz(file: UploadFile = File(...), t: Teacher = Depends(current_teacher), s: AsyncSession = Depends(get_session)):
    raw = await file.read(20_000_001)
    if len(raw) > 20_000_000:
        raise HTTPException(413, "Zip is over 20 MB")
    try:
        z = zipfile.ZipFile(io.BytesIO(raw))
        data = json.loads(z.read("quiz.json"))
    except (zipfile.BadZipFile, KeyError, json.JSONDecodeError) as e:
        raise HTTPException(400, "Not a CompSoc Challenge quiz export") from e
    return await import_quiz_data(s, t, data, z)


async def import_quiz_data(s: AsyncSession, t: Teacher, data: dict, z: zipfile.ZipFile | None = None) -> dict:
    quiz = Quiz(owner_id=t.id, title=str(data.get("title") or "Imported quiz")[:120], settings=data.get("settings") or {})
    s.add(quiz)
    await s.flush()
    for i, item in enumerate(data.get("questions", [])):
        media_id = None
        if z is not None and item.get("image_file"):
            try:
                img, w, h = process_image(z.read(item["image_file"]))
            except (KeyError, BadImage) as e:
                raise HTTPException(400, f"Bad image in question {i + 1}") from e
            mid, path = store(get_settings().media_dir, img)
            s.add(Media(id=mid, owner_id=t.id, path=path, width=w, height=h, bytes=len(img)))
            await s.flush()
            media_id = str(mid)
        fields = {k: v for k, v in item.items() if k in QuestionIn.model_fields and k != "image_media_id"}
        try:
            body = QuestionIn(**fields, image_media_id=media_id)
        except ValueError as e:
            raise HTTPException(400, f"Question {i + 1} is invalid: {e}") from e
        q = Question(quiz_id=quiz.id, position=i)
        _apply(q, body)
        s.add(q)
    await s.flush()
    return quiz_summary(quiz, await questions_of(s, quiz.id))
