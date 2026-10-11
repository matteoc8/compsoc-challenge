"""Teacher tools during a game (hints, seeing a team's code and tests, showing the winning
and model solutions), replying to submitted problems by email, and problem of the week."""

import uuid
from datetime import datetime, timedelta, timezone

from app import mailer
from app.config import get_settings
from app.models import Game

from .conftest import db, join, login_teacher, make_quiz, new_game, wait_state, wait_until
from .test_game_flow import PAIRS_FAST, PAIRS_SLOW, STAIRS_LONG, STAIRS_SHORT, judged, submit
from .test_site_sections import EDITABLE

HINTS = ["Use str.rjust.", "Try range(n) and -~i."]


def team_snapshot(c, token):
    with c.websocket_connect(f"/ws?role=team&token={token}") as ws:
        return ws.receive_json()["data"]


def test_hints_team_work_and_spotlight(client):
    c = client
    login_teacher(c)
    quiz = make_quiz(c, "code_golf")
    q = quiz["questions"][0]
    r = c.put(f"/api/questions/{q['id']}", json={k: q[k] for k in EDITABLE if k != "unlimited_time"} | {"config": {**q["config"], "hints": HINTS}})
    assert r.status_code == 200 and r.json()["verified_at"], "adding hints must not un-verify the question"
    game = new_game(c, quiz["id"])
    gid = game["id"]
    alpha, beta = join(c, game["join_code"], "Alpha"), join(c, game["join_code"], "Beta")
    assert c.post(f"/api/games/{gid}/hints", json={"hint_index": 0, "team_id": alpha["team_id"]}).status_code == 409  # lobby
    c.post(f"/api/games/{gid}/start", json={"expect_state": "lobby"})
    c.post(f"/api/games/{gid}/next", json={"expect_state": "round_intro"})

    # --- hints: one team, then everyone; never in the team's copy of the question
    assert c.post(f"/api/games/{gid}/hints", json={"hint_index": 0, "team_id": alpha["team_id"]}).json() == {"sent": 1}
    assert c.post(f"/api/games/{gid}/hints", json={"hint_index": 0, "team_id": alpha["team_id"]}).json() == {"sent": 0}  # already had it
    assert c.post(f"/api/games/{gid}/hints", json={"hint_index": 5}).status_code == 400
    snap_a, snap_b = team_snapshot(c, alpha["token"]), team_snapshot(c, beta["token"])
    assert snap_a["my_hints"] == [{"index": 0, "number": 1, "text": HINTS[0]}] and snap_b["my_hints"] == []
    assert "hints" not in snap_a["question"] and HINTS[1] not in str(snap_a)
    assert c.post(f"/api/games/{gid}/hints", json={"hint_index": 1}).json() == {"sent": 2}
    assert [h["number"] for h in team_snapshot(c, alpha["token"])["my_hints"]] == [1, 2]

    # --- the teacher sees each team's code and every hidden test
    submit(c, alpha["token"], q["id"], STAIRS_SHORT)
    submit(c, beta["token"], q["id"], "print('#')")
    judged(c, gid, alpha["team_id"], 1)
    judged(c, gid, beta["team_id"], 1)
    c.put(f"/api/drafts/{q['id']}", json={"code": "n=int(input())  # still golfing"}, headers={"Authorization": f"Bearer {beta['token']}"})
    work = c.get(f"/api/games/{gid}/teams/{beta['team_id']}/work").json()
    assert work["draft"]["code"].endswith("still golfing")
    [sub] = work["submissions"]
    assert sub["code"] == "print('#')" and len(sub["tests"]) == 10 and 0 < sub["passed"] < 10
    failing = next(t for t in sub["tests"] if not t["passed"])
    assert failing["stdin"] and failing["expected"] and failing["stdout"].strip() == "#" and failing["status"] == "Wrong Answer"
    assert c.get(f"/api/games/{gid}/teams/{uuid.uuid4()}/work").status_code == 404
    c.cookies.clear()
    assert c.get(f"/api/games/{gid}/teams/{beta['team_id']}/work").status_code == 401
    login_teacher(c, password="correct-horse-battery")

    # --- after the buzzer: the winning solution, then the model solution, on every screen
    assert c.post(f"/api/games/{gid}/spotlight", json={"show": "winner"}).status_code == 409  # not at results yet
    c.post(f"/api/games/{gid}/end-now")
    wait_state(c, gid, "results", 15)
    assert c.post(f"/api/games/{gid}/hints", json={"hint_index": 0}).status_code == 409
    assert c.post(f"/api/games/{gid}/spotlight", json={"show": "winner"}).status_code == 200
    res = team_snapshot(c, beta["token"])["results"]
    assert res["spotlight"] == "winner" and res["winner"]["name"] == "Alpha" and res["winner"]["code"] == STAIRS_SHORT
    assert "model_solution" not in res
    assert c.post(f"/api/games/{gid}/spotlight", json={"show": "solution"}).status_code == 200
    res = team_snapshot(c, beta["token"])["results"]
    assert res["spotlight"] == "solution" and res["model_solution"] == q["reference_solution"] and res["winner"]
    # a rescore keeps what was revealed
    assert c.post(f"/api/games/{gid}/questions/{q['id']}/rescore").status_code == 200
    res = db(c, lambda s: s.get(Game, uuid.UUID(gid))).results[q["id"]]
    assert res["model_solution"] and res["winner"]["name"] == "Alpha"
    assert c.post(f"/api/games/{gid}/spotlight", json={"show": "results"}).status_code == 200
    assert c.post(f"/api/games/{gid}/spotlight", json={"show": "nope"}).status_code == 400


def test_email_reply_to_submitter(client, monkeypatch):
    c = client
    c.post("/api/problems/submit", json={"author_name": "Sam", "email": "sam@school.example", "title": "Reverse words", "description_md": "Reverse the words on the line."})
    login_teacher(c)
    sid = c.get("/api/problem-submissions").json()["items"][0]["id"]
    msg = {"subject": "Your problem", "body": "Accepted, thanks!"}

    # not set up: the console falls back to the teacher's own mail app
    assert c.get("/api/email/status").json() == {"configured": False, "from": None}
    assert c.post(f"/api/problem-submissions/{sid}/email", json=msg).status_code == 503
    assert c.post(f"/api/problem-submissions/{sid}/emailed").json()["emailed_at"]

    sent = []
    monkeypatch.setenv("SMTP_HOST", "smtp.example")
    monkeypatch.setenv("SMTP_USERNAME", "teacher@school.example")
    get_settings.cache_clear()
    monkeypatch.setattr(mailer, "_send_sync", lambda to, subject, body: sent.append((to, subject, body)))
    assert c.get("/api/email/status").json() == {"configured": True, "from": "teacher@school.example"}
    r = c.post(f"/api/problem-submissions/{sid}/email", json=msg)
    assert r.status_code == 200, r.text
    assert sent == [("sam@school.example", "Your problem", "Accepted, thanks!")]

    def refuse(*_):
        raise mailer.MailError("The email server refused the login.")

    monkeypatch.setattr(mailer, "_send_sync", refuse)
    r = c.post(f"/api/problem-submissions/{sid}/email", json=msg)
    assert r.status_code == 503 and "refused" in r.json()["detail"]


def iso(dt: datetime) -> str:
    return dt.isoformat()


def wait_mine(c, wid, email, n):
    def done():
        r = c.get(f"/api/weekly/{wid}/mine", params={"email": email}).json()
        subs = r["submissions"]
        return len(subs) >= n and all(x["status"] in ("judged", "error") for x in subs) and r

    try:
        return wait_until(done, 60, what="weekly judging")
    except AssertionError:
        print("DEBUG", c.get(f"/api/weekly/{wid}/mine", params={"email": email}).json())
        raise


def test_problem_of_the_week(client):
    c = client
    login_teacher(c)
    quiz = make_quiz(c, "code_golf", "best_complexity", "multiple_choice", "super_fast")
    golf, cx, mcq, fast = quiz["questions"]
    unverified = make_quiz(c, "code_golf", verify=False)["questions"][0]
    now = datetime.now(timezone.utc)
    week = {"question_id": golf["id"], "opens_at": iso(now - timedelta(hours=1)), "closes_at": iso(now + timedelta(days=6)), "published": True, "credit": " Submitted by Sam Smith "}
    assert c.post("/api/weekly-admin", json={**week, "question_id": mcq["id"]}).status_code == 400
    assert c.post("/api/weekly-admin", json={**week, "question_id": fast["id"]}).status_code == 400  # no Super Fast weeks
    assert c.post("/api/weekly-admin", json={**week, "question_id": unverified["id"]}).status_code == 400
    assert c.post("/api/weekly-admin", json={**week, "closes_at": iso(now - timedelta(days=1))}).status_code == 422
    eligible = {q["id"] for q in c.get("/api/weekly-admin/questions").json()}
    assert golf["id"] in eligible and cx["id"] in eligible and mcq["id"] not in eligible and fast["id"] not in eligible
    w = c.post("/api/weekly-admin", json=week).json()
    wid = w["id"]
    assert w["phase"] == "open"
    assert c.delete(f"/api/questions/{golf['id']}").status_code == 409  # in use

    # --- public: anyone, no login
    c.cookies.clear()
    idx = c.get("/api/weekly").json()
    assert idx["current"]["id"] == wid
    detail = c.get(f"/api/weekly/{wid}").json()
    assert detail["question"]["examples"] and "tests" not in detail["question"] and "solution" not in detail
    assert golf["reference_solution"].strip() not in str(detail)
    ran = c.post(f"/api/weekly/{wid}/run", json={"code": STAIRS_SHORT}).json()
    assert ran["cases"] and all(x["passed"] for x in ran["cases"])

    people = [("Ada Lovelace", "ada@school.example", STAIRS_SHORT, "5"), ("Bob Smith", "BOB@school.example", STAIRS_LONG, "L8"), ("Cy Young", "cy@school.example", "print('#')", "U8")]
    assert c.post(f"/api/weekly/{wid}/submit", json={"name": "Ada Lovelace", "email": "ada@school.example", "code": "x"}).status_code == 422  # no year group yet
    assert c.post(f"/api/weekly/{wid}/submit", json={"name": "Ada Lovelace", "email": "ada@school.example", "year_group": "7", "code": "x"}).status_code == 422
    assert c.post(f"/api/weekly/{wid}/submit", json={"name": "Ada Lovelace", "email": "nope", "code": "x"}).status_code == 422
    for name, email, code, year in people:
        r = c.post(f"/api/weekly/{wid}/submit", json={"name": name, "email": email, "year_group": year, "code": code})
        assert r.status_code == 202, r.text
    assert c.post(f"/api/weekly/{wid}/submit", json={"name": "Ada Lovelace", "email": "ada@school.example", "code": STAIRS_SHORT}).status_code == 429
    # the email has to be at the school, the name has to be a full name, and it sticks to the email
    assert c.post("/api/weekly/sign-in", json={"name": "Ada Lovelace", "email": "ada@gmail.com"}).status_code == 422
    assert c.post("/api/weekly/sign-in", json={"name": "Ada", "email": "ada@school.example"}).status_code == 422
    assert c.post("/api/weekly/sign-in", json={"name": "ada  lovelace", "email": "ADA@school.example"}).json() == {"name": "Ada Lovelace", "email": "ada@school.example", "year_group": "5"}
    r = c.post("/api/weekly/sign-in", json={"name": "Not Ada", "email": "ada@school.example"})
    assert r.status_code == 409 and "Email carriem@stpaulsschool.org.uk" in r.json()["detail"]
    assert c.post(f"/api/weekly/{wid}/submit", json={"name": "Not Ada", "email": "ada@school.example", "code": STAIRS_SHORT}).status_code == 409
    assert c.post("/api/weekly/sign-in", json={"name": "Dee Dee", "email": "dee@year9.school.example", "year_group": "4"}).status_code == 422  # no subdomains
    assert c.post("/api/weekly/sign-in", json={"name": "Dee Dee", "email": "dee@school.example", "year_group": "4"}).status_code == 200
    for _, email, _, _ in people:
        wait_mine(c, wid, email, 1)
    mine = c.get(f"/api/weekly/{wid}/mine", params={"email": "bob@school.example"}).json()
    assert mine["standing"]["rank"] == 2 and mine["submissions"][0]["passed"] == 10

    board = c.get(f"/api/weekly/{wid}").json()["standings"]
    assert [r["name"] for r in board] == ["Ada Lovelace", "Bob Smith", "Cy Young"]
    assert board[0]["points"] == 1000 and board[1]["points"] > board[2]["points"] > 0  # Cy: partial credit
    assert "@" not in str(board)

    # --- a second week (Best Time Complexity, measured at scale) adds to the school board
    c.cookies.clear()
    login_teacher(c, password="correct-horse-battery")
    w2 = c.post("/api/weekly-admin", json={**week, "question_id": cx["id"]}).json()["id"]
    c.cookies.clear()
    c.post(f"/api/weekly/{w2}/submit", json={"name": "Bob Smith", "email": "bob@school.example", "code": PAIRS_FAST})
    c.post(f"/api/weekly/{w2}/submit", json={"name": "Ada Lovelace", "email": "ada@school.example", "code": PAIRS_SLOW})
    for email in ("bob@school.example", "ada@school.example"):
        wait_mine(c, w2, email, 1)
    b2 = c.get(f"/api/weekly/{w2}").json()["standings"]
    assert b2[0]["name"] == "Bob Smith" and b2[0]["class_label"] and b2[0]["points"] == 1000
    school = c.get("/api/weekly/leaderboard").json()
    totals = {r["name"]: r for r in school["rows"]}
    assert school["weeks"] == 2 and totals["Ada Lovelace"]["weeks"] == 2 and totals["Ada Lovelace"]["wins"] == 1 and totals["Bob Smith"]["wins"] == 1
    assert totals["Ada Lovelace"]["points"] == board[0]["points"] + next(r["points"] for r in b2 if r["name"] == "Ada Lovelace")
    assert "@" not in str(school)
    for period in ("week", "month", "year"):  # both weeks are open now
        assert c.get("/api/weekly/leaderboard", params={"period": period}).json()["rows"] == school["rows"]
    assert c.get("/api/weekly/leaderboard", params={"period": "decade"}).status_code == 422
    names = lambda **kw: [r["name"] for r in c.get("/api/weekly/leaderboard", params=kw).json()["rows"]]  # noqa: E731
    assert names(group="juniors") == ["Ada Lovelace"]
    assert sorted(names(group="seniors")) == ["Bob Smith", "Cy Young"]
    assert names(group="U8", period="month") == ["Cy Young"] and names(group="6") == []
    assert names(group="5,U8") == ["Ada Lovelace", "Cy Young"] and sorted(names(group="juniors,L8")) == ["Ada Lovelace", "Bob Smith"]
    assert c.get("/api/weekly/leaderboard", params={"group": "5,7"}).status_code == 422
    assert c.get("/api/weekly/leaderboard", params={"group": "7"}).status_code == 422
    assert {r["year_group"] for r in school["rows"]} == {"5", "L8", "U8"}

    # --- the teacher sees emails and code; closing it and publishing the solution
    login_teacher(c, password="correct-horse-battery")
    entries = c.get(f"/api/weekly-admin/{wid}/entries").json()
    assert {e["email"] for e in entries["submissions"]} == {"ada@school.example", "bob@school.example", "cy@school.example"}
    assert entries["people"] == 3 and entries["standings"][0]["email"] == "ada@school.example"
    closed = {**week, "opens_at": iso(now - timedelta(days=7)), "closes_at": iso(now - timedelta(minutes=1)), "solution_published": True}
    assert c.put(f"/api/weekly-admin/{wid}", json=closed).status_code == 200
    assert c.put(f"/api/weekly-admin/{wid}", json={**closed, "question_id": cx["id"]}).status_code == 409  # has entries
    c.cookies.clear()
    detail = c.get(f"/api/weekly/{wid}").json()
    assert detail["phase"] == "closed" and detail["solution"] == golf["reference_solution"]
    assert c.post(f"/api/weekly/{wid}/submit", json={"name": "Ada Lovelace", "email": "ada@school.example", "code": STAIRS_SHORT}).status_code == 409
    assert any(p["id"] == wid for p in c.get("/api/weekly").json()["past"])
    assert detail["credit"] == "Submitted by Sam Smith"

    # once closed it's on the problems page under Past Weekly Problems, with its solution and credit
    groups = {g["name"]: g["id"] for g in c.get("/api/problems/groups").json()}
    past = [p for p in c.get("/api/problems").json() if p["group_id"] == groups["Past Weekly Problems"]]
    assert [(p["title"], p["credit"]) for p in past] == [(golf["title"], "Submitted by Sam Smith")]
    assert c.get(f"/api/problems/{past[0]['id']}/solution").json()["solution_code"] == golf["reference_solution"]
    assert len(c.get("/api/problems").json()) == 1  # only once
    login_teacher(c, password="correct-horse-battery")
    assert c.delete(f"/api/featured/{past[0]['id']}").status_code == 200
    assert c.get("/api/featured").json() == []  # deleting it doesn't bring it back
    c.cookies.clear()

    # unpublished weeks are invisible
    login_teacher(c, password="correct-horse-battery")
    c.put(f"/api/weekly-admin/{w2}", json={**week, "question_id": cx["id"], "published": False})
    c.cookies.clear()
    assert c.get(f"/api/weekly/{w2}").status_code == 404

    # a week that closed before this week started drops out of "this week"
    login_teacher(c, password="correct-horse-battery")
    long_ago = {**closed, "opens_at": iso(now - timedelta(days=60)), "closes_at": iso(now - timedelta(days=40))}
    assert c.put(f"/api/weekly-admin/{wid}", json=long_ago).status_code == 200
    assert c.get("/api/weekly/leaderboard", params={"period": "week"}).json() == {"rows": [], "weeks": 0, "period": "week", "group": "all"}
    assert c.get("/api/weekly/leaderboard").json()["weeks"] == 1

    # the admin can fix a name or ban an email
    assert c.get("/api/weekly-admin/people").status_code == 200
    people = {p["email"]: p for p in c.get("/api/weekly-admin/people").json()}
    assert people["ada@school.example"]["weeks"] == 2 and people["dee@school.example"]["entries"] == 0
    r = c.put("/api/weekly-admin/people", json={"email": "cy@school.example", "name": "Cyrus Young", "banned": False})
    assert r.status_code == 200 and r.json()["name"] == "Cyrus Young"
    assert c.put("/api/weekly-admin/people", json={"email": "bob@school.example", "name": "Bob Smith", "banned": True}).status_code == 200
    assert c.put("/api/weekly-admin/people", json={"email": "nobody@school.example", "name": "No One", "banned": True}).status_code == 404
    c.cookies.clear()
    assert c.get("/api/weekly-admin/people").status_code == 401
    names = [r["name"] for r in c.get(f"/api/weekly/{wid}").json()["standings"]]
    assert names == ["Ada Lovelace", "Cyrus Young"]
    assert "Bob Smith" not in str(c.get("/api/weekly/leaderboard").json())
    assert c.post("/api/weekly/sign-in", json={"name": "Bob Smith", "email": "bob@school.example"}).status_code == 403

    login_teacher(c, password="correct-horse-battery")
    ada = c.get("/api/weekly-admin/people/detail", params={"email": "ADA@school.example"}).json()
    assert ada["year_group"] == "5" and len(ada["weeks_detail"]) == 2 and ada["total_points"] > 0
    first = next(w for w in ada["weeks_detail"] if w["id"] == wid)
    assert first["rank"] == 1 and first["submissions"][0]["code"] == STAIRS_SHORT
    assert c.put("/api/weekly-admin/people", json={"email": "ada@school.example", "name": "Ada Lovelace", "year_group": "6", "banned": False}).json()["year_group"] == "6"
    assert c.delete("/api/weekly-admin/people/week", params={"email": "ada@school.example", "weekly_id": wid}).json() == {"removed": 1}
    assert [r["name"] for r in c.get(f"/api/weekly/{wid}").json()["standings"]] == ["Cyrus Young"]
    other = c.get("/api/weekly-admin/people/detail", params={"email": "ada@school.example"}).json()["weeks_detail"]
    assert len(other) == 1
    assert c.delete(f"/api/weekly-admin/entries/{other[0]['submissions'][0]['id']}").json() == {"ok": True}
    assert c.delete(f"/api/weekly-admin/entries/{other[0]['submissions'][0]['id']}").status_code == 404
    assert c.get("/api/weekly-admin/people/detail", params={"email": "ada@school.example"}).json()["weeks_detail"] == []
    assert c.delete("/api/weekly-admin/people", params={"email": "cy@school.example"}).json() == {"removed": 1}
    assert c.get("/api/weekly-admin/people/detail", params={"email": "cy@school.example"}).status_code == 404
    assert c.get(f"/api/weekly/{wid}").json()["standings"] == []
    c.cookies.clear()
    assert c.delete("/api/weekly-admin/people", params={"email": "ada@school.example"}).status_code == 401
    # a cleared email can be used again, under any name
    assert c.post("/api/weekly/sign-in", json={"name": "Cy Other", "email": "cy@school.example", "year_group": "4"}).status_code == 200


def test_leaderboard_periods():
    from app.routers.weekly import SCHOOL_TZ, period_start

    at = datetime(2026, 10, 28, 12, 0, tzinfo=timezone.utc)  # a Wednesday, the week the clocks went back
    assert period_start("all", at) is None
    assert period_start("week", at) == datetime(2026, 10, 27, tzinfo=SCHOOL_TZ)  # weeks start on Tuesday
    assert period_start("week", datetime(2026, 10, 26, 12, tzinfo=timezone.utc)) == datetime(2026, 10, 20, tzinfo=SCHOOL_TZ)  # a Monday
    assert period_start("week", datetime(2026, 10, 27, 0, 30, tzinfo=timezone.utc)) == datetime(2026, 10, 27, tzinfo=SCHOOL_TZ)
    assert period_start("week", at).utcoffset() == timedelta(0)
    assert period_start("month", at) == datetime(2026, 10, 1, tzinfo=SCHOOL_TZ)
    assert period_start("month", at).utcoffset() == timedelta(hours=1)  # BST
    assert period_start("year", at) == datetime(2026, 9, 1, tzinfo=SCHOOL_TZ)
    assert period_start("year", datetime(2027, 3, 1, tzinfo=timezone.utc)) == datetime(2026, 9, 1, tzinfo=SCHOOL_TZ)
