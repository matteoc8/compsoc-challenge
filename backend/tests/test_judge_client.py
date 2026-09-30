"""Judge0 client against a fake Judge0 server: success, compile errors, TLE, timeouts, down."""

import base64
import json

import httpx
import pytest

from app.judge.client import (
    ACCEPTED,
    COMPILE_ERROR,
    TLE,
    ExecRequest,
    Judge0Executor,
    JudgeUnavailable,
    LocalExecutor,
    status_text,
)


def b64(s: str) -> str:
    return base64.b64encode(s.encode()).decode()


class FakeJudge0:
    """Minimal Judge0 CE batch API. `script` maps a source to (status, stdout, stderr, time)."""

    def __init__(self, script, polls_before_done=1, never_finish=False):
        self.script = script
        self.polls_before_done = polls_before_done
        self.never_finish = never_finish
        self.subs: dict[str, dict] = {}
        self.polls = 0
        self.seen_headers: dict = {}
        self.seen_body: dict = {}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.seen_headers = dict(request.headers)
        if request.method == "POST" and request.url.path == "/submissions/batch":
            body = json.loads(request.content)
            self.seen_body = body
            out = []
            for i, sub in enumerate(body["submissions"]):
                token = f"t{len(self.subs)}"
                self.subs[token] = sub
                out.append({"token": token})
            return httpx.Response(201, json=out)
        if request.method == "GET" and request.url.path == "/submissions/batch":
            self.polls += 1
            tokens = request.url.params["tokens"].split(",")
            res = []
            for t in tokens:
                src = base64.b64decode(self.subs[t]["source_code"]).decode()
                if self.never_finish or self.polls < self.polls_before_done:
                    res.append({"token": t, "status": {"id": 2, "description": "Processing"}})
                    continue
                status, out, err, tm = self.script(src)
                res.append(
                    {
                        "token": t,
                        "status": {"id": status},
                        "stdout": b64(out) if out else None,
                        "stderr": None,
                        "compile_output": b64(err) if err else None,
                        "time": tm,
                        "memory": 3000,
                    }
                )
            return httpx.Response(200, json={"submissions": res})
        if request.url.path == "/languages":
            return httpx.Response(200, json=[{"id": 71, "name": "Python (3.8.1)"}])
        return httpx.Response(404)


def make(fake, **kw) -> Judge0Executor:
    return Judge0Executor("http://judge0", 71, auth_token="tok", poll_interval_s=0.01, transport=httpx.MockTransport(fake), **kw)


async def test_success_and_request_shape():
    fake = FakeJudge0(lambda src: (ACCEPTED, "42\n", "", "0.012"), polls_before_done=3)
    ex = make(fake)
    [r] = await ex.run_batch([ExecRequest(source="print(42)", stdin="x")])
    assert r.status_id == ACCEPTED and r.stdout == "42\n" and r.time_ms == 12 and r.memory_kb == 3000
    assert fake.polls >= 3
    sub = fake.seen_body["submissions"][0]
    assert sub["enable_network"] is False and sub["language_id"] == 71
    assert base64.b64decode(sub["stdin"]).decode() == "x"
    assert fake.seen_headers["x-auth-token"] == "tok"
    assert await ex.health()
    await ex.aclose()


async def test_compile_error_and_tle():
    def script(src):
        if "syntax" in src:
            return (COMPILE_ERROR, "", "SyntaxError", None)
        return (TLE, "", "", "2.0")

    ex = make(FakeJudge0(script))
    a, b = await ex.run_batch([ExecRequest(source="syntax"), ExecRequest(source="while 1: pass")])
    assert a.status_id == COMPILE_ERROR and a.stderr == "SyntaxError" and status_text(a.status_id) == "Compilation Error"
    assert b.status_id == TLE and status_text(b.status_id) == "Time Limit Exceeded"
    assert status_text(11) == "Runtime Error"


async def test_batches_are_chunked_to_20():
    fake = FakeJudge0(lambda src: (ACCEPTED, src, "", "0.001"))
    ex = make(fake)
    res = await ex.run_batch([ExecRequest(source=str(i)) for i in range(45)])
    assert [r.stdout for r in res] == [str(i) for i in range(45)]


async def test_never_finishes_raises_unavailable():
    ex = make(FakeJudge0(lambda s: (ACCEPTED, "", "", "0"), never_finish=True), timeout_s=0.2)
    with pytest.raises(JudgeUnavailable):
        await ex.run_batch([ExecRequest(source="x")])


async def test_down_raises_unavailable():
    def boom(request):
        raise httpx.ConnectError("refused")

    ex = Judge0Executor("http://judge0", 71, transport=httpx.MockTransport(boom))
    with pytest.raises(JudgeUnavailable):
        await ex.run_batch([ExecRequest(source="x")])
    assert not await ex.health()


async def test_server_error_raises_unavailable():
    ex = Judge0Executor("http://judge0", 71, transport=httpx.MockTransport(lambda r: httpx.Response(503, text="busy")))
    with pytest.raises(JudgeUnavailable):
        await ex.run_batch([ExecRequest(source="x")])


async def test_local_executor_basics():
    ex = LocalExecutor(2)
    ok, err, tle = await ex.run_batch(
        [
            ExecRequest(source="print(input()[::-1])", stdin="abc\n"),
            ExecRequest(source="x = 1\nraise ValueError('nope')"),
            ExecRequest(source="while True: pass", cpu_limit_s=1, wall_limit_s=1),
        ]
    )
    assert ok.status_id == ACCEPTED and ok.stdout.strip() == "cba"
    assert err.status_id == 11 and "line 2" in err.stderr and "script.py" in err.stderr
    assert tle.status_id == TLE
