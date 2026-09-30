"""Run and Submit (the LeetCode model), judge jobs, question verification and benchmarks."""

import asyncio
import logging
import time
import uuid
from datetime import timedelta

from sqlalchemy import func, select

from ..db import session_scope
from ..judge.benchmark import estimate_class, measure
from ..judge.client import (
    ACCEPTED,
    ExecRequest,
    JudgeUnavailable,
    outputs_match,
    status_text,
    summarise_error,
)
from ..judge.golf import golf_chars
from ..judge.queue import RUN, SUBMIT
from ..models import (
    Game,
    GameState,
    Question,
    QuestionType,
    RunLog,
    Submission,
    SubStatus,
    Team,
)
from ..runtime import rt
from ..schemas.question import QuestionConfig
from . import views
from .game import GRACE_MS, GameError, engine
from .views import now

log = logging.getLogger(__name__)

MAX_CODE = 10_000
MAX_STDIN = 10_000
SUBMIT_COOLDOWN_S, SUBMIT_MAX = 5, 20
RUN_COOLDOWN_S, RUN_MAX = 3, 60
JUDGE_RETRIES = 20
JUDGE_RETRY_DELAY_S = 3

# A built-in practice problem so teams can try Run in the lobby.
PRACTICE = {
    "id": "practice",
    "round_name": "Practice",
    "title": "Warm-up: add two numbers",
    "description_md": "Read two integers on one line and print their sum.\n\nThis is only a practice problem: **Run** works, nothing is scored.",
    "starter_code": "a, b = map(int, input().split())\nprint(a + b)\n",
    "examples": [{"stdin": "2 3\n", "expected": "5\n"}, {"stdin": "-4 10\n", "expected": "6\n"}],
}

# In-memory Run limits (one process by design; they reset on restart, which is harmless).
_run_in_flight: set[str] = set()
_run_last: dict[str, float] = {}


def reset_run_limits() -> None:
    _run_in_flight.clear()
    _run_last.clear()


def exec_limits(cfg: QuestionConfig) -> dict:
    return {
        "cpu_limit_s": cfg.cpu_limit_s,
        "wall_limit_s": max(5.0, cfg.cpu_limit_s * 2 + 1),
        "memory_kb": cfg.memory_mb * 1000,
    }


def program(code: str, cfg: QuestionConfig) -> str:
    return code + ("\n\n" + cfg.harness if cfg.harness else "")


async def run_with_retry(reqs: list[ExecRequest], game_id: str | None = None):
    """Run a batch, retrying while Judge0 is down and telling everyone about it."""
    for attempt in range(JUDGE_RETRIES):
        try:
            results = await rt.executor.run_batch(reqs)
            if not rt.judge_ok:
                rt.judge_ok, rt.judge_error = True, None
                if game_id:
                    rt.hub.send(game_id, "judge.status", {"ok": True})
            return results
        except JudgeUnavailable as e:
            log.warning("judge unavailable (attempt %d): %s", attempt + 1, e)
            if rt.judge_ok or attempt == 0:
                rt.judge_ok, rt.judge_error = False, str(e)
                if game_id:
                    rt.hub.send(game_id, "judge.status", {"ok": False, "message": "Judge unavailable, retrying…"})
            await asyncio.sleep(JUDGE_RETRY_DELAY_S)
    raise JudgeUnavailable("gave up after retries")


# ---------------------------------------------------------------------- submit


async def submit(team: Team, question_id: str, code: str) -> dict:
    if len(code) > MAX_CODE:
        raise GameError("Code is over 10,000 characters", 413)
    gid = str(team.game_id)
    async with engine.lock(gid):
        async with session_scope() as s:
            game = await s.get(Game, team.game_id, with_for_update=True)
            t = now()
            if str(game.current_question_id) != question_id:
                raise GameError("That question isn't open", 409)
            q = await s.get(Question, game.current_question_id)
            if q.type == QuestionType.multiple_choice:
                raise GameError("That isn't a coding question", 409)
            if game.state == GameState.paused:
                raise GameError("The game is paused, submit when it resumes", 409)
            if game.state != GameState.open or t > game.deadline + timedelta(milliseconds=GRACE_MS):
                raise GameError("Time's up for this question", 409)
            mine = (
                await s.scalars(
                    select(Submission)
                    .where(Submission.game_id == game.id, Submission.question_id == game.current_question_id, Submission.team_id == team.id)
                    .order_by(Submission.attempt_no.desc())
                )
            ).all()
            if any(x.status in (SubStatus.queued, SubStatus.running) for x in mine):
                raise GameError("Your last submission is still being judged", 429)
            if len(mine) >= SUBMIT_MAX:
                raise GameError(f"You've used all {SUBMIT_MAX} submissions for this question", 429)
            if mine and (t - mine[0].submitted_at).total_seconds() < SUBMIT_COOLDOWN_S:
                wait = SUBMIT_COOLDOWN_S - (t - mine[0].submitted_at).total_seconds()
                raise GameError(f"Wait {wait:.0f} s before submitting again", 429)
            elapsed = views.elapsed_ms(game, t)
            sub = Submission(
                game_id=game.id,
                question_id=q.id,
                team_id=team.id,
                attempt_no=(mine[0].attempt_no + 1) if mine else 1,
                code=code,
                char_count=golf_chars(code),
                status=SubStatus.queued,
                elapsed_ms=elapsed,
                submitted_at=t,
            )
            s.add(sub)
            await s.flush()
            sub_id, attempt = sub.id, sub.attempt_no
    rt.queue.put(SUBMIT, lambda: judge_submission(sub_id))
    asyncio.create_task(engine.push_live(gid, uuid.UUID(question_id)))
    return {"submission_id": sub_id, "attempt": attempt, "attempts_left": SUBMIT_MAX - attempt}


async def judge_submission(sub_id: int) -> None:
    async with session_scope() as s:
        sub = await s.get(Submission, sub_id)
        if not sub or sub.status not in (SubStatus.queued, SubStatus.running):
            return
        sub.status = SubStatus.running
        q = await s.get(Question, sub.question_id)
        cfg = QuestionConfig(**q.config)
        code, gid, team_id, qid = sub.code, str(sub.game_id), str(sub.team_id), q.id
    reqs = [ExecRequest(source=program(code, cfg), stdin=t.stdin, **exec_limits(cfg)) for t in cfg.tests]
    try:
        results = await run_with_retry(reqs, gid) if reqs else []
    except JudgeUnavailable:
        async with session_scope() as s:
            sub = await s.get(Submission, sub_id)
            sub.status = SubStatus.error
            sub.verdict = "Judge Error"
            sub.judged_at = now()
            row = views.submission_result(sub)
        rt.hub.send(gid, "submission.result", row, role="team", team_id=team_id)
        await engine.push_live(gid, qid)
        return

    passed, first_failed, verdict, err = 0, None, "Accepted", None
    for i, (test, r) in enumerate(zip(cfg.tests, results), start=1):
        ok = r.status_id == ACCEPTED and outputs_match(r.stdout, test.expected)
        if ok:
            passed += 1
        elif first_failed is None:
            first_failed = i
            verdict = "Wrong Answer" if r.status_id == ACCEPTED else status_text(r.status_id)
            if r.status_id != ACCEPTED:
                err = summarise_error(r.stderr) or None
    times = [r.time_ms for r in results if r.time_ms is not None]
    mems = [r.memory_kb for r in results if r.memory_kb is not None]

    async with engine.lock(gid):
        async with session_scope() as s:
            sub = await s.get(Submission, sub_id)
            game = await s.get(Game, sub.game_id)
            q = await s.get(Question, sub.question_id)
            sub.status = SubStatus.judged
            sub.tests_passed, sub.tests_total = passed, len(cfg.tests)
            sub.verdict = verdict if passed < len(cfg.tests) else "Accepted"
            sub.first_failed = first_failed
            sub.error_summary = err
            sub.exec_time_ms = max(times) if times else None
            sub.memory_kb = max(mems) if mems else None
            sub.judged_at = now()
            sub.provisional_points = await engine.score_submission(s, game, q, sub)
            if sub.provisional_points is None and q.type == QuestionType.code_golf and passed == len(cfg.tests):
                rows = await views.monitor_rows(s, game, q)
                mine = next((r for r in rows if r["team_id"] == team_id), None)
                sub.provisional_points = mine["provisional_points"] if mine else None
            await s.flush()
            row = views.submission_result(sub)
            row["provisional"] = q.type != QuestionType.super_fast
            full = passed == len(cfg.tests) and passed > 0
            qtype = q.type
    rt.hub.send(gid, "submission.result", row, role="team", team_id=team_id)
    await engine.push_live(gid, qid)
    if full and qtype == QuestionType.super_fast:
        rt.hub.send_roles(gid, "solve", {"team_id": team_id, "elapsed_ms": row["elapsed_ms"]}, ("screen",))
        await engine.check_auto_end(gid, qid)


# ---------------------------------------------------------------------- run


async def run(team: Team, question_id: str, code: str, stdin: str | None) -> dict:
    if len(code) > MAX_CODE:
        raise GameError("Code is over 10,000 characters", 413)
    if stdin is not None and len(stdin) > MAX_STDIN:
        raise GameError("Custom input is over 10 KB", 413)
    gid, tid = str(team.game_id), str(team.id)
    key = f"{tid}:{question_id}"
    if tid in _run_in_flight:
        raise GameError("Your last Run is still going", 429)
    last = _run_last.get(key)
    if last and time.monotonic() - last < RUN_COOLDOWN_S:
        raise GameError(f"Wait {RUN_COOLDOWN_S - (time.monotonic() - last):.0f} s before running again", 429)

    async with session_scope() as s:
        game = await s.get(Game, team.game_id)
        if question_id == "practice":
            if game.state != GameState.lobby:
                raise GameError("Practice is only open in the lobby", 409)
            cfg = QuestionConfig(examples=PRACTICE["examples"])
            qid = None
        else:
            if str(game.current_question_id) != question_id or game.state not in (GameState.open, GameState.paused):
                raise GameError("That question isn't open", 409)
            q = await s.get(Question, game.current_question_id)
            if q.type == QuestionType.multiple_choice:
                raise GameError("That isn't a coding question", 409)
            cfg = QuestionConfig(**q.config)
            qid = q.id
            used = await s.scalar(
                select(func.count()).where(RunLog.game_id == game.id, RunLog.question_id == qid, RunLog.team_id == team.id)
            )
            if used >= RUN_MAX:
                raise GameError(f"You've used all {RUN_MAX} runs for this question", 429)
        log_row = RunLog(game_id=game.id, question_id=qid, team_id=team.id, custom_input=stdin is not None)
        s.add(log_row)
        await s.flush()
        run_id = log_row.id

    _run_in_flight.add(tid)
    _run_last[key] = time.monotonic()
    rt.queue.put(RUN, lambda: _run_job(run_id, gid, tid, qid, code, stdin, cfg))
    return {"run_id": run_id}


async def _run_job(run_id, gid, tid, qid, code, stdin, cfg: QuestionConfig) -> None:
    try:
        cases = [(None, stdin)] if stdin is not None else [(e, e.stdin) for e in cfg.examples]
        reqs = [ExecRequest(source=program(code, cfg), stdin=inp or "", **exec_limits(cfg)) for _, inp in cases]
        try:
            results = await run_with_retry(reqs, gid) if reqs else []
        except JudgeUnavailable:
            rt.hub.send(gid, "run.result", {"run_id": run_id, "error": "The judge is unavailable. Try again shortly."}, role="team", team_id=tid)
            return
        out = []
        for i, ((ex, inp), r) in enumerate(zip(cases, results), start=1):
            item = {
                "index": i,
                "stdin": inp,
                "stdout": r.stdout[:20_000],
                "stderr": r.stderr[:5_000],
                "status": status_text(r.status_id),
                "time_ms": r.time_ms,
                "memory_kb": r.memory_kb,
            }
            if ex is not None:
                item["expected"] = ex.expected
                item["passed"] = r.status_id == ACCEPTED and outputs_match(r.stdout, ex.expected)
            out.append(item)
        async with session_scope() as s:
            row = await s.get(RunLog, run_id)
            if row:
                row.status = "ok" if all(r.status_id == ACCEPTED for r in results) else "error"
        rt.hub.send(gid, "run.result", {"run_id": run_id, "custom": stdin is not None, "cases": out}, role="team", team_id=tid)
        if qid:
            await engine.push_live(gid, qid)
    except Exception:
        rt.hub.send(gid, "run.result", {"run_id": run_id, "error": "Run failed on the server. Try again."}, role="team", team_id=tid)
        raise
    finally:
        _run_in_flight.discard(tid)


# ---------------------------------------------------------------------- teacher tools


async def verify_question(q: Question) -> dict:
    """Run the reference solution on every hidden test (and examples). Must all pass."""
    cfg = QuestionConfig(**q.config)
    problems: list[str] = []
    if q.type == QuestionType.multiple_choice:
        texts = [o.text.strip() for o in cfg.options]
        if len(texts) < 2:
            problems.append("Add at least two answers.")
        if any(not t for t in texts):
            problems.append("Every answer needs some text (or remove the empty ones).")
        if not cfg.correct:
            problems.append("Mark at least one answer as correct.")
        return {"ok": not problems, "problems": problems, "tests": [], "examples": []}
    if not q.reference_solution.strip():
        problems.append("Add a reference solution.")
    if not cfg.tests:
        problems.append("Add at least one hidden test.")
    if q.type == QuestionType.code_golf and len(cfg.tests) < 8:
        problems.append("Code Golf needs at least 8 hidden tests (including edge cases) so outputs can't be hard-coded.")
    if q.type == QuestionType.best_complexity and not cfg.benchmark:
        problems.append("Best Time Complexity needs a benchmark generator and sizes.")
    if problems:
        return {"ok": False, "problems": problems, "tests": [], "examples": []}
    cases = [("test", t) for t in cfg.tests] + [("example", e) for e in cfg.examples]
    reqs = [ExecRequest(source=program(q.reference_solution, cfg), stdin=c.stdin, **exec_limits(cfg)) for _, c in cases]
    results = await rt.executor.run_batch(reqs)
    report = {"tests": [], "examples": []}
    for (kind, c), r in zip(cases, results):
        ok = r.status_id == ACCEPTED and outputs_match(r.stdout, c.expected)
        report["tests" if kind == "test" else "examples"].append(
            {"passed": ok, "status": status_text(r.status_id), "actual": r.stdout[:2000], "stderr": r.stderr[:2000], "time_ms": r.time_ms}
        )
        if not ok:
            problems.append(f"Reference solution fails {kind} {len(report['tests' if kind == 'test' else 'examples'])}.")
    if q.type == QuestionType.best_complexity:
        bench = cfg.benchmark
        base = await measure(rt.executor, bench, None)
        if base.error or base.timed_out_at:
            problems.append(f"Benchmark generator fails: {base.error or 'timed out'}.")
        else:
            ref = await measure(rt.executor, bench, q.reference_solution, base.times_ms)
            if ref.error or ref.timed_out_at:
                problems.append(f"Reference solution fails the benchmark: {ref.error or f'timed out at n={ref.timed_out_at}'}.")
            report["benchmark"] = {"baseline_ms": base.times_ms, "reference_ms": ref.times_ms}
    report["ok"] = not problems
    report["problems"] = problems
    return report


async def generate_outputs(q: Question) -> dict:
    """Fill expected outputs for hidden tests and examples from the reference solution."""
    cfg = QuestionConfig(**q.config)
    cases = cfg.tests + cfg.examples
    reqs = [ExecRequest(source=program(q.reference_solution, cfg), stdin=c.stdin, **exec_limits(cfg)) for c in cases]
    results = await rt.executor.run_batch(reqs)
    failures = []
    for i, (c, r) in enumerate(zip(cases, results)):
        if r.status_id == ACCEPTED:
            c.expected = r.stdout
        else:
            failures.append({"index": i, "status": status_text(r.status_id), "stderr": r.stderr[:2000]})
    return {"config": cfg.model_dump(), "failures": failures}


# ---------------------------------------------------------------------- benchmarks


async def benchmark_question(gid: str, qid) -> dict:
    """Benchmark each team's latest passing submission, one at a time."""
    async with session_scope() as s:
        q = await s.get(Question, qid)
        cfg = QuestionConfig(**q.config)
        passes = await views.full_passes(s, uuid.UUID(gid), qid)
        teams = {str(t.id) for t in (await s.scalars(select(Team).where(Team.game_id == uuid.UUID(gid), Team.kicked.is_(False)))).all()}
        reference = q.reference_solution
    latest: dict[str, Submission] = {}
    for p in passes:
        tid = str(p.team_id)
        if tid in teams and (tid not in latest or p.id > latest[tid].id):
            latest[tid] = p
    bench_cfg = cfg.benchmark
    result = {"sizes": bench_cfg.sizes if bench_cfg else [], "floor_ms": bench_cfg.floor_ms if bench_cfg else 0, "teams": {}}
    if not bench_cfg or not latest:
        return result
    total = len(latest)
    rt.hub.send_roles(gid, "judging.progress", {"done": 0, "total": total}, ("screen", "teacher", "team"))
    try:
        baseline = await measure(rt.executor, bench_cfg, None)
        ref = await measure(rt.executor, bench_cfg, reference, baseline.times_ms)
    except JudgeUnavailable:
        log.error("benchmark: judge unavailable; everyone passing gets the minimum share")
        for tid, sub in latest.items():
            result["teams"][tid] = {"submission_id": sub.id, "elapsed_ms": sub.elapsed_ms, "score_ms": None, "class_label": "not measured (judge down)"}
        return result
    done = 0
    for tid, sub in sorted(latest.items(), key=lambda kv: kv[1].elapsed_ms):
        try:
            r = await measure(rt.executor, bench_cfg, sub.code, baseline.times_ms)
        except JudgeUnavailable:
            r = None
        info = {"submission_id": sub.id, "elapsed_ms": sub.elapsed_ms}
        if r is None:
            info.update(score_ms=None, class_label="not measured (judge down)")
        else:
            wrong_at = next((n for n, h in r.hashes.items() if ref.hashes.get(n) and h != ref.hashes[n]), None)
            completed = r.timed_out_at is None and r.error is None and wrong_at is None
            top = r.top_time
            info.update(
                times_ms={str(n): round(v, 1) for n, v in r.times_ms.items()},
                top_ms=round(top, 1) if top is not None and completed else None,
                timed_out_at=r.timed_out_at,
                wrong_at=wrong_at,
                error=r.error,
                score_ms=max(top, float(bench_cfg.floor_ms)) if completed and top is not None else None,
                class_label=(
                    "wrong answer on a large input"
                    if wrong_at
                    else ("error on a large input" if r.error else estimate_class(r.times_ms, r.timed_out_at, bench_cfg.floor_ms, bench_cfg.cpu_limit_s * 1000))
                ),
            )
        result["teams"][tid] = info
        async with session_scope() as s:
            sub_row = await s.get(Submission, sub.id)
            sub_row.perf = info
        done += 1
        rt.hub.send_roles(gid, "judging.progress", {"done": done, "total": total}, ("screen", "teacher", "team"))
    return result


async def requeue_pending() -> int:
    """On restart, put queued/running submissions back on the queue."""
    async with session_scope() as s:
        ids = (
            await s.scalars(
                select(Submission.id).where(Submission.status.in_([SubStatus.queued, SubStatus.running])).order_by(Submission.id)
            )
        ).all()
    for sid in ids:
        rt.queue.put(SUBMIT, lambda sid=sid: judge_submission(sid))
    return len(ids)
