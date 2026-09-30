"""Restart recovery, WebSocket auth, device takeover, rejoin, judge outages."""

import uuid

import pytest
from sqlalchemy import select
from starlette.websockets import WebSocketDisconnect

from app.engine import judging
from app.judge.client import Executor, JudgeUnavailable
from app.models import Game, Submission
from app.runtime import rt

from .conftest import NEW_PW, auth, db, join, login_teacher, make_client, make_quiz, new_game, sample_quiz, state, wait_state, wait_until


def test_backend_restart_mid_question(tmp_path, monkeypatch):
    dbp, media = tmp_path / "r.db", tmp_path / "m"
    with make_client(dbp, media, monkeypatch) as c:
        login_teacher(c)
        quiz = make_quiz(c, "super_fast")
        game = new_game(c, quiz["id"])
        gid = game["id"]
        t = join(c, game["join_code"], "Restarters")
        c.post(f"/api/games/{gid}/start", json={"force": True})
        c.post(f"/api/games/{gid}/next", json={"expect_state": "round_intro"})
        assert state(c, gid) == "open"
        c.post(f"/api/games/{gid}/adjust-time", json={"set_remaining_s": 6})
        before = db(c, lambda s: s.get(Game, uuid.UUID(gid)))
        r = c.put(f"/api/drafts/{quiz['questions'][0]['id']}", json={"code": "print('draft')"}, headers=auth(t["token"]))
        assert r.status_code == 200
    # "docker compose restart backend"
    with make_client(dbp, media, monkeypatch) as c:
        c.post("/api/auth/login", json={"username": "teacher", "password": NEW_PW})
        after = db(c, lambda s: s.get(Game, uuid.UUID(gid)))
        assert after.state.value == "open" and after.deadline == before.deadline
        # the device token still works and the draft survived
        d = c.get(f"/api/drafts/{quiz['questions'][0]['id']}", headers=auth(t["token"])).json()
        assert d["code"] == "print('draft')"
        # the re-armed timer closes the question by itself
        wait_state(c, gid, "results", 20)


def test_ws_auth_rules(client):
    c = client
    login_teacher(c)
    quiz = sample_quiz(c)
    game = new_game(c, quiz["id"])
    gid = game["id"]

    def closed_with(url, code):
        with c.websocket_connect(url) as ws:
            with pytest.raises(WebSocketDisconnect) as e:
                ws.receive_json()
            assert e.value.code == code

    closed_with(f"/ws?role=screen&game={gid}&token=wrong", 4401)
    closed_with(f"/ws?role=team&token=nope", 4401)
    closed_with(f"/ws?role=admin&game={gid}", 4400)
    with c.websocket_connect(f"/ws?role=screen&game={gid}&token={game['screen_token']}") as ws:
        snap = ws.receive_json()["data"]
        assert snap["role"] == "screen" and snap["game"]["join_code"] == game["join_code"]
        assert "screen_token" not in snap and "monitor" not in snap
    with c.websocket_connect(f"/ws?role=teacher&game={gid}") as ws:  # cookie from the logged-in client
        snap = ws.receive_json()["data"]
        assert snap["role"] == "teacher" and snap["screen_token"] == game["screen_token"]
    # a teacher WS from another site is refused even with the cookie
    closed_with_origin = c.websocket_connect(f"/ws?role=teacher&game={gid}", headers={"origin": "https://evil.example"})
    with closed_with_origin as ws:
        with pytest.raises(WebSocketDisconnect) as e:
            ws.receive_json()
        assert e.value.code == 4401
    c.post("/api/auth/logout")
    c.cookies.clear()
    closed_with(f"/ws?role=teacher&game={gid}", 4401)
    assert c.get("/api/quizzes").status_code == 401


def test_second_device_takes_over_and_rejoin(client):
    c = client
    login_teacher(c)
    quiz = sample_quiz(c)
    game = new_game(c, quiz["id"])
    gid = game["id"]
    t = join(c, game["join_code"], "Takeover")
    with c.websocket_connect(f"/ws?role=team&token={t['token']}") as first:
        assert first.receive_json()["type"] == "snapshot"
        with c.websocket_connect(f"/ws?role=team&token={t['token']}") as second:
            assert second.receive_json()["type"] == "snapshot"
            msg = first.receive_json()
            while msg["type"] != "session.replaced":
                msg = first.receive_json()
            with pytest.raises(WebSocketDisconnect) as e:
                first.receive_json()
            assert e.value.code == 4001

    # teacher reissues: one-time rejoin code, old token stops working
    code = c.post(f"/api/games/{gid}/teams/{t['team_id']}/reissue").json()["rejoin_code"]
    r = c.post("/api/join", json={"rejoin_code": code.lower()})
    assert r.status_code == 200 and r.json()["team_id"] == t["team_id"]
    assert c.get("/api/team/me", headers=auth(t["token"])).status_code == 401
    assert c.get("/api/team/me", headers=auth(r.json()["token"])).status_code == 200
    assert c.post("/api/join", json={"rejoin_code": code}).status_code == 400  # one-time

    # rename validation
    assert c.post(f"/api/games/{gid}/teams/{t['team_id']}/rename", json={"name": "New Name"}).status_code == 200
    join(c, game["join_code"], "Other")
    assert c.post(f"/api/games/{gid}/teams/{t['team_id']}/rename", json={"name": "other"}).status_code == 409


class DownExecutor(Executor):
    name = "down"

    async def run_batch(self, reqs):
        raise JudgeUnavailable("connection refused")

    async def health(self):
        return False


def test_judge_down_marks_error_and_recovers(client, monkeypatch):
    c = client
    login_teacher(c)
    quiz = make_quiz(c, "super_fast")
    game = new_game(c, quiz["id"])
    gid = game["id"]
    t = join(c, game["join_code"], "Unlucky")
    c.post(f"/api/games/{gid}/start", json={"force": True})
    c.post(f"/api/games/{gid}/next", json={"expect_state": "round_intro"})
    monkeypatch.setattr(judging, "JUDGE_RETRIES", 2)
    monkeypatch.setattr(judging, "JUDGE_RETRY_DELAY_S", 0.1)
    real = rt.executor
    rt.executor = DownExecutor()
    try:
        with c.websocket_connect(f"/ws?role=teacher&game={gid}") as ws:
            ws.receive_json()
            r = c.post("/api/submissions", json={"question_id": quiz["questions"][0]["id"], "code": "print(1)"}, headers=auth(t["token"]))
            assert r.status_code == 202
            msg = ws.receive_json()
            while msg["type"] != "judge.status":
                msg = ws.receive_json()
            assert msg["data"]["ok"] is False
        wait_until(lambda: db(c, lambda s: s.scalar(select(Submission.status))).value == "error", 10, what="error status")
        assert rt.judge_ok is False
        assert c.get("/api/health").json()["judge"] is False
    finally:
        rt.executor = real
    # the next successful judge call flips the flag back; the errored attempt doesn't block resubmitting
    import time

    time.sleep(5)
    r = c.post("/api/submissions", json={"question_id": quiz["questions"][0]["id"], "code": "print(1)"}, headers=auth(t["token"]))
    assert r.status_code == 202, r.text
    wait_until(lambda: rt.judge_ok, 15, what="judge recovered")
