"""Unlimited-time questions, the public problem submission queue and featured problems."""

import time
import uuid

from app.models import Game

from .conftest import db, join, login_teacher, make_quiz, new_game, state, wait_state

EDITABLE = (
    "round_name", "type", "title", "description_md", "image_media_id", "image_alt", "starter_code",
    "reference_solution", "config", "time_limit_s", "unlimited_time", "auto_end", "scoring",
)


def set_unlimited(c, q: dict) -> dict:
    body = {k: q[k] for k in EDITABLE} | {"unlimited_time": True}
    r = c.put(f"/api/questions/{q['id']}", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def test_unlimited_time_runs_until_the_teacher_ends_it(client):
    c = client
    login_teacher(c)
    quiz = make_quiz(c, "code_golf")
    q = set_unlimited(c, quiz["questions"][0])
    assert q["unlimited_time"] and q["verified_at"]  # the clock isn't judged: still verified
    game = new_game(c, quiz["id"])
    gid = game["id"]
    team = join(c, game["join_code"], "Alpha")
    c.post(f"/api/games/{gid}/start", json={"expect_state": "lobby"})
    c.post(f"/api/games/{gid}/next", json={"expect_state": "round_intro"})
    assert state(c, gid) == "open"
    assert db(c, lambda s: s.get(Game, uuid.UUID(gid))).deadline is None

    with c.websocket_connect(f"/ws?role=team&token={team['token']}") as ws:
        snap = ws.receive_json()["data"]
    assert snap["game"]["unlimited"] and snap["game"]["deadline"] is None and snap["game"]["remaining_ms"] is None
    assert "No time limit" in snap["question"]["rule_line"] and snap["question"]["unlimited_time"]

    # time adjustments need a countdown; pause/resume still work and the clock keeps counting up
    assert c.post(f"/api/games/{gid}/adjust-time", json={"delta_s": 15}).status_code == 409
    assert c.post(f"/api/games/{gid}/pause").status_code == 200
    assert c.post(f"/api/games/{gid}/resume").status_code == 200
    time.sleep(1.2)
    assert state(c, gid) == "open"
    with c.websocket_connect(f"/ws?role=team&token={team['token']}") as ws:
        assert ws.receive_json()["data"]["game"]["elapsed_ms"] >= 1000

    # the teacher ends it: the usual 3 s countdown, then results
    assert c.post(f"/api/games/{gid}/end-now").status_code == 200
    assert db(c, lambda s: s.get(Game, uuid.UUID(gid))).deadline is not None
    wait_state(c, gid, "results", 15)


def test_unlimited_time_can_switch_to_a_countdown(client):
    c = client
    login_teacher(c)
    quiz = make_quiz(c, "multiple_choice")
    set_unlimited(c, quiz["questions"][0])
    game = new_game(c, quiz["id"])
    gid = game["id"]
    c.post(f"/api/games/{gid}/start", json={"expect_state": "lobby", "force": True})
    c.post(f"/api/games/{gid}/next", json={"expect_state": "round_intro"})
    assert c.post(f"/api/games/{gid}/adjust-time", json={"set_remaining_s": 2}).status_code == 200
    wait_state(c, gid, "results", 15)


def test_problem_submission_queue(client):
    c = client
    problem = {
        "author_name": "Sam",
        "email": "Sam@School.example",
        "title": "Reverse words",
        "description_md": "Print the words of the line in reverse order.",
        "examples": [{"stdin": "a b c", "expected": "c b a"}],
        "solution": "print(' '.join(input().split()[::-1]))",
    }
    # anyone can submit; validation and the bot trap
    assert c.post("/api/problems/submit", json=problem).status_code == 200
    assert c.post("/api/problems/submit", json={**problem, "title": ""}).status_code == 422
    assert c.post("/api/problems/submit", json={**problem, "email": "not-an-email"}).status_code == 422
    assert c.post("/api/problems/submit", json={k: v for k, v in problem.items() if k != "email"}).status_code == 422
    assert c.post("/api/problems/submit", json={**problem, "website": "spam.example"}).status_code == 200  # dropped
    # only teachers see the queue
    assert c.get("/api/problem-submissions").status_code == 401
    login_teacher(c)
    queue = c.get("/api/problem-submissions?status=pending").json()
    assert queue["counts"] == {"pending": 1, "accepted": 0, "rejected": 0}
    [item] = queue["items"]
    assert item["title"] == "Reverse words" and item["solution"] == problem["solution"]
    assert item["email"] == "sam@school.example" and item["emailed_at"] is None

    r = c.put(f"/api/problem-submissions/{item['id']}", json={"status": "rejected", "teacher_note": "duplicate"})
    assert r.status_code == 200 and r.json()["reviewed_at"]
    assert c.get("/api/problem-submissions").json()["counts"]["rejected"] == 1

    # add it to a quiz as a coding question
    quiz = make_quiz(c, "multiple_choice", verify=False)
    r = c.post(f"/api/problem-submissions/{item['id']}/to-quiz", json={"quiz_id": quiz["id"]})
    assert r.status_code == 200, r.text
    full = c.get(f"/api/quizzes/{quiz['id']}").json()
    added = full["questions"][-1]
    assert added["type"] == "super_fast" and added["title"] == "Reverse words" and not added["verified_at"]
    assert added["config"]["examples"] == problem["examples"] and added["reference_solution"] == problem["solution"]
    assert c.post(f"/api/problem-submissions/{item['id']}/to-quiz", json={"quiz_id": quiz["id"], "type": "multiple_choice"}).status_code == 400

    assert c.delete(f"/api/problem-submissions/{item['id']}").status_code == 200
    assert c.get("/api/problem-submissions").json()["items"] == []


def test_featured_problems(client):
    c = client
    assert c.post("/api/featured", json={"title": "x"}).status_code == 401
    login_teacher(c)
    c.post("/api/problems/submit", json={"author_name": "Ana", "email": "ana@school.example", "title": "Two sum", "description_md": "Find two numbers that add up to k.", "solution": "SECRET-SOLUTION"})
    sub = c.get("/api/problem-submissions").json()["items"][0]
    draft = c.post(f"/api/problem-submissions/{sub['id']}/feature").json()
    assert draft["published"] is False and draft["credit"] == "Submitted by Ana" and draft["solution_code"] == "SECRET-SOLUTION"
    assert c.get("/api/problem-submissions").json()["counts"]["accepted"] == 1

    # drafts are invisible to the public
    c.cookies.clear()
    assert c.get("/api/problems").json() == []
    assert c.get(f"/api/problems/{draft['id']}").status_code == 404
    assert c.get(f"/api/problems/{draft['id']}/solution").status_code == 404

    login_teacher(c, password="correct-horse-battery")
    body = {k: draft[k] for k in ("title", "difficulty", "description_md", "examples", "solution_code", "credit")}
    r = c.put(f"/api/featured/{draft['id']}", json={**body, "solution_md": "Use a set.", "difficulty": "easy", "published": True})
    assert r.status_code == 200, r.text
    assert c.put(f"/api/featured/{draft['id']}", json={**body, "difficulty": "impossible"}).status_code == 422

    # public: the problem page never carries the solution; it's a separate request
    c.cookies.clear()
    [listed] = c.get("/api/problems").json()
    assert listed["title"] == "Two sum" and listed["difficulty"] == "easy"
    page = c.get(f"/api/problems/{draft['id']}")
    assert page.status_code == 200 and page.json()["has_solution"] and "SECRET-SOLUTION" not in page.text
    assert c.get(f"/api/problems/{draft['id']}/solution").json() == {"solution_code": "SECRET-SOLUTION", "solution_md": "Use a set."}
    assert c.get("/api/problems/not-a-uuid").status_code == 404

    # a quiz's coding question can be featured too (multiple choice can't)
    login_teacher(c, password="correct-horse-battery")
    quiz = make_quiz(c, "multiple_choice", "code_golf", verify=False)
    mcq, golf = quiz["questions"]
    assert c.post(f"/api/questions/{mcq['id']}/feature").status_code == 400
    f = c.post(f"/api/questions/{golf['id']}/feature").json()
    assert f["title"] == golf["title"] and f["solution_code"] == golf["reference_solution"] and not f["published"]
    assert len(c.get("/api/featured").json()) == 2
    assert c.delete(f"/api/featured/{f['id']}").status_code == 200


def test_problem_groups(client):
    c = client
    assert c.post("/api/featured-groups", json={"name": "x"}).status_code == 401
    login_teacher(c)
    a = c.post("/api/featured-groups", json={"name": "CompSoc 10/12", "description": "From the Challenge"}).json()
    b = c.post("/api/featured-groups", json={"name": "Weekly Challenges"}).json()
    assert (a["position"], b["position"]) == (0, 1)
    assert c.post("/api/featured-groups", json={"name": ""}).status_code == 422

    # a whole quiz's coding questions go into a group in one go; multiple choice is skipped
    quiz = make_quiz(c, "multiple_choice", "code_golf", "super_fast", verify=False)
    assert c.post(f"/api/quizzes/{quiz['id']}/feature", json={"group_id": a["id"], "published": True}).json() == {"created": 2}
    single = c.post(f"/api/questions/{quiz['questions'][1]['id']}/feature", json={"group_id": b["id"]}).json()
    assert single["group_id"] == b["id"] and not single["published"]
    assert c.post(f"/api/questions/{quiz['questions'][1]['id']}/feature", json={"group_id": str(uuid.uuid4())}).status_code == 404

    # moving a problem between groups goes through the normal edit
    body = {k: single[k] for k in ("title", "difficulty", "description_md", "examples", "solution_code", "credit")}
    assert c.put(f"/api/featured/{single['id']}", json={**body, "group_id": a["id"], "published": True}).json()["group_id"] == a["id"]

    assert [g["name"] for g in c.put("/api/featured-groups/order", json={"group_ids": [b["id"], a["id"]]}).json()] == ["Weekly Challenges", "CompSoc 10/12"]
    assert c.put("/api/featured-groups/order", json={"group_ids": [a["id"]]}).status_code == 400
    assert c.put(f"/api/featured-groups/{a['id']}", json={"name": "CompSoc 10 Dec"}).json()["name"] == "CompSoc 10 Dec"

    c.cookies.clear()
    assert [g["name"] for g in c.get("/api/problems/groups").json()] == ["Weekly Challenges", "CompSoc 10 Dec"]
    listed = c.get("/api/problems").json()
    assert len(listed) == 3 and {p["group_id"] for p in listed} == {a["id"]}

    # deleting a group keeps its problems, ungrouped
    login_teacher(c, password="correct-horse-battery")
    assert c.delete(f"/api/featured-groups/{a['id']}").status_code == 200
    assert {p["group_id"] for p in c.get("/api/featured").json()} == {None}


def test_submitted_problem_use(client):
    c = client
    base = {"author_name": "Ana", "email": "ana@school.example", "title": "Two sum", "description_md": "Find two numbers that add up to k."}
    assert c.post("/api/problems/submit", json={**base, "intended_use": "weekly"}).status_code == 200
    assert c.post("/api/problems/submit", json=base).status_code == 200  # defaults to either
    assert c.post("/api/problems/submit", json={**base, "intended_use": "homework"}).status_code == 422
    login_teacher(c)
    assert [x["intended_use"] for x in c.get("/api/problem-submissions").json()["items"]] == ["weekly", "either"]
