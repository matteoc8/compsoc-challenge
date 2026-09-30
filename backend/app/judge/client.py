"""Code execution backends.

Judge0Executor talks to a self-hosted Judge0 CE (or RapidAPI) using batch submit + poll.
LocalExecutor runs Python in a plain subprocess with timeouts only: it is NOT a sandbox
and exists so the app can be developed and tested on machines that can't run Judge0.
"""

import asyncio
import base64
import os
import re
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field

import httpx

# Judge0 status ids
IN_QUEUE, PROCESSING, ACCEPTED, WRONG_ANSWER, TLE, COMPILE_ERROR = 1, 2, 3, 4, 5, 6
RUNTIME_ERRORS = range(7, 13)  # SIGSEGV, SIGXFSZ, SIGFPE, SIGABRT, NZEC, other
INTERNAL_ERROR, EXEC_FORMAT_ERROR = 13, 14

STATUS_TEXT = {
    ACCEPTED: "Accepted",
    WRONG_ANSWER: "Wrong Answer",
    TLE: "Time Limit Exceeded",
    COMPILE_ERROR: "Compilation Error",
    INTERNAL_ERROR: "Judge Error",
    EXEC_FORMAT_ERROR: "Judge Error",
}


def status_text(status_id: int) -> str:
    if status_id in RUNTIME_ERRORS:
        return "Runtime Error"
    return STATUS_TEXT.get(status_id, "Judge Error")


class JudgeUnavailable(Exception):
    """Judge0 could not be reached or did not finish in time."""


@dataclass
class ExecRequest:
    source: str
    stdin: str = ""
    cpu_limit_s: float = 2
    wall_limit_s: float = 5
    memory_kb: int = 128_000


@dataclass
class ExecResult:
    status_id: int
    stdout: str = ""
    stderr: str = ""
    time_ms: int | None = None
    memory_kb: int | None = None
    extra: dict = field(default_factory=dict)

    @property
    def ran_ok(self) -> bool:
        return self.status_id == ACCEPTED


def normalise_output(s: str) -> str:
    """Strip trailing whitespace on each line and trailing blank lines."""
    lines = s.replace("\r\n", "\n").split("\n")
    return "\n".join(line.rstrip() for line in lines).rstrip("\n")


def outputs_match(actual: str, expected: str) -> bool:
    return normalise_output(actual) == normalise_output(expected)


_LINE_RE = re.compile(r'File "[^"]*", line (\d+)')


def summarise_error(stderr: str) -> str:
    """Exception type and line number only. Messages are dropped because they can
    echo hidden test input (e.g. ValueError: invalid literal for int(): '...')."""
    lines = [ln for ln in stderr.strip().splitlines() if ln.strip()]
    if not lines:
        return ""
    last = lines[-1].strip()
    exc = last.split(":", 1)[0].strip()
    if not re.fullmatch(r"[A-Za-z_][\w.]*", exc):
        exc = "Error"
    line_nos = _LINE_RE.findall(stderr)
    return f"{exc} on line {line_nos[-1]}" if line_nos else exc


class Executor:
    name = "base"

    async def run_batch(self, reqs: list[ExecRequest]) -> list[ExecResult]:  # pragma: no cover
        raise NotImplementedError

    async def health(self) -> bool:  # pragma: no cover
        raise NotImplementedError

    async def aclose(self) -> None:
        pass


def _b64(s: str) -> str:
    return base64.b64encode(s.encode()).decode()


def _unb64(s: str | None) -> str:
    return base64.b64decode(s).decode(errors="replace") if s else ""


class Judge0Executor(Executor):
    name = "judge0"
    BATCH_MAX = 20  # Judge0's MAX_SUBMISSION_BATCH_SIZE default

    def __init__(
        self,
        base_url: str,
        language_id: int,
        auth_token: str = "",
        rapidapi_key: str = "",
        rapidapi_host: str = "",
        poll_interval_s: float = 0.3,
        timeout_s: float = 30,
        transport: httpx.AsyncBaseTransport | None = None,
        pack_tests: bool = True,
    ):
        headers = {}
        if auth_token:
            headers["X-Auth-Token"] = auth_token
        if rapidapi_key:
            headers["X-RapidAPI-Key"] = rapidapi_key
            headers["X-RapidAPI-Host"] = rapidapi_host
        self.language_id = language_id
        self.poll_interval_s = poll_interval_s
        self.timeout_s = timeout_s
        self.pack_tests = pack_tests
        self.http = httpx.AsyncClient(base_url=base_url.rstrip("/"), headers=headers, timeout=10, transport=transport)

    async def aclose(self) -> None:
        await self.http.aclose()

    async def health(self) -> bool:
        try:
            r = await self.http.get("/languages")
            return r.status_code == 200
        except httpx.HTTPError:
            return False

    async def run_batch(self, reqs: list[ExecRequest]) -> list[ExecResult]:
        if not self.pack_tests:
            return await self._run_unpacked(reqs)
        from .pack import plan, unpack

        # Tests of the same program go into one submission (see pack.py); anything the
        # packed run couldn't settle is judged on its own afterwards.
        packs, singles = plan(reqs)
        first = await self._run_unpacked([p.request for p in packs] + [reqs[i] for i in singles])
        results: dict[int, ExecResult | None] = {}
        for p, r in zip(packs, first):
            results.update(unpack(p, r))
        for i, r in zip(singles, first[len(packs) :]):
            results[i] = r
        redo = [i for i in range(len(reqs)) if results[i] is None]
        if redo:
            for i, r in zip(redo, await self._run_unpacked([reqs[i] for i in redo])):
                results[i] = r
        return [results[i] for i in range(len(reqs))]

    async def _run_unpacked(self, reqs: list[ExecRequest]) -> list[ExecResult]:
        out: list[ExecResult] = []
        for i in range(0, len(reqs), self.BATCH_MAX):
            out.extend(await self._run_chunk(reqs[i : i + self.BATCH_MAX]))
        return out

    async def _run_chunk(self, reqs: list[ExecRequest]) -> list[ExecResult]:
        body = {
            "submissions": [
                {
                    "language_id": self.language_id,
                    "source_code": _b64(r.source),
                    "stdin": _b64(r.stdin),
                    "cpu_time_limit": r.cpu_limit_s,
                    "wall_time_limit": r.wall_limit_s,
                    "memory_limit": r.memory_kb,
                    "enable_network": False,
                }
                for r in reqs
            ]
        }
        try:
            resp = await self.http.post("/submissions/batch", params={"base64_encoded": "true"}, json=body)
            if resp.status_code >= 400:
                raise JudgeUnavailable(f"Judge0 returned {resp.status_code}: {resp.text[:200]}")
            created = resp.json()
            tokens = [c.get("token") for c in created]
            if not all(tokens):
                raise JudgeUnavailable(f"Judge0 rejected a submission: {created}")
            deadline = time.monotonic() + self.timeout_s
            fields = "token,stdout,stderr,compile_output,message,status,time,memory"
            while True:
                await asyncio.sleep(self.poll_interval_s)
                r = await self.http.get(
                    "/submissions/batch",
                    params={"tokens": ",".join(tokens), "base64_encoded": "true", "fields": fields},
                )
                if r.status_code >= 400:
                    raise JudgeUnavailable(f"Judge0 poll returned {r.status_code}")
                subs = r.json()["submissions"]
                if all(s["status"]["id"] not in (IN_QUEUE, PROCESSING) for s in subs):
                    break
                if time.monotonic() > deadline:
                    raise JudgeUnavailable("Judge0 did not finish within 30 s")
        except httpx.HTTPError as e:
            raise JudgeUnavailable(f"Judge0 unreachable: {e}") from e

        results = []
        for s in subs:
            t = s.get("time")
            results.append(
                ExecResult(
                    status_id=s["status"]["id"],
                    stdout=_unb64(s.get("stdout")),
                    stderr=_unb64(s.get("stderr")) or _unb64(s.get("compile_output")),
                    time_ms=round(float(t) * 1000) if t is not None else None,
                    memory_kb=s.get("memory"),
                )
            )
        return results


class LocalExecutor(Executor):
    """Development only. Runs code with the backend's own Python, isolated mode, no sandbox."""

    name = "local"

    def __init__(self, concurrency: int = 4):
        self.sem = asyncio.Semaphore(concurrency)

    async def health(self) -> bool:
        return True

    async def run_batch(self, reqs: list[ExecRequest]) -> list[ExecResult]:
        return list(await asyncio.gather(*(self._run_one(r) for r in reqs)))

    async def _run_one(self, req: ExecRequest) -> ExecResult:
        async with self.sem:
            return await asyncio.to_thread(self._run_sync, req)

    @staticmethod
    def _run_sync(req: ExecRequest) -> ExecResult:
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "script.py")
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                f.write(req.source)
            env = {"PYTHONIOENCODING": "utf-8", "SYSTEMROOT": os.environ.get("SYSTEMROOT", "")}
            start = time.perf_counter()
            try:
                p = subprocess.run(
                    [sys.executable, "-I", "-X", "utf8", path],
                    input=req.stdin.encode(),
                    capture_output=True,
                    timeout=min(req.cpu_limit_s, req.wall_limit_s),
                    cwd=d,
                    env=env,
                )
            except subprocess.TimeoutExpired as e:
                return ExecResult(
                    status_id=TLE,
                    stdout=(e.stdout or b"").decode(errors="replace"),
                    stderr=(e.stderr or b"").decode(errors="replace"),
                    time_ms=round(req.cpu_limit_s * 1000),
                )
            elapsed = round((time.perf_counter() - start) * 1000)
            stdout = p.stdout.decode(errors="replace")
            stderr = p.stderr.decode(errors="replace").replace(path, "script.py")
            status = ACCEPTED if p.returncode == 0 else 11  # NZEC
            return ExecResult(status_id=status, stdout=stdout, stderr=stderr, time_ms=elapsed)


def make_executor(settings) -> Executor:
    if settings.judge_backend == "local":
        return LocalExecutor(concurrency=settings.judge_workers)
    return Judge0Executor(
        settings.judge0_url,
        settings.judge0_python_id,
        auth_token=settings.judge0_auth_token,
        rapidapi_key=settings.judge0_rapidapi_key,
        rapidapi_host=settings.judge0_rapidapi_host,
        pack_tests=settings.judge0_pack_tests,
    )
