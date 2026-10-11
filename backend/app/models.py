"""SQLAlchemy models. Mirrors the schema in the build plan, with a few additions
marked "added:" that the plan's features need (rejoin codes, projector token,
cached results, the runs log)."""

import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    TypeDecorator,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UTCDateTime(TypeDecorator):
    """timestamptz that always comes back timezone-aware (SQLite drops the zone)."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value

    def process_result_value(self, value, dialect):
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value


JSONType = JSON().with_variant(JSONB(), "postgresql")
BigId = BigInteger().with_variant(Integer(), "sqlite")  # SQLite only autoincrements INTEGER


class Base(DeclarativeBase):
    pass


class QuestionType(str, enum.Enum):
    multiple_choice = "multiple_choice"
    super_fast = "super_fast"
    code_golf = "code_golf"
    best_complexity = "best_complexity"


class GameState(str, enum.Enum):
    lobby = "lobby"
    round_intro = "round_intro"
    open = "open"
    paused = "paused"
    closed = "closed"
    judging = "judging"
    results = "results"
    leaderboard = "leaderboard"
    podium = "podium"
    finished = "finished"


class SubStatus(str, enum.Enum):
    queued = "queued"
    running = "running"
    judged = "judged"
    error = "error"


def _enum(e: type[enum.Enum], name: str) -> Enum:
    return Enum(e, name=name, values_callable=lambda x: [m.value for m in x])


class Teacher(Base):
    __tablename__ = "teachers"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    username: Mapped[str] = mapped_column(Text, unique=True)
    password_hash: Mapped[str] = mapped_column(Text)  # argon2id
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False)  # added
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Media(Base):
    __tablename__ = "media"
    __table_args__ = (CheckConstraint("bytes <= 5000000", name="media_bytes_cap"),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("teachers.id"))
    path: Mapped[str] = mapped_column(Text)
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    bytes: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Quiz(Base):
    __tablename__ = "quizzes"
    __table_args__ = (CheckConstraint("length(title) between 1 and 120", name="quiz_title_len"),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("teachers.id"))
    title: Mapped[str] = mapped_column(Text)
    settings: Mapped[dict] = mapped_column(JSONType, default=dict)  # allow_negative_totals, sounds
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Question(Base):
    __tablename__ = "questions"
    __table_args__ = (
        UniqueConstraint("quiz_id", "position", name="questions_quiz_position_uq"),
        CheckConstraint("length(round_name) between 1 and 60", name="q_round_name_len"),
        CheckConstraint("length(title) between 1 and 120", name="q_title_len"),
        CheckConstraint("image_alt is null or length(image_alt) <= 200", name="q_image_alt_len"),
        CheckConstraint("time_limit_s between 5 and 900", name="q_time_limit"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    quiz_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("quizzes.id", ondelete="CASCADE"))
    position: Mapped[int] = mapped_column(Integer)
    round_name: Mapped[str] = mapped_column(Text)
    type: Mapped[QuestionType] = mapped_column(_enum(QuestionType, "question_type"))
    title: Mapped[str] = mapped_column(Text)
    description_md: Mapped[str] = mapped_column(Text)
    image_media_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("media.id"), nullable=True)
    image_alt: Mapped[str | None] = mapped_column(Text, nullable=True)
    starter_code: Mapped[str] = mapped_column(Text, default="")
    reference_solution: Mapped[str] = mapped_column(Text)  # never sent to teams
    config: Mapped[dict] = mapped_column(JSONType)  # examples, hidden tests, limits, benchmark
    time_limit_s: Mapped[int] = mapped_column(Integer, default=240)
    # added: no countdown; the clock counts up until the teacher ends the question.
    # time_limit_s is then only the reference time for speed-based scoring.
    unlimited_time: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    auto_end: Mapped[dict] = mapped_column(JSONType, default=dict)
    scoring: Mapped[dict] = mapped_column(JSONType)
    verified_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Game(Base):
    __tablename__ = "games"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    quiz_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("quizzes.id"))
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("teachers.id"))  # added
    join_code: Mapped[str] = mapped_column(String(6), unique=True)
    screen_token: Mapped[str] = mapped_column(Text)  # added: read-only projector token
    state: Mapped[GameState] = mapped_column(_enum(GameState, "game_state"), default=GameState.lobby)
    # added: "live" (the host moves everyone through one question at a time) or "free_run"
    # (every unlocked problem open at once, one clock for the whole game)
    mode: Mapped[str] = mapped_column(Text, default="live", server_default="live")
    question_index: Mapped[int] = mapped_column(Integer, default=-1)  # added
    current_question_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("questions.id"), nullable=True
    )
    phase_ends_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)  # added: round intro
    opened_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    deadline: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    paused_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    paused_total_ms: Mapped[int] = mapped_column(Integer, default=0)
    ended_early: Mapped[bool] = mapped_column(Boolean, default=False)
    ending: Mapped[bool] = mapped_column(Boolean, default=False)  # added: "Ending…" countdown running
    results: Mapped[dict] = mapped_column(JSONType, default=dict)  # added: per-question results
    last_board: Mapped[list] = mapped_column(JSONType, default=list)  # added: for rank-change arrows
    settings: Mapped[dict] = mapped_column(JSONType, default=dict)  # added: copy of quiz settings
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Team(Base):
    __tablename__ = "teams"
    __table_args__ = (
        CheckConstraint("length(name) between 2 and 24", name="team_name_len"),
        Index("teams_name_uq", "game_id", func.lower(text("name")), unique=True),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    game_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("games.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(Text)
    session_token_hash: Mapped[str] = mapped_column(Text, index=True)
    rejoin_code_hash: Mapped[str | None] = mapped_column(Text, nullable=True)  # added
    rejoin_expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)  # added
    kicked: Mapped[bool] = mapped_column(Boolean, default=False)
    joined_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Submission(Base):
    __tablename__ = "submissions"
    __table_args__ = (
        UniqueConstraint("game_id", "question_id", "team_id", "attempt_no", name="sub_attempt_uq"),
        CheckConstraint("length(code) <= 10000", name="sub_code_len"),
        Index("submissions_lookup", "game_id", "question_id", "status", "submitted_at"),
    )
    id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    game_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("games.id", ondelete="CASCADE"))
    question_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("questions.id"))
    team_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("teams.id"))
    attempt_no: Mapped[int] = mapped_column(Integer)
    code: Mapped[str] = mapped_column(Text)
    char_count: Mapped[int] = mapped_column(Integer)  # golf rule applied
    status: Mapped[SubStatus] = mapped_column(_enum(SubStatus, "sub_status"), default=SubStatus.queued)
    tests_passed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tests_total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    verdict: Mapped[str | None] = mapped_column(Text, nullable=True)  # added
    first_failed: Mapped[int | None] = mapped_column(Integer, nullable=True)  # added: test number only
    elapsed_ms: Mapped[int] = mapped_column(Integer)  # since question opened, pauses excluded
    exec_time_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    memory_kb: Mapped[int | None] = mapped_column(Integer, nullable=True)
    perf: Mapped[dict | None] = mapped_column(JSONType, nullable=True)  # best complexity: {n: median_ms}
    # added: per hidden test {passed, status, time_ms, stdout, stderr}; teacher console only
    test_results: Mapped[list | None] = mapped_column(JSONType, nullable=True)
    provisional_points: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)  # never test data
    submitted_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    judged_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class RunLog(Base):
    """added: the optional `runs` log, used for the monitor's run counts and analytics."""

    __tablename__ = "runs"
    id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    game_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("games.id", ondelete="CASCADE"))
    question_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("questions.id"), nullable=True)
    team_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("teams.id"))
    custom_input: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Answer(Base):
    """added: one multiple-choice answer per team per question (locked once sent)."""

    __tablename__ = "answers"
    __table_args__ = (UniqueConstraint("game_id", "question_id", "team_id", name="answer_once_uq"),)
    id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    game_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("games.id", ondelete="CASCADE"))
    question_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("questions.id"))
    team_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("teams.id"))
    choice: Mapped[int] = mapped_column(Integer)
    correct: Mapped[bool] = mapped_column(Boolean)
    elapsed_ms: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class HintGiven(Base):
    """added: a hint the teacher sent to a team during a question (index into config.hints)."""

    __tablename__ = "hints_given"
    __table_args__ = (UniqueConstraint("game_id", "question_id", "team_id", "hint_index", name="hint_once_uq"),)
    id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    game_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("games.id", ondelete="CASCADE"))
    question_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("questions.id"))
    team_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("teams.id"))
    hint_index: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class CodeDraft(Base):
    __tablename__ = "code_drafts"
    __table_args__ = (CheckConstraint("length(code) <= 10000", name="draft_code_len"),)
    game_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("games.id", ondelete="CASCADE"), primary_key=True)
    question_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("questions.id"), primary_key=True)
    team_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("teams.id"), primary_key=True)
    code: Mapped[str] = mapped_column(Text)
    saved_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class ScoreEvent(Base):
    """Append-only ledger; manual rows are never edited."""

    __tablename__ = "score_events"
    __table_args__ = (
        CheckConstraint("note is null or length(note) <= 120", name="score_note_len"),
        # automatic scoring is idempotent: one 'question' row per team per question
        Index(
            "score_auto_uq",
            "game_id",
            "team_id",
            "question_id",
            unique=True,
            postgresql_where=text("reason = 'question'"),
            sqlite_where=text("reason = 'question'"),
        ),
    )
    id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    game_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("games.id", ondelete="CASCADE"))
    team_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("teams.id"))
    question_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("questions.id"), nullable=True)  # null = manual
    points: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(Text)  # 'question', 'manual', 'undo'
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("teachers.id"), nullable=True)
    undoes_id: Mapped[int | None] = mapped_column(ForeignKey("score_events.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class ProblemSubmission(Base):
    """added: a problem anyone can suggest on the public site; the teacher reviews the queue."""

    __tablename__ = "problem_submissions"
    __table_args__ = (
        CheckConstraint("length(title) between 1 and 120", name="ps_title_len"),
        Index("problem_submissions_status", "status", "created_at"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    author_name: Mapped[str] = mapped_column(Text)
    email: Mapped[str | None] = mapped_column(Text, nullable=True)  # for the teacher's reply; never public
    title: Mapped[str] = mapped_column(Text)
    intended_use: Mapped[str] = mapped_column(Text, default="either")  # added: challenge, weekly, either
    description_md: Mapped[str] = mapped_column(Text)
    examples: Mapped[list] = mapped_column(JSONType, default=list)  # [{stdin, expected}]
    solution: Mapped[str] = mapped_column(Text, default="")  # optional, never public
    notes: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(Text, default="pending")  # pending, accepted, rejected
    teacher_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    reviewed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    emailed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class ProblemGroup(Base):
    """added: a named section of the public problems page, e.g. one event's problems."""

    __tablename__ = "problem_groups"
    __table_args__ = (CheckConstraint("length(name) between 1 and 60", name="pg_name_len"),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("teachers.id"))
    name: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text, default="")
    position: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class FeaturedProblem(Base):
    """added: a problem the teacher publishes on the site, with a solution students can reveal."""

    __tablename__ = "featured_problems"
    __table_args__ = (CheckConstraint("length(title) between 1 and 120", name="fp_title_len"),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("teachers.id"))
    title: Mapped[str] = mapped_column(Text)
    difficulty: Mapped[str] = mapped_column(Text, default="medium")  # easy, medium, hard
    description_md: Mapped[str] = mapped_column(Text, default="")
    examples: Mapped[list] = mapped_column(JSONType, default=list)  # [{stdin, expected}]
    solution_code: Mapped[str] = mapped_column(Text, default="")
    solution_md: Mapped[str] = mapped_column(Text, default="")  # explanation
    credit: Mapped[str | None] = mapped_column(Text, nullable=True)  # e.g. who suggested it
    published: Mapped[bool] = mapped_column(Boolean, default=False)
    group_id: Mapped[uuid.UUID | None] = mapped_column(  # added: section on the problems page
        ForeignKey("problem_groups.id", ondelete="SET NULL"), nullable=True
    )
    source_submission_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("problem_submissions.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class WeeklyProblem(Base):
    """added: problem of the week. The problem itself is a verified coding question from one
    of the teacher's quizzes, so it's written and checked in the normal editor."""

    __tablename__ = "weekly_problems"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("teachers.id"))
    question_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("questions.id"))
    opens_at: Mapped[datetime] = mapped_column(UTCDateTime)
    closes_at: Mapped[datetime] = mapped_column(UTCDateTime)
    published: Mapped[bool] = mapped_column(Boolean, default=False)
    solution_published: Mapped[bool] = mapped_column(Boolean, default=False)  # shown once it has closed
    credit: Mapped[str | None] = mapped_column(Text, nullable=True)  # added: e.g. "Submitted by Sam Smith"
    featured_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)  # added: copied to Past Weekly Problems
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class WeeklyEntry(Base):
    """added: one submission to a problem of the week. People are told apart by email."""

    __tablename__ = "weekly_entries"
    __table_args__ = (
        CheckConstraint("length(code) <= 10000", name="weekly_code_len"),
        Index("weekly_entries_lookup", "weekly_id", "email"),
    )
    id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    weekly_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("weekly_problems.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(Text)
    email: Mapped[str] = mapped_column(Text)  # lower-cased; never public
    code: Mapped[str] = mapped_column(Text)
    char_count: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(Text, default="queued")  # queued, running, measuring, judged, error
    tests_passed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tests_total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    verdict: Mapped[str | None] = mapped_column(Text, nullable=True)
    first_failed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    exec_time_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    perf: Mapped[dict | None] = mapped_column(JSONType, nullable=True)  # best complexity benchmark
    submitted_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    judged_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class WeeklyPerson(Base):
    """added: someone who enters the problem of the week. Their school email links every week's
    entries; the name is fixed at first entry (an admin can change it, or ban the email)."""

    __tablename__ = "weekly_people"
    email: Mapped[str] = mapped_column(Text, primary_key=True)  # lower-cased; never public
    name: Mapped[str] = mapped_column(Text)
    year_group: Mapped[str | None] = mapped_column(Text, nullable=True)  # 4, 5, 6, L8, U8
    banned: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


LEADERBOARD_VIEW_SQL = """
create view leaderboard as
  select t.game_id, t.id as team_id, t.name,
         coalesce(sum(s.points), 0) as points,
         rank() over (partition by t.game_id
                      order by coalesce(sum(s.points), 0) desc) as rank
  from teams t left join score_events s on s.team_id = t.id
  where not t.kicked group by t.id, t.game_id, t.name
"""
