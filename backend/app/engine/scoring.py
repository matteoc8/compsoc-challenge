"""Scoring rules. Pure functions so they can be tested exactly against the plan's examples."""

import math
from dataclasses import dataclass

from ..schemas.question import Closest, Flat, Ranked, SpeedWeighted, Timed


def _round(x: float) -> int:
    return int(math.floor(x + 0.5))


def super_fast_points(rule: SpeedWeighted, elapsed_ms: int, limit_ms: int, passed: int, total: int) -> int:
    """points = P * (1 - (1 - speed_floor) * t/T) * (cf + (1 - cf) * f), 0 below min_pass."""
    if total <= 0:
        return 0
    f = passed / total
    if f < rule.min_pass or f == 0:
        return 0
    t = min(max(elapsed_ms, 0), limit_ms) / limit_ms if limit_ms > 0 else 1.0
    speed = 1 - (1 - rule.speed_floor) * t
    correctness = rule.correctness_floor + (1 - rule.correctness_floor) * f
    return _round(rule.max * speed * correctness)


def timed_points(rule: Timed, elapsed_ms: int, limit_ms: int) -> int:
    """Multiple choice: max × (1 − (t / T) / 2) for a correct answer (max at once, max/2 at the buzzer)."""
    t = min(max(elapsed_ms, 0), limit_ms) / limit_ms if limit_ms > 0 else 1.0
    return _round(rule.max * (1 - t / 2))


def closest_points(rule: Closest, value: float, best: float) -> int:
    """points = P * (s + (1 - s) * best / value) with s = min_share (1/2 by default)."""
    if value <= 0 or best <= 0:
        return rule.max
    ratio = min(best / value, 1.0)
    return _round(rule.max * (rule.min_share + (1 - rule.min_share) * ratio))


def ranked_points(rule: Ranked, position: int) -> int:
    """position is 0-based; beyond the list scores 0."""
    return rule.points[position] if 0 <= position < len(rule.points) else 0


@dataclass
class Entry:
    team_id: str
    value: float | None  # chars or runtime; None = passed but no measurement (e.g. timed out)
    tiebreak: float = 0  # earlier submission wins ties in ranked mode


def score_at_close(rule: Closest | Flat | Ranked, entries: list[Entry]) -> dict[str, int]:
    """Points for golf / complexity once the question closes. Lower value is better.

    Entries with value None (e.g. a correct solution that timed out at the largest size)
    get the minimum share in closest mode and rank after every measured entry."""
    measured = sorted((e for e in entries if e.value is not None), key=lambda e: (e.value, e.tiebreak))
    unmeasured = sorted((e for e in entries if e.value is None), key=lambda e: e.tiebreak)
    out: dict[str, int] = {}
    if isinstance(rule, Flat):
        return {e.team_id: rule.max for e in entries}
    if isinstance(rule, Ranked):
        # ties share the better position
        pos = 0
        prev = None
        for i, e in enumerate(measured):
            if prev is None or e.value != prev:
                pos = i
            prev = e.value
            out[e.team_id] = ranked_points(rule, pos)
        for j, e in enumerate(unmeasured):
            out[e.team_id] = ranked_points(rule, len(measured) + j)
        return out
    best = measured[0].value if measured else None
    for e in measured:
        out[e.team_id] = closest_points(rule, e.value, best)
    for e in unmeasured:
        out[e.team_id] = _round(rule.max * rule.min_share)
    return out
