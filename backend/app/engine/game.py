"""The game: a server-authoritative state machine the teacher drives.

Live game:
LOBBY → ROUND_INTRO (4 s) → OPEN ⇄ PAUSED → CLOSED → [JUDGING] → RESULTS → LEADERBOARD
      → next ROUND_INTRO … → PODIUM → FINISHED

Free Run (every unlocked problem open at once, one clock for the whole game):
LOBBY → OPEN ⇄ PAUSED → CLOSED → [JUDGING: every Best Time Complexity problem] → LEADERBOARD
      → PODIUM → FINISHED
The host can set pause points ("breaks") so teams can't run ahead, and unlock the next section.

Every transition is one DB transaction (under a per-game lock) followed by one broadcast,
so a crash mid-event loses nothing: on restart `rearm_all` rebuilds timers from the DB.
"""

import asyncio
import hashlib
import logging
import secrets
import uuid
from collections import defaultdict
from datetime import datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import session_scope
from ..models import (
    Answer,
    Game,
    GameState,
    HintGiven,
    Question,
    QuestionType,
    ScoreEvent,
    Submission,
    SubStatus,
    Team,
)
from ..runtime import rt
from ..schemas.question import AutoEnd, Closest, Flat, QuestionConfig, Ranked, SpeedWeighted, Timed, parse_scoring
from . import views
from .leaderboard import slim, team_totals, with_previous
from .scoring import Entry, Partial, partial_points, ranked_points, score_at_close, super_fast_points, timed_points
from .views import now

log = logging.getLogger(__name__)

# What the projector shows on the results screen, and what stays revealed once shown.
SPOTLIGHTS = ("results", "winner", "solution")
REVEAL_KEYS = ("spotlight", "winner", "model_solution")

ROUND_INTRO_S = 4
END_NOW_S = 3
GRACE_MS = 500
JOIN_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O/1/I


class GameError(Exception):
    def __init__(self, message: str, status: int = 409):
        super().__init__(message)
        self.message = message
        self.status = status


def new_join_code() -> str:
    return "".join(secrets.choice(JOIN_ALPHABET) for _ in range(6))


def sha256(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


async def upsert_question_score(s: AsyncSession, game_id, team_id, question_id, points: int) -> None:
    row = await s.scalar(
        select(ScoreEvent).where(
            ScoreEvent.game_id == game_id,
            ScoreEvent.team_id == team_id,
            ScoreEvent.question_id == question_id,
            ScoreEvent.reason == "question",
        )
    )
    if row:
        row.points = points
    else:
        s.add(ScoreEvent(game_id=game_id, team_id=team_id, question_id=question_id, points=points, reason="question"))


class GameEngine:
    def __init__(self) -> None:
        self.locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self.timers: dict[str, asyncio.Task] = {}
        self.finishers: dict[str, asyncio.Task] = {}
        self.debounced: dict[str, asyncio.Task] = {}  # Free Run: coalesced broadcasts

    # ------------------------------------------------------------------ plumbing

    def lock(self, game_id) -> asyncio.Lock:
        return self.locks[str(game_id)]

    async def load(self, s: AsyncSession, game_id) -> Game:
        game = await s.get(Game, uuid.UUID(str(game_id)), with_for_update=True)
        if not game:
            raise GameError("Game not found", 404)
        return game

    async def broadcast(self, game_id) -> None:
        """Send every connection a fresh, role-filtered snapshot."""
        gid = str(game_id)
        conns = rt.hub.conns(gid)
        if not conns:
            return
        async with session_scope() as s:
            game = await s.get(Game, uuid.UUID(gid))
            if not game:
                return
            cache: dict[str, dict] = {}
            for c in conns:
                key = c.role if c.role != "team" else f"team:{c.team_id}"
                if key not in cache:
                    cache[key] = await views.build_snapshot(s, game, c.role, c.team_id)
                c.send("snapshot", cache[key])

    async def send_snapshot(self, conn) -> None:
        async with session_scope() as s:
            game = await s.get(Game, uuid.UUID(conn.game_id))
            if game:
                conn.send("snapshot", await views.build_snapshot(s, game, conn.role, conn.team_id))

    async def push_live(self, game_id, question_id) -> None:
        """Monitor rows to the teacher; the progress strip (solves, answer count) to everyone."""
        gid = str(game_id)
        async with session_scope() as s:
            game = await s.get(Game, uuid.UUID(gid))
            if game and views.is_free_run(game):
                self.schedule_broadcast(gid)
                return
            q = await s.get(Question, question_id)
            if not game or not q or game.current_question_id != q.id:
                return
            if rt.hub.conns(gid, "teacher"):
                rt.hub.send(
                    gid,
                    "monitor.update",
                    {
                        "question_id": str(q.id),
                        "rows": await views.monitor_rows(s, game, q),
                        "in_flight": await views.in_flight_count(s, game.id, q.id),
                    },
                    role="teacher",
                )
            prog = await views.progress(s, game, q)
            rt.hub.send_roles(gid, "progress.update", {"question_id": str(q.id), **prog}, ("screen", "teacher", "team"))

    def schedule_broadcast(self, gid: str, delay: float = 0.4) -> None:
        """Free Run: many small changes (judged submissions, answers) become one broadcast."""
        task = self.debounced.get(gid)
        if task and not task.done():
            return

        async def runner():
            await asyncio.sleep(delay)
            self.debounced.pop(gid, None)
            try:
                await self.broadcast(gid)
            except Exception:
                log.exception("broadcast failed for game %s", gid)

        self.debounced[gid] = asyncio.create_task(runner())

    def _cancel_timer(self, gid: str) -> None:
        t = self.timers.pop(gid, None)
        if t and t is not asyncio.current_task() and not t.done():
            t.cancel()

    def _arm(self, gid: str, when: datetime, cb) -> None:
        self._cancel_timer(gid)

        async def runner():
            delay = (when - now()).total_seconds()
            if delay > 0:
                await asyncio.sleep(delay)
            try:
                await cb(gid)
            except Exception:
                log.exception("timer callback failed for game %s", gid)

        self.timers[gid] = asyncio.create_task(runner())

    def _arm_deadline(self, game: Game) -> None:
        if game.deadline:
            self._arm(str(game.id), game.deadline + timedelta(milliseconds=GRACE_MS), self._on_deadline)

    async def _transition(self, game_id, fn, expect: set[GameState] | None = None, expect_state: str | None = None):
        gid = str(game_id)
        async with self.lock(gid):
            async with session_scope() as s:
                game = await self.load(s, gid)
                if expect_state and game.state.value != expect_state:
                    raise GameError("The game has already moved on", 409)
                if expect and game.state not in expect:
                    raise GameError(f"Not allowed while the game is '{game.state.value}'", 409)
                result = await fn(s, game)
        await self.broadcast(gid)
        return result

    # ------------------------------------------------------------------ lifecycle

    async def start(self, game_id, force: bool = False, expect_state: str | None = None) -> None:
        async def fn(s: AsyncSession, game: Game):
            teams = (await s.scalars(select(Team).where(Team.game_id == game.id, Team.kicked.is_(False)))).all()
            if not teams and not force:
                raise GameError("No teams have joined yet. Start anyway?", 409)
            questions = await views.quiz_questions(s, game.quiz_id)
            if not questions:
                raise GameError("This quiz has no questions", 409)
            game.started_at = now()
            if views.is_free_run(game):
                self._start_free_run(game)
            else:
                await self._start_round(s, game, 0, questions)

        await self._transition(game_id, fn, expect={GameState.lobby}, expect_state=expect_state)

    def _start_free_run(self, game: Game) -> None:
        t = now()
        game.last_board = []
        game.question_index = -1
        game.current_question_id = None
        game.state = GameState.open
        game.phase_ends_at = None
        game.opened_at = t
        game.deadline = t + timedelta(seconds=int((game.settings or {}).get("duration_s", 3600)))
        game.paused_at = None
        game.paused_total_ms = 0
        game.ending = game.ended_early = False
        self._arm_deadline(game)

    async def _start_round(self, s: AsyncSession, game: Game, index: int, questions: list[Question]) -> None:
        q = questions[index]
        game.last_board = slim(await team_totals(s, game.id))
        game.question_index = index
        game.current_question_id = q.id
        game.state = GameState.round_intro
        game.phase_ends_at = now() + timedelta(seconds=ROUND_INTRO_S)
        game.opened_at = game.deadline = game.paused_at = None
        game.paused_total_ms = 0
        game.ending = game.ended_early = False
        self._arm(str(game.id), game.phase_ends_at, self._on_intro_done)

    async def _on_intro_done(self, gid: str) -> None:
        async def fn(s: AsyncSession, game: Game):
            await self._open(s, game)

        try:
            await self._transition(gid, fn, expect={GameState.round_intro})
        except GameError:
            pass  # teacher skipped the intro already

    async def _open(self, s: AsyncSession, game: Game) -> None:
        q = await s.get(Question, game.current_question_id)
        t = now()
        game.state = GameState.open
        game.phase_ends_at = None
        game.opened_at = t
        # Unlimited time: no deadline, the clock counts up until the teacher presses End now.
        game.deadline = None if q.unlimited_time else t + timedelta(seconds=q.time_limit_s)
        game.paused_at = None
        game.paused_total_ms = 0
        self._arm_deadline(game)

    async def pause(self, game_id) -> None:
        async def fn(s, game: Game):
            game.state = GameState.paused
            game.paused_at = now()
            self._cancel_timer(str(game.id))

        await self._transition(game_id, fn, expect={GameState.open})

    def _resume_in_place(self, game: Game) -> None:
        t = now()
        paused_for = t - game.paused_at
        game.paused_total_ms += views.ms(paused_for)
        if game.deadline:
            game.deadline = game.deadline + paused_for
        game.paused_at = None
        game.state = GameState.open

    async def resume(self, game_id) -> None:
        async def fn(s, game: Game):
            self._resume_in_place(game)
            self._arm_deadline(game)

        await self._transition(game_id, fn, expect={GameState.paused})

    async def adjust_time(self, game_id, delta_s: float | None = None, set_remaining_s: float | None = None) -> None:
        async def fn(s, game: Game):
            ref = game.paused_at or now()
            if game.deadline is None and set_remaining_s is None:
                raise GameError("This question has no time limit. Use Set remaining to start a countdown, or End now", 409)
            remaining = (game.deadline - ref).total_seconds() if game.deadline else 0
            if set_remaining_s is not None:
                remaining = set_remaining_s
            elif delta_s is not None:
                remaining += delta_s
            remaining = min(max(remaining, 1), 60 * 60 * (6 if views.is_free_run(game) else 1))
            game.deadline = ref + timedelta(seconds=remaining)
            game.ending = False
            if game.state == GameState.open:
                self._arm_deadline(game)
            rt.hub.send(str(game.id), "timer.update", self._timer_payload(game))

        await self._transition(game_id, fn, expect={GameState.open, GameState.paused})

    def _timer_payload(self, game: Game) -> dict:
        return {
            "deadline": game.deadline.isoformat() if game.deadline else None,
            "paused": game.state == GameState.paused,
            "remaining_ms": views.remaining_ms(game),
            "elapsed_ms": views.elapsed_ms(game, now()),
            "ending": game.ending,
            "server_time": now().isoformat(),
        }

    async def end_now(self, game_id) -> None:
        async def fn(s, game: Game):
            if game.ending:
                return  # idempotent: already counting down
            if game.state == GameState.paused:
                self._resume_in_place(game)
            target = now() + timedelta(seconds=END_NOW_S)
            if game.deadline is None or game.deadline > target:
                game.deadline = target
            game.ending = True
            game.ended_early = True
            self._arm_deadline(game)
            rt.hub.send(str(game.id), "timer.update", self._timer_payload(game))

        await self._transition(game_id, fn, expect={GameState.open, GameState.paused})

    async def _on_deadline(self, gid: str) -> None:
        close = False

        async def fn(s, game: Game):
            nonlocal close
            if game.state != GameState.open or game.deadline is None:
                return
            due = game.deadline + timedelta(milliseconds=GRACE_MS)
            if now() < due - timedelta(milliseconds=20):
                self._arm_deadline(game)  # the deadline moved; sleep again
                return
            game.state = GameState.closed
            game.ending = False
            close = True

        await self._transition(gid, fn)
        if close:
            self._spawn_finisher(gid)

    def _spawn_finisher(self, gid: str) -> None:
        old = self.finishers.get(gid)
        if old and not old.done():
            return
        self.finishers[gid] = asyncio.create_task(self._finish_question(gid))

    async def _finish_question(self, gid: str) -> None:
        """After the buzzer: let in-flight submissions finish and count, then score and show results."""
        try:
            async with session_scope() as s:
                game = await s.get(Game, uuid.UUID(gid))
                qid = game.current_question_id
                free = views.is_free_run(game)
            if free:
                await self._finish_free_run(gid)
                return
            waited = 0.0
            while waited < 90:
                async with session_scope() as s:
                    if await views.in_flight_count(s, uuid.UUID(gid), qid) == 0:
                        break
                await asyncio.sleep(0.25)
                waited += 0.25
            await asyncio.sleep(1.5)  # hold "Time's up!" on screen for a moment

            async with session_scope() as s:
                q = await s.get(Question, qid)
                qtype = q.type
            if qtype == QuestionType.best_complexity:
                async def to_judging(s, game: Game):
                    if game.state not in (GameState.closed, GameState.judging) or game.current_question_id != qid:
                        raise GameError("moved on")
                    game.state = GameState.judging

                try:
                    await self._transition(gid, to_judging)
                except GameError:
                    return
                from .judging import benchmark_question

                bench = await benchmark_question(gid, qid)
            else:
                bench = None

            await self._to_results(gid, qid, bench)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("finishing question failed for game %s", gid)

    async def _to_results(self, gid: str, qid, bench: dict | None) -> bool:
        async def to_results(s, game: Game):
            if game.state not in (GameState.closed, GameState.judging) or game.current_question_id != qid:
                raise GameError("moved on")
            q = await s.get(Question, qid)
            await self._score_at_close(s, game, q, bench)
            game.results = {**(game.results or {}), str(qid): await self._results_payload(s, game, q, bench)}
            game.state = GameState.results

        try:
            await self._transition(gid, to_results)
        except GameError:
            return False
        async with session_scope() as s:
            game = await s.get(Game, uuid.UUID(gid))
            rt.hub.send(gid, "results", (game.results or {}).get(str(qid)))
        return True

    async def skip_measuring(self, game_id) -> None:
        """Best Time Complexity: stop benchmarking and show results now. Teams already
        measured keep their result; the rest show as not measured, and the teacher can
        give them points with an override."""
        gid = str(game_id)
        async with session_scope() as s:
            game = await s.get(Game, uuid.UUID(gid))
            if not game or game.state != GameState.judging:
                raise GameError("Nothing is being measured", 409)
            qid = game.current_question_id
            free = views.is_free_run(game)
            complexity = [q.id for q in await views.quiz_questions(s, game.quiz_id) if q.type == QuestionType.best_complexity]
        task = self.finishers.get(gid)
        if task and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        from .judging import partial_bench

        if free:
            benches = {str(c): await partial_bench(gid, c) for c in complexity}
            if not await self._close_free_run(gid, benches):
                raise GameError("The game has already moved on", 409)
            return

        if not await self._to_results(gid, qid, await partial_bench(gid, qid)):
            raise GameError("The game has already moved on", 409)

    # ------------------------------------------------------------------ scoring

    async def score_submission(self, s: AsyncSession, game: Game, q: Question, sub: Submission) -> int | None:
        """Immediate scoring on judge (Super Fast). Returns the points shown to the team."""
        rule = parse_scoring(q.scoring)
        full = bool(sub.tests_total) and sub.tests_passed == sub.tests_total
        if isinstance(rule, SpeedWeighted):
            pts = super_fast_points(rule, sub.elapsed_ms, q.time_limit_s * 1000, sub.tests_passed or 0, sub.tests_total or 0)
            current = (await views.question_points(s, game.id, q.id)).get(str(sub.team_id))
            if pts > 0 and (current is None or pts > current):
                await upsert_question_score(s, game.id, sub.team_id, q.id, pts)
            return pts
        if q.type == QuestionType.super_fast and isinstance(rule, Ranked):
            if not full:
                return 0
            return (await self._rank_first_solves(s, game, q, rule)).get(str(sub.team_id), 0)
        if q.type == QuestionType.super_fast and isinstance(rule, Flat):
            if not full:
                return 0
            await upsert_question_score(s, game.id, sub.team_id, q.id, rule.max)
            return rule.max
        return None  # scored at close

    async def _rank_first_solves(self, s: AsyncSession, game: Game, q: Question, rule: Ranked) -> dict[str, int]:
        """Super Fast: places go by when each team's first full pass was *received* (not when it
        was judged), so re-rank everyone on every new pass; only the first len(points) score."""
        await s.flush()
        active = {t.id for t in (await s.scalars(select(Team).where(Team.game_id == game.id, Team.kicked.is_(False)))).all()}
        order: list[uuid.UUID] = []
        for p in await views.full_passes(s, game.id, q.id):  # sorted by elapsed_ms, id
            if p.team_id in active and p.team_id not in order:
                order.append(p.team_id)
        await s.execute(
            delete(ScoreEvent).where(ScoreEvent.game_id == game.id, ScoreEvent.question_id == q.id, ScoreEvent.reason == "question")
        )
        out: dict[str, int] = {}
        for place, tid in enumerate(order[: len(rule.points)]):
            out[str(tid)] = ranked_points(rule, place)
            s.add(ScoreEvent(game_id=game.id, team_id=tid, question_id=q.id, points=out[str(tid)], reason="question"))
        await s.flush()
        return out

    async def _score_at_close(self, s: AsyncSession, game: Game, q: Question, bench: dict | None) -> None:
        rule = parse_scoring(q.scoring)
        if q.type == QuestionType.super_fast:
            # Full passes were scored as they arrived; partial credit is added once it closes.
            if isinstance(rule, (Flat, Ranked)):
                scored = {tid for tid, p in (await views.question_points(s, game.id, q.id)).items() if p > 0}
                for tid, pts in (await self._partial_scores(s, game, q, rule, scored)).items():
                    await upsert_question_score(s, game.id, uuid.UUID(tid), q.id, pts)
                await s.flush()
            return
        if q.type == QuestionType.multiple_choice:
            await self._score_answers(s, game, q, rule)
            return
        entries = self._close_entries(q, await views.full_passes(s, game.id, q.id), bench)
        points = score_at_close(rule, entries) if isinstance(rule, (Closest, Flat, Ranked)) else {}
        if isinstance(rule, (Closest, Flat, Ranked)):
            overridden = {tid for tid, info in (bench or {}).get("teams", {}).items() if info.get("override_points") is not None}
            keep = {tid for tid, p in points.items() if p > 0} | overridden
            points.update(await self._partial_scores(s, game, q, rule, keep))
        await s.execute(
            delete(ScoreEvent).where(
                ScoreEvent.game_id == game.id, ScoreEvent.question_id == q.id, ScoreEvent.reason == "question"
            )
        )
        for tid, pts in points.items():
            s.add(ScoreEvent(game_id=game.id, team_id=uuid.UUID(tid), question_id=q.id, points=pts, reason="question"))
        # Store the final points on each team's counted submission for the history view.
        await s.flush()

    async def _score_answers(self, s: AsyncSession, game: Game, q: Question, rule) -> None:
        """Multiple choice is scored once, at close, so nobody's total gives the answer away early."""
        await s.execute(
            delete(ScoreEvent).where(ScoreEvent.game_id == game.id, ScoreEvent.question_id == q.id, ScoreEvent.reason == "question")
        )
        for a in await views.answers_of(s, game.id, q.id):
            if not a.correct:
                continue
            pts = timed_points(rule, a.elapsed_ms, q.time_limit_s * 1000) if isinstance(rule, Timed) else rule.max
            s.add(ScoreEvent(game_id=game.id, team_id=a.team_id, question_id=q.id, points=pts, reason="question"))
        await s.flush()

    async def _partial_scores(self, s: AsyncSession, game: Game, q: Question, rule, exclude: set[str]) -> dict[str, int]:
        """Partial credit for every active team not in `exclude` (teams whose full pass already
        scored). Each team's best judged submission counts: most tests passed first, then the
        round's own measure: fewest characters (golf), fastest test run (complexity), or
        earliest submission (Super Fast)."""
        active = {
            str(t.id) for t in (await s.scalars(select(Team).where(Team.game_id == game.id, Team.kicked.is_(False)))).all()
        }
        subs = (
            await s.scalars(
                select(Submission)
                .where(Submission.game_id == game.id, Submission.question_id == q.id, Submission.status == SubStatus.judged)
                .order_by(Submission.id)
            )
        ).all()
        best: dict[str, tuple[tuple, Partial]] = {}
        for sub in subs:
            tid = str(sub.team_id)
            if tid not in active or tid in exclude or not sub.tests_total or not sub.tests_passed:
                continue
            if q.type == QuestionType.code_golf:
                value = sub.char_count
            elif q.type == QuestionType.best_complexity:
                value = sub.exec_time_ms
            else:
                value = sub.elapsed_ms
            key = (sub.tests_passed, -(value if value is not None else float("inf")))
            if tid not in best or key > best[tid][0]:
                best[tid] = (key, Partial(tid, sub.tests_passed, sub.tests_total, value))
        return partial_points(rule, [p for _, p in best.values()])

    def _close_entries(self, q: Question, passes: list[Submission], bench: dict | None) -> list[Entry]:
        entries: dict[str, Entry] = {}
        if q.type == QuestionType.code_golf:
            for p in passes:  # shortest passing entry per team; earlier wins ties
                tid = str(p.team_id)
                e = entries.get(tid)
                if e is None or p.char_count < e.value:
                    entries[tid] = Entry(tid, p.char_count, p.elapsed_ms)
        elif q.type == QuestionType.best_complexity:
            for tid, info in (bench or {}).get("teams", {}).items():
                if info.get("override_points") is not None:
                    continue
                entries[tid] = Entry(tid, info.get("score_ms"), info.get("elapsed_ms", 0))
        return list(entries.values())

    async def rescore(self, game_id, question_id) -> None:
        """Recompute a question's automatic points from stored submissions (manual rows untouched)."""

        async def fn(s: AsyncSession, game: Game):
            q = await s.get(Question, uuid.UUID(str(question_id)))
            if not q or q.quiz_id != game.quiz_id:
                raise GameError("Question not in this game", 404)
            if q.type == QuestionType.super_fast:
                await s.execute(
                    delete(ScoreEvent).where(
                        ScoreEvent.game_id == game.id, ScoreEvent.question_id == q.id, ScoreEvent.reason == "question"
                    )
                )
                await s.flush()
                subs = (
                    await s.scalars(
                        select(Submission)
                        .where(Submission.game_id == game.id, Submission.question_id == q.id, Submission.status == SubStatus.judged)
                        .order_by(Submission.elapsed_ms, Submission.id)
                    )
                ).all()
                for sub in subs:
                    sub.provisional_points = await self.score_submission(s, game, q, sub)
                    await s.flush()
                if str(q.id) in (game.results or {}):
                    await self._score_at_close(s, game, q, None)
            else:
                bench = (game.results or {}).get(str(q.id), {}).get("bench")
                await self._score_at_close(s, game, q, bench)
                await self._apply_overrides(s, game, q, bench)
            if str(q.id) in (game.results or {}):
                await self._refresh_results(s, game, q, (game.results or {}).get(str(q.id), {}).get("bench"))

        await self._transition(game_id, fn)

    async def _apply_overrides(self, s: AsyncSession, game: Game, q: Question, bench: dict | None) -> None:
        for tid, info in (bench or {}).get("teams", {}).items():
            if info.get("override_points") is not None:
                await upsert_question_score(s, game.id, uuid.UUID(tid), q.id, int(info["override_points"]))

    async def override_result(self, game_id, team_id: str, class_label: str | None, points: int | None) -> None:
        """Best Time Complexity: the teacher can correct the estimated class or the points."""

        async def fn(s: AsyncSession, game: Game):
            q = await s.get(Question, game.current_question_id)
            if not q or q.type != QuestionType.best_complexity:
                raise GameError("Overrides apply to Best Time Complexity results", 409)
            res = dict((game.results or {}).get(str(q.id)) or {})
            bench = res.get("bench") or {"teams": {}}
            info = dict(bench["teams"].get(team_id) or {})
            if not info:
                raise GameError("That team has no benchmarked entry", 404)
            if class_label is not None:
                info["class_override"] = class_label[:40]
            if points is not None:
                info["override_points"] = points
            bench = {**bench, "teams": {**bench["teams"], team_id: info}}
            res["bench"] = bench
            game.results = {**game.results, str(q.id): res}
            await self._score_at_close(s, game, q, bench)
            await self._apply_overrides(s, game, q, bench)
            await s.flush()
            await self._refresh_results(s, game, q, bench)

        await self._transition(game_id, fn, expect={GameState.results, GameState.leaderboard})

    async def _refresh_results(self, s: AsyncSession, game: Game, q: Question, bench: dict | None) -> None:
        """Rebuild a question's results after points change, keeping what was already revealed."""
        old = (game.results or {}).get(str(q.id)) or {}
        new = await self._results_payload(s, game, q, bench)
        new.update({k: old[k] for k in REVEAL_KEYS if k in old})
        if "winner" in old:
            new["winner"] = await self._winner(s, game, q, new) or old["winner"]
        game.results = {**(game.results or {}), str(q.id): new}

    async def _winner(self, s: AsyncSession, game: Game, q: Question, res: dict) -> dict | None:
        """The top-scoring team's counted solution, for showing on the projector."""
        rows = [r for r in res.get("rows", []) if (r.get("points") or 0) > 0]
        if not rows:
            return None
        best = max(r["points"] for r in rows)
        top = next(r for r in rows if r["points"] == best)
        return await self._team_solution(s, game, q, res, top)

    async def _team_solution(self, s: AsyncSession, game: Game, q: Question, res: dict, top: dict) -> dict | None:
        """The solution that counts for one team (results row `top`)."""
        subs = (
            await s.scalars(
                select(Submission)
                .where(
                    Submission.game_id == game.id,
                    Submission.question_id == q.id,
                    Submission.team_id == uuid.UUID(top["team_id"]),
                    Submission.status == SubStatus.judged,
                )
                .order_by(Submission.id)
            )
        ).all()
        if not subs:
            return None
        full = [x for x in subs if x.tests_total and x.tests_passed == x.tests_total]
        bench_id = ((res.get("bench") or {}).get("teams", {}).get(top["team_id"]) or {}).get("submission_id")
        if bench_id and any(x.id == bench_id for x in subs):
            sub = next(x for x in subs if x.id == bench_id)
        elif full and q.type == QuestionType.code_golf:
            sub = min(full, key=lambda x: (x.char_count, x.elapsed_ms))
        elif full:
            sub = min(full, key=lambda x: (x.elapsed_ms, x.id))
        else:
            sub = max(subs, key=lambda x: (x.tests_passed or 0, -x.elapsed_ms))
        return {
            "team_id": top["team_id"],
            "name": top["name"],
            "points": top["points"],
            "code": sub.code,
            "passed": sub.tests_passed,
            "total": sub.tests_total,
            "chars": sub.char_count,
            "class_label": top.get("class_label"),
        }

    async def spotlight(self, game_id, what: str) -> None:
        """Results screen: show the table, the winning team's solution, or the model solution
        on the projector (and on every team's screen). Once shown, a solution stays revealed."""
        if what not in SPOTLIGHTS:
            raise GameError("Unknown thing to show", 400)

        async def fn(s: AsyncSession, game: Game):
            q = await s.get(Question, game.current_question_id)
            if q.type == QuestionType.multiple_choice and what != "results":
                raise GameError("Multiple-choice questions have no code to show", 409)
            res = dict((game.results or {}).get(str(q.id)) or {})
            if not res:
                raise GameError("No results yet", 409)
            if what == "winner":
                w = await self._winner(s, game, q, res)
                if not w:
                    raise GameError("Nobody scored on this question, so there's no winning solution", 409)
                res["winner"] = w
            elif what == "solution":
                res["model_solution"] = q.reference_solution
            res["spotlight"] = None if what == "results" else what
            game.results = {**(game.results or {}), str(q.id): res}

        await self._transition(game_id, fn, expect={GameState.results})

    async def give_hint(self, game_id, hint_index: int, team_id: str | None = None, question_id: str | None = None) -> int:
        """Send one of the question's hints to a team (or every team that hasn't had it yet).
        In Free Run the host says which problem it's for."""
        sent: list[str] = []
        info: dict = {}

        async def fn(s: AsyncSession, game: Game):
            if views.is_free_run(game):
                if not question_id:
                    raise GameError("Choose which problem the hint is for", 400)
                q = await self._free_question(s, game, question_id, check_locked=False)
            else:
                q = await s.get(Question, game.current_question_id) if game.current_question_id else None
            if not q or game.state not in (GameState.open, GameState.paused):
                raise GameError("Hints can only be given while a question is running", 409)
            hints = (q.config or {}).get("hints") or []
            if not 0 <= hint_index < len(hints):
                raise GameError("That hint doesn't exist", 400)
            teams = (await s.scalars(select(Team).where(Team.game_id == game.id, Team.kicked.is_(False)))).all()
            if team_id is not None:
                teams = [t for t in teams if str(t.id) == team_id]
                if not teams:
                    raise GameError("Unknown team", 404)
            had = set(
                (
                    await s.scalars(
                        select(HintGiven.team_id).where(
                            HintGiven.game_id == game.id, HintGiven.question_id == q.id, HintGiven.hint_index == hint_index
                        )
                    )
                ).all()
            )
            for t in teams:
                if t.id not in had:
                    s.add(HintGiven(game_id=game.id, question_id=q.id, team_id=t.id, hint_index=hint_index))
                    sent.append(str(t.id))
            info.update(question_id=str(q.id), title=q.title, index=hint_index, number=hint_index + 1, text=hints[hint_index])

        await self._transition(game_id, fn)
        for tid in sent:
            rt.hub.send(str(game_id), "hint", info, role="team", team_id=tid)
        if sent:
            await self.push_live(game_id, uuid.UUID(info["question_id"]))
        return len(sent)

    async def _results_payload(self, s: AsyncSession, game: Game, q: Question, bench: dict | None) -> dict:
        teams = {
            str(t.id): t.name
            for t in (await s.scalars(select(Team).where(Team.game_id == game.id, Team.kicked.is_(False)))).all()
        }
        points = await views.question_points(s, game.id, q.id)
        if q.type == QuestionType.multiple_choice:
            return await self._mcq_results(s, game, q, teams, points)
        subs = (
            await s.scalars(
                select(Submission)
                .where(Submission.game_id == game.id, Submission.question_id == q.id, Submission.status == SubStatus.judged)
                .order_by(Submission.id)
            )
        ).all()
        per: dict[str, list[Submission]] = defaultdict(list)
        for sub in subs:
            per[str(sub.team_id)].append(sub)
        rows = []
        for tid, name in teams.items():
            mine = per.get(tid, [])
            full = [x for x in mine if x.tests_total and x.tests_passed == x.tests_total]
            best = max(mine, key=lambda x: ((x.tests_passed or 0) / (x.tests_total or 1), -x.elapsed_ms), default=None)
            row = {
                "team_id": tid,
                "name": name,
                "points": points.get(tid, 0),
                "attempts": len(mine),
                "passed": best.tests_passed if best else None,
                "total": best.tests_total if best else None,
                "first_full_ms": min((x.elapsed_ms for x in full), default=None),
                "chars": min((x.char_count for x in full), default=None),
            }
            if bench and tid in bench.get("teams", {}):
                info = bench["teams"][tid]
                row["time_ms"] = info.get("top_ms")
                row["class_label"] = info.get("class_override") or info.get("class_label")
                row["timed_out"] = info.get("timed_out_at") is not None
                row["wrong_at_scale"] = info.get("wrong_at") is not None
            rows.append(row)

        if q.type == QuestionType.super_fast:
            rows.sort(key=lambda r: (-r["points"], r["first_full_ms"] if r["first_full_ms"] is not None else 1e12))
        elif q.type == QuestionType.code_golf:
            rows.sort(key=lambda r: (r["chars"] if r["chars"] is not None else 1e12, -r["points"]))
        else:
            rows.sort(key=lambda r: (-r["points"], r.get("time_ms") if r.get("time_ms") is not None else 1e12))

        payload = {"question_id": str(q.id), "type": q.type.value, "round_name": q.round_name, "title": q.title, "rows": rows}
        if q.type == QuestionType.code_golf:
            best_by_team: dict[str, Submission] = {}
            for sub in subs:
                tid = str(sub.team_id)
                if tid in teams and sub.tests_total and sub.tests_passed == sub.tests_total:
                    cur = best_by_team.get(tid)
                    if cur is None or sub.char_count < cur.char_count:
                        best_by_team[tid] = sub
            top = sorted(best_by_team.values(), key=lambda x: (x.char_count, x.elapsed_ms))[:3]
            payload["top3"] = [{"team_id": str(x.team_id), "name": teams[str(x.team_id)], "chars": x.char_count, "code": x.code} for x in top]
        if q.type == QuestionType.super_fast:
            payload["solves"] = (await views.progress(s, game, q)).get("solves", [])
        if bench is not None:
            payload["bench"] = bench
            payload["sizes"] = bench.get("sizes")
            payload["floor_ms"] = bench.get("floor_ms", 0)
        return payload

    # ------------------------------------------------------------------ navigation

    async def next(self, game_id, expect_state: str | None = None) -> None:
        async def fn(s: AsyncSession, game: Game):
            if game.state == GameState.round_intro:
                await self._open(s, game)
            elif game.state == GameState.results:
                game.state = GameState.leaderboard
            elif game.state == GameState.leaderboard and views.is_free_run(game):
                game.state = GameState.podium
            elif game.state == GameState.leaderboard:
                questions = await views.quiz_questions(s, game.quiz_id)
                if game.question_index + 1 < len(questions):
                    await self._start_round(s, game, game.question_index + 1, questions)
                else:
                    game.state = GameState.podium
            elif game.state == GameState.podium:
                game.state = GameState.finished
                game.finished_at = now()
            else:
                raise GameError(f"Nothing to advance to from '{game.state.value}'", 409)
            return game.state

        state = await self._transition(game_id, fn, expect_state=expect_state)
        await self._after_navigation(game_id, state)

    async def _after_navigation(self, game_id, state: GameState) -> None:
        gid = str(game_id)
        async with session_scope() as s:
            game = await s.get(Game, uuid.UUID(gid))
            board = with_previous(await team_totals(s, game.id), game.last_board)
        if state == GameState.leaderboard:
            rt.hub.send(gid, "leaderboard.update", {"rows": board})
        elif state == GameState.podium:
            rt.hub.send(gid, "podium", {"rows": board})

    async def goto(self, game_id, target: str) -> None:
        """Explicit /results, /leaderboard, /podium buttons."""
        allowed = {
            "results": ({GameState.leaderboard}, GameState.results),
            "leaderboard": ({GameState.results}, GameState.leaderboard),
            "podium": ({GameState.leaderboard, GameState.results}, GameState.podium),
        }
        if target not in allowed:
            raise GameError("Unknown target", 404)
        frm, to = allowed[target]

        async def fn(s, game: Game):
            game.state = to
            return to

        state = await self._transition(game_id, fn, expect=frm)
        await self._after_navigation(game_id, state)

    # ------------------------------------------------------------------ auto end

    async def _mcq_results(self, s: AsyncSession, game: Game, q: Question, teams: dict[str, str], points: dict[str, int]) -> dict:
        cfg = q.config or {}
        correct = set(cfg.get("correct", []))
        answers = {str(a.team_id): a for a in await views.answers_of(s, game.id, q.id) if str(a.team_id) in teams}
        options = [
            {"index": i, "text": o.get("text", ""), "correct": i in correct, "count": sum(1 for a in answers.values() if a.choice == i)}
            for i, o in enumerate(cfg.get("options", []))
        ]
        rows = [
            {
                "team_id": tid,
                "name": name,
                "points": points.get(tid, 0),
                "choice": answers[tid].choice if tid in answers else None,
                "correct": answers[tid].correct if tid in answers else False,
                "answer_ms": answers[tid].elapsed_ms if tid in answers else None,
            }
            for tid, name in teams.items()
        ]
        rows.sort(key=lambda r: (-r["points"], r["answer_ms"] if r["answer_ms"] is not None else 1e12, r["name"].lower()))
        return {
            "question_id": str(q.id),
            "type": q.type.value,
            "round_name": q.round_name,
            "title": q.title,
            "options": options,
            "answered": len(answers),
            "rows": rows,
        }

    async def answer(self, team: Team, question_id: str, choice: int) -> dict:
        """A team locks in a multiple-choice answer. Correctness stays hidden until results."""
        gid = str(team.game_id)
        close = False
        async with self.lock(gid):
            async with session_scope() as s:
                game = await s.get(Game, team.game_id, with_for_update=True)
                t = now()
                if views.is_free_run(game):
                    q = await self._free_question(s, game, question_id)
                    await self._free_answer(s, game, q, team, choice, t)
                    qid = q.id
                    free = True
                else:
                    free = False
            if free:
                await self.push_live(gid, qid)
                return {"ok": True, "choice": choice}
            async with session_scope() as s:
                game = await s.get(Game, team.game_id, with_for_update=True)
                t = now()
                if str(game.current_question_id) != question_id:
                    raise GameError("That question isn't open", 409)
                q = await s.get(Question, game.current_question_id)
                if q.type != QuestionType.multiple_choice:
                    raise GameError("That isn't a multiple-choice question", 409)
                if game.state == GameState.paused:
                    raise GameError("The game is paused", 409)
                if game.state != GameState.open or (game.deadline and t > game.deadline + timedelta(milliseconds=GRACE_MS)):
                    raise GameError("Time's up for this question", 409)
                options = (q.config or {}).get("options", [])
                if not 0 <= choice < len(options):
                    raise GameError("That answer doesn't exist", 400)
                if await s.scalar(select(Answer.id).where(Answer.game_id == game.id, Answer.question_id == q.id, Answer.team_id == team.id)):
                    raise GameError("You've already answered", 409)
                s.add(
                    Answer(
                        game_id=game.id,
                        question_id=q.id,
                        team_id=team.id,
                        choice=choice,
                        correct=choice in (q.config or {}).get("correct", []),
                        elapsed_ms=views.elapsed_ms(game, t),
                    )
                )
                await s.flush()
                prog = await views.progress(s, game, q)
                qid = q.id
                # Everyone has answered: close straight away.
                if prog["teams_total"] and prog["answered"] >= prog["teams_total"]:
                    game.state = GameState.closed
                    game.ending = False
                    game.ended_early = True
                    self._cancel_timer(gid)
                    close = True
        if close:
            await self.broadcast(gid)
            self._spawn_finisher(gid)
        else:
            await self.push_live(gid, qid)
        return {"ok": True, "choice": choice}

    # ------------------------------------------------------------------ Free Run

    async def open_question(self, s: AsyncSession, game: Game, question_id: str) -> Question:
        """The question a team may run / submit / answer right now."""
        if views.is_free_run(game):
            return await self._free_question(s, game, question_id)
        if str(game.current_question_id) != question_id:
            raise GameError("That question isn't open", 409)
        return await s.get(Question, game.current_question_id)

    async def _free_question(self, s: AsyncSession, game: Game, question_id: str, check_locked: bool = True) -> Question:
        try:
            qid = uuid.UUID(str(question_id))
        except ValueError:
            raise GameError("Unknown problem", 404) from None
        questions = await views.quiz_questions(s, game.quiz_id)
        idx = next((i for i, q in enumerate(questions) if q.id == qid), None)
        if idx is None:
            raise GameError("Unknown problem", 404)
        if check_locked and idx >= views.free_run_visible(game, len(questions)):
            raise GameError("That problem is locked until the host unlocks the next section", 409)
        return questions[idx]

    def check_not_closed(self, game: Game, q: Question) -> None:
        if views.is_free_run(game) and str(q.id) in views.free_run_closed(game):
            raise GameError("This problem was closed after it was analysed", 409)

    async def _free_answer(self, s: AsyncSession, game: Game, q: Question, team: Team, choice: int, t) -> None:
        """Free Run multiple choice: one answer, scored straight away (no per-question clock,
        so no speed bonus)."""
        if q.type != QuestionType.multiple_choice:
            raise GameError("That isn't a multiple-choice question", 409)
        self.check_not_closed(game, q)
        if game.state == GameState.paused:
            raise GameError("The game is paused", 409)
        if game.state != GameState.open or (game.deadline and t > game.deadline + timedelta(milliseconds=GRACE_MS)):
            raise GameError("Time's up", 409)
        options = (q.config or {}).get("options", [])
        if not 0 <= choice < len(options):
            raise GameError("That answer doesn't exist", 400)
        if await s.scalar(select(Answer.id).where(Answer.game_id == game.id, Answer.question_id == q.id, Answer.team_id == team.id)):
            raise GameError("You've already answered", 409)
        correct = choice in (q.config or {}).get("correct", [])
        s.add(Answer(game_id=game.id, question_id=q.id, team_id=team.id, choice=choice, correct=correct, elapsed_ms=views.elapsed_ms(game, t)))
        if correct:
            await upsert_question_score(s, game.id, team.id, q.id, parse_scoring(q.scoring).max)

    async def free_run_rescore(self, s: AsyncSession, game: Game, q: Question) -> None:
        """Free Run: points update as submissions are judged. Code Golf and Best Time Complexity
        are provisional (complexity uses the test run times until the real benchmark at the end);
        Super Fast places are already set as solves arrive, this adds partial credit."""
        if q.type == QuestionType.multiple_choice:
            return
        bench = None
        if q.type == QuestionType.best_complexity:
            cfg = QuestionConfig(**q.config)
            floor = cfg.benchmark.floor_ms if cfg.benchmark else 0
            latest: dict[str, Submission] = {}
            for p in await views.full_passes(s, game.id, q.id):
                tid = str(p.team_id)
                if tid not in latest or p.id > latest[tid].id:
                    latest[tid] = p
            bench = {
                "teams": {
                    tid: {"submission_id": p.id, "elapsed_ms": p.elapsed_ms, "score_ms": max(float(p.exec_time_ms or 0), float(floor))}
                    for tid, p in latest.items()
                }
            }
        await self._score_at_close(s, game, q, bench)

    async def _finish_free_run(self, gid: str) -> None:
        """After the buzzer: let in-flight submissions finish, benchmark every Best Time
        Complexity problem, then settle all the points and show the leaderboard."""
        waited = 0.0
        while waited < 90:
            async with session_scope() as s:
                busy = await s.scalar(
                    select(func.count()).where(
                        Submission.game_id == uuid.UUID(gid), Submission.status.in_([SubStatus.queued, SubStatus.running])
                    )
                )
            if not busy:
                break
            await asyncio.sleep(0.25)
            waited += 0.25
        await asyncio.sleep(1.5)  # hold "Time's up!" on screen for a moment
        async with session_scope() as s:
            game = await s.get(Game, uuid.UUID(gid))
            complexity = [q.id for q in await views.quiz_questions(s, game.quiz_id) if q.type == QuestionType.best_complexity]
        benches: dict[str, dict] = {}
        if complexity:
            async def to_judging(s, game: Game):
                if game.state not in (GameState.closed, GameState.judging):
                    raise GameError("moved on")
                game.state = GameState.judging

            try:
                await self._transition(gid, to_judging)
            except GameError:
                return
            from .judging import benchmark_question

            for qid in complexity:
                benches[str(qid)] = await benchmark_question(gid, qid)
        await self._close_free_run(gid, benches)

    async def _close_free_run(self, gid: str, benches: dict[str, dict]) -> bool:
        async def to_board(s, game: Game):
            if game.state not in (GameState.closed, GameState.judging):
                raise GameError("moved on")
            results = dict(game.results or {})
            for q in await views.quiz_questions(s, game.quiz_id):
                bench = benches.get(str(q.id))
                if q.type != QuestionType.multiple_choice:  # multiple choice was scored as answered
                    await self._score_at_close(s, game, q, bench)
                results[str(q.id)] = await self._results_payload(s, game, q, bench)
            game.results = results
            game.state = GameState.leaderboard
            return game.state

        try:
            state = await self._transition(gid, to_board)
        except GameError:
            return False
        await self._after_navigation(gid, state)
        return True

    async def start_analysis(self, game_id, question_id: str) -> None:
        """Free Run: pause the clock and put one problem on every screen: how teams did and
        the best team solution so far (the host can switch to the model solution)."""

        async def fn(s: AsyncSession, game: Game):
            if not views.is_free_run(game):
                raise GameError("Analyse is for Free Run games", 409)
            if game.state not in (GameState.open, GameState.paused) or game.ending:
                raise GameError("You can analyse a problem while the game is running", 409)
            settings = game.settings or {}
            if settings.get("analysing"):
                raise GameError("Finish the current analysis first", 409)
            q = await self._free_question(s, game, question_id)
            paused_it = game.state == GameState.open
            if paused_it:
                game.state = GameState.paused
                game.paused_at = now()
                self._cancel_timer(str(game.id))
            res = await self._results_payload(s, game, q, None)
            winner = None if q.type == QuestionType.multiple_choice else await self._winner(s, game, q, res)
            if winner:
                res["winner"] = winner
            game.results = {**(game.results or {}), str(q.id): res}
            game.settings = {
                **settings,
                "analysing": str(q.id),
                "analysis_show": "winner" if winner else "results",
                "analysis_paused": paused_it,
            }

        await self._transition(game_id, fn)

    async def show_analysis(self, game_id, what: str, team_id: str | None = None) -> None:
        """What the screens show while analysing: the table, the best team solution, one team's
        solution (to talk through each in turn) or the model solution."""
        if what not in (*SPOTLIGHTS, "team"):
            raise GameError("Unknown thing to show", 400)

        async def fn(s: AsyncSession, game: Game):
            qid = (game.settings or {}).get("analysing")
            if not qid:
                raise GameError("Nothing is being analysed", 409)
            q = await s.get(Question, uuid.UUID(qid))
            res = dict((game.results or {}).get(qid) or {})
            if what == "winner" and not res.get("winner"):
                raise GameError("Nobody has solved this one yet, so there's no best solution", 409)
            if what == "solution":
                if q.type == QuestionType.multiple_choice:
                    raise GameError("Multiple-choice questions have no code to show", 409)
                res["model_solution"] = q.reference_solution
                game.results = {**(game.results or {}), qid: res}
            if what == "team":
                if q.type == QuestionType.multiple_choice:
                    raise GameError("Multiple-choice questions have no code to show", 409)
                row = next((r for r in res.get("rows", []) if r["team_id"] == team_id), None)
                sol = await self._team_solution(s, game, q, res, row) if row else None
                if not sol:
                    raise GameError("That team hasn't submitted anything for this problem", 409)
                res["team_solution"] = sol
                game.results = {**(game.results or {}), qid: res}
            game.settings = {**(game.settings or {}), "analysis_show": what}

        await self._transition(game_id, fn)

    async def end_analysis(self, game_id, lock: bool) -> None:
        """Back to the game. Locking stops any more submissions or answers on that problem
        (points so far stand). The clock restarts if analysing paused it."""

        async def fn(s: AsyncSession, game: Game):
            settings = dict(game.settings or {})
            qid = settings.get("analysing")
            if not qid:
                raise GameError("Nothing is being analysed", 409)
            closed = set(settings.get("closed_questions", []))
            if lock:
                closed.add(qid)
            resume = settings.get("analysis_paused") and game.state == GameState.paused
            game.settings = {
                **settings,
                "analysing": None,
                "analysis_show": None,
                "analysis_paused": False,
                "closed_questions": sorted(closed),
            }
            if resume:
                self._resume_in_place(game)
                self._arm_deadline(game)

        await self._transition(game_id, fn)

    async def set_breaks(self, game_id, breaks: list[int]) -> None:
        """Free Run pause points: a break after question index b."""

        async def fn(s: AsyncSession, game: Game):
            if not views.is_free_run(game):
                raise GameError("Pause points are for Free Run games", 409)
            n = len(await views.quiz_questions(s, game.quiz_id))
            game.settings = {**(game.settings or {}), "breaks": sorted({b for b in breaks if 0 <= b < n - 1})}

        await self._transition(game_id, fn)

    async def unlock_next(self, game_id) -> None:
        async def fn(s: AsyncSession, game: Game):
            if not views.is_free_run(game):
                raise GameError("Sections are for Free Run games", 409)
            n = len(await views.quiz_questions(s, game.quiz_id))
            visible = views.free_run_visible(game, n)
            if visible >= n:
                raise GameError("Everything is already unlocked", 409)
            game.settings = {**(game.settings or {}), "unlocked_through": visible}

        await self._transition(game_id, fn)

    async def check_auto_end(self, game_id, question_id) -> None:
        async with session_scope() as s:
            game = await s.get(Game, uuid.UUID(str(game_id)))
            q = await s.get(Question, question_id)
            if not game or game.state != GameState.open or game.ending or game.current_question_id != q.id:
                return
            if q.type != QuestionType.super_fast:
                return
            rule = AutoEnd(**(q.auto_end or {}))
            scoring = parse_scoring(q.scoring)
            if isinstance(scoring, Ranked):
                # First-N round: ends as soon as the last scoring place is taken (or everyone has solved it).
                rule = AutoEnd(all_passed=True, after_n_passed=len(scoring.points))
            prog = await views.progress(s, game, q)
        passing, total = prog["passing"], prog["teams_total"]
        if total and ((rule.all_passed and passing >= total) or (rule.after_n_passed and passing >= rule.after_n_passed)):
            try:
                await self.end_now(game_id)
            except GameError:
                pass

    # ------------------------------------------------------------------ points

    async def adjust_points(self, game_id, team_id: str, points: int, note: str | None, teacher_id) -> None:
        payload = {}

        async def fn(s: AsyncSession, game: Game):
            team = await s.get(Team, uuid.UUID(team_id))
            if not team or team.game_id != game.id:
                raise GameError("Unknown team", 404)
            total = int(
                await s.scalar(select(func.coalesce(func.sum(ScoreEvent.points), 0)).where(ScoreEvent.team_id == team.id))
            )
            if not (game.settings or {}).get("allow_negative_totals") and total + points < 0:
                raise GameError(f"That would take {team.name} below zero (they have {total})", 400)
            s.add(ScoreEvent(game_id=game.id, team_id=team.id, points=points, reason="manual", note=note, created_by=teacher_id))
            payload.update(
                {
                    "team_id": team_id,
                    "team": team.name,
                    "delta": points,
                    "note": note,
                    "show_note": bool((game.settings or {}).get("show_reasons", True)),
                    "total": total + points,
                }
            )

        await self._transition(game_id, fn)
        rt.hub.send(str(game_id), "points.adjusted", payload)

    async def undo(self, game_id, event_id: int, teacher_id) -> None:
        payload = {}

        async def fn(s: AsyncSession, game: Game):
            ev = await s.get(ScoreEvent, event_id)
            if not ev or ev.game_id != game.id or ev.reason != "manual":
                raise GameError("Only manual adjustments can be undone", 404)
            if await s.scalar(select(ScoreEvent.id).where(ScoreEvent.undoes_id == ev.id)):
                raise GameError("Already undone", 409)
            s.add(
                ScoreEvent(
                    game_id=game.id,
                    team_id=ev.team_id,
                    points=-ev.points,
                    reason="undo",
                    note=f"Undo: {ev.note or ''}".strip()[:120],
                    created_by=teacher_id,
                    undoes_id=ev.id,
                )
            )
            await s.flush()
            team = await s.get(Team, ev.team_id)
            total = int(
                await s.scalar(select(func.coalesce(func.sum(ScoreEvent.points), 0)).where(ScoreEvent.team_id == team.id))
            )
            payload.update(
                {"team_id": str(team.id), "team": team.name, "delta": -ev.points, "note": "Undo", "show_note": True, "total": total}
            )

        await self._transition(game_id, fn)
        rt.hub.send(str(game_id), "points.adjusted", payload)

    async def update_settings(self, game_id, changes: dict) -> None:
        async def fn(s, game: Game):
            game.settings = {**(game.settings or {}), **changes}

        await self._transition(game_id, fn)

    # ------------------------------------------------------------------ moderation

    async def kick(self, game_id, team_id: str) -> None:
        async def fn(s, game: Game):
            team = await s.get(Team, uuid.UUID(team_id))
            if not team or team.game_id != game.id:
                raise GameError("Unknown team", 404)
            team.kicked = True
            team.session_token_hash = sha256(secrets.token_hex(32))  # invalidate the device token

        await self._transition(game_id, fn)
        rt.hub.kick_team(str(game_id), team_id, "Your team was removed by the host.")

    async def rename(self, game_id, team_id: str, name: str) -> None:
        from ..routers.join import validate_team_name

        async def fn(s, game: Game):
            team = await s.get(Team, uuid.UUID(team_id))
            if not team or team.game_id != game.id:
                raise GameError("Unknown team", 404)
            clean = validate_team_name(name)
            clash = await s.scalar(
                select(Team.id).where(Team.game_id == game.id, func.lower(Team.name) == clean.lower(), Team.id != team.id)
            )
            if clash:
                raise GameError("Another team already has that name", 409)
            team.name = clean

        await self._transition(game_id, fn)

    async def reissue(self, game_id, team_id: str) -> str:
        code = "".join(secrets.choice(JOIN_ALPHABET) for _ in range(8))

        async def fn(s, game: Game):
            team = await s.get(Team, uuid.UUID(team_id))
            if not team or team.game_id != game.id or team.kicked:
                raise GameError("Unknown team", 404)
            team.rejoin_code_hash = sha256(code)
            team.rejoin_expires_at = now() + timedelta(minutes=15)

        await self._transition(game_id, fn)
        return code

    # ------------------------------------------------------------------ restart recovery

    async def rearm_all(self) -> None:
        async with session_scope() as s:
            games = (
                await s.scalars(
                    select(Game).where(
                        Game.state.in_([GameState.round_intro, GameState.open, GameState.closed, GameState.judging])
                    )
                )
            ).all()
            for g in games:
                gid = str(g.id)
                if g.state == GameState.round_intro:
                    self._arm(gid, g.phase_ends_at or now(), self._on_intro_done)
                elif g.state == GameState.open:
                    self._arm_deadline(g)
                else:
                    self._spawn_finisher(gid)
                log.info("re-armed game %s in state %s", gid, g.state.value)

    async def shutdown(self) -> None:
        tasks = [t for t in list(self.timers.values()) + list(self.finishers.values()) if not t.done()]
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


engine = GameEngine()
