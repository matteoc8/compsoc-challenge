"""Free Run: every unlocked problem open at once, one clock, pause points, hints, live points."""

import uuid

from app.models import Question

from .conftest import auth, db, join, login_teacher, make_quiz, state, wait_state, wait_until
from .test_game_flow import PAIRS_FAST, PAIRS_SLOW, STAIRS_LONG, STAIRS_SHORT, VOWELS_LOWER_ONLY, VOWELS_OK, judged, question_points, submit


def snapshot(c, path):
    with c.websocket_connect(path) as ws:
        return ws.receive_json()["data"]


def test_free_run(client):
    c = client
    login_teacher(c)
    quiz = make_quiz(c, "multiple_choice", "super_fast", "code_golf", "best_complexity")
    qm, qf, qg, qc = (q["id"] for q in quiz["questions"])
    secrets = [q["reference_solution"].strip() for q in quiz["questions"] if q["reference_solution"].strip()]

    r = c.post("/api/games", json={"quiz_id": quiz["id"], "mode": "free_run", "minutes": 30})
    assert r.status_code == 200 and r.json()["mode"] == "free_run"
    game = r.json()
    gid = game["id"]
    assert c.post("/api/games", json={"quiz_id": quiz["id"], "mode": "free_run", "minutes": 2}).status_code == 422
    alpha, beta = join(c, game["join_code"], "Alpha"), join(c, game["join_code"], "Beta")
    team = lambda t: snapshot(c, f"/ws?role=team&token={t['token']}")  # noqa: E731

    async def add_hints(s):
        q = await s.get(Question, uuid.UUID(qf))
        q.config = {**q.config, "hints": ["Count both cases", "Try str.lower()"]}

    db(c, add_hints)

    # pause point after the 2nd problem: only the first two are open to start with
    assert c.post(f"/api/games/{gid}/breaks", json={"breaks": [1, 99]}).status_code == 200
    assert c.post(f"/api/games/{gid}/start", json={"expect_state": "lobby"}).status_code == 200
    assert state(c, gid) == "open"  # no round intro: straight in
    snap = team(alpha)
    fr = snap["free_run"]
    assert snap["game"]["mode"] == "free_run" and snap["game"]["deadline"]
    assert fr["visible"] == 2 and [p["id"] for p in fr["problems"]] == [qm, qf]
    assert "title" not in fr["questions"][2] and fr["questions"][2]["locked"]
    for s in secrets:
        assert s not in str(snap)
    assert submit(c, alpha["token"], qg, STAIRS_SHORT, expect=409)["detail"].startswith("That problem is locked")

    # multiple choice scores straight away; one answer each
    ans = lambda t, ch: c.post("/api/answers", json={"question_id": qm, "choice": ch}, headers=auth(t["token"]))  # noqa: E731
    assert ans(alpha, 0).status_code == 200 and ans(alpha, 1).status_code == 409
    assert ans(beta, 2).status_code == 200
    assert question_points(c, gid, qm) == {alpha["team_id"]: 1000}

    # Super Fast: places by solve order; partial credit shows up live too
    submit(c, beta["token"], qf, VOWELS_LOWER_ONLY)
    judged(c, gid, beta["team_id"], 1)
    submit(c, alpha["token"], qf, VOWELS_OK)
    judged(c, gid, alpha["team_id"], 1)
    pts = question_points(c, gid, qf)
    assert pts[alpha["team_id"]] > pts[beta["team_id"]] > 0

    # hints in Free Run say which problem
    assert c.post(f"/api/games/{gid}/hints", json={"hint_index": 0}).status_code == 400
    r = c.post(f"/api/games/{gid}/hints", json={"hint_index": 0, "question_id": qf, "team_id": beta["team_id"]})
    assert r.status_code == 200 and r.json() == {"sent": 1}, r.text
    assert team(beta)["free_run"]["hints"] == {qf: [{"index": 0, "number": 1, "text": "Count both cases"}]}
    assert team(alpha)["free_run"]["hints"] == {}
    teacher = snapshot(c, f"/ws?role=teacher&game={gid}")
    assert teacher["free_run"]["questions"][1]["hints"] == ["Count both cases", "Try str.lower()"]
    assert "hints" not in team(alpha)["free_run"]["questions"][1]

    # unlock the rest
    assert c.post(f"/api/games/{gid}/unlock-next").status_code == 200
    assert c.post(f"/api/games/{gid}/unlock-next").status_code == 409  # nothing left
    assert team(alpha)["free_run"]["visible"] == 4
    submit(c, alpha["token"], qg, STAIRS_LONG)
    submit(c, beta["token"], qg, STAIRS_SHORT)
    judged(c, gid, beta["team_id"], 2)
    wait_until(lambda: len(question_points(c, gid, qg)) == 2, 30, what="golf points")
    golf = question_points(c, gid, qg)
    assert golf[beta["team_id"]] > golf[alpha["team_id"]]  # shorter is better, provisional already
    # analyse: the clock stops and every screen shows the problem and the best solution so far
    assert c.post(f"/api/games/{gid}/analyse", json={"question_id": qg}).status_code == 200
    assert state(c, gid) == "paused"
    assert c.post(f"/api/games/{gid}/analyse", json={"question_id": qm}).status_code == 409  # one at a time
    a = team(alpha)["free_run"]["analysis"]
    assert a["question_id"] == qg and a["show"] == "winner" and a["results"]["winner"]["name"] == "Beta"
    assert a["results"]["winner"]["code"] == STAIRS_SHORT and "model_solution" not in a["results"]
    assert c.post(f"/api/games/{gid}/analyse/show", json={"show": "results"}).status_code == 200
    assert "winner" not in team(alpha)["free_run"]["analysis"]["results"]  # only while it's shown
    assert "team_solution" not in team(alpha)["free_run"]["analysis"]["results"]
    # step through each team's own solution
    show_team = lambda tid: c.post(f"/api/games/{gid}/analyse/show", json={"show": "team", "team_id": tid})  # noqa: E731
    assert show_team(alpha["team_id"]).status_code == 200
    a = team(beta)["free_run"]["analysis"]
    assert a["show"] == "team" and a["results"]["team_solution"]["name"] == "Alpha" and a["results"]["team_solution"]["code"] == STAIRS_LONG
    assert show_team(beta["team_id"]).status_code == 200
    assert team(alpha)["free_run"]["analysis"]["results"]["team_solution"]["code"] == STAIRS_SHORT
    assert show_team("00000000-0000-0000-0000-000000000000").status_code == 409
    assert c.post(f"/api/games/{gid}/analyse/show", json={"show": "solution"}).status_code == 200
    golf_ref = next(q for q in quiz["questions"] if q["id"] == qg)["reference_solution"]
    assert team(beta)["free_run"]["analysis"]["results"]["model_solution"] == golf_ref
    # finish and lock: the clock runs again and nobody can submit to it any more
    assert c.post(f"/api/games/{gid}/analyse/end", json={"lock": True}).status_code == 200
    assert state(c, gid) == "open"
    snap = team(alpha)["free_run"]
    assert "analysis" not in snap and snap["questions"][2]["closed"]
    assert golf_ref.strip() not in str(snap)
    assert submit(c, alpha["token"], qg, STAIRS_SHORT, expect=409)["detail"].startswith("This problem was closed")
    # a paused game stays paused; finishing without locking leaves the problem open
    assert c.post(f"/api/games/{gid}/pause").status_code == 200
    assert c.post(f"/api/games/{gid}/analyse", json={"question_id": qm}).status_code == 200
    assert team(alpha)["free_run"]["analysis"]["show"] == "results"  # multiple choice: no code
    assert c.post(f"/api/games/{gid}/analyse/show", json={"show": "winner"}).status_code == 409
    assert c.post(f"/api/games/{gid}/analyse/end", json={"lock": False}).status_code == 200
    assert state(c, gid) == "paused" and not team(alpha)["free_run"]["questions"][0]["closed"]
    assert c.post(f"/api/games/{gid}/resume").status_code == 200

    submit(c, alpha["token"], qc, PAIRS_FAST)
    submit(c, beta["token"], qc, PAIRS_SLOW)
    judged(c, gid, beta["team_id"], 3)
    judged(c, gid, alpha["team_id"], 3)
    wait_until(lambda: len(question_points(c, gid, qc)) == 2, 30, what="provisional complexity points")

    # the projector and console see the grid
    screen = snapshot(c, f"/ws?role=screen&game={gid}&token={game['screen_token']}")
    grid = {r["name"]: r for r in screen["free_run"]["grid"]}
    assert grid["Alpha"]["cells"][qm]["status"] == "correct" and grid["Beta"]["cells"][qm]["status"] == "wrong"
    assert grid["Beta"]["cells"][qf]["status"] == "partial" and grid["Alpha"]["cells"][qg]["status"] == "solved"
    for s in secrets:
        assert s not in str(screen)

    # the clock: more time, then end now → benchmark → leaderboard → podium
    assert c.post(f"/api/games/{gid}/adjust-time", json={"set_remaining_s": 2 * 3600}).status_code == 200
    assert c.post(f"/api/games/{gid}/end-now").status_code == 200
    wait_state(c, gid, "leaderboard", 90)
    final = question_points(c, gid, qc)
    assert final[alpha["team_id"]] > final[beta["team_id"]]  # O(n) beats O(n²) on big inputs
    assert c.post(f"/api/games/{gid}/next", json={"expect_state": "leaderboard"}).status_code == 200
    assert state(c, gid) == "podium"
