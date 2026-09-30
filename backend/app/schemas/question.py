"""Validated shapes for the JSONB columns on `questions`."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..models import QuestionType


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class IOCase(Strict):
    stdin: str = Field(default="", max_length=100_000)
    expected: str = Field(default="", max_length=100_000)


class Benchmark(Strict):
    # Python source defining gen(n, rng) -> tuple of positional args for solve().
    generator: str = Field(min_length=1, max_length=10_000)
    sizes: list[int] = Field(default=[500, 2000, 8000], min_length=2, max_length=5)
    repeats: int = Field(default=3, ge=1, le=5)
    cpu_limit_s: float = Field(default=5, gt=0, le=15)
    # Runtimes below this are treated as equal: Judge0's timer can't separate O(n) from O(n log n).
    floor_ms: int = Field(default=20, ge=0, le=1000)

    @model_validator(mode="after")
    def _sizes_increase(self):
        if any(b <= a for a, b in zip(self.sizes, self.sizes[1:])) or self.sizes[0] < 1:
            raise ValueError("benchmark sizes must be positive and increasing")
        return self


class Option(Strict):
    text: str = Field(default="", max_length=120)


class QuestionConfig(Strict):
    examples: list[IOCase] = Field(default_factory=list, max_length=10)
    tests: list[IOCase] = Field(default_factory=list, max_length=60)
    cpu_limit_s: float = Field(default=2, gt=0, le=10)
    memory_mb: int = Field(default=128, ge=16, le=512)
    # Appended after the team's code for function-style questions (reads stdin, calls solve, prints).
    harness: str | None = Field(default=None, max_length=10_000)
    benchmark: Benchmark | None = None
    # Multiple choice only: up to four answers and the indexes of the correct one(s).
    options: list["Option"] = Field(default_factory=list, max_length=4)
    correct: list[int] = Field(default_factory=list, max_length=4)


class Timed(Strict):
    """Multiple choice: a correct answer scores max × (1 − (t / T) / 2), so between max/2 and max."""

    mode: Literal["timed"] = "timed"
    max: int = Field(default=1000, ge=0, le=100_000)


class SpeedWeighted(Strict):
    mode: Literal["speed_weighted"] = "speed_weighted"
    max: int = Field(default=4000, ge=0, le=100_000)
    speed_floor: float = Field(default=0.1, ge=0, le=1)
    correctness_floor: float = Field(default=0.6, ge=0, le=1)
    min_pass: float = Field(default=0.5, ge=0, le=1)


class Closest(Strict):
    mode: Literal["closest"] = "closest"
    max: int = Field(default=4000, ge=0, le=100_000)
    min_share: float = Field(default=0.5, ge=0, le=1)


class Flat(Strict):
    mode: Literal["flat"] = "flat"
    max: int = Field(default=4000, ge=0, le=100_000)


class Ranked(Strict):
    """Points by position. For Super Fast only the first len(points) full solves score,
    and the round ends as soon as the last scoring place is taken."""

    mode: Literal["ranked"] = "ranked"
    points: list[int] = Field(default=[4000, 3000, 2000], min_length=1, max_length=50)

    @property
    def max(self) -> int:
        return max(self.points)


Scoring = Annotated[Timed | SpeedWeighted | Closest | Flat | Ranked, Field(discriminator="mode")]


class ScoringHolder(BaseModel):
    scoring: Scoring


class AutoEnd(Strict):
    all_passed: bool = False
    after_n_passed: int | None = Field(default=None, ge=1, le=100)


def parse_scoring(raw: dict) -> Timed | SpeedWeighted | Closest | Flat | Ranked:
    return ScoringHolder(scoring=raw).scoring


ALLOWED_MODES = {
    QuestionType.multiple_choice: ("timed", "flat"),
    QuestionType.super_fast: ("ranked", "speed_weighted", "flat"),
    QuestionType.code_golf: ("closest", "flat", "ranked"),
    QuestionType.best_complexity: ("closest", "flat", "ranked"),
}

TIME_LIMITS = {QuestionType.multiple_choice: (5, 240)}  # coding rounds: 60–900 s


def time_limits(qtype: QuestionType) -> tuple[int, int]:
    return TIME_LIMITS.get(qtype, (60, 900))


def default_scoring(qtype: QuestionType) -> dict:
    if qtype == QuestionType.multiple_choice:
        return Timed().model_dump()
    if qtype == QuestionType.super_fast:
        return Ranked().model_dump()
    return Closest().model_dump()


class QuestionIn(Strict):
    """Body for creating or editing a question (multiple choice or coding)."""

    round_name: str = Field(min_length=1, max_length=60)
    type: QuestionType
    title: str = Field(min_length=1, max_length=120)
    description_md: str = Field(default="", max_length=20_000)
    image_media_id: str | None = None
    image_alt: str | None = Field(default=None, max_length=200)
    starter_code: str = Field(default="", max_length=10_000)
    reference_solution: str = Field(default="", max_length=10_000)
    config: QuestionConfig = Field(default_factory=QuestionConfig)
    time_limit_s: int = Field(default=240, ge=5, le=900)
    auto_end: AutoEnd = Field(default_factory=AutoEnd)
    scoring: Scoring | None = None
    # Optimistic concurrency for autosave: the updated_at the editor last saw.
    expected_updated_at: str | None = None

    @model_validator(mode="after")
    def _type_rules(self):
        lo, hi = time_limits(self.type)
        if not lo <= self.time_limit_s <= hi:
            raise ValueError(f"Time limit for this question type must be {lo}–{hi} seconds")
        if self.type == QuestionType.multiple_choice:
            # Drafts may have blank answers while being written; Verify checks they're complete.
            n = len(self.config.options)
            if any(i < 0 or i >= n for i in self.config.correct):
                raise ValueError("A correct answer points at an option that doesn't exist")
            self.config.correct = sorted(set(self.config.correct))
            self.config.examples, self.config.tests = [], []
            self.config.harness, self.config.benchmark = None, None
            self.starter_code, self.reference_solution = "", ""
            self.auto_end = AutoEnd()
        else:
            self.config.options, self.config.correct = [], []
            # A Best Time Complexity draft may lack a benchmark while being edited; verify rejects it.
            if self.type != QuestionType.best_complexity:
                self.config.benchmark = None
        if self.scoring is None:
            self.scoring = parse_scoring(default_scoring(self.type))
        if self.scoring.mode not in ALLOWED_MODES[self.type]:
            raise ValueError(f"Scoring mode '{self.scoring.mode}' doesn't apply to this question type")
        return self
