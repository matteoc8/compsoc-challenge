"""Read-side: what each role sees. Everything here is recomputed from the database,
so a refreshed or reconnected screen always gets the full, current picture."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..judge.golf import GOLF_RULE_TEXT
from ..models import (
    Answer,
    Game,
    GameState,
    HintGiven,
    Question,
    QuestionType,
    RunLog,
    ScoreEvent,
    Submission,
    SubStatus,
    Team,
)
from ..runtime import rt
from ..schemas.question import Closest, parse_scoring
from .leaderboard import team_totals, with_previous
from .scoring import closest_points
from .serialize import TYPE_LABEL, rule_line, serialize_question

QUESTION_STATES = {GameState.open, GameState.paused, GameState.closed, GameState.judging, GameState.results}
FREE_RUN = "free_run"
FREE_RUN_STATES = {GameState.open, GameState.paused, GameState.closed, GameState.judging}


def is_free_run(game: Game) -> bool:
    return game.mode == FREE_RUN


def free_run_breaks(game: Game, n: int) -> list[int]:
    """Pause points: a break after question index b stops teams going past it until unlocked."""
    return sorted({b for b in (game.settings or {}).get("breaks", []) if isinstance(b, int) and 0 <= b < n - 1})


def free_run_closed(game: Game) -> set[str]:
    """Problems the host closed after analysing them: still visible, no more submissions."""
    return set((game.settings or {}).get("closed_questions", []))


def free_run_visible(game: Game, n: int) -> int:
    """How many questions (from the start) teams can open: up to the first break at or after
    the point the host has unlocked to."""
    through = int((game.settings or {}).get("unlocked_through", -1))
    for b in free_run_breaks(game, n):
        if b >= through:
            return b + 1
    return n


def now() -> datetime:
    return datetime.now(timezone.utc)


def ms(td) -> int:
    return int(td.total_seconds() * 1000)


def elapsed_ms(game: Game, at: datetime) -> int:
    """Time since the question opened, excluding pauses, on the server clock."""
    if not game.opened_at:
        return 0
    paused = game.paused_total_ms
    if game.paused_at:
        paused += max(ms(at - game.paused_at), 0)
    return max(ms(at - game.opened_at) - paused, 0)


def remaining_ms(game: Game) -> int | None:
    if not game.deadline:
        return None
    ref = game.paused_at or now()
    return max(ms(game.deadline - ref), 0)


async def quiz_questions(s: AsyncSession, quiz_id: uuid.UUID) -> list[Question]:
    return list((await s.scalars(select(Question).where(Question.quiz_id == quiz_id).order_by(Question.position))).all())


async def current_question(s: AsyncSession, game: Game) -> Question | None:
    return await s.get(Question, game.current_question_id) if game.current_question_id else None


def game_header(game: Game, questions_count: int, q: Question | None, role: str) -> dict:
    h = {
        "id": str(game.id),
        "mode": game.mode or "live",
        "state": game.state.value,
        "question_index": game.question_index,
        "question_count": questions_count,
        "round_name": q.round_name if q else None,
        "question_type": q.type.value if q else None,
        "deadline": game.deadline.isoformat() if game.deadline else None,
        "paused": game.state == GameState.paused,
        "remaining_ms": remaining_ms(game),
        "unlimited": bool(q and q.unlimited_time),
        "elapsed_ms": elapsed_ms(game, now()),
        "ending": game.ending,
        "ended_early": game.ended_early,
        "phase_ends_at": game.phase_ends_at.isoformat() if game.phase_ends_at else None,
        "server_time": now().isoformat(),
        "judge_ok": rt.judge_ok,
    }
    if role in ("teacher", "screen"):
        h["join_code"] = game.join_code
    if is_free_run(game):
        h["duration_s"] = int((game.settings or {}).get("duration_s", 3600))
    return h


async def team_submission_rows(s: AsyncSession, game_id, question_id, team_id) -> list[dict]:
    subs = (
        await s.scalars(
            select(Submission)
            .where(Submission.game_id == game_id, Submission.question_id == question_id, Submission.team_id == team_id)
            .order_by(Submission.attempt_no)
        )
    ).all()
    return [submission_result(sub) for sub in subs]


def submission_result(sub: Submission) -> dict:
    """What a team sees about its own submission. Never test data."""
    return {
        "id": sub.id,
        "question_id": str(sub.question_id),
        "attempt": sub.attempt_no,
        "status": sub.status.value,
        "passed": sub.tests_passed,
        "total": sub.tests_total,
        "verdict": sub.verdict,
        "first_failed": sub.first_failed,
        "error_summary": sub.error_summary,
        "chars": sub.char_count,
        "elapsed_ms": sub.elapsed_ms,
        "time_ms": sub.exec_time_ms,
        "points": sub.provisional_points,
        "submitted_at": sub.submitted_at.isoformat(),
    }


async def question_points(s: AsyncSession, game_id, question_id) -> dict[str, int]:
    rows = (
        await s.execute(
            select(ScoreEvent.team_id, ScoreEvent.points).where(
                ScoreEvent.game_id == game_id, ScoreEvent.question_id == question_id, ScoreEvent.reason == "question"
            )
        )
    ).all()
    return {str(t): p for t, p in rows}


async def full_passes(s: AsyncSession, game_id, question_id) -> list[Submission]:
    return list(
        (
            await s.scalars(
                select(Submission)
                .where(
                    Submission.game_id == game_id,
                    Submission.question_id == question_id,
                    Submission.status == SubStatus.judged,
                    Submission.tests_total > 0,
                    Submission.tests_passed == Submission.tests_total,
                )
                .order_by(Submission.elapsed_ms, Submission.id)
            )
        ).all()
    )


async def answers_of(s: AsyncSession, game_id, question_id) -> list[Answer]:
    return list(
        (await s.scalars(select(Answer).where(Answer.game_id == game_id, Answer.question_id == question_id).order_by(Answer.id))).all()
    )


async def progress(s: AsyncSession, game: Game, q: Question) -> dict:
    teams = {str(t.id): t.name for t in (await s.scalars(select(Team).where(Team.game_id == game.id, Team.kicked.is_(False)))).all()}
    if q.type == QuestionType.multiple_choice:
        answered = sum(1 for a in await answers_of(s, game.id, q.id) if str(a.team_id) in teams)
        return {"type": q.type.value, "teams_total": len(teams), "passing": 0, "answered": answered}
    passes = await full_passes(s, game.id, q.id)
    first: dict[str, Submission] = {}
    for p in passes:
        tid = str(p.team_id)
        if tid in teams and tid not in first:
            first[tid] = p
    out = {"type": q.type.value, "teams_total": len(teams), "passing": len(first)}
    if q.type == QuestionType.super_fast:
        scoring = q.scoring or {}
        if scoring.get("mode") == "ranked":
            out["place_points"] = list(scoring.get("points") or [])
        out["solves"] = [
            {"team_id": tid, "name": teams[tid], "elapsed_ms": sub.elapsed_ms}
            for tid, sub in sorted(first.items(), key=lambda kv: (kv[1].elapsed_ms, kv[1].id))
        ]
    elif q.type == QuestionType.code_golf:
        best = min((p.char_count for p in passes if str(p.team_id) in teams), default=None)
        out["best_chars"] = best
    return out


async def hints_by_team(s: AsyncSession, game_id, question_id) -> dict[str, list[int]]:
    out: dict[str, list[int]] = {}
    rows = (
        await s.execute(
            select(HintGiven.team_id, HintGiven.hint_index)
            .where(HintGiven.game_id == game_id, HintGiven.question_id == question_id)
            .order_by(HintGiven.hint_index)
        )
    ).all()
    for tid, idx in rows:
        out.setdefault(str(tid), []).append(idx)
    return out


async def monitor_rows(s: AsyncSession, game: Game, q: Question) -> list[dict]:
    rows = await _monitor_rows(s, game, q)
    hints = await hints_by_team(s, game.id, q.id)
    for r in rows:
        r["hints"] = hints.get(r["team_id"], [])
    return rows


async def _monitor_rows(s: AsyncSession, game: Game, q: Question) -> list[dict]:
    teams = (await s.scalars(select(Team).where(Team.game_id == game.id).order_by(Team.joined_at))).all()
    if q.type == QuestionType.multiple_choice:
        online = rt.hub.online_team_ids(str(game.id))
        answers = {a.team_id: a for a in await answers_of(s, game.id, q.id)}
        return [
            {
                "team_id": str(t.id),
                "name": t.name,
                "kicked": t.kicked,
                "online": str(t.id) in online,
                "answered": t.id in answers,
                "choice": answers[t.id].choice if t.id in answers else None,
                "correct": answers[t.id].correct if t.id in answers else None,
                "answer_ms": answers[t.id].elapsed_ms if t.id in answers else None,
            }
            for t in teams
        ]
    subs = (
        await s.scalars(select(Submission).where(Submission.game_id == game.id, Submission.question_id == q.id))
    ).all()
    run_counts = dict(
        (
            await s.execute(
                select(RunLog.team_id, func.count())
                .where(RunLog.game_id == game.id, RunLog.question_id == q.id)
                .group_by(RunLog.team_id)
            )
        ).all()
    )
    points = await question_points(s, game.id, q.id)
    online = rt.hub.online_team_ids(str(game.id))
    by_team: dict = {}
    for sub in subs:
        by_team.setdefault(sub.team_id, []).append(sub)
    golf_best = min(
        (x.char_count for x in subs if x.status == SubStatus.judged and x.tests_total and x.tests_passed == x.tests_total),
        default=None,
    )
    rule = parse_scoring(q.scoring)
    rows = []
    for t in teams:
        mine = by_team.get(t.id, [])
        judged = [x for x in mine if x.status == SubStatus.judged and x.tests_total]
        full = [x for x in judged if x.tests_passed == x.tests_total]
        best_rate = max((x.tests_passed / x.tests_total for x in judged), default=None)
        best_chars = min((x.char_count for x in full), default=None)
        provisional = points.get(str(t.id))
        if provisional is None and full:
            if q.type == QuestionType.code_golf and isinstance(rule, Closest) and golf_best:
                provisional = closest_points(rule, best_chars, golf_best)
        rows.append(
            {
                "team_id": str(t.id),
                "name": t.name,
                "kicked": t.kicked,
                "online": str(t.id) in online,
                "attempts": len(mine),
                "runs": int(run_counts.get(t.id, 0)),
                "best_pass_rate": best_rate,
                "best_chars": best_chars,
                "first_full_ms": min((x.elapsed_ms for x in full), default=None),
                "passing": bool(full),
                "in_flight": any(x.status in (SubStatus.queued, SubStatus.running) for x in mine),
                "provisional_points": provisional,
            }
        )
    return rows


async def in_flight_count(s: AsyncSession, game_id, question_id) -> int:
    return int(
        await s.scalar(
            select(func.count()).where(
                Submission.game_id == game_id,
                Submission.question_id == question_id,
                Submission.status.in_([SubStatus.queued, SubStatus.running]),
            )
        )
        or 0
    )


async def adjustments(s: AsyncSession, game_id) -> list[dict]:
    rows = (
        await s.execute(
            select(ScoreEvent, Team.name)
            .join(Team, Team.id == ScoreEvent.team_id)
            .where(ScoreEvent.game_id == game_id, ScoreEvent.reason.in_(["manual", "undo"]))
            .order_by(ScoreEvent.id.desc())
        )
    ).all()
    undone = {e.undoes_id for e, _ in rows if e.undoes_id}
    return [
        {
            "id": e.id,
            "team_id": str(e.team_id),
            "team": name,
            "points": e.points,
            "reason": e.reason,
            "note": e.note,
            "undone": e.id in undone,
            "created_at": e.created_at.isoformat(),
        }
        for e, name in rows
    ]


def _cell(q: Question, subs: list[Submission], answer: Answer | None, points: int | None) -> dict:
    """One team on one problem: solved / partial / tried / judging, or correct / wrong."""
    if q.type == QuestionType.multiple_choice:
        status = None if answer is None else ("correct" if answer.correct else "wrong")
        return {"status": status, "points": points, "attempts": 1 if answer else 0}
    judged = [x for x in subs if x.status == SubStatus.judged and x.tests_total]
    if any(x.tests_passed == x.tests_total for x in judged):
        status = "solved"
    elif any(x.tests_passed for x in judged):
        status = "partial"
    elif any(x.status in (SubStatus.queued, SubStatus.running) for x in subs):
        status = "judging"
    elif subs:
        status = "tried"
    else:
        status = None
    best = max(judged, key=lambda x: x.tests_passed or 0, default=None)
    return {
        "status": status,
        "points": points,
        "attempts": len(subs),
        "passed": best.tests_passed if best else None,
        "total": best.tests_total if best else None,
    }


async def _free_run(s: AsyncSession, game: Game, role: str, team_id: str | None, board: list[dict]) -> dict:
    questions = await quiz_questions(s, game.quiz_id)
    n = len(questions)
    visible = free_run_visible(game, n)
    breaks = free_run_breaks(game, n)
    out: dict = {"visible": visible, "total": n, "breaks": breaks}
    closed = free_run_closed(game)
    section = 0
    info = []
    for i, q in enumerate(questions):
        locked = i >= visible
        row = {
            "id": str(q.id),
            "index": i,
            "type": q.type.value,
            "type_label": TYPE_LABEL[q.type],
            "section": section,
            "locked": locked,
            "closed": str(q.id) in closed,
        }
        if role == "teacher" or not locked:
            row["title"] = q.title
        if role == "teacher":
            row["hints"] = list((q.config or {}).get("hints") or [])
        info.append(row)
        if i in breaks:
            section += 1
    out["questions"] = info
    analysing = (game.settings or {}).get("analysing")
    if analysing and game.state in FREE_RUN_STATES:
        show = (game.settings or {}).get("analysis_show") or "results"
        res = dict((game.results or {}).get(analysing) or {})
        res.pop("bench", None)
        # code only reaches the screens while the host is showing it
        if show != "winner":
            res.pop("winner", None)
        if show != "solution":
            res.pop("model_solution", None)
        if show != "team":
            res.pop("team_solution", None)
        q = next((x for x in questions if str(x.id) == analysing), None)
        out["analysis"] = {
            "question_id": analysing,
            "title": q.title if q else "",
            "description_md": q.description_md if q else "",
            "show": show,
            "results": res,
        }
    if game.state not in FREE_RUN_STATES and game.state not in (GameState.leaderboard, GameState.podium, GameState.finished):
        return out

    subs = (await s.scalars(select(Submission).where(Submission.game_id == game.id).order_by(Submission.id))).all()
    answers = {(a.question_id, a.team_id): a for a in (await s.scalars(select(Answer).where(Answer.game_id == game.id))).all()}
    pts = {
        (qid, tid): p
        for qid, tid, p in (
            await s.execute(
                select(ScoreEvent.question_id, ScoreEvent.team_id, ScoreEvent.points).where(
                    ScoreEvent.game_id == game.id, ScoreEvent.reason == "question"
                )
            )
        ).all()
    }
    by: dict[tuple, list[Submission]] = {}
    for x in subs:
        by.setdefault((x.question_id, x.team_id), []).append(x)

    def cells(tid: uuid.UUID) -> dict:
        return {str(q.id): _cell(q, by.get((q.id, tid), []), answers.get((q.id, tid)), pts.get((q.id, tid))) for q in questions}

    if role in ("teacher", "screen"):
        out["grid"] = [{**r, "cells": cells(uuid.UUID(r["team_id"]))} for r in board]
    if role == "teacher":
        out["in_flight"] = sum(1 for x in subs if x.status in (SubStatus.queued, SubStatus.running))
    if role == "team" and team_id and game.state in FREE_RUN_STATES:
        tid = uuid.UUID(team_id)
        out["problems"] = [serialize_question(q, "team") for q in questions[:visible]]
        out["status"] = cells(tid)
        out["submissions"] = {
            str(q.id): [submission_result(x) for x in sorted(by.get((q.id, tid), []), key=lambda x: x.attempt_no)] for q in questions[:visible]
        }
        out["answers"] = {str(q.id): answers[(q.id, tid)].choice for q in questions[:visible] if (q.id, tid) in answers}
        given = (
            await s.execute(
                select(HintGiven.question_id, HintGiven.hint_index)
                .where(HintGiven.game_id == game.id, HintGiven.team_id == tid)
                .order_by(HintGiven.hint_index)
            )
        ).all()
        texts = {q.id: (q.config or {}).get("hints") or [] for q in questions}
        hints: dict[str, list] = {}
        for qid, i in given:
            if i < len(texts.get(qid, [])):
                hints.setdefault(str(qid), []).append({"index": i, "number": i + 1, "text": texts[qid][i]})
        out["hints"] = hints
    return out


async def build_snapshot(s: AsyncSession, game: Game, role: str, team_id: str | None = None) -> dict:
    questions = await quiz_questions(s, game.quiz_id)
    q = await current_question(s, game)
    snap: dict = {"role": role, "game": game_header(game, len(questions), q, role)}
    board = await team_totals(s, game.id)
    snap["leaderboard"] = with_previous(board, game.last_board)
    if is_free_run(game):
        snap["free_run"] = await _free_run(s, game, role, team_id, board)

    if q and game.state == GameState.round_intro:
        snap["intro"] = {
            "round_name": q.round_name,
            "type": q.type.value,
            "type_label": TYPE_LABEL[q.type],
            "rule_line": rule_line(q),
            "question_text": q.title if q.type == QuestionType.multiple_choice else None,
            "position": game.question_index + 1,
            "count": len(questions),
        }
    if q and game.state in QUESTION_STATES:
        snap["question"] = serialize_question(q, "screen" if role == "screen" else role)
        if q.type == QuestionType.code_golf and role == "screen":
            snap["question"]["golf_rule"] = GOLF_RULE_TEXT
    if q and game.state in (GameState.results, GameState.leaderboard):
        snap["results"] = (game.results or {}).get(str(q.id))
    if game.state in (GameState.podium, GameState.finished):
        snap["podium"] = board

    if role in ("teacher", "screen"):
        online = rt.hub.online_team_ids(str(game.id))
        teams = (await s.scalars(select(Team).where(Team.game_id == game.id, Team.kicked.is_(False)).order_by(Team.joined_at))).all()
        snap["teams"] = [{"team_id": str(t.id), "name": t.name, "online": str(t.id) in online} for t in teams]
        snap["settings"] = {"sounds": (game.settings or {}).get("sounds", True)}
        if q and game.state in QUESTION_STATES:
            snap["progress"] = await progress(s, game, q)

    if role == "teacher":
        snap["screen_token"] = game.screen_token
        snap["questions"] = [
            {"id": str(x.id), "position": x.position, "round_name": x.round_name, "title": x.title, "type": x.type.value}
            for x in questions
        ]
        snap["adjustments"] = await adjustments(s, game.id)
        snap["settings"] = game.settings or {}
        if q and game.state in QUESTION_STATES:
            snap["monitor"] = await monitor_rows(s, game, q)
            snap["in_flight"] = await in_flight_count(s, game.id, q.id)
        all_teams = (await s.scalars(select(Team).where(Team.game_id == game.id).order_by(Team.joined_at))).all()
        snap["all_teams"] = [{"team_id": str(t.id), "name": t.name, "kicked": t.kicked} for t in all_teams]

    if role == "team" and team_id:
        me = next((r for r in board if r["team_id"] == team_id), None)
        team = await s.get(Team, uuid.UUID(team_id))
        snap["me"] = {
            "team_id": team_id,
            "name": team.name if team else "",
            "points": me["points"] if me else 0,
            "rank": me["rank"] if me else None,
            "teams_total": len(board),
        }
        if q and game.state in QUESTION_STATES:
            snap["progress"] = await progress(s, game, q)
            if q.type == QuestionType.multiple_choice:
                mine = await s.scalar(
                    select(Answer).where(Answer.game_id == game.id, Answer.question_id == q.id, Answer.team_id == uuid.UUID(team_id))
                )
                snap["my_answer"] = {"choice": mine.choice} if mine else None
            snap["my_submissions"] = await team_submission_rows(s, game.id, q.id, uuid.UUID(team_id))
            texts = (q.config or {}).get("hints") or []
            snap["my_hints"] = [
                {"index": i, "number": i + 1, "text": texts[i]}
                for i in (await hints_by_team(s, game.id, q.id)).get(team_id, [])
                if i < len(texts)
            ]
            pts = (await question_points(s, game.id, q.id)).get(team_id)
            snap["my_question_points"] = pts
    return snap
