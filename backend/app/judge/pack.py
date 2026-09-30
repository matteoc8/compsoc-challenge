"""Pack several tests of the same program into one Judge0 submission.

Judge0 spends far more CPU on each submission (its worker, sandbox setup and teardown)
than a small Python program does, so ten hidden tests as ten submissions made judging
CPU-bound on a 2 vCPU server. A packed submission runs RUNNER inside the sandbox; the
runner starts a fresh Python process per test (same isolation from each other as before),
applies that test's CPU, wall, memory and file-size limits itself, and prints one JSON
line with every test's result. Judge0 status ids are reproduced for each test.

Tests the runner could not finish within the submission's overall budget, or whose
output was too large to send back, come back as "redo" and are judged one by one.

RUNNER runs on Judge0's Python 3.8: no 3.9+ syntax. It degrades to wall-clock limits
where `resource`/`os.wait4` don't exist (Windows), which only the unit tests use.
"""

import base64
import json
import math
from dataclasses import dataclass

from .client import ACCEPTED, ExecRequest, ExecResult

# Judge0's MAX_CPU_TIME_LIMIT / MAX_WALL_TIME_LIMIT / MAX_MEMORY_LIMIT (judge0.conf, and
# the defaults on hosted Judge0 CE). Asking for more is rejected with a 422.
JOB_CPU_MAX_S = 15
JOB_WALL_MAX_S = 20
JOB_MEMORY_MAX_KB = 512_000
# Room for the runner's own interpreter next to one test's process.
RUNNER_MEMORY_KB = 64_000
# Judge0 caps stdout at MAX_FILE_SIZE (1024 KB); the runner's JSON must fit under it.
OUTPUT_BUDGET_BYTES = 600_000

RUNNER = r'''
import base64, json, math, os, shutil, signal, subprocess, sys, time
try:
    import resource
except ImportError:
    resource = None

USER_CODE = base64.b64decode("__CODE__")
TLE, SIGNALS = 5, {11: 7, 25: 8, 8: 9, 6: 10}

cfg = json.loads(sys.stdin.read())

cpu_limit, wall_limit, mem_kb = cfg["cpu"], cfg["wall"], cfg["mem_kb"]
cpu_soft = int(math.ceil(cpu_limit + 0.5))
cap = cfg["out_cap"]


def limits():
    resource.setrlimit(resource.RLIMIT_CPU, (cpu_soft, cpu_soft + 1))
    resource.setrlimit(resource.RLIMIT_AS, ((mem_kb + 64000) * 1024,) * 2)
    resource.setrlimit(resource.RLIMIT_FSIZE, (1024 * 1024,) * 2)
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def read(name):
    with open(os.path.join("u", name), "rb") as f:
        data = f.read(cap + 1)
    return data[:cap].decode("utf-8", "replace"), len(data) > cap


def run(stdin):
    # A fresh folder and a fresh copy of the program per test, like separate submissions.
    shutil.rmtree("u", ignore_errors=True)
    os.mkdir("u")
    with open(os.path.join("u", "script.py"), "wb") as f:
        f.write(USER_CODE)
    with open(os.path.join("u", "in"), "wb") as f:
        f.write(stdin.encode("utf-8"))
    fin = open(os.path.join("u", "in"), "rb")
    fout = open(os.path.join("u", "out"), "wb")
    ferr = open(os.path.join("u", "err"), "wb")
    start = time.monotonic()
    p = subprocess.Popen([sys.executable, "script.py"], cwd="u", stdin=fin, stdout=fout, stderr=ferr,
                         preexec_fn=limits if resource else None)
    killed, cpu, mem = False, None, None
    if resource and hasattr(os, "wait4"):
        while True:
            pid, status, ru = os.wait4(p.pid, os.WNOHANG)
            if pid:
                break
            if time.monotonic() - start > wall_limit:
                os.kill(p.pid, signal.SIGKILL)
                pid, status, ru = os.wait4(p.pid, 0)
                killed = True
                break
            time.sleep(0.005)
        p.returncode = 0
        cpu, mem = ru.ru_utime + ru.ru_stime, ru.ru_maxrss
        sig = os.WTERMSIG(status) if os.WIFSIGNALED(status) else 0
        code = os.WEXITSTATUS(status) if os.WIFEXITED(status) else -1
    else:
        try:
            code = p.wait(timeout=wall_limit)
        except subprocess.TimeoutExpired:
            p.kill()
            p.wait()
            killed, code = True, -1
        sig = 0
    wall = time.monotonic() - start
    for f in (fin, fout, ferr):
        f.close()
    out, big_out = read("out")
    err, big_err = read("err")
    shutil.rmtree("u", ignore_errors=True)
    if killed or (cpu is not None and cpu > cpu_limit) or sig in (24, 9):
        status_id = TLE
    elif sig:
        status_id = SIGNALS.get(sig, 12)
    else:
        status_id = 3 if code == 0 else 11
    t = cpu if cpu is not None else wall
    return {"s": status_id, "o": out, "e": err, "t": round(t * 1000), "m": mem, "redo": big_out or big_err}


results = []
t0 = time.monotonic()
cpu_reserve = cpu_soft + 1.5
for stdin in cfg["tests"]:
    used_cpu = time.process_time()
    if resource:
        ru = resource.getrusage(resource.RUSAGE_CHILDREN)
        used_cpu += ru.ru_utime + ru.ru_stime
    if used_cpu + cpu_reserve > cfg["job_cpu"] or time.monotonic() - t0 + wall_limit + 1 > cfg["job_wall"]:
        results.append({"redo": True})
        continue
    results.append(run(stdin))
sys.stdout.write(json.dumps(results))
'''


@dataclass
class Packed:
    request: ExecRequest
    indices: list[int]


def pack(reqs: list[ExecRequest], indices: list[int]) -> Packed:
    """One submission running reqs[i] for every i in indices (same source and limits)."""
    first = reqs[indices[0]]
    n = len(indices)
    job_cpu = min(JOB_CPU_MAX_S, n * (math.ceil(first.cpu_limit_s + 0.5) + 1.5) + 1)
    job_wall = min(JOB_WALL_MAX_S, n * first.wall_limit_s + 2)
    cfg = {
        "tests": [reqs[i].stdin for i in indices],
        "cpu": first.cpu_limit_s,
        "wall": first.wall_limit_s,
        "mem_kb": first.memory_kb,
        "job_cpu": job_cpu - 1,
        "job_wall": job_wall - 1,
        "out_cap": OUTPUT_BUDGET_BYTES // (2 * n),
    }
    source = RUNNER.replace("__CODE__", base64.b64encode(first.source.encode()).decode())
    return Packed(
        ExecRequest(
            source=source,
            stdin=json.dumps(cfg),
            cpu_limit_s=job_cpu,
            wall_limit_s=job_wall,
            memory_kb=min(JOB_MEMORY_MAX_KB, first.memory_kb + RUNNER_MEMORY_KB * 2),
        ),
        indices,
    )


def unpack(p: Packed, r: ExecResult) -> dict[int, ExecResult | None]:
    """Results by original index; None = judge that test on its own."""
    try:
        if r.status_id != ACCEPTED:
            raise ValueError(r.status_id)
        rows = json.loads(r.stdout)
        if not isinstance(rows, list) or len(rows) != len(p.indices):
            raise ValueError("wrong length")
    except ValueError:
        return {i: None for i in p.indices}
    out: dict[int, ExecResult | None] = {}
    for i, row in zip(p.indices, rows):
        if row.get("redo"):
            out[i] = None
        else:
            out[i] = ExecResult(status_id=row["s"], stdout=row["o"], stderr=row["e"], time_ms=row["t"], memory_kb=row["m"])
    return out


def plan(reqs: list[ExecRequest]) -> tuple[list[Packed], list[int]]:
    """Group requests that share source and limits. Returns packs and the indices left single."""
    groups: dict[tuple, list[int]] = {}
    for i, r in enumerate(reqs):
        groups.setdefault((r.source, r.cpu_limit_s, r.wall_limit_s, r.memory_kb), []).append(i)
    packs, singles = [], []
    for idx in groups.values():
        if len(idx) >= 2:
            packs.append(pack(reqs, idx))
        else:
            singles.extend(idx)
    return packs, singles
