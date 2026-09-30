"""Packed judging: many tests of one program in one Judge0 submission.

The fake Judge0 here really runs each submission's source with the backend's Python, so
the runner that goes into the sandbox is exercised end to end (with wall-clock limits
only where `resource` is missing, e.g. on Windows).
"""

import base64
import json
import subprocess
import sys
import tempfile

import httpx

from app.judge.client import ACCEPTED, INTERNAL_ERROR, TLE, ExecRequest, Judge0Executor
from app.judge.pack import OUTPUT_BUDGET_BYTES, plan


def b64(s: str) -> str:
    return base64.b64encode(s.encode()).decode()


class RunningJudge0:
    """Judge0 batch API that executes each submission. `fail` makes packed runs die."""

    def __init__(self, fail: bool = False):
        self.fail = fail
        self.subs: dict[str, dict] = {}
        self.created: list[dict] = []

    def _run(self, sub: dict) -> dict:
        src = base64.b64decode(sub["source_code"]).decode()
        stdin = base64.b64decode(sub["stdin"]).decode() if sub.get("stdin") else ""
        if self.fail and "USER_CODE" in src:
            return {"status": {"id": INTERNAL_ERROR}}
        try:
            with tempfile.TemporaryDirectory() as box:
                p = subprocess.run(
                    [sys.executable, "-c", src], input=stdin.encode(), capture_output=True, timeout=sub["wall_time_limit"], cwd=box
                )
        except subprocess.TimeoutExpired:
            return {"status": {"id": TLE}}
        return {
            "status": {"id": ACCEPTED if p.returncode == 0 else 11},
            "stdout": base64.b64encode(p.stdout).decode() if p.stdout else None,
            "stderr": base64.b64encode(p.stderr).decode() if p.stderr else None,
            "time": "0.01",
            "memory": 3000,
        }

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            out = []
            for sub in json.loads(request.content)["submissions"]:
                token = f"t{len(self.subs)}"
                self.subs[token] = self._run(sub)
                self.created.append(sub)
                out.append({"token": token})
            return httpx.Response(201, json=out)
        tokens = request.url.params["tokens"].split(",")
        return httpx.Response(200, json={"submissions": [{"token": t, **self.subs[t]} for t in tokens]})


def make(fake, **kw) -> Judge0Executor:
    return Judge0Executor("http://judge0", 71, poll_interval_s=0.01, transport=httpx.MockTransport(fake), **kw)


def reqs(source: str, inputs: list[str], **limits) -> list[ExecRequest]:
    return [ExecRequest(source=source, stdin=s, **limits) for s in inputs]


async def test_ten_tests_become_one_submission():
    fake = RunningJudge0()
    res = await make(fake).run_batch(reqs("print(int(input()) * 2)", [f"{i}\n" for i in range(10)]))
    assert len(fake.created) == 1
    assert [r.stdout.strip() for r in res] == [str(i * 2) for i in range(10)]
    assert all(r.status_id == ACCEPTED and r.time_ms is not None for r in res)


async def test_per_test_verdicts_match_separate_runs():
    src = "n = int(input())\nif n == 2:\n    raise ValueError('secret input')\nif n == 3:\n    while True: pass\nprint(n)"
    res = await make(RunningJudge0()).run_batch(reqs(src, ["1\n", "2\n", "3\n", "4\n"], cpu_limit_s=1, wall_limit_s=1.5))
    assert [r.status_id for r in res] == [ACCEPTED, 11, TLE, ACCEPTED]
    assert 'script.py", line 3' in res[1].stderr  # Judge0's 3.8 prints the bare name
    assert res[0].stdout.strip() == "1" and res[3].stdout.strip() == "4"


async def test_tests_do_not_share_files():
    src = "import os\nprint(os.path.exists('note'))\nopen('note', 'w').write('x')"
    res = await make(RunningJudge0()).run_batch(reqs(src, ["", ""]))
    assert [r.stdout.strip() for r in res] == ["False", "False"]


async def test_failed_pack_falls_back_to_one_submission_per_test():
    fake = RunningJudge0(fail=True)
    res = await make(fake).run_batch(reqs("print(input())", ["a\n", "b\n", "c\n"]))
    assert [r.stdout.strip() for r in res] == ["a", "b", "c"]
    assert len(fake.created) == 1 + 3


async def test_oversized_output_is_judged_on_its_own():
    fake = RunningJudge0()
    big = OUTPUT_BUDGET_BYTES  # well over one test's share of the packed output
    res = await make(fake).run_batch(reqs(f"n = int(input())\nprint('x' * (n * {big}))", ["0\n", "1\n"]))
    assert res[0].stdout.strip() == "" and len(res[1].stdout.strip()) == big
    assert len(fake.created) == 1 + 1


async def test_different_programs_and_singles_keep_order():
    fake = RunningJudge0()
    batch = reqs("print('a' + input())", ["1\n", "2\n"]) + [ExecRequest(source="print('solo')")] + reqs("print('b' + input())", ["3\n", "4\n"])
    res = await make(fake).run_batch(batch)
    assert [r.stdout.strip() for r in res] == ["a1", "a2", "solo", "b3", "b4"]
    assert len(fake.created) == 3


async def test_packing_can_be_switched_off():
    fake = RunningJudge0()
    await make(fake, pack_tests=False).run_batch(reqs("print(1)", ["", "", ""]))
    assert len(fake.created) == 3


def test_packed_limits_stay_within_judge0_maximums():
    [p], _ = plan(reqs("print(1)", [""] * 20, cpu_limit_s=5, wall_limit_s=11, memory_kb=500_000))
    assert p.request.cpu_limit_s <= 15 and p.request.wall_limit_s <= 20 and p.request.memory_kb <= 512_000
