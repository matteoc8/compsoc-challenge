"""Problem of the week. The teacher picks a verified coding question from one of their quizzes
and sets when it opens and closes; anyone at school enters their full name and school email, runs
and submits code. Points: the week's test points shared over the hidden tests, plus a bonus for
the best full solves by the question's own rule (fewest characters, or fastest at scale), and an
admin can set anyone's bonus by hand. The email links someone's entries across weeks, and the name is fixed to
it at first entry. Weekly points add up into a school-wide leaderboard for this week, this month,
this school year or all time. Emails are never public."""

import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import current_teacher
from ..config import get_settings
from ..db import get_session, session_scope
from ..engine import judging
from ..engine.scoring import tie_groups, weekly_bonus, weekly_test_points
from ..engine.serialize import serialize_question
from ..engine.views import now
from ..judge import speed
from ..judge.client import ACCEPTED, ExecRequest, JudgeUnavailable, outputs_match, status_text
from ..judge.golf import golf_chars
from ..judge.queue import WEEKLY
from ..limiter import limiter
from ..models import FeaturedProblem, ProblemGroup, Question, QuestionType, Quiz, Teacher, WeeklyEntry, WeeklyPerson, WeeklyProblem
from ..runtime import rt
from ..schemas.question import QuestionConfig
from .problems import clean_email

router = APIRouter(tags=["weekly"])

# Weekly scoring, per week: test_points shared over the hidden tests, plus a bonus for the best
# full solves (1st, 2nd, 3rd...). Defaults below; the admin can change them for each week.
DEFAULT_TEST_POINTS = 1000
DEFAULT_BONUS = [500, 300, 150]
# Fastest Code (best_complexity) and Code Golf. Super Fast ("first to solve it") isn't offered:
# over a whole week it mostly rewards whoever sees the problem first.
WEEKLY_TYPES = (QuestionType.best_complexity, QuestionType.code_golf)
SUBMIT_COOLDOWN_S = 10
SUBMIT_MAX = 30  # per person per week
IN_FLIGHT = ("queued", "running", "measuring")
_last_submit: dict[str, float] = {}
_bench_cache: dict[tuple, tuple] = {}  # (question id, updated_at) -> (baseline, reference run)
try:
    SCHOOL_TZ = ZoneInfo("Europe/London")  # where "this week" and "this month" start
except ZoneInfoNotFoundError:  # no tzdata installed
    SCHOOL_TZ = timezone.utc


def _uuid(raw: str) -> uuid.UUID:
    try:
        return uuid.UUID(raw)
    except ValueError:
        raise HTTPException(404, "Not found") from None


def phase(w: WeeklyProblem, at: datetime | None = None) -> str:
    at = at or now()
    return "upcoming" if at < w.opens_at else "closed" if at >= w.closes_at else "open"


# ------------------------------------------------------------------ standings


def bonus_of(w: WeeklyProblem) -> list[int]:
    return list(w.bonus_points) if w.bonus_points is not None else list(DEFAULT_BONUS)


def _measure_of(q: Question, e: WeeklyEntry, opens_at: datetime) -> tuple | None:
    """The round's own measure for a full pass, lower is better. None = not measured."""
    if q.type == QuestionType.code_golf:
        return (e.char_count,)
    if q.type == QuestionType.best_complexity:
        return speed.rank_key(e.perf)
    return (max((e.submitted_at - opens_at).total_seconds() * 1000, 0),)  # older Super Fast weeks


def tie_share(q: Question) -> float:
    """Fastest Code times within 20% are a tie; characters and solve order must be equal."""
    return speed.TIE_SHARE if q.type == QuestionType.best_complexity else 0.0


def standings(w: WeeklyProblem, q: Question, entries: list[WeeklyEntry], people: dict[str, WeeklyPerson], with_email: bool = False) -> list[dict]:
    """Each person's best entry (most tests passed, then the best measure). Points are the
    week's test points for the share of hidden tests passed, plus a bonus by place among
    full passes (ties: scoring.tie_groups). A bonus set by hand on any of someone's entries
    replaces only their bonus (the latest edit counts; test points stay automatic): they
    keep their place and nobody else's bonus changes. Only admins (with_email) see that it
    was set by hand. Banned people are left out and everyone is shown under the name
    on their email."""
    names: dict[str, str] = {}
    best: dict[str, tuple[tuple, WeeklyEntry]] = {}
    manual: dict[str, WeeklyEntry] = {}
    for e in sorted(entries, key=lambda x: x.id):
        person = people.get(e.email)
        if person and person.banned:
            continue
        names[e.email] = person.name if person else e.name
        if e.bonus_override is not None:
            cur = manual.get(e.email)
            if cur is None or (e.bonus_override_at or e.submitted_at) >= (cur.bonus_override_at or cur.submitted_at):
                manual[e.email] = e
        if e.status != "judged" or not e.tests_total:
            continue
        m = _measure_of(q, e, w.opens_at) if e.tests_passed == e.tests_total else None
        # more tests, then measured, then the better measure, then the earlier entry
        key = (e.tests_passed or 0, m is not None, tuple(-x for x in m) if m else (), -e.id)
        if e.email not in best or key > best[e.email][0]:
            best[e.email] = (key, e)
    measures = {email: _measure_of(q, e, w.opens_at) for email, (_, e) in best.items() if e.tests_passed == e.tests_total}
    bonus = weekly_bonus(bonus_of(w), measures, tie_share(q))
    places = tie_groups(measures, tie_share(q))
    rows = []
    for email in set(best) | set(manual):
        e = best[email][1] if email in best else manual[email]
        perf = (e.perf or {}) if q.type == QuestionType.best_complexity else {}
        tests = weekly_test_points(w.test_points, e.tests_passed or 0, e.tests_total or 0) if email in best else 0
        m = manual.get(email)
        if m:
            b = m.bonus_override
        else:
            b = bonus.get(email, 0) if tests == w.test_points else 0  # only on top of the full test points
        key = measures.get(email)
        row = {
            "name": names[email],
            "passed": e.tests_passed,
            "total": e.tests_total,
            "points": tests + b,
            "test_points": tests,
            "bonus": b,
            "chars": e.char_count if q.type == QuestionType.code_golf else None,
            "class_label": speed.describe(perf) if perf else None,
            "time_ms": perf.get("top_ms"),
            "tier": perf.get("tier"),
            "tiers": perf.get("tiers"),
            "floor_ms": None,
            "solved_after_ms": key[0] if q.type == QuestionType.super_fast and key else None,
            "submitted_at": e.submitted_at.isoformat(),
            "_order": (places.get(email, len(places)), key or (float("inf"),)),
        }
        if with_email:
            row["email"] = email
            row["entry_id"] = e.id
            row["manual_bonus"] = m is not None
            row["vs_reference"] = perf.get("vs_reference")
            if m:
                row["manual_entry_id"], row["bonus_note"] = m.id, m.bonus_note
        rows.append(row)
    rows.sort(key=lambda r: (-r["points"], -(r["passed"] or 0), r["_order"], r["name"].lower()))
    for i, r in enumerate(rows):
        same = i > 0 and r["points"] == rows[i - 1]["points"]
        r["rank"] = rows[i - 1]["rank"] if same else i + 1
        del r["_order"]
    return rows


async def _entries(s: AsyncSession, weekly_id) -> list[WeeklyEntry]:
    return list((await s.scalars(select(WeeklyEntry).where(WeeklyEntry.weekly_id == weekly_id))).all())


async def _people(s: AsyncSession) -> dict[str, WeeklyPerson]:
    return {p.email: p for p in (await s.scalars(select(WeeklyPerson))).all()}


Period = Literal["week", "month", "year", "all"]
TUESDAY = 1  # weeks run Tuesday to Tuesday
YearGroup = Literal["4", "5", "6", "L8", "U8"]
YEARS = ("4", "5", "6", "L8", "U8")
GROUPS: dict[str, set[str]] = {"juniors": {"4", "5", "6"}, "seniors": {"L8", "U8"}, **{y: {y} for y in YEARS}}


def parse_groups(raw: str) -> set[str] | None:
    """"all", or a comma list of year groups and/or juniors/seniors. None means everyone."""
    parts = [x.strip() for x in raw.split(",") if x.strip()]
    if not parts or "all" in parts:
        return None
    if any(x not in GROUPS for x in parts):
        raise HTTPException(422, "Unknown year group")
    return set().union(*(GROUPS[x] for x in parts))


def period_start(period: Period, at: datetime | None = None) -> datetime | None:
    """Start of this week (Tuesday, when problems change over), this month or this school year
    (1 September), school time."""
    if period == "all":
        return None
    local = (at or now()).astimezone(SCHOOL_TZ)
    day = local.replace(hour=0, minute=0, second=0, microsecond=0)
    if period == "week":
        start = day - timedelta(days=(local.weekday() - TUESDAY) % 7)
    elif period == "month":
        start = day.replace(day=1)
    else:
        start = day.replace(year=local.year if local.month >= 9 else local.year - 1, month=9, day=1)
    return start  # wall-clock midnight, so the clock change doesn't shift it


# ------------------------------------------------------------------ public


def summary(w: WeeklyProblem, q: Question) -> dict:
    return {
        "id": str(w.id),
        "title": q.title,
        "type": q.type.value,
        "opens_at": w.opens_at.isoformat(),
        "closes_at": w.closes_at.isoformat(),
        "phase": phase(w),
        "credit": w.credit,
        "test_points": w.test_points,
        "bonus_points": bonus_of(w),
    }


async def _public(s: AsyncSession, weekly_id: str) -> tuple[WeeklyProblem, Question]:
    w = await s.get(WeeklyProblem, _uuid(weekly_id))
    if not w or not w.published or phase(w) == "upcoming":
        raise HTTPException(404, "Problem not found")
    return w, await s.get(Question, w.question_id)


@router.get("/weekly")
async def weekly_index(s: AsyncSession = Depends(get_session)):
    rows = (await s.scalars(select(WeeklyProblem).where(WeeklyProblem.published.is_(True)).order_by(WeeklyProblem.opens_at.desc()))).all()
    out = {"current": None, "past": [], "next_opens_at": None}
    for w in rows:
        q = await s.get(Question, w.question_id)
        p = phase(w)
        if p == "open" and out["current"] is None:
            out["current"] = summary(w, q)
        elif p == "closed":
            out["past"].append(summary(w, q))
        elif p == "upcoming":
            nxt = out["next_opens_at"]
            out["next_opens_at"] = min(nxt, w.opens_at.isoformat()) if nxt else w.opens_at.isoformat()
    return out


@router.get("/weekly/leaderboard")
async def school_leaderboard(period: Period = "all", group: str = "all", s: AsyncSession = Depends(get_session)):
    """Everyone's weekly points added up, over every published week that has opened. A week
    counts towards a period if it was open at some point during it. `group` keeps some year
    groups (e.g. "4,5", or "juniors" for 4th to 6th, "seniors" for L8th and U8th)."""
    start = period_start(period)
    weeks = [
        w
        for w in (await s.scalars(select(WeeklyProblem).where(WeeklyProblem.published.is_(True)).order_by(WeeklyProblem.opens_at))).all()
        if phase(w) != "upcoming" and (start is None or w.closes_at > start)
    ]
    people = await _people(s)
    keep = parse_groups(group)
    totals: dict[str, dict] = {}
    for w in weeks:
        q = await s.get(Question, w.question_id)
        for r in standings(w, q, await _entries(s, w.id), people, with_email=True):
            year = people[r["email"]].year_group if r["email"] in people else None
            if keep is not None and year not in keep:
                continue
            t = totals.setdefault(r["email"], {"name": r["name"], "year_group": year, "points": 0, "weeks": 0, "wins": 0})
            t["points"] += r["points"]
            t["weeks"] += 1
            t["wins"] += 1 if r["rank"] == 1 and r["points"] > 0 else 0
    rows = sorted(totals.values(), key=lambda t: (-t["points"], -t["wins"], t["name"].lower()))
    for i, r in enumerate(rows):
        r["rank"] = rows[i - 1]["rank"] if i and r["points"] == rows[i - 1]["points"] else i + 1
    return {"rows": rows, "weeks": len(weeks), "period": period, "group": group}


@router.get("/weekly/{weekly_id}")
async def weekly_detail(weekly_id: str, s: AsyncSession = Depends(get_session)):
    w, q = await _public(s, weekly_id)
    question = serialize_question(q, "team")  # no hidden tests, harness or reference solution
    for k in ("round_name", "position", "time_limit_s", "unlimited_time", "scoring", "scoring_max", "rule_line", "golf_rule"):
        question.pop(k, None)
    out = {
        **summary(w, q),
        "question": question,
        "standings": standings(w, q, await _entries(s, w.id), await _people(s)),
        "email_domain": get_settings().school_email_domain.strip().lower().lstrip("@") or None,
    }
    if phase(w) == "closed" and w.solution_published:
        out["solution"] = q.reference_solution
    return out


class RunIn(BaseModel):
    code: str = Field(max_length=judging.MAX_CODE)


def school_email(v: str) -> str:
    v = clean_email(v)
    domain = get_settings().school_email_domain.strip().lower().lstrip("@")
    host = v.rsplit("@", 1)[1]
    if domain and host != domain:
        raise ValueError(f"Use your school email (@{domain})")
    return v


def full_name(v: str) -> str:
    v = " ".join(v.split())
    if len(v.split()) < 2:
        raise ValueError("Enter your full name")
    return v


class IdentityIn(BaseModel):
    name: str = Field(max_length=60)
    email: str = Field(max_length=200)
    year_group: YearGroup | None = None  # needed the first time; can change (people move up)

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        return school_email(v)

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        return full_name(v)


class SubmitIn(IdentityIn):
    code: str = Field(min_length=1, max_length=judging.MAX_CODE)


async def person_for(s: AsyncSession, body: IdentityIn) -> WeeklyPerson:
    """The person on this email, made on first use. After that the name has to match."""
    contact = get_settings().contact_email
    p = await s.get(WeeklyPerson, body.email)
    if p is None:
        if not body.year_group:
            raise HTTPException(422, "Choose your year group")
        p = WeeklyPerson(email=body.email, name=body.name, year_group=body.year_group)
        s.add(p)
        try:
            await s.flush()
        except IntegrityError:  # someone else claimed it at the same moment
            await s.rollback()
            raise HTTPException(409, "Try again") from None
        return p
    if p.banned:
        raise HTTPException(403, f"This email can't enter. Email {contact} if that's wrong.")
    if p.name.casefold() != body.name.casefold():
        raise HTTPException(409, f"This email is already used under a different name. Email {contact} if that's wrong.")
    if body.year_group and body.year_group != p.year_group:
        p.year_group = body.year_group
    elif not p.year_group:
        raise HTTPException(422, "Choose your year group")
    return p


async def _open_problem(s: AsyncSession, weekly_id: str) -> tuple[WeeklyProblem, Question]:
    w, q = await _public(s, weekly_id)
    if phase(w) != "open":
        raise HTTPException(409, "This problem has closed")
    return w, q


@router.post("/weekly/sign-in")
@limiter.limit("20/minute")
async def weekly_sign_in(request: Request, body: IdentityIn, s: AsyncSession = Depends(get_session)):
    """Checks a name and school email before the first submission (nothing else is needed)."""
    p = await person_for(s, body)
    return {"name": p.name, "email": p.email, "year_group": p.year_group}


@router.post("/weekly/{weekly_id}/run")
@limiter.limit("30/minute")
async def weekly_run(request: Request, weekly_id: str, body: RunIn, s: AsyncSession = Depends(get_session)):
    """Run the code on the visible examples and show the output (nothing is recorded)."""
    _, q = await _open_problem(s, weekly_id)
    cfg = QuestionConfig(**q.config)

    async def job():
        reqs = [ExecRequest(source=judging.program(body.code, cfg), stdin=e.stdin, **judging.exec_limits(cfg)) for e in cfg.examples]
        return await rt.executor.run_batch(reqs) if reqs else []

    try:
        results = await rt.queue.call(WEEKLY, job)
    except JudgeUnavailable as e:
        raise HTTPException(503, "The judge is busy or down. Try again in a minute.") from e
    return {
        "cases": [
            {
                "index": i + 1,
                "stdin": e.stdin,
                "expected": e.expected,
                "stdout": r.stdout[:5000],
                "stderr": r.stderr[-2000:],
                "status": status_text(r.status_id),
                "passed": r.status_id == ACCEPTED and outputs_match(r.stdout, e.expected),
            }
            for i, (e, r) in enumerate(zip(cfg.examples, results))
        ]
    }


@router.post("/weekly/{weekly_id}/submit", status_code=202)
@limiter.limit("30/minute")
async def weekly_submit(request: Request, weekly_id: str, body: SubmitIn, s: AsyncSession = Depends(get_session)):
    w, _ = await _open_problem(s, weekly_id)
    person = await person_for(s, body)
    mine = (await s.scalars(select(WeeklyEntry).where(WeeklyEntry.weekly_id == w.id, WeeklyEntry.email == body.email))).all()
    if any(e.status in IN_FLIGHT for e in mine):
        raise HTTPException(429, "Your last submission is still being judged")
    if len(mine) >= SUBMIT_MAX:
        raise HTTPException(429, f"You've used all {SUBMIT_MAX} submissions for this week")
    key = f"{w.id}:{body.email}"
    wait = SUBMIT_COOLDOWN_S - (time.monotonic() - _last_submit.get(key, 0))
    if wait > 0:
        raise HTTPException(429, f"Wait {wait:.0f} s before submitting again")
    _last_submit[key] = time.monotonic()
    e = WeeklyEntry(weekly_id=w.id, name=person.name, email=body.email, code=body.code, char_count=golf_chars(body.code), status="queued")
    s.add(e)
    await s.commit()  # before queueing, or a fast worker could look for the entry and not find it
    entry_id = e.id
    rt.queue.put(WEEKLY, lambda: judge_entry(entry_id))
    return {"entry_id": entry_id, "submissions_left": SUBMIT_MAX - len(mine) - 1}


@router.get("/weekly/{weekly_id}/mine")
async def weekly_mine(weekly_id: str, email: str, s: AsyncSession = Depends(get_session)):
    """Your own submissions this week (results only) and where you stand."""
    w, q = await _public(s, weekly_id)
    try:
        email = clean_email(email)
    except ValueError:
        raise HTTPException(400, "Enter a valid email address") from None
    entries = await _entries(s, w.id)
    mine = sorted((e for e in entries if e.email == email), key=lambda e: e.id)
    me = next((r for r in standings(w, q, entries, await _people(s), with_email=True) if r["email"] == email), None)
    if me:
        for k in ("email", "entry_id", "manual_bonus", "manual_entry_id", "bonus_note", "vs_reference"):  # admins only
            me.pop(k, None)
    return {
        "standing": me,
        "submissions": [
            {
                "id": e.id,
                "status": e.status,
                "passed": e.tests_passed,
                "total": e.tests_total,
                "verdict": e.verdict,
                "first_failed": e.first_failed,
                "error_summary": e.error_summary,
                "chars": e.char_count,
                "class_label": speed.describe(e.perf),
                "time_ms": (e.perf or {}).get("top_ms"),
                "submitted_at": e.submitted_at.isoformat(),
            }
            for e in mine
        ],
    }


# ------------------------------------------------------------------ judging


async def _speed_refs(q: Question, bench) -> tuple[speed.Baseline, speed.SpeedResult]:
    """The generator-only baseline and the reference solution's run, once per question version."""
    key = (str(q.id), q.updated_at.isoformat() if q.updated_at else "")
    if key not in _bench_cache:
        base = await speed.baseline(rt.executor, bench)
        ref = await speed.measure(rt.executor, bench, q.reference_solution, base, None)
        _bench_cache[key] = (base, ref)
    return _bench_cache[key]


async def measure_speed(q: Question, code: str) -> dict:
    bench = QuestionConfig(**q.config).benchmark
    try:
        base, ref = await _speed_refs(q, bench)
        res = await speed.measure(rt.executor, bench, code, base, {r.n: r.hash for r in ref.runs})
    except JudgeUnavailable:
        return {"method": "tiers", "tier": None, "class_label": "not measured (judge down)"}
    return speed.to_perf(res, bench.sizes, ref)


async def judge_entry(entry_id: int) -> None:
    async with session_scope() as s:
        e = await s.get(WeeklyEntry, entry_id)
        if not e or e.status not in IN_FLIGHT:
            return
        e.status = "running"
        w = await s.get(WeeklyProblem, e.weekly_id)
        q = await s.get(Question, w.question_id)
        cfg = QuestionConfig(**q.config)
        code = e.code
    try:
        out = await judging.run_tests(code, cfg)
    except JudgeUnavailable:
        async with session_scope() as s:
            if e := await s.get(WeeklyEntry, entry_id):
                e.status, e.verdict, e.judged_at = "error", "Judge Error", now()
        return
    full = out.total > 0 and out.passed == out.total
    measure_it = full and q.type == QuestionType.best_complexity and cfg.benchmark is not None
    async with session_scope() as s:
        e = await s.get(WeeklyEntry, entry_id)
        if not e:  # removed by an admin meanwhile
            return
        e.tests_passed, e.tests_total = out.passed, out.total
        e.verdict, e.first_failed, e.error_summary = out.verdict, out.first_failed, out.error_summary
        e.exec_time_ms = out.exec_time_ms
        e.status = "measuring" if measure_it else "judged"
        e.judged_at = now()
    if not measure_it:
        return
    info = await measure_speed(q, code)
    async with session_scope() as s:
        if e := await s.get(WeeklyEntry, entry_id):
            e.perf, e.status = info, "judged"


async def remeasure_entry(entry_id: int) -> None:
    async with session_scope() as s:
        e = await s.get(WeeklyEntry, entry_id)
        if not e or e.status != "measuring":
            return
        w = await s.get(WeeklyProblem, e.weekly_id)
        q = await s.get(Question, w.question_id)
        code = e.code
    info = await measure_speed(q, code)
    async with session_scope() as s:
        if e := await s.get(WeeklyEntry, entry_id):
            e.perf, e.status = info, "judged"


async def requeue_pending() -> int:
    async with session_scope() as s:
        ids = (await s.scalars(select(WeeklyEntry.id).where(WeeklyEntry.status.in_(IN_FLIGHT)).order_by(WeeklyEntry.id))).all()
    for i in ids:
        rt.queue.put(WEEKLY, lambda i=i: judge_entry(i))
    return len(ids)


# ------------------------------------------------------------------ people (before /weekly-admin/{weekly_id})


class PersonEdit(BaseModel):
    email: str = Field(max_length=200)
    name: str = Field(min_length=2, max_length=60)
    year_group: YearGroup | None = None
    banned: bool

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        return v.strip().lower()

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        return " ".join(v.split())


async def person_row(s: AsyncSession, p: WeeklyPerson) -> dict:
    weeks = await s.scalar(select(func.count(func.distinct(WeeklyEntry.weekly_id))).where(WeeklyEntry.email == p.email))
    n = await s.scalar(select(func.count()).where(WeeklyEntry.email == p.email))
    last = await s.scalar(select(func.max(WeeklyEntry.submitted_at)).where(WeeklyEntry.email == p.email))
    return {
        "email": p.email,
        "name": p.name,
        "year_group": p.year_group,
        "banned": p.banned,
        "weeks": int(weeks or 0),
        "entries": int(n or 0),
        "joined_at": p.created_at.isoformat(),
        "last_entry_at": last.isoformat() if last else None,
    }


@router.get("/weekly-admin/people")
async def admin_people(t: Teacher = Depends(current_teacher), s: AsyncSession = Depends(get_session)):
    """Everyone who has entered, with their email (admin only)."""
    rows = (await s.scalars(select(WeeklyPerson).order_by(WeeklyPerson.name))).all()
    return [await person_row(s, p) for p in rows]


@router.put("/weekly-admin/people")
async def admin_edit_person(body: PersonEdit, t: Teacher = Depends(current_teacher), s: AsyncSession = Depends(get_session)):
    """Fix someone's name, or ban the email (they drop off every leaderboard and can't enter)."""
    p = await s.get(WeeklyPerson, body.email)
    if not p:
        raise HTTPException(404, "Nobody has entered with that email")
    p.name, p.banned = body.name, body.banned
    if body.year_group:
        p.year_group = body.year_group
    return await person_row(s, p)


async def _person_or_404(s: AsyncSession, email: str) -> WeeklyPerson:
    p = await s.get(WeeklyPerson, email.strip().lower())
    if not p:
        raise HTTPException(404, "Nobody has entered with that email")
    return p


@router.get("/weekly-admin/people/detail")
async def admin_person(email: str, t: Teacher = Depends(current_teacher), s: AsyncSession = Depends(get_session)):
    """Everything about one person: each week they entered, where they came and every submission."""
    p = await _person_or_404(s, email)
    people = await _people(s)
    mine = (await s.scalars(select(WeeklyEntry).where(WeeklyEntry.email == p.email).order_by(WeeklyEntry.id.desc()))).all()
    weeks = []
    for wid in dict.fromkeys(e.weekly_id for e in mine):  # newest first
        w = await s.get(WeeklyProblem, wid)
        q = await s.get(Question, w.question_id)
        me = next((r for r in standings(w, q, await _entries(s, w.id), people, with_email=True) if r["email"] == p.email), None)
        weeks.append(
            {
                **summary(w, q),
                "rank": me["rank"] if me else None,
                "points": me["points"] if me else 0,
                "submissions": [
                    {
                        "id": e.id,
                        "code": e.code,
                        "status": e.status,
                        "passed": e.tests_passed,
                        "total": e.tests_total,
                        "verdict": e.verdict,
                        "chars": e.char_count,
                        "class_label": speed.describe(e.perf),
                        "time_ms": (e.perf or {}).get("top_ms"),
                        "submitted_at": e.submitted_at.isoformat(),
                    }
                    for e in mine
                    if e.weekly_id == wid
                ],
            }
        )
    return {**(await person_row(s, p)), "total_points": sum(x["points"] for x in weeks), "weeks_detail": weeks}


@router.delete("/weekly-admin/people/week")
async def admin_remove_week(email: str, weekly_id: str, t: Teacher = Depends(current_teacher), s: AsyncSession = Depends(get_session)):
    """Remove all of someone's submissions for one week."""
    p = await _person_or_404(s, email)
    rows = (await s.scalars(select(WeeklyEntry).where(WeeklyEntry.email == p.email, WeeklyEntry.weekly_id == _uuid(weekly_id)))).all()
    for e in rows:
        await s.delete(e)
    return {"removed": len(rows)}


@router.delete("/weekly-admin/people")
async def admin_clear_person(email: str, t: Teacher = Depends(current_teacher), s: AsyncSession = Depends(get_session)):
    """Delete someone and every submission they made. The email can be used again afterwards."""
    p = await _person_or_404(s, email)
    rows = (await s.scalars(select(WeeklyEntry).where(WeeklyEntry.email == p.email))).all()
    for e in rows:
        await s.delete(e)
    await s.delete(p)
    return {"removed": len(rows)}


@router.delete("/weekly-admin/entries/{entry_id}")
async def admin_remove_entry(entry_id: int, t: Teacher = Depends(current_teacher), s: AsyncSession = Depends(get_session)):
    e = await s.get(WeeklyEntry, entry_id)
    if not e:
        raise HTTPException(404, "Submission not found")
    await s.delete(e)
    return {"ok": True}


# ------------------------------------------------------------------ teacher


class WeeklyIn(BaseModel):
    question_id: str
    opens_at: datetime
    closes_at: datetime
    published: bool = False
    solution_published: bool = False
    credit: str | None = Field(default=None, max_length=80)  # e.g. "Submitted by Sam Smith"
    test_points: int = Field(default=DEFAULT_TEST_POINTS, ge=0, le=100_000)
    bonus_points: list[Annotated[int, Field(ge=0, le=100_000)]] = Field(default_factory=lambda: list(DEFAULT_BONUS), max_length=10)

    @model_validator(mode="after")
    def _dates(self):
        for k in ("opens_at", "closes_at"):
            if getattr(self, k).tzinfo is None:
                raise ValueError(f"{k} needs a timezone")
        if self.closes_at <= self.opens_at:
            raise ValueError("It has to close after it opens")
        return self


async def _own_weekly(s: AsyncSession, weekly_id: str, t: Teacher) -> WeeklyProblem:
    w = await s.get(WeeklyProblem, _uuid(weekly_id))
    if not w or w.owner_id != t.id:
        raise HTTPException(404, "Problem of the week not found")
    return w


async def _usable_question(s: AsyncSession, question_id: str, t: Teacher, published: bool) -> Question:
    q = await s.get(Question, _uuid(question_id))
    quiz = await s.get(Quiz, q.quiz_id) if q else None
    if not q or not quiz or quiz.owner_id != t.id:
        raise HTTPException(404, "Question not found")
    if q.type not in WEEKLY_TYPES:
        raise HTTPException(400, "Problem of the week has to be a Fastest Code or Code Golf question")
    if published and not q.verified_at:
        raise HTTPException(400, "Verify the question in the quiz editor before publishing it")
    return q


async def admin_row(s: AsyncSession, w: WeeklyProblem) -> dict:
    q = await s.get(Question, w.question_id)
    quiz = await s.get(Quiz, q.quiz_id)
    n = await s.scalar(select(func.count()).where(WeeklyEntry.weekly_id == w.id))
    people = await s.scalar(select(func.count(func.distinct(WeeklyEntry.email))).where(WeeklyEntry.weekly_id == w.id))
    return {
        **summary(w, q),
        "question_id": str(q.id),
        "quiz_title": quiz.title,
        "verified": bool(q.verified_at),
        "published": w.published,
        "solution_published": w.solution_published,
        "featured": w.featured_at is not None,
        "entries": int(n or 0),
        "people": int(people or 0),
    }


@router.get("/weekly-admin")
async def admin_list(t: Teacher = Depends(current_teacher), s: AsyncSession = Depends(get_session)):
    rows = (await s.scalars(select(WeeklyProblem).where(WeeklyProblem.owner_id == t.id).order_by(WeeklyProblem.opens_at.desc()))).all()
    return [await admin_row(s, w) for w in rows]


@router.get("/weekly-admin/questions")
async def admin_questions(t: Teacher = Depends(current_teacher), s: AsyncSession = Depends(get_session)):
    """Coding questions the teacher can use (from any of their quizzes)."""
    rows = (
        await s.execute(
            select(Question, Quiz.title)
            .join(Quiz, Quiz.id == Question.quiz_id)
            .where(Quiz.owner_id == t.id, Question.type.in_(WEEKLY_TYPES))
            .order_by(Quiz.title, Question.position)
        )
    ).all()
    return [{"id": str(q.id), "title": q.title, "type": q.type.value, "quiz_title": title, "verified": bool(q.verified_at)} for q, title in rows]


@router.post("/weekly-admin")
async def admin_create(body: WeeklyIn, t: Teacher = Depends(current_teacher), s: AsyncSession = Depends(get_session)):
    q = await _usable_question(s, body.question_id, t, body.published)
    w = WeeklyProblem(
        owner_id=t.id,
        question_id=q.id,
        opens_at=body.opens_at,
        closes_at=body.closes_at,
        published=body.published,
        solution_published=body.solution_published,
        credit=(body.credit or "").strip() or None,
        test_points=body.test_points,
        bonus_points=body.bonus_points,
    )
    s.add(w)
    await s.flush()
    return await admin_row(s, w)


@router.put("/weekly-admin/{weekly_id}")
async def admin_edit(weekly_id: str, body: WeeklyIn, t: Teacher = Depends(current_teacher), s: AsyncSession = Depends(get_session)):
    w = await _own_weekly(s, weekly_id, t)
    q = await _usable_question(s, body.question_id, t, body.published)
    if q.id != w.question_id and await s.scalar(select(func.count()).where(WeeklyEntry.weekly_id == w.id)):
        raise HTTPException(409, "People have already submitted, so the question can't be swapped")
    w.question_id, w.opens_at, w.closes_at = q.id, body.opens_at, body.closes_at
    w.published, w.solution_published = body.published, body.solution_published
    w.credit = (body.credit or "").strip() or None
    w.test_points, w.bonus_points = body.test_points, body.bonus_points
    return await admin_row(s, w)


@router.delete("/weekly-admin/{weekly_id}")
async def admin_delete(weekly_id: str, t: Teacher = Depends(current_teacher), s: AsyncSession = Depends(get_session)):
    await s.delete(await _own_weekly(s, weekly_id, t))
    return {"ok": True}


@router.get("/weekly-admin/{weekly_id}/entries")
async def admin_entries(weekly_id: str, t: Teacher = Depends(current_teacher), s: AsyncSession = Depends(get_session)):
    """Every submission with names, emails and code, plus the standings (teacher only)."""
    w = await _own_weekly(s, weekly_id, t)
    q = await s.get(Question, w.question_id)
    entries = await _entries(s, w.id)
    return {
        **(await admin_row(s, w)),
        "standings": standings(w, q, entries, await _people(s), with_email=True),
        "submissions": [
            {
                "id": e.id,
                "name": e.name,
                "email": e.email,
                "code": e.code,
                "status": e.status,
                "passed": e.tests_passed,
                "total": e.tests_total,
                "verdict": e.verdict,
                "chars": e.char_count,
                "class_label": speed.describe(e.perf),
                "time_ms": (e.perf or {}).get("top_ms"),
                "vs_reference": (e.perf or {}).get("vs_reference"),
                "bonus_override": e.bonus_override,
                "bonus_note": e.bonus_note,
                "submitted_at": e.submitted_at.isoformat(),
            }
            for e in sorted(entries, key=lambda e: e.id, reverse=True)
        ],
    }


class BonusIn(BaseModel):
    bonus: int | None = Field(default=None, ge=0, le=100_000)  # None goes back to automatic
    note: str | None = Field(default=None, max_length=200)  # admins only


@router.put("/weekly-admin/entries/{entry_id}/bonus")
async def admin_set_bonus(entry_id: int, body: BonusIn, t: Teacher = Depends(current_teacher), s: AsyncSession = Depends(get_session)):
    """Set someone's bonus for the week by hand, on one of their submissions (their test points
    stay automatic). The latest edit of theirs counts, nobody else's bonus changes, and it
    looks automatic to everyone but admins. bonus=None clears it."""
    e = await s.get(WeeklyEntry, entry_id)
    w = await s.get(WeeklyProblem, e.weekly_id) if e else None
    if not e or not w or w.owner_id != t.id:
        raise HTTPException(404, "Submission not found")
    e.bonus_override = body.bonus
    e.bonus_override_at = now() if body.bonus is not None else None
    e.bonus_note = ((body.note or "").strip() or None) if body.bonus is not None else None
    return {"id": e.id, "bonus_override": e.bonus_override, "bonus_note": e.bonus_note}


@router.post("/weekly-admin/{weekly_id}/remeasure")
async def admin_remeasure(weekly_id: str, t: Teacher = Depends(current_teacher), s: AsyncSession = Depends(get_session)):
    """Time every full-pass Fastest Code submission again (e.g. after changing the benchmark,
    or ones measured the old way). They show as "measuring" until done."""
    w = await _own_weekly(s, weekly_id, t)
    q = await s.get(Question, w.question_id)
    if q.type != QuestionType.best_complexity or not QuestionConfig(**q.config).benchmark:
        raise HTTPException(400, "Only Fastest Code weeks are measured")
    for k in [k for k in _bench_cache if k[0] == str(q.id)]:
        del _bench_cache[k]  # time the reference again too
    rows = [e for e in await _entries(s, w.id) if e.status == "judged" and e.tests_total and e.tests_passed == e.tests_total]
    for e in rows:
        e.status = "measuring"
    await s.commit()
    for e in rows:
        rt.queue.put(WEEKLY, lambda i=e.id: remeasure_entry(i))
    return {"queued": len(rows)}



# ------------------------------------------------------------------ past weekly problems

PAST_GROUP = "Past Weekly Problems"


async def feature_past_weeks(s: AsyncSession) -> None:
    """Every published week that has closed becomes a published problem in the Past Weekly
    Problems section of the problems page, once. After that it's an ordinary featured problem:
    the admin can edit, hide or delete it and it won't come back."""
    due = (
        await s.scalars(
            select(WeeklyProblem)
            .where(WeeklyProblem.published.is_(True), WeeklyProblem.featured_at.is_(None), WeeklyProblem.closes_at <= now())
            .order_by(WeeklyProblem.closes_at)
        )
    ).all()
    for w in due:
        q = await s.get(Question, w.question_id)
        group = (await s.scalars(select(ProblemGroup).where(ProblemGroup.owner_id == w.owner_id, func.lower(ProblemGroup.name) == PAST_GROUP.lower()))).first()
        if group is None:
            pos = await s.scalar(select(func.coalesce(func.max(ProblemGroup.position), -1)).where(ProblemGroup.owner_id == w.owner_id))
            group = ProblemGroup(owner_id=w.owner_id, name=PAST_GROUP, position=pos + 1)
            s.add(group)
            await s.flush()
        s.add(
            FeaturedProblem(
                owner_id=w.owner_id,
                title=q.title,
                description_md=q.description_md,
                examples=(q.config or {}).get("examples", []),
                solution_code=q.reference_solution if w.solution_published else "",
                credit=w.credit,
                published=True,
                group_id=group.id,
                created_at=w.closes_at,
                updated_at=now(),
            )
        )
        w.featured_at = now()
    if due:
        await s.flush()
