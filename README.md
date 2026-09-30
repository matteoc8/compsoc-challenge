# CompSoc Challenge

The whole CompSoc competition on one site: multiple-choice questions (question and four answers
on every team's screen, optional image, faster correct answers score more) and three live coding
rounds (Super Fast, Code Golf, Best Time Complexity), with a game-show lobby, timer, leaderboard
and podium, a LeetCode-style editor on each team's computer, and Judge0 to run code.

Built from the *CompSoc Challenge — Build Plan* doc. One server-authoritative game engine
(FastAPI), three thin Next.js screens pushed over one WebSocket each, Postgres as the source of
truth, Caddy in front so everything runs on one URL.

| Screen | URL | Who |
|---|---|---|
| Team computer | `/join` → `/play` | teams (desktop, 1366×768 and up) |
| Projector | `/presentation?game=…&token=…` (link on the console) | the room |
| Teacher console | `/teacher` | teacher, on a separate device |

## Run it for real (Docker Compose)

Needs a **Linux host with cgroup v1** for Judge0 (Ubuntu 22.04: add
`systemd.unified_cgroup_hierarchy=0` to `GRUB_CMDLINE_LINUX`, `sudo update-grub`, reboot).
A 2 vCPU / 4 GB VPS or a spare school Linux machine is plenty.

```bash
cp .env.example .env            # set POSTGRES_PASSWORD, SECRET_KEY, TEACHER_PASSWORD, SITE_ADDRESS
# edit judge0.conf: replace every change-me; put its AUTHN_TOKEN in .env as JUDGE0_AUTH_TOKEN
docker compose -f docker-compose.yml -f docker-compose.judge0.yml up -d --build
curl http://localhost/api/health   # {"ok":true,"judge":true,...}
```

Then open `/teacher`, log in with `TEACHER_USERNAME` / `TEACHER_PASSWORD` (you must pick a new
password), write your questions (the sample quiz has 5 example multiple-choice questions and the
3 coding rounds), press **Verify all**, then **New game**. The full hosting walkthrough is in the
*CompSoc Challenge — Hosting Guide* doc.

- `SITE_ADDRESS=challenge.example.org` gets automatic HTTPS (also set `COOKIE_SECURE=true`);
  `:80` serves plain HTTP on a LAN.
- Check Python's language id on your Judge0 (`GET /languages`) and set `JUDGE0_PYTHON_ID`.
  Judge0 CE 1.13.1 ships **Python 3.8**, so challenges must avoid 3.9+ syntax such as
  `list[int]` annotations (the linter targets py38 too).
- Fallback if Judge0 can't be self-hosted: Judge0 on RapidAPI; set `JUDGE0_URL`,
  `JUDGE0_RAPIDAPI_KEY`, `JUDGE0_RAPIDAPI_HOST` in `.env` (config only, no code change).

## Develop locally (no Docker needed)

`JUDGE_BACKEND=local` runs submissions with the backend's own Python in a subprocess with
timeouts. **It is not a sandbox**: development only, never in front of students.

```bash
# backend
cd backend
python -m venv .venv && .venv/Scripts/pip install -r requirements-dev.txt   # (bin/ on Linux/macOS)
JUDGE_BACKEND=local .venv/Scripts/python -m uvicorn app.main:app --port 8000
# defaults to SQLite (./dev.db); set DATABASE_URL=postgresql+asyncpg://… for Postgres

# frontend
cd frontend && npm install && npm run build
cp -r .next/static .next/standalone/.next/static && cp -r public .next/standalone/public
PORT=3000 node .next/standalone/server.js

# one URL for both (WebSockets included), like production
SITE_ADDRESS=:8080 BACKEND_UPSTREAM=localhost:8000 FRONTEND_UPSTREAM=localhost:3000 caddy run --config Caddyfile
```

`npm run dev` works for UI work too (REST is proxied), but WebSockets need Caddy in front.
`npm run gen:types` regenerates `frontend/lib/api-types.ts` from the running backend's OpenAPI
(WebSocket message shapes are published there too).

## Tests

```bash
cd backend
.venv/Scripts/python -m pytest                     # SQLite
TEST_PG_ADMIN_URL=postgresql://postgres@localhost:5432/postgres .venv/Scripts/python -m pytest   # real Postgres
.venv/Scripts/python scripts/load_test.py --base http://localhost:8080 --password <teacher pw>   # 15 bot teams
```

- `test_scoring.py`: the plan's worked example exactly (2992 / 3100 / 1300), thresholds,
  closest-to-best with ties, golf character rule, error summaries that never echo test input,
  complexity class estimates.
- `test_serialize.py`: for every role and challenge, no hidden tests, reference solution,
  harness or generator reaches teams or the projector.
- `test_judge_client.py`: Judge0 client against a fake Judge0 (batching, compile errors, TLE,
  never finishing, down, 5xx) and the local executor.
- `test_game_flow.py`: a full game over REST + WebSocket (joining, name rules, a
  multiple-choice question that hides the answer until it closes and closes once everyone has
  answered, Run never scores, cooldowns, pause excluded from elapsed time, Super Fast first-three
  places and auto-end, end now, idempotent Next, golf scoring and top-3, benchmarks, override,
  manual points and undo, podium totals, analytics and CSV).
- `test_resilience.py`: backend restart mid-question (timer re-armed, drafts kept), WebSocket
  auth rules and cross-site origin refusal, second device takes over, reissue/rejoin codes,
  Judge0 down then recovering.
- `test_editor.py`: editor round trip, generate outputs, verify, conflict detection, reorder,
  image re-encoding and rejection, zip export/import.
- `scripts/load_test.py`: the plan's load test and pass criteria.
- `scripts/browser_e2e.py`: a whole game in real browsers (Playwright), with screenshots of
  every screen; useful before each rehearsal.

## Event-day runbook

- **Day before:** open the site from a school laptop on school Wi-Fi (WebSockets and the domain
  must not be blocked; ask IT). Have a hotspot as backup. Do two full rehearsals on the real
  computers.
- **T−30 min:** `docker compose … up -d`, check `/api/health` says `"judge": true`,
  `docker compose exec postgres pg_dump -U compsoc compsoc > before.sql`, confirm all three
  questions show **Verified**.
- **As people arrive:** projector lobby up; teams join on their computers and try **Run** on the
  warm-up problem, then **Start game**.
- **Projector:** open it from the console, click **Start presentation** (unlocks sound, goes
  full screen). Console stays on a separate device.
- **If something breaks:** Pause, fix, Resume. Add time with −15 s / +15 s / +1 min / Set
  remaining. Manual points (with a reason, undoable) for disputes. A team that must change
  computer: ⋯ → Reissue, and they type the rejoin code on the new machine.
- **After the podium:** Stats & export → CSV (teams and submissions), `pg_dump` again.

Timing: each multiple-choice question takes about 40 s (4 s intro, up to 20 s to answer, results,
leaderboard), so 12 questions ≈ 8 min. The coding rounds take ~15 min: Super Fast up to 3 (ends
as soon as the 3rd team solves it) · Code Golf 4 + 1 · Best Time Complexity 4 + 1 (includes
~30 s measuring) · podium 1.

## How it works (short)

- **State machine** (`backend/app/engine/game.py`): `lobby → round_intro (4 s) → open ⇄ paused
  → closed → [judging] → results → leaderboard → … → podium → finished`. Each transition is one
  transaction under a per-game lock, then a role-filtered snapshot to every screen.
- **Server-owned clock:** `opened_at`, `deadline`, paused time in Postgres. Clients correct for
  clock offset (ping median) and render `deadline − (now + offset)`. Submissions up to 500 ms
  after the deadline count; elapsed time excludes pauses.
- **Scoring ledger:** leaderboard = `SUM(points)` over `score_events` (automatic, manual, undo).
  One automatic row per team per question, replaced (never accumulated).
- **Multiple choice:** one locked-in answer per team; a correct answer scores
  1000 × (1 − (t / T) / 2), so 500–1000. Nothing is scored (or revealed) until the question closes,
  which happens at the buzzer or as soon as every team has answered.
- **Super Fast:** only the first 3 teams to pass every hidden test score (4,000 · 3,000 · 2,000,
  editable), ordered by when their submission arrived, not when it was judged. The round ends
  (3 s countdown) as soon as the 3rd place is taken; the intro card and problem say so.
- **Judge queue:** 4 workers, Submit always ahead of Run, one in flight per team, cooldowns
  (Run 3 s, Submit 5 s), caps (60 runs / 20 submits per question). Outputs compared in the
  backend after trimming trailing whitespace. Judge0 outages retry and show a banner.
- **Best Time Complexity:** after the buzzer, each team's latest passing submission is run on
  seeded inputs (500 / 2,000 / 8,000 by default) one team at a time, using the judge's own CPU
  time, minus a generator-only baseline, 3 repeats (slow runs aren't repeated). Results are
  checked against the reference solution's output at every size. Ranking uses the time at the
  largest size (anything under the 20 ms floor counts as equal). The class shown is estimated
  from the growth between the two largest sizes; the teacher can override class or points.

## Differences from the plan (deliberate)

- `JUDGE_BACKEND=local` dev executor, so the whole app runs and is tested without Judge0.
- WebSocket `seq` counts per connection (a gap means lost messages on that socket; any gap
  or reconnect triggers a full snapshot).
- A few columns/tables beyond the plan's schema: `runs` log, rejoin codes, projector token,
  cached results, `must_change_password`.
- Multiple choice is built in (the plan had it in Kahoot), so the Kahoot-scores step is gone.
- Super Fast defaults to "first three win" instead of the speed-weighted formula (still available
  per question in the editor).
- A built-in warm-up problem in the lobby (Run only) for the break, per the runbook.
- Next.js pinned to 14.2.35 (earlier 14.2.x releases carry a published security advisory).

## Not verified here

Docker images, the Compose files and Judge0 itself were **not** run: the development machine
had no Docker and Judge0 needs Linux with cgroup v1. The Judge0 client was only tested against
a fake Judge0, and the local executor measures wall time rather than Judge0's CPU time.
First thing to do on the real host: bring the stack up, press **Verify all** on the sample
quiz (this runs the reference solutions and a benchmark on Judge0), then run
`scripts/load_test.py`.
