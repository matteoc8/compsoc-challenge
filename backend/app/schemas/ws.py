"""WebSocket message shapes, published in OpenAPI so `npm run gen:types` keeps the
frontend in step. Every message is {"type", "seq", "data"}."""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field


class GameHeader(BaseModel):
    id: str
    state: Literal["lobby", "round_intro", "open", "paused", "closed", "judging", "results", "leaderboard", "podium", "finished"]
    question_index: int
    question_count: int
    round_name: str | None
    question_type: Literal["super_fast", "code_golf", "best_complexity"] | None
    deadline: str | None
    paused: bool
    remaining_ms: int | None
    ending: bool
    ended_early: bool
    phase_ends_at: str | None
    server_time: str
    judge_ok: bool
    join_code: str | None = None


class BoardRow(BaseModel):
    team_id: str
    name: str
    points: int
    rank: int
    prev_rank: int | None = None
    prev_points: int = 0


class Snapshot(BaseModel):
    role: Literal["team", "teacher", "screen"]
    game: GameHeader
    leaderboard: list[BoardRow]
    intro: dict[str, Any] | None = None
    question: dict[str, Any] | None = None
    results: dict[str, Any] | None = None
    podium: list[BoardRow] | None = None
    teams: list[dict[str, Any]] | None = None
    progress: dict[str, Any] | None = None
    me: dict[str, Any] | None = None
    my_submissions: list[dict[str, Any]] | None = None
    my_question_points: int | None = None
    monitor: list[dict[str, Any]] | None = None
    in_flight: int | None = None
    screen_token: str | None = None
    questions: list[dict[str, Any]] | None = None
    my_answer: dict[str, Any] | None = None
    adjustments: list[dict[str, Any]] | None = None
    settings: dict[str, Any] | None = None
    all_teams: list[dict[str, Any]] | None = None


class SubmissionResult(BaseModel):
    id: int
    attempt: int
    status: str
    passed: int | None
    total: int | None
    verdict: str | None
    first_failed: int | None
    error_summary: str | None
    chars: int
    elapsed_ms: int
    time_ms: int | None
    points: int | None
    submitted_at: str
    provisional: bool | None = None


class RunCase(BaseModel):
    index: int
    stdin: str | None
    stdout: str
    stderr: str
    status: str
    time_ms: int | None
    memory_kb: int | None
    expected: str | None = None
    passed: bool | None = None


class RunResult(BaseModel):
    run_id: int
    custom: bool | None = None
    cases: list[RunCase] | None = None
    error: str | None = None


class TimerUpdate(BaseModel):
    deadline: str | None
    paused: bool
    remaining_ms: int | None
    ending: bool
    server_time: str


class PointsAdjusted(BaseModel):
    team_id: str
    team: str
    delta: int
    note: str | None
    show_note: bool
    total: int


def _msg(name: str, data_type):
    return type(
        f"Msg_{name.replace('.', '_')}",
        (BaseModel,),
        {"__annotations__": {"type": Literal[name], "seq": int, "data": data_type}},
    )


WsMessage = Annotated[
    _msg("snapshot", Snapshot)
    | _msg("submission.result", SubmissionResult)
    | _msg("run.result", RunResult)
    | _msg("timer.update", TimerUpdate)
    | _msg("points.adjusted", PointsAdjusted)
    | _msg("leaderboard.update", dict[str, list[BoardRow]])
    | _msg("podium", dict[str, list[BoardRow]])
    | _msg("results", dict[str, Any])
    | _msg("monitor.update", dict[str, Any])
    | _msg("progress.update", dict[str, Any])
    | _msg("judging.progress", dict[str, int])
    | _msg("judge.status", dict[str, Any])
    | _msg("presence", dict[str, list[str]])
    | _msg("solve", dict[str, Any])
    | _msg("pong", dict[str, Any])
    | _msg("session.replaced", dict[str, str])
    | _msg("session.ended", dict[str, str]),
    Field(discriminator="type"),
]
