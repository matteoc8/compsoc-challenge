"""A complete game (a multiple-choice question + the three coding rounds), driven through
the real REST and WebSocket APIs."""

import json
import time
import uuid

from sqlalchemy import func, select

from app.engine.scoring import timed_points
from app.models import Answer, Game, RunLog, ScoreEvent, Submission
from app.schemas.question import Timed

from .conftest import auth, db, join, login_teacher, make_quiz, new_game, state, wait_state, wait_until

VOWELS_OK = "print(sum(c in 'aeiouAEIOU' for c in input()))"
VOWELS_LOWER_ONLY = "print(sum(c in 'aeiou' for c in input()))"  # 6 / 10 hidden tests
VOWELS_WRONG = "input()\nprint(0)"  # 3 / 10 (below half)
STAIRS_LONG = "n = int(input())\nfor i in range(1, n + 1):\n    print(' ' * (n - i) + '#' * i)\n"
STAIRS_SHORT = "n=int(input())\nfor i in range(n):print(('#'*-~i).rjust(n))"
PAIRS_FAST = "def solve(nums, k):\n    seen = {}\n    c = 0\n    for x in nums:\n        c += seen.get(k - x, 0)\n        seen[x] = seen.get(x, 0) + 1\n    return c\n"
PAIRS_SLOW = "def solve(nums, k):\n    c = 0\n    n = len(nums)\n    for i in range(n):\n        for j in range(i + 1, n):\n            if nums[i] + nums[j] == k:\n                c += 1\n    return c\n"
PAIRS_WRONG = "def solve(nums, k):\n    return 1\n"


def subs_of(c, gid, team_id):
    async def q(s):
        rows = (await s.scalars(select(Submission).where(Submission.game_id == uuid.UUID(gid), Submission.team_id == uuid.UUID(team_id)).order_by(Submission.id))).all()
        return [(r.status.value, r.tests_passed, r.tests_total, r.provisional_points, r.elapsed_ms) for r in rows]

    return db(c, q)


def question_points(c, gid, qid):
    async def q(s):
        rows = (await s.execute(select(ScoreEvent.team_id, ScoreEvent.points).where(ScoreEvent.game_id == uuid.UUID(gid), ScoreEvent.question_id == uuid.UUID(qid), ScoreEvent.reason == "question"))).all()
        return {str(t): p for t, p in rows}

    return db(c, q)


def judged(c, gid, tid, n):
    return wait_until(lambda: (lambda s: len(s) >= n and all(x[0] == "judged" for x in s) and s)(subs_of(c, gid, tid)), 30, what="judging")


def submit(c, token, qid, code, expect=202):
    r = c.post("/api/submissions", json={"question_id": qid, "code": code}, headers=auth(token))
    assert r.status_code == expect, r.text
    return r.json()


def test_full_game(client):
    c = client
    login_teacher(c)
    quiz = make_quiz(c, "multiple_choice", "super_fast", "code_golf", "best_complexity")
    qm, q1, q2, q3 = (q["id"] for q in quiz["questions"])
    secret_strings = [q["reference_solution"].strip() for q in quiz["questions"] if q["reference_solution"].strip()]
    secret_strings.append(quiz["questions"][3]["config"]["harness"].strip())
    game = new_game(c, quiz["id"])
    gid, code = game["id"], game["join_code"]
    assert len(code) == 6 and not set(code) & set("01OI")

    # --- joining and names
    alpha, delta, gamma = (join(c, code, n) for n in ("Alpha", "Delta", "Gamma"))
    assert c.post("/api/join", json={"code": code, "team_name": "alpha"}).status_code == 409  # case-insensitive
    assert c.post("/api/join", json={"code": code, "team_name": "f_u_c_k"}).status_code == 400
    assert c.post("/api/join", json={"code": code, "team_name": "<script>"}).status_code == 400
    assert c.post("/api/join", json={"code": "ZZZZZZ", "team_name": "Nope"}).status_code == 404
    sussex = join(c, code, "Sussex")  # Scunthorpe-safe
    assert c.post(f"/api/games/{gid}/teams/{sussex['team_id']}/kick").status_code == 200
    assert c.get("/api/team/me", headers=auth(sussex["token"])).status_code == 401

    # --- practice Run in the lobby
    with c.websocket_connect(f"/ws?role=team&token={alpha['token']}") as ws:
        snap = ws.receive_json()
        assert snap["type"] == "snapshot" and snap["data"]["game"]["state"] == "lobby"
        assert c.post("/api/runs", json={"question_id": "practice", "code": "a,b=map(int,input().split())\nprint(a+b)"}, headers=auth(alpha["token"])).status_code == 202
        msg = ws.receive_json()
        while msg["type"] != "run.result":
            msg = ws.receive_json()
        assert all(case["passed"] for case in msg["data"]["cases"])

    # --- start (no Kahoot step any more); a double click is harmless
    assert c.post(f"/api/games/{gid}/start", json={"expect_state": "lobby"}).status_code == 200
    assert c.post(f"/api/games/{gid}/start", json={"expect_state": "lobby"}).status_code == 409
    assert state(c, gid) == "round_intro"

    # ================================================================ Multiple choice
    wait_state(c, gid, "open", 8)  # the 4 s intro opens the question by itself
    with c.websocket_connect(f"/ws?role=team&token={gamma['token']}") as ws:
        snap = ws.receive_json()["data"]
        assert snap["question"]["id"] == qm and len(snap["question"]["options"]) == 4
        assert "correct" not in snap["question"] and snap["my_answer"] is None
    with c.websocket_connect(f"/ws?role=screen&game={gid}&token={game['screen_token']}") as ws:
        assert "correct" not in ws.receive_json()["data"]["question"]
    with c.websocket_connect(f"/ws?role=teacher&game={gid}") as ws:
        assert ws.receive_json()["data"]["question"]["correct"] == [0]  # console only
    assert c.post("/api/runs", json={"question_id": qm, "code": "print(1)"}, headers=auth(alpha["token"])).status_code == 409

    def ans(t, choice):
        return c.post("/api/answers", json={"question_id": qm, "choice": choice}, headers=auth(t["token"]))

    assert ans(alpha, 0).status_code == 200  # correct: "Central Processing Unit"
    assert ans(alpha, 1).status_code == 409  # locked in
    assert ans(delta, 9).status_code == 422
    assert ans(delta, 2).status_code == 200  # wrong
    assert question_points(c, gid, qm) == {}  # nothing scored until the question closes
    assert state(c, gid) == "open"
    assert ans(gamma, 0).status_code == 200  # last team answers → closes at once
    wait_state(c, gid, "results", 10)
    pts = question_points(c, gid, qm)
    a_ms = db(c, lambda s: s.scalar(select(Answer.elapsed_ms).where(Answer.team_id == uuid.UUID(alpha["team_id"]))))
    assert pts[alpha["team_id"]] == timed_points(Timed(), a_ms, 20_000) and 500 <= pts[alpha["team_id"]] <= 1000
    assert delta["team_id"] not in pts and gamma["team_id"] in pts
    res = db(c, lambda s: s.get(Game, uuid.UUID(gid))).results[qm]
    assert [o["count"] for o in res["options"]] == [2, 0, 1, 0] and res["options"][0]["correct"]
    c.post(f"/api/games/{gid}/next", json={"expect_state": "results"})
    c.post(f"/api/games/{gid}/next", json={"expect_state": "leaderboard"})

    # ================================================================ Round 1: Super Fast (first three)
    wait_state(c, gid, "open", 8)
    with c.websocket_connect(f"/ws?role=team&token={delta['token']}") as ws:
        snap = ws.receive_json()["data"]
        assert snap["question"]["id"] == q1 and snap["question"]["examples"]
        blob = json.dumps(snap)
        assert not any(sec in blob for sec in secret_strings)

    # Run never creates a submission or points
    assert c.post("/api/runs", json={"question_id": q1, "code": VOWELS_OK}, headers=auth(gamma["token"])).status_code == 202
    assert c.post("/api/runs", json={"question_id": q1, "code": VOWELS_OK}, headers=auth(gamma["token"])).status_code == 429  # in flight / cooldown
    assert c.post("/api/runs", json={"question_id": q1, "code": VOWELS_OK, "stdin": "aaa\n"}, headers=auth(delta["token"])).status_code == 202
    wait_until(lambda: db(c, lambda s: s.scalar(select(func.count()).select_from(RunLog).where(RunLog.status.is_not(None)))) >= 3, 15, what="runs")
    assert subs_of(c, gid, gamma["team_id"]) == []

    submit(c, alpha["token"], q1, VOWELS_LOWER_ONLY)
    submit(c, delta["token"], q1, VOWELS_OK)
    submit(c, gamma["token"], q1, VOWELS_WRONG)
    submit(c, delta["token"], q1, VOWELS_OK, expect=429)  # in flight or cooldown
    submit(c, alpha["token"], q2, VOWELS_OK, expect=409)  # not the open question
    a = judged(c, gid, alpha["team_id"], 1)[0]
    d = judged(c, gid, delta["team_id"], 1)[0]
    g = judged(c, gid, gamma["team_id"], 1)[0]
    assert (a[1], a[2]) == (6, 10) and (d[1], d[2]) == (10, 10) and (g[1], g[2]) == (3, 10)
    # only full passes count, in order: Delta is 1st
    assert a[3] == 0 and d[3] == 4000 and g[3] == 0
    assert question_points(c, gid, q1) == {delta["team_id"]: 4000}

    # pause excludes time; submitting while paused is refused
    assert c.post(f"/api/games/{gid}/pause").status_code == 200
    before = db(c, lambda s: s.get(Game, uuid.UUID(gid)))
    time.sleep(1.2)
    time.sleep(max(0, 5 - 1.2))  # also clears Alpha's 5 s cooldown
    submit(c, alpha["token"], q1, VOWELS_OK, expect=409)
    assert c.post(f"/api/games/{gid}/resume").status_code == 200
    after = db(c, lambda s: s.get(Game, uuid.UUID(gid)))
    assert after.paused_total_ms >= 4900
    assert (after.deadline - before.deadline).total_seconds() >= 4.9
    assert c.post(f"/api/games/{gid}/adjust-time", json={"delta_s": 15}).status_code == 200
    assert c.post(f"/api/games/{gid}/adjust-time", json={"delta_s": 15, "set_remaining_s": 3}).status_code == 422

    # Alpha now solves it: 2nd place
    submit(c, alpha["token"], q1, VOWELS_OK)
    a2 = judged(c, gid, alpha["team_id"], 2)[1]
    assert a2[3] == 3000
    assert question_points(c, gid, q1) == {delta["team_id"]: 4000, alpha["team_id"]: 3000}
    assert state(c, gid) == "open"  # 2 of 3 places taken and Gamma hasn't solved it: still running
    # elapsed excludes the ~5 s pause
    assert a2[4] < (time.time() - after.opened_at.timestamp()) * 1000 - 4500

    # End now: 3 s countdown, then closed → results
    assert c.post(f"/api/games/{gid}/end-now").status_code == 200
    assert c.post(f"/api/games/{gid}/end-now").status_code == 200  # idempotent
    wait_state(c, gid, "results", 15)
    submit(c, gamma["token"], q1, VOWELS_OK, expect=409)
    res = db(c, lambda s: s.get(Game, uuid.UUID(gid))).results[q1]
    assert res["rows"][0]["name"] in ("Alpha", "Delta") and res["solves"][0]["name"] in ("Alpha", "Delta")
    assert [r["name"] for r in res["rows"]][-1] == "Gamma"

    # navigation is idempotent with expect_state
    assert c.post(f"/api/games/{gid}/next", json={"expect_state": "results"}).status_code == 200
    assert c.post(f"/api/games/{gid}/next", json={"expect_state": "results"}).status_code == 409
    assert state(c, gid) == "leaderboard"
    assert c.post(f"/api/games/{gid}/next", json={"expect_state": "leaderboard"}).status_code == 200
    assert state(c, gid) == "round_intro"
    assert c.post(f"/api/games/{gid}/next", json={"expect_state": "round_intro"}).status_code == 200  # skip intro
    assert state(c, gid) == "open"

    # ================================================================ Round 2: Code Golf
    submit(c, alpha["token"], q2, STAIRS_LONG)
    submit(c, delta["token"], q2, STAIRS_SHORT)
    submit(c, gamma["token"], q2, "print('#')")
    judged(c, gid, alpha["team_id"], 3)
    judged(c, gid, delta["team_id"], 2)
    judged(c, gid, gamma["team_id"], 2)
    assert question_points(c, gid, q2) == {}  # golf is scored at close
    c.post(f"/api/games/{gid}/end-now")
    wait_state(c, gid, "results", 15)
    pts = question_points(c, gid, q2)
    long_len, short_len = len(STAIRS_LONG.rstrip()), len(STAIRS_SHORT)
    assert pts[delta["team_id"]] == 4000
    assert pts[alpha["team_id"]] == round(4000 * (0.5 + 0.5 * short_len / long_len))
    assert gamma["team_id"] not in pts
    res = db(c, lambda s: s.get(Game, uuid.UUID(gid))).results[q2]
    assert res["top3"][0]["name"] == "Delta" and res["top3"][0]["code"] == STAIRS_SHORT and len(res["top3"]) == 2

    c.post(f"/api/games/{gid}/next", json={"expect_state": "results"})
    c.post(f"/api/games/{gid}/next", json={"expect_state": "leaderboard"})
    wait_state(c, gid, "open", 8)

    # ================================================================ Round 3: Best Time Complexity
    submit(c, alpha["token"], q3, PAIRS_FAST)
    submit(c, delta["token"], q3, PAIRS_SLOW)
    submit(c, gamma["token"], q3, PAIRS_WRONG)
    assert judged(c, gid, alpha["team_id"], 4)[3][1:3] == (10, 10)
    assert judged(c, gid, delta["team_id"], 3)[2][1:3] == (10, 10)
    judged(c, gid, gamma["team_id"], 3)
    c.post(f"/api/games/{gid}/end-now")
    wait_state(c, gid, "judging", 15)
    wait_state(c, gid, "results", 120)
    res = db(c, lambda s: s.get(Game, uuid.UUID(gid))).results[q3]
    teams = res["bench"]["teams"]
    assert set(teams) == {alpha["team_id"], delta["team_id"]}
    assert teams[alpha["team_id"]]["class_label"].startswith("≈ O(n)")
    assert "n²" in teams[delta["team_id"]]["class_label"] or teams[delta["team_id"]]["timed_out_at"]
    pts = question_points(c, gid, q3)
    assert pts[alpha["team_id"]] == 4000 and 2000 <= pts[delta["team_id"]] < 3000
    # teacher override before moving on
    r = c.post(f"/api/games/{gid}/results/override", json={"team_id": delta["team_id"], "class_label": "O(n²) (checked)", "points": 2500})
    assert r.status_code == 200, r.text
    assert question_points(c, gid, q3)[delta["team_id"]] == 2500
    res = db(c, lambda s: s.get(Game, uuid.UUID(gid))).results[q3]
    assert next(x for x in res["rows"] if x["team_id"] == delta["team_id"])["class_label"] == "O(n²) (checked)"

    # ================================================================ manual points
    r = c.post(f"/api/games/{gid}/teams/{gamma['team_id']}/points", json={"points": 500, "note": "cleanest code"})
    assert r.status_code == 200
    assert c.post(f"/api/games/{gid}/teams/{gamma['team_id']}/points", json={"points": -100_000}).status_code == 400  # no negatives
    ev = db(c, lambda s: s.scalar(select(ScoreEvent).where(ScoreEvent.reason == "manual")))
    assert c.post(f"/api/games/{gid}/score-events/{ev.id}/undo").status_code == 200
    assert c.post(f"/api/games/{gid}/score-events/{ev.id}/undo").status_code == 409

    # ================================================================ finish
    c.post(f"/api/games/{gid}/next", json={"expect_state": "results"})
    c.post(f"/api/games/{gid}/next", json={"expect_state": "leaderboard"})
    assert state(c, gid) == "podium"
    with c.websocket_connect(f"/ws?role=screen&game={gid}&token={game['screen_token']}") as ws:
        snap = ws.receive_json()["data"]
        podium = snap["podium"]
        totals = {r["name"]: r["points"] for r in podium}
        expected_alpha = sum(question_points(c, gid, q).get(alpha["team_id"], 0) for q in (qm, q1, q2, q3))
        assert totals["Alpha"] == expected_alpha
        assert totals["Gamma"] == question_points(c, gid, qm)[gamma["team_id"]]  # only its quiz answer
        assert podium[0]["rank"] == 1 and "Sussex" not in totals
    c.post(f"/api/games/{gid}/next", json={"expect_state": "podium"})
    assert state(c, gid) == "finished"
    assert c.post("/api/join", json={"code": code, "team_name": "Latecomers"}).status_code == 404

    stats = c.get(f"/api/games/{gid}/analytics").json()
    assert stats["best_golfer"]["team"] == "Delta" and stats["most_efficient"]["team"] == "Alpha"
    csv_teams = c.get(f"/api/games/{gid}/analytics.csv?kind=teams")
    assert csv_teams.status_code == 200 and "Alpha" in csv_teams.text and "Round 1: Super Fast: points" in csv_teams.text
    csv_subs = c.get(f"/api/games/{gid}/analytics.csv?kind=submissions")
    assert "solve(nums, k)" in csv_subs.text


def test_super_fast_first_three_then_ends(client):
    """Only the first three full solves score (by when they were sent), and the round ends
    as soon as the third team gets it; a fourth solve during the 3 s countdown scores 0."""
    c = client
    login_teacher(c)
    quiz = make_quiz(c, "super_fast")
    qid = quiz["questions"][0]["id"]
    game = new_game(c, quiz["id"])
    gid = game["id"]
    teams = [join(c, game["join_code"], n) for n in ("One", "Two", "Three", "Four", "Five")]
    c.post(f"/api/games/{gid}/start", json={})
    c.post(f"/api/games/{gid}/next", json={"expect_state": "round_intro"})
    rule = quiz["questions"][0]["scoring"]
    assert rule == {"mode": "ranked", "points": [4000, 3000, 2000]}
    with c.websocket_connect(f"/ws?role=team&token={teams[0]['token']}") as ws:
        intro = ws.receive_json()["data"]["question"]["rule_line"]
    assert "first 3 teams" in intro and "3rd team" in intro

    submit(c, teams[4]["token"], qid, VOWELS_LOWER_ONLY)  # partial: never scores now
    for i, t in enumerate(teams[:3]):
        submit(c, t["token"], qid, VOWELS_OK)
        judged(c, gid, t["team_id"], 1)
        if i < 2:
            assert state(c, gid) == "open"
    # third solve starts the 3 s "Ending…" countdown; a fourth solve still gets judged but scores 0
    assert db(c, lambda s: s.get(Game, uuid.UUID(gid))).ending
    submit(c, teams[3]["token"], qid, VOWELS_OK)
    judged(c, gid, teams[3]["team_id"], 1)
    wait_state(c, gid, "results", 15)
    assert question_points(c, gid, qid) == {teams[0]["team_id"]: 4000, teams[1]["team_id"]: 3000, teams[2]["team_id"]: 2000}
    res = db(c, lambda s: s.get(Game, uuid.UUID(gid))).results[qid]
    assert [s["name"] for s in res["solves"]][:3] == ["One", "Two", "Three"]


def test_skip_measuring_keeps_measured_teams_and_allows_overrides(client):
    c = client
    login_teacher(c)
    quiz = make_quiz(c, "best_complexity")
    [q] = (x["id"] for x in quiz["questions"])
    game = new_game(c, quiz["id"])
    gid = game["id"]
    fast, slow = join(c, game["join_code"], "Fast"), join(c, game["join_code"], "Slow")
    assert c.post(f"/api/games/{gid}/skip-measuring").status_code == 409  # nothing to skip in the lobby
    c.post(f"/api/games/{gid}/start", json={"expect_state": "lobby"})
    c.post(f"/api/games/{gid}/next", json={"expect_state": "round_intro"})
    wait_state(c, gid, "open", 8)
    submit(c, fast["token"], q, PAIRS_FAST)
    judged(c, gid, fast["team_id"], 1)
    submit(c, slow["token"], q, PAIRS_SLOW)
    judged(c, gid, slow["team_id"], 1)
    c.post(f"/api/games/{gid}/end-now")
    wait_state(c, gid, "judging", 15)

    def fast_measured(s):
        async def q_(s):
            return (await s.scalar(select(Submission).where(Submission.team_id == uuid.UUID(fast["team_id"])))).perf

        return q_(s)

    wait_until(lambda: db(c, fast_measured), 60, what="first team measured")
    r = c.post(f"/api/games/{gid}/skip-measuring")
    assert r.status_code == 200, r.text
    assert state(c, gid) == "results"
    teams = db(c, lambda s: s.get(Game, uuid.UUID(gid))).results[q]["bench"]["teams"]
    assert teams[fast["team_id"]]["class_label"].startswith("≈ O(n)")
    assert teams[slow["team_id"]]["class_label"] == "not measured (skipped)"
    pts = question_points(c, gid, q)
    assert pts[fast["team_id"]] == 4000
    r = c.post(f"/api/games/{gid}/results/override", json={"team_id": slow["team_id"], "points": 2500})
    assert r.status_code == 200, r.text
    assert question_points(c, gid, q)[slow["team_id"]] == 2500
    assert c.post(f"/api/games/{gid}/skip-measuring").status_code == 409
