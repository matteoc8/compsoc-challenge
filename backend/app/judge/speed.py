"""Fastest Code for the problem of the week: size tiers, timed from inside the program.

The old measurement timed the whole process from outside and subtracted a baseline. Python's
start-up and a shared droplet CPU are tens of milliseconds of noise, which is bigger than the
work a good solution does, so close entries swapped places and the O() guess was mostly wrong.

Here each benchmark size is one run. Inside it, the harness times only the solve() call with
the process's own CPU clock, 5 calls on fresh copies of the input, with the garbage collector
off (like timeit), and takes the mean. Ranking:

1. **Tier**: how many sizes, smallest first, the solution finished correctly with each call
   under the time limit (the benchmark's cpu_limit_s). Only a good algorithm reaches the
   largest size, and that doesn't depend on noise.
2. Within the same tier, the mean time at the largest size reached. Means within TIE_SHARE
   (20%) of each other are a tie: see scoring.weekly_bonus for exactly how.

Each time is also shown against the reference solution's at the same size ("1.3× the
reference"), measured the same way.

The number the program prints could be faked by the code being timed (it shares the process),
so it's checked against Judge0's own CPU time for the whole run, minus a baseline run of just
the generator. If the printed time is far below what Judge0 saw, the outside figure is used.

Harness code runs on Judge0's Python 3.8: no 3.9+ syntax.
"""

import json
from dataclasses import dataclass, field

from ..schemas.question import Benchmark
from .benchmark import SEED
from .client import ACCEPTED, TLE, ExecRequest, Executor

REPEATS = 5  # solve() calls per size, averaged (fewer if the time budget runs out)
TIE_SHARE = 0.2  # mean times within 20% of the group's fastest count as a tie
PROC_CPU_MAX_S = 15  # Judge0's MAX_CPU_TIME_LIMIT
# The printed time may be this much below Judge0's figure before it's not believed.
TRUST_RATIO, TRUST_SLACK_MS = 0.5, 40

_HARNESS = '''

# ---- speed harness (added by the judge) ----
def __compsoc_speed():
    import sys as _s, random as _r, hashlib as _h, gc as _gc, time as _t, json as _j
    _n = int(_s.stdin.readline())
    _reps = int(_s.stdin.readline())
    _limit = float(_s.stdin.readline())
    _ns = {}
    exec(compile(__COMPSOC_GEN, "generator", "exec"), _ns)
    # CPU time on Judge0 (Linux). Windows only ticks it every ~16 ms, so the local judge uses wall time.
    _clock = _t.perf_counter if _s.platform == "win32" else _t.process_time
    _times, _hash, _spent = [], None, 0.0
    for _i in range(_reps):
        _args = _ns["gen"](_n, _r.Random(%d + _n))
        if not isinstance(_args, tuple):
            _args = (_args,)
        if not __COMPSOC_CALL:
            continue
        _gc.collect()
        _gc.disable()
        _t0 = _clock()
        _res = solve(*_args)
        _dt = _clock() - _t0
        _gc.enable()
        if _hash is None:
            _hash = _h.sha256(repr(_res).encode()).hexdigest()
        _times.append(round(_dt * 1000, 3))
        _spent += _dt
        if _dt > _limit or _spent + _dt > _limit or _t.process_time() > 2 * _limit + 1:
            break
    print()
    print("__compsoc__" + _j.dumps({"h": _hash, "t": _times}))
__compsoc_speed()
''' % SEED

MARK = "__compsoc__"


def build_source(team_code: str | None, generator: str) -> str:
    """team_code=None builds the baseline (the generator only, same number of times)."""
    prefix = f"__COMPSOC_GEN = {generator!r}\n__COMPSOC_CALL = {team_code is not None}\n"
    return prefix + (team_code or "") + _HARNESS


def _request(source: str, n: int, reps: int, limit_s: float) -> ExecRequest:
    cpu = min(PROC_CPU_MAX_S, 2 * limit_s + 3)
    return ExecRequest(source=source, stdin=f"{n}\n{reps}\n{limit_s}\n", cpu_limit_s=cpu, wall_limit_s=min(20, cpu + 5), memory_kb=256_000)


def _parse(stdout: str) -> dict | None:
    line = next((x for x in reversed(stdout.splitlines()) if x.startswith(MARK)), None)
    if line is None:
        return None
    try:
        out = json.loads(line[len(MARK):])
        times = [float(t) for t in out["t"]]
        return {"h": out.get("h"), "t": times}
    except (ValueError, KeyError, TypeError):
        return None


@dataclass
class SizeRun:
    n: int
    mean_ms: float | None = None  # the time used for ranking
    calls: int = 0
    judge_ms: float | None = None  # Judge0's CPU time for the whole run
    checked: str = "inner"  # "inner", or "outer" when the printed time wasn't believed
    hash: str | None = None


@dataclass
class SpeedResult:
    runs: list[SizeRun] = field(default_factory=list)  # sizes completed, smallest first
    stopped_at: int | None = None  # the size it didn't finish
    reason: str | None = None  # "slow", "wrong", "error"

    @property
    def tier(self) -> int:
        return len(self.runs)

    @property
    def top(self) -> SizeRun | None:
        return self.runs[-1] if self.runs else None


@dataclass
class Baseline:
    """Judge0 CPU time of the generator alone: start-up + one call (one_ms) and per extra call."""

    one_ms: dict[int, float] = field(default_factory=dict)
    per_call_ms: dict[int, float] = field(default_factory=dict)

    def expected_ms(self, n: int, calls: int) -> float:
        one, per = self.one_ms.get(n, 0.0), self.per_call_ms.get(n, 0.0)
        return one + per * max(calls - 1, 0)


async def baseline(ex: Executor, bench: Benchmark) -> Baseline:
    src = build_source(None, bench.generator)
    reqs = [_request(src, n, reps, bench.cpu_limit_s) for n in bench.sizes for reps in (1, REPEATS)]
    res = await ex.run_batch(reqs)
    out = Baseline()
    for i, n in enumerate(bench.sizes):
        one, many = res[2 * i], res[2 * i + 1]
        if one.status_id != ACCEPTED or many.status_id != ACCEPTED:
            continue
        t1, tr = float(one.time_ms or 0), float(many.time_ms or 0)
        out.one_ms[n] = t1
        out.per_call_ms[n] = max((tr - t1) / (REPEATS - 1), 0.0)
    return out


async def measure(ex: Executor, bench: Benchmark, code: str, base: Baseline | None, ref_hashes: dict[int, str] | None) -> SpeedResult:
    """Sizes smallest first, one run each, stopping at the first one it doesn't finish."""
    src = build_source(code, bench.generator)
    limit_ms = bench.cpu_limit_s * 1000
    res = SpeedResult()
    for n in bench.sizes:
        [r] = await ex.run_batch([_request(src, n, REPEATS, bench.cpu_limit_s)])
        if r.status_id == TLE:
            res.stopped_at, res.reason = n, "slow"
            return res
        got = _parse(r.stdout) if r.status_id == ACCEPTED else None
        if got is None or not got["t"]:
            res.stopped_at, res.reason = n, "error"
            return res
        if ref_hashes and ref_hashes.get(n) and got["h"] != ref_hashes[n]:
            res.stopped_at, res.reason = n, "wrong"
            return res
        times = got["t"]
        run = SizeRun(n=n, mean_ms=sum(times) / len(times), calls=len(times), judge_ms=float(r.time_ms) if r.time_ms is not None else None, hash=got["h"])
        if base is not None and run.judge_ms is not None and n in base.one_ms:
            outer = max(run.judge_ms - base.expected_ms(n, run.calls), 0.0)  # all calls together
            if sum(times) < TRUST_RATIO * outer - TRUST_SLACK_MS:
                run.mean_ms, run.checked = outer / run.calls, "outer"
        if times[0] > limit_ms or run.mean_ms > limit_ms:
            res.stopped_at, res.reason = n, "slow"
            return res
        res.runs.append(run)
    return res


def fmt_n(n: int) -> str:
    return f"{n:,}"


def fmt_ms(ms: float) -> str:
    return f"{ms:.2f} ms" if ms < 10 else f"{ms:.1f} ms" if ms < 100 else f"{ms:,.0f} ms"


WHY = {"slow": "timed out", "wrong": "wrong answer", "error": "error"}


def describe(perf: dict | None) -> str | None:
    """How a measured entry is shown: "3/3 test sizes in 1.61 ms", or
    "1/3 test sizes in 21.0 ms (timed out)". Old-style entries keep their own label."""
    if not perf:
        return None
    if perf.get("method") != "tiers" or perf.get("tier") is None:
        return perf.get("class_label")
    out = f"{perf['tier']}/{perf.get('tiers')} test sizes"
    if perf.get("top_ms") is not None:
        out += f" in {fmt_ms(perf['top_ms'])}"
    if perf["tier"] != perf.get("tiers"):
        out += f" ({WHY.get(perf.get('reason') or 'error', 'error')})"
    return out


def to_perf(res: SpeedResult, sizes: list[int], ref: SpeedResult | None = None) -> dict:
    """What's stored on the entry. The comparison with the reference is for admins only."""
    top = res.top
    ref_ms = next((r.mean_ms for r in ref.runs if top and r.n == top.n), None) if ref else None
    ratio = round(top.mean_ms / ref_ms, 2) if top and ref_ms else None
    out = {
        "method": "tiers",
        "tier": res.tier,
        "tiers": len(sizes),
        "top_n": top.n if top else None,
        "top_ms": round(top.mean_ms, 3) if top else None,
        "ref_ms": round(ref_ms, 3) if ref_ms else None,
        "vs_reference": ratio,
        "sizes_ms": {str(r.n): round(r.mean_ms, 3) for r in res.runs},
        "checked": [r.n for r in res.runs if r.checked == "outer"],
        "stopped_at": res.stopped_at,
        "reason": res.reason,
    }
    out["class_label"] = describe(out)
    return out


def rank_key(perf: dict | None) -> tuple | None:
    """Lower is better: more tiers first, then the time at the top tier. None = not measured.
    Older entries measured the old way rank by how many sizes they finished, then their time."""
    if not perf:
        return None
    if perf.get("method") == "tiers":
        if perf.get("tier") is None:  # the judge was down
            return None
        return (-int(perf.get("tier") or 0), perf["top_ms"] if perf.get("top_ms") is not None else float("inf"))
    times = perf.get("times_ms") or {}
    if not times and perf.get("score_ms") is None:
        return None
    tier = len(times)
    if perf.get("wrong_at"):
        tier = sum(1 for n in times if int(n) < int(perf["wrong_at"]))
    top = perf.get("top_ms")
    return (-tier, top if top is not None else float("inf"))
