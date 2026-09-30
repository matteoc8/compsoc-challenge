"""Submit deliberately bad programs to a running deployment and check the sandbox copes.

    python scripts/sandbox_check.py --base https://challenge.example.org --password <teacher password>

Creates a test game on the first verified quiz, joins one team, skips to the first Code
Golf question (or any coding question) and submits each program below, waiting for its
verdict. Passes when every verdict is what the sandbox should give, every result comes
back in time, and /api/health still says the judge is fine afterwards.
"""

import argparse
import asyncio
import json
import time

import httpx
import websockets

CORRECT = "n=int(input())\nfor i in range(n):print(('#'*-~i).rjust(n))"

# (name, code, acceptable verdicts)
CASES = [
    ("correct solution", CORRECT, {"Accepted"}),
    ("wrong answer", "print('#')", {"Wrong Answer"}),
    ("infinite loop", "while True: pass", {"Time Limit Exceeded"}),
    ("sleeps 10 s", "import time\ntime.sleep(10)", {"Time Limit Exceeded"}),
    ("memory hog, gradual", "a = []\nwhile True:\n    a.append(' ' * 10**7)", {"Runtime Error", "Time Limit Exceeded"}),
    ("memory hog, 1 GB at once", "x = ' ' * 10**9", {"Runtime Error"}),
    ("prints forever", "while True:\n    print('x' * 1000)", {"Runtime Error", "Time Limit Exceeded"}),
    ("writes a 10 MB file", "open('f', 'w').write('x' * 10**7)", {"Runtime Error"}),
    ("crash echoing the input", "raise ValueError(input())", {"Runtime Error"}),
    ("tries the internet", "import urllib.request\nurllib.request.urlopen('http://example.com', timeout=3)", {"Runtime Error", "Time Limit Exceeded"}),
    ("fork bomb", "import os\nwhile True:\n    os.fork()", {"Runtime Error", "Time Limit Exceeded", "Wrong Answer"}),
    ("kills its parent", "import os\nos.kill(os.getppid(), 9)\n" + CORRECT, {"Runtime Error", "Accepted", "Wrong Answer"}),
    ("correct again (still healthy)", CORRECT + "\n", {"Accepted"}),
]
RESULT_TIMEOUT_S = 90


def ws_url(base: str, **params) -> str:
    return base.replace("http", "ws", 1) + "/ws?" + "&".join(f"{k}={v}" for k, v in params.items())


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8080")
    ap.add_argument("--username", default="teacher")
    ap.add_argument("--password", required=True)
    args = ap.parse_args()

    teacher = httpx.AsyncClient(base_url=args.base, timeout=60)
    (await teacher.post("/api/auth/login", json={"username": args.username, "password": args.password})).raise_for_status()
    quiz = next(q for q in (await teacher.get("/api/quizzes")).json() if q["all_verified"])
    questions = (await teacher.get(f"/api/quizzes/{quiz['id']}")).json()["questions"]
    qtypes = [q["type"] for q in questions]
    target = qtypes.index("code_golf") if "code_golf" in qtypes else next(i for i, t in enumerate(qtypes) if t != "multiple_choice")
    game = (await teacher.post("/api/games", json={"quiz_id": quiz["id"]})).json()
    gid = game["id"]
    print(f"game {game['join_code']}: testing on question {target + 1} ({qtypes[target]})")

    team = httpx.AsyncClient(base_url=args.base, timeout=60)
    r = await team.post("/api/join", json={"code": game["join_code"], "team_name": "Sandbox check"})
    r.raise_for_status()
    token = r.json()["token"]
    team.headers["Authorization"] = f"Bearer {token}"

    async def get_state():
        return (await teacher.get(f"/api/games/{gid}")).json()

    async def wait_for(state: str, timeout: float = 60):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if (await get_state())["state"] == state:
                return
            await asyncio.sleep(0.3)
        raise SystemExit(f"game never reached {state}")

    await teacher.post(f"/api/games/{gid}/start", json={"force": True})
    for i in range(target):
        await teacher.post(f"/api/games/{gid}/next", json={"expect_state": "round_intro"})
        await wait_for("open")
        await teacher.post(f"/api/games/{gid}/end-now")
        await wait_for("results")
        await teacher.post(f"/api/games/{gid}/next", json={"expect_state": "results"})
        await teacher.post(f"/api/games/{gid}/next", json={"expect_state": "leaderboard"})
    await teacher.post(f"/api/games/{gid}/next", json={"expect_state": "round_intro"})
    await wait_for("open")
    await teacher.post(f"/api/games/{gid}/adjust-time", json={"delta_s": 600})
    qid = questions[target]["id"]

    results: dict[int, dict] = {}
    async with websockets.connect(ws_url(args.base, role="team", token=token), max_size=2**22) as ws:

        async def listen():
            async for raw in ws:
                m = json.loads(raw)
                if m["type"] == "submission.result" and m["data"]["status"] in ("judged", "error"):
                    results[m["data"]["attempt"]] = m["data"]

        listener = asyncio.create_task(listen())
        ok_all = True
        print(f"\n{'program':32} {'verdict':22} {'tests':>6} {'took':>6}  error shown")
        for name, code, allowed in CASES:
            while True:
                r = await team.post("/api/submissions", json={"question_id": qid, "code": code})
                if r.status_code != 429:
                    break
                await asyncio.sleep(1)
            r.raise_for_status()
            attempt, sent = r.json()["attempt"], time.monotonic()
            while attempt not in results and time.monotonic() - sent < RESULT_TIMEOUT_S:
                await asyncio.sleep(0.2)
            took = time.monotonic() - sent
            res = results.get(attempt)
            if res is None:
                ok_all = False
                print(f"{name:32} {'NO RESULT':22} {'':>6} {took:5.1f}s  FAIL")
                continue
            verdict = res["verdict"] or res["status"]
            ok = verdict in allowed
            leaked = name.startswith("crash") and res.get("error_summary") and "#" in (res["error_summary"] or "")
            ok = ok and not leaked
            ok_all &= ok
            tests = f"{res['passed']}/{res['total']}" if res["total"] else ""
            print(f"{name:32} {verdict:22} {tests:>6} {took:5.1f}s  {res.get('error_summary') or ''} {'ok' if ok else 'FAIL, expected ' + ' / '.join(sorted(allowed))}")
        listener.cancel()

    await teacher.post(f"/api/games/{gid}/end-now")
    health = (await teacher.get("/api/health")).json()
    print(f"\nhealth afterwards: {health}")
    ok_all &= bool(health.get("judge"))
    print("PASS" if ok_all else "FAIL")
    raise SystemExit(0 if ok_all else 1)


if __name__ == "__main__":
    asyncio.run(main())
