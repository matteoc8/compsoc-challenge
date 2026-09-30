"""Role-filtered views. THE security boundary for hidden data.

Teams and the projector must never receive hidden tests, the reference solution, the
I/O harness or the benchmark generator. Every question sent over the wire to those
roles goes through `serialize_question`; tests assert that for every role and state.
"""

from ..judge.golf import GOLF_RULE_TEXT
from ..models import Question, QuestionType

TYPE_LABEL = {
    QuestionType.multiple_choice: "Multiple choice",
    QuestionType.super_fast: "Super Fast Round",
    QuestionType.code_golf: "Code Golf",
    QuestionType.best_complexity: "Best Time Complexity",
}


def _ordinal(n: int) -> str:
    return f"{n}{'th' if 11 <= n % 100 <= 13 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def rule_line(q: Question) -> str:
    """The one-line rules shown on the round intro card and in the problem pane."""
    scoring = q.scoring or {}
    if q.type == QuestionType.multiple_choice:
        return "Answer fast: quicker correct answers score more"
    if q.type == QuestionType.super_fast:
        if scoring.get("mode") == "ranked":
            pts = scoring.get("points") or []
            places = " · ".join(f"{_ordinal(i + 1)} {p:,}" for i, p in enumerate(pts))
            n = len(pts)
            return (
                f"Only the first {n} team{'s' if n != 1 else ''} to pass every test score ({places}). "
                f"The round ends as soon as the {_ordinal(n)} team gets it."
            )
        if scoring.get("mode") == "flat":
            return "Every team that passes all the tests scores"
        return "Speed beats perfection: every second counts"
    if q.type == QuestionType.code_golf:
        return "Shortest correct code wins"
    return "Fastest correct code on big inputs wins"


def media_url(media_id) -> str | None:
    return f"/api/media/{media_id}.webp" if media_id else None


def serialize_question(q: Question, role: str) -> dict:
    if role not in ("team", "teacher", "screen"):
        raise ValueError(f"unknown role {role!r}")
    cfg = q.config or {}
    public = {
        "id": str(q.id),
        "position": q.position,
        "round_name": q.round_name,
        "type": q.type.value,
        "type_label": TYPE_LABEL[q.type],
        "rule_line": rule_line(q),
        "title": q.title,
        "description_md": q.description_md,
        "image_url": media_url(q.image_media_id),
        "image_alt": q.image_alt,
        "time_limit_s": q.time_limit_s,
        "scoring_max": _scoring_max(q.scoring),
    }
    if q.type == QuestionType.multiple_choice:
        public["options"] = [{"index": i, "text": o.get("text", "")} for i, o in enumerate(cfg.get("options", []))]
        if role == "teacher":
            public["correct"] = list(cfg.get("correct", []))  # console only, never projected
        return public
    if role == "screen":
        return public
    public.update(
        {
            "starter_code": q.starter_code,
            "examples": [{"stdin": e.get("stdin", ""), "expected": e.get("expected", "")} for e in cfg.get("examples", [])],
            "tests_total": len(cfg.get("tests", [])),
            "cpu_limit_s": cfg.get("cpu_limit_s", 2),
            "memory_mb": cfg.get("memory_mb", 128),
            "scoring": _public_scoring(q.scoring),
        }
    )
    if q.type == QuestionType.code_golf:
        public["golf_rule"] = GOLF_RULE_TEXT
    if q.type == QuestionType.best_complexity and cfg.get("benchmark"):
        public["benchmark_sizes"] = list(cfg["benchmark"].get("sizes", []))
    # team and teacher: the console doesn't need secrets either; the editor fetches them over REST.
    return public


def _scoring_max(scoring: dict) -> int:
    if scoring.get("mode") == "ranked":
        return max(scoring.get("points") or [0])
    return int(scoring.get("max", 0))


def _public_scoring(scoring: dict) -> dict:
    allowed = {"mode", "max", "speed_floor", "correctness_floor", "min_pass", "min_share", "points"}
    return {k: v for k, v in scoring.items() if k in allowed}


def serialize_question_full(q: Question) -> dict:
    """Editor view (teacher REST only): includes hidden tests and the reference solution."""
    return {
        "id": str(q.id),
        "quiz_id": str(q.quiz_id),
        "position": q.position,
        "round_name": q.round_name,
        "type": q.type.value,
        "title": q.title,
        "description_md": q.description_md,
        "image_media_id": str(q.image_media_id) if q.image_media_id else None,
        "image_url": media_url(q.image_media_id),
        "image_alt": q.image_alt,
        "starter_code": q.starter_code,
        "reference_solution": q.reference_solution,
        "config": q.config,
        "time_limit_s": q.time_limit_s,
        "auto_end": q.auto_end,
        "scoring": q.scoring,
        "verified_at": q.verified_at.isoformat() if q.verified_at else None,
        "updated_at": q.updated_at.isoformat() if q.updated_at else None,
    }
