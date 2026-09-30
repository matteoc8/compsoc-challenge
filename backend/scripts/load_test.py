"""Load test: N bot teams play a whole game against a running deployment.

    python scripts/load_test.py --base http://localhost:8080 --password <teacher password>

Each bot joins, keeps a WebSocket open, Runs every 10–20 s and Submits a mix of wrong,
partial and correct solutions in all three rounds. A bot teacher drives the game.
Pass criteria (from the build plan): no seq gaps, countdowns agree within 200 ms,
submission results within 5 s at p95, benchmarks finish within 30 s.
Uses a verified quiz (the seeded sample by default).
"""

import argparse
import asyncio
import json
import random
import statistics
import time

import httpx
import websockets

SOLUTIONS = {
    "super_fast": {
        "wrong": "input()\nprint(0)",
        "partial": "print(sum(c in 'aeiou' for c in input()))",
        "correct": "print(sum(c in 'aeiouAEIOU' for c in input()))",
    },
    "code_golf": {
        "wrong": "print('#')",
        "partial": "n=int(input())\nfor i in range(n):print('#'*(i+1))",
        "correct": "n=int(input())\nfor i in range(n):print(('#'*-~i).rjust(n))",
    },
    "best_complexity": {
        "wrong": "def solve(nums, k):\n    return 0\n",
        "partial": "def solve(nums, k):\n    return len(nums) // 2\n",
        "correct": "def solve(nums, k):\n    s = {}\n    c = 0\n    for x in nums:\n        c += s.get(k - x, 0)\n        s[x] = s.get(x, 0) + 1\n    return c\n",
        "slow": "def solve(nums, k):\n    c = 0\n    for i in range(len(nums)):\n        for j in range(i + 1, len(nums)):\n            c += nums[i] + nums[j] == k\n    return c\n",
    },
}


class Stats:
    def __init__(self):
        self.seq_gaps = 0
        self.latencies: list[float] = []
        self.deadlines: dict[str, set[str]] = {}
        self.offsets: list[float] = []
        self.errors: list[str] = []
        self.submits = 0
        self.runs = 0
        self.rejected = 0
        self.answers = 0


def ws_url(base: str, **params) -> str:
    return base.replace("http", "ws", 1) + "/ws?" + "&".join(f"{k}={v}" for k, v in params.items())


class Bot:
    def __init__(self, base: str, name: str, stats: Stats, rng: random.Random):
        self.base, self.name, self.stats, self.rng = base, name, stats, rng
        self.http = httpx.AsyncClient(base_url=base, timeout=30)
        self.token = ""
        self.snapshot: dict = {}
        self.pending: dict[int, float] = {}  # attempt -> sent at
        self.last_seq = 0
        self.offset_samples: list[float] = []

    async def join(self, code: str):
        r = await self.http.post("/api/join", json={"code": code, "team_name": self.name})
        r.raise_for_status()
        self.token = r.json()["token"]
        self.http.headers["Authorization"] = f"Bearer {self.token}"

    async def listen(self, stop: asyncio.Event):
        async with websockets.connect(ws_url(self.base, role="team", token=self.token), max_size=2**22) as ws:
            for _ in range(5):
                await ws.send(json.dumps({"type": "ping", "data": {"t0": time.time() * 1000}}))
            while not stop.is_set():
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=1)
                except asyncio.TimeoutError:
                    continue
                m = json.loads(raw)
                if self.last_seq and m["seq"] != self.last_seq + 1:
                    self.stats.seq_gaps += 1
                self.last_seq = m["seq"]
                t, d = m["type"], m["data"]
                if t == "pong":
                    now = time.time() * 1000
                    self.offset_samples.append(d["server_ms"] + (now - d["t0"]) / 2 - now)
                elif t == "snapshot":
                    self.snapshot = d
                    g = d["game"]
                    if g["state"] == "open" and g["deadline"]:
                        self.stats.deadlines.setdefault(f"{g['question_index']}:{g['ending']}", set()).add(g["deadline"])
                elif t == "submission.result" and d["status"] in ("judged", "error"):
                    sent = self.pending.pop(d["attempt"], None)
                    if sent:
                        self.stats.latencies.append(time.monotonic() - sent)
        if self.offset_samples:
            self.stats.offsets.append(statistics.median(self.offset_samples))

    def state(self) -> tuple[str | None, dict | None]:
        g = self.snapshot.get("game") or {}
        return g.get("state"), self.snapshot.get("question")

    async def play(self, stop: asyncio.Event, speed: float):
        plan_index = 0
        plan: list[str] = []
        current_q = None
        next_run = time.monotonic() + self.rng.uniform(1, 5) / speed
        next_submit = time.monotonic() + self.rng.uniform(2, 8) / speed
        while not stop.is_set():
            await asyncio.sleep(0.2)
            state, q = self.state()
            if state != "open" or not q:
                continue
            if q["type"] == "multiple_choice":
                if q["id"] != current_q:
                    current_q = q["id"]
                    await asyncio.sleep(self.rng.uniform(0.5, 4) / speed)
                    r = await self.http.post("/api/answers", json={"question_id": q["id"], "choice": self.rng.randrange(len(q["options"]))})
                    self.stats.answers += r.status_code == 200
                continue
            if q["id"] != current_q:
                current_q, plan_index = q["id"], 0
                head = ["wrong", "partial"]
                self.rng.shuffle(head)
                last = "slow" if q["type"] == "best_complexity" and self.rng.random() < 0.3 else "correct"
                plan = head + [last]
            now = time.monotonic()
            if now >= next_run:
                next_run = now + self.rng.uniform(10, 20) / speed
                r = await self.http.post("/api/runs", json={"question_id": q["id"], "code": SOLUTIONS[q["type"]]["partial"]})
                self.stats.runs += r.status_code == 202
            if now >= next_submit and plan_index < len(plan) and not self.pending:
                kind = plan[plan_index]
                r = await self.http.post("/api/submissions", json={"question_id": q["id"], "code": SOLUTIONS[q["type"]][kind]})
                if r.status_code == 202:
                    self.pending[r.json()["attempt"]] = time.monotonic()
                    self.stats.submits += 1
                    plan_index += 1
                else:
                    self.stats.rejected += 1
                next_submit = now + self.rng.uniform(6, 12) / speed


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8080")
    ap.add_argument("--username", default="teacher")
    ap.add_argument("--password", required=True)
    ap.add_argument("--teams", type=int, default=15)
    ap.add_argument("--round-seconds", type=float, default=45, help="how long each question stays open")
    ap.add_argument("--speed", type=float, default=1.0, help=">1 makes bots act faster")
    args = ap.parse_args()
    rng = random.Random(7)
    stats = Stats()

    teacher = httpx.AsyncClient(base_url=args.base, timeout=120)
    r = await teacher.post("/api/auth/login", json={"username": args.username, "password": args.password})
    r.raise_for_status()
    quiz = next(q for q in (await teacher.get("/api/quizzes")).json() if q["all_verified"])
    qtypes = [q["type"] for q in (await teacher.get(f"/api/quizzes/{quiz['id']}")).json()["questions"]]
    game = (await teacher.post("/api/games", json={"quiz_id": quiz["id"]})).json()
    gid = game["id"]
    print(f"game {game['join_code']} with {args.teams} bots on quiz '{quiz['title']}'")

    bots = [Bot(args.base, f"Bot {i + 1:02d}", stats, random.Random(i)) for i in range(args.teams)]
    await asyncio.gather(*(b.join(game["join_code"]) for b in bots))
    stop = asyncio.Event()
    tasks = [asyncio.create_task(b.listen(stop)) for b in bots] + [asyncio.create_task(b.play(stop, args.speed)) for b in bots]
    await asyncio.sleep(2)
    await teacher.post(f"/api/games/{gid}/start", json={"force": True})

    bench_times = []
    for round_no in range(quiz["question_count"]):
        await teacher.post(f"/api/games/{gid}/next", json={"expect_state": "round_intro"})
        print(f"round {round_no + 1} open ({qtypes[round_no]})")
        waited = 0.0
        while waited < args.round_seconds and (await teacher.get(f"/api/games/{gid}")).json()["state"] == "open":
            await asyncio.sleep(0.5)
            waited += 0.5
        await teacher.post(f"/api/games/{gid}/end-now")
        closed_at = time.monotonic()
        while (await teacher.get(f"/api/games/{gid}")).json()["state"] != "results":
            await asyncio.sleep(0.25)
        took = time.monotonic() - closed_at - 3  # minus the 3 s "Ending…" countdown
        print(f"round {round_no + 1} results after {took:.1f} s")
        if qtypes[round_no] == "best_complexity":
            bench_times.append(took)
        await teacher.post(f"/api/games/{gid}/next", json={"expect_state": "results"})
        await teacher.post(f"/api/games/{gid}/next", json={"expect_state": "leaderboard"})
    await asyncio.sleep(1)
    stop.set()
    await asyncio.gather(*tasks, return_exceptions=True)

    lat = sorted(stats.latencies)
    p95 = lat[int(len(lat) * 0.95) - 1] if lat else float("nan")
    spread_deadline = max((len(v) for v in stats.deadlines.values()), default=1)
    off_spread = (max(stats.offsets) - min(stats.offsets)) if stats.offsets else 0
    print("\n--- results")
    print(f"answers {stats.answers}, submissions accepted {stats.submits}, rejected {stats.rejected} (cooldowns), runs {stats.runs}")
    print(f"judge latency: median {statistics.median(lat):.2f} s, p95 {p95:.2f} s, max {lat[-1]:.2f} s" if lat else "no latencies")
    print(f"seq gaps: {stats.seq_gaps}")
    print(f"distinct deadlines per question state (1 = everyone agrees): {spread_deadline}")
    print(f"clock-offset spread across bots: {off_spread:.0f} ms")
    print(f"benchmark phase: {', '.join(f'{t:.1f} s' for t in bench_times) or 'n/a'}")
    ok = stats.seq_gaps == 0 and spread_deadline == 1 and off_spread <= 200 and p95 <= 5 and all(t <= 30 for t in bench_times)
    print("PASS" if ok else "FAIL")
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    asyncio.run(main())
