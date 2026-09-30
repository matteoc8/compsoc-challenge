"""Post-game stats and CSV export."""

import csv
import io
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .engine.leaderboard import team_totals
from .engine.views import quiz_questions
from .models import Answer, Game, QuestionType, RunLog, ScoreEvent, Submission, SubStatus, Team


def _full(sub: Submission) -> bool:
    return sub.status == SubStatus.judged and bool(sub.tests_total) and sub.tests_passed == sub.tests_total


async def _load(s: AsyncSession, game: Game):
    teams = {t.id: t for t in (await s.scalars(select(Team).where(Team.game_id == game.id))).all()}
    subs = (await s.scalars(select(Submission).where(Submission.game_id == game.id).order_by(Submission.id))).all()
    runs = (await s.scalars(select(RunLog).where(RunLog.game_id == game.id))).all()
    questions = await quiz_questions(s, game.quiz_id)
    return teams, subs, runs, questions


async def _answers(s: AsyncSession, game: Game) -> list[Answer]:
    return list((await s.scalars(select(Answer).where(Answer.game_id == game.id).order_by(Answer.id))).all())


async def stats(s: AsyncSession, game: Game) -> dict:
    teams, subs, runs, questions = await _load(s, game)
    answers = await _answers(s, game)
    qtype = {q.id: q.type for q in questions}
    name = lambda tid: teams[tid].name if tid in teams else "?"  # noqa: E731

    fastest = min((x for x in subs if _full(x) and qtype.get(x.question_id) == QuestionType.super_fast), key=lambda x: x.elapsed_ms, default=None)
    golfer = min((x for x in subs if _full(x) and qtype.get(x.question_id) == QuestionType.code_golf), key=lambda x: x.char_count, default=None)
    efficient = None
    for x in subs:
        if qtype.get(x.question_id) == QuestionType.best_complexity and x.perf and x.perf.get("top_ms") is not None:
            if efficient is None or x.perf["top_ms"] < efficient.perf["top_ms"]:
                efficient = x

    per_team_rate: dict = defaultdict(lambda: [0, 0])
    for x in subs:
        if x.status == SubStatus.judged and x.tests_total:
            per_team_rate[x.team_id][0] += x.tests_passed / x.tests_total
            per_team_rate[x.team_id][1] += 1
    accurate = max(per_team_rate.items(), key=lambda kv: kv[1][0] / kv[1][1], default=None)

    quiz_right: dict = defaultdict(int)
    for a in answers:
        quiz_right[a.team_id] += a.correct
    quiz_whiz = max(quiz_right.items(), key=lambda kv: kv[1], default=None)

    per_question = []
    for q in questions:
        if q.type == QuestionType.multiple_choice:
            qa = [a for a in answers if a.question_id == q.id]
            per_question.append(
                {
                    "question_id": str(q.id),
                    "round_name": q.round_name,
                    "title": q.title,
                    "type": q.type.value,
                    "answers": len(qa),
                    "correct_rate": round(sum(a.correct for a in qa) / len(qa), 3) if qa else None,
                    "avg_answer_ms": round(sum(a.elapsed_ms for a in qa) / len(qa)) if qa else None,
                }
            )
            continue
        qs = [x for x in subs if x.question_id == q.id]
        firsts: dict = {}
        for x in qs:
            if _full(x) and (x.team_id not in firsts or x.elapsed_ms < firsts[x.team_id]):
                firsts[x.team_id] = x.elapsed_ms
        per_question.append(
            {
                "question_id": str(q.id),
                "round_name": q.round_name,
                "title": q.title,
                "type": q.type.value,
                "submissions": len(qs),
                "runs": sum(1 for r in runs if r.question_id == q.id),
                "teams_submitting": len({x.team_id for x in qs}),
                "attempts_per_team": round(len(qs) / max(len({x.team_id for x in qs}), 1), 2),
                "teams_passing": len(firsts),
                "avg_time_to_first_pass_ms": round(sum(firsts.values()) / len(firsts)) if firsts else None,
            }
        )

    return {
        "quiz_whiz": {"team": name(quiz_whiz[0]), "correct": quiz_whiz[1]} if quiz_whiz and quiz_whiz[1] else None,
        "fastest_solver": {"team": name(fastest.team_id), "elapsed_ms": fastest.elapsed_ms} if fastest else None,
        "most_accurate": {"team": name(accurate[0]), "pass_rate": round(accurate[1][0] / accurate[1][1], 3), "submissions": accurate[1][1]} if accurate else None,
        "best_golfer": {"team": name(golfer.team_id), "chars": golfer.char_count} if golfer else None,
        "most_efficient": {"team": name(efficient.team_id), "top_ms": efficient.perf["top_ms"], "class": efficient.perf.get("class_label")} if efficient else None,
        "questions": per_question,
        "leaderboard": await team_totals(s, game.id),
    }


def _cell(v):
    if v is None:
        return ""
    # Stop spreadsheet formula injection from team code or names ("=HYPERLINK(...)").
    if isinstance(v, str) and v[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + v
    return v


def _csv(rows: list[list]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    for r in rows:
        w.writerow([_cell(v) for v in r])
    return "﻿" + buf.getvalue()  # BOM so Excel opens UTF-8 correctly


async def teams_csv(s: AsyncSession, game: Game) -> str:
    teams, subs, runs, questions = await _load(s, game)
    answers = await _answers(s, game)
    events = (await s.scalars(select(ScoreEvent).where(ScoreEvent.game_id == game.id))).all()
    board = {r["team_id"]: r for r in await team_totals(s, game.id)}
    header = ["rank", "team", "total", "manual"]
    for q in questions:
        if q.type == QuestionType.multiple_choice:
            header += [f"{q.round_name}: points", f"{q.round_name}: answer", f"{q.round_name}: correct", f"{q.round_name}: time (s)"]
        else:
            header += [f"{q.round_name}: points", f"{q.round_name}: attempts", f"{q.round_name}: best pass rate", f"{q.round_name}: first pass (s)"]
    header += ["runs", "kicked"]
    rows = [header]
    ordered = sorted(teams.values(), key=lambda t: (board.get(str(t.id), {}).get("rank") or 10**6, t.name.lower()))
    for t in ordered:
        mine_ev = [e for e in events if e.team_id == t.id]
        b = board.get(str(t.id))
        row = [
            b["rank"] if b else None,
            t.name,
            sum(e.points for e in mine_ev),
            sum(e.points for e in mine_ev if e.reason in ("manual", "undo")),
        ]
        for q in questions:
            if q.type == QuestionType.multiple_choice:
                a = next((x for x in answers if x.team_id == t.id and x.question_id == q.id), None)
                row += [
                    sum(e.points for e in mine_ev if e.reason == "question" and e.question_id == q.id),
                    "ABCD"[a.choice] if a else None,
                    ("yes" if a.correct else "no") if a else None,
                    round(a.elapsed_ms / 1000, 1) if a else None,
                ]
                continue
            qs = [x for x in subs if x.team_id == t.id and x.question_id == q.id]
            judged = [x for x in qs if x.status == SubStatus.judged and x.tests_total]
            full = [x for x in qs if _full(x)]
            row += [
                sum(e.points for e in mine_ev if e.reason == "question" and e.question_id == q.id),
                len(qs),
                round(max(x.tests_passed / x.tests_total for x in judged), 3) if judged else None,
                round(min(x.elapsed_ms for x in full) / 1000, 1) if full else None,
            ]
        row += [sum(1 for r in runs if r.team_id == t.id), "yes" if t.kicked else ""]
        rows.append(row)
    return _csv(rows)


async def submissions_csv(s: AsyncSession, game: Game) -> str:
    teams, subs, _, questions = await _load(s, game)
    qname = {q.id: q.round_name for q in questions}
    rows = [["id", "team", "round", "attempt", "status", "verdict", "passed", "total", "chars", "elapsed_s", "exec_ms", "points", "submitted_at", "code"]]
    for x in subs:
        rows.append(
            [
                x.id,
                teams[x.team_id].name if x.team_id in teams else "?",
                qname.get(x.question_id, "?"),
                x.attempt_no,
                x.status.value,
                x.verdict,
                x.tests_passed,
                x.tests_total,
                x.char_count,
                round(x.elapsed_ms / 1000, 2),
                x.exec_time_ms,
                x.provisional_points,
                x.submitted_at.isoformat(),
                x.code,
            ]
        )
    return _csv(rows)
