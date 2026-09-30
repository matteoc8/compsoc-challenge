"""Best Time Complexity harness and class estimate.

Each passing entry is run on seeded inputs of growing size. Times come from the
executor's own measurement (Judge0 CPU time), never from anything the program prints,
because team code shares the process and could fake a printed number.
"""

import math
import statistics
from dataclasses import dataclass, field

from ..schemas.question import Benchmark
from .client import ACCEPTED, TLE, ExecRequest, Executor

SEED = 20260929

_HARNESS = '''

# ---- benchmark harness (added by the judge) ----
def __compsoc_bench():
    import sys as _s, random as _r, hashlib as _h
    _n = int(_s.stdin.readline())
    _ns = {}
    exec(compile(__COMPSOC_GEN, "generator", "exec"), _ns)
    _args = _ns["gen"](_n, _r.Random(%d + _n))
    if not isinstance(_args, tuple):
        _args = (_args,)
    if __COMPSOC_CALL:
        _res = solve(*_args)
        print(_h.sha256(repr(_res).encode()).hexdigest())
    else:
        print("baseline")
__compsoc_bench()
''' % SEED


def build_source(team_code: str | None, generator: str) -> str:
    """team_code=None builds the baseline (generator only)."""
    prefix = f"__COMPSOC_GEN = {generator!r}\n__COMPSOC_CALL = {team_code is not None}\n"
    body = team_code if team_code is not None else ""
    # Team code goes after the two constants so its line numbers shift by 2; errors from
    # benchmarks are never shown line-by-line, so that is acceptable.
    return prefix + body + _HARNESS


@dataclass
class BenchResult:
    times_ms: dict[int, float] = field(default_factory=dict)  # n -> median ms, baseline subtracted
    timed_out_at: int | None = None
    wrong_at: int | None = None
    error: str | None = None
    hashes: dict[int, str] = field(default_factory=dict)

    @property
    def top_time(self) -> float | None:
        return self.times_ms[max(self.times_ms)] if self.times_ms else None


async def measure(
    ex: Executor, bench: Benchmark, team_code: str | None, baseline: dict[int, float] | None = None
) -> BenchResult:
    """Run sizes in order, serially. Stops at the first timeout. Slow runs (>1 s) aren't repeated."""
    res = BenchResult()
    for n in bench.sizes:
        samples: list[float] = []
        for rep in range(bench.repeats):
            [r] = await ex.run_batch(
                [
                    ExecRequest(
                        source=build_source(team_code, bench.generator),
                        stdin=f"{n}\n",
                        cpu_limit_s=bench.cpu_limit_s,
                        wall_limit_s=bench.cpu_limit_s * 2 + 1,
                        memory_kb=256_000,
                    )
                ]
            )
            if r.status_id == TLE:
                res.timed_out_at = n
                return res
            if r.status_id != ACCEPTED:
                res.error = f"status {r.status_id} at n={n}"
                return res
            res.hashes[n] = r.stdout.strip()
            samples.append(float(r.time_ms or 0))
            if (r.time_ms or 0) > 1000:
                break
        med = statistics.median(samples)
        base = (baseline or {}).get(n, 0.0)
        res.times_ms[n] = max(med - base, 0.0)
    return res


def slope(times_ms: dict[int, float], floor_ms: float = 1.0) -> float | None:
    """log-log slope between the two largest measured sizes."""
    if len(times_ms) < 2:
        return None
    (n1, t1), (n2, t2) = sorted(times_ms.items())[-2:]
    t1, t2 = max(t1, floor_ms), max(t2, floor_ms)
    return math.log(t2 / t1) / math.log(n2 / n1)


def estimate_class(times_ms: dict[int, float], timed_out_at: int | None, floor_ms: float, cpu_limit_ms: float) -> str:
    """Estimate the growth class from the two largest sizes.

    Small timings are mostly noise once the interpreter start-up is subtracted, so anything
    under 3 × floor is clamped up to that (which can only lower the estimate), and a timeout
    counts as taking at least the CPU limit at that size."""
    timed_out = timed_out_at is not None
    points = dict(times_ms)
    if timed_out:
        points[timed_out_at] = max(cpu_limit_ms, points.get(timed_out_at, 0))
    reliable = max(3 * floor_ms, 1.0)
    top = points[max(points)] if points else None
    if not timed_out and top is not None and top <= reliable:
        return "≈ O(n) or better"
    s = slope(points, floor_ms=reliable)
    if s is None:
        return "too slow" if timed_out else "?"
    if s < 0.5:
        label = "≈ O(1) / O(log n)"
    elif s < 1.5:
        label = "≈ O(n) / O(n log n)"
    elif s < 2.5:
        label = "≈ O(n²)"
    else:
        label = "≈ O(n³) or worse"
    return label + (" (timed out at the largest size)" if timed_out else "")
