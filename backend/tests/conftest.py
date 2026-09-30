import asyncio
import io
import json
import os
import time
import uuid
import zipfile
from collections.abc import Callable
from pathlib import Path

import asyncpg
import pytest
from fastapi.testclient import TestClient

from app.config import get_settings

SEED = json.loads((Path(__file__).resolve().parent.parent / "seed" / "sample_quiz.json").read_text(encoding="utf-8"))

NEW_PW = "correct-horse-battery"


PG_ADMIN = os.environ.get("TEST_PG_ADMIN_URL")  # e.g. postgresql://postgres@localhost:5433/postgres
_pg_dbs: dict[str, str] = {}


def _pg_url_for(db_path) -> str:
    """With TEST_PG_ADMIN_URL set, each test gets its own fresh Postgres database."""
    key = str(db_path)
    if key not in _pg_dbs:
        name = "cc_test_" + uuid.uuid4().hex[:12]

        async def create():
            conn = await asyncpg.connect(PG_ADMIN)
            await conn.execute(f'create database "{name}"')
            await conn.close()

        asyncio.run(create())
        base = PG_ADMIN.rsplit("/", 1)[0].replace("postgresql://", "postgresql+asyncpg://")
        _pg_dbs[key] = f"{base}/{name}"
    return _pg_dbs[key]


def make_client(db_path, media_dir, monkeypatch) -> TestClient:
    url = _pg_url_for(db_path) if PG_ADMIN else f"sqlite+aiosqlite:///{db_path.as_posix()}"
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("JUDGE_BACKEND", "local")
    monkeypatch.setenv("MEDIA_DIR", str(media_dir))
    monkeypatch.setenv("SECRET_KEY", "test-secret-test-secret-test-secret-123")
    get_settings.cache_clear()
    from app.main import create_app

    return TestClient(create_app())


@pytest.fixture
def client(tmp_path, monkeypatch):
    with make_client(tmp_path / "test.db", tmp_path / "media", monkeypatch) as c:
        yield c
    get_settings.cache_clear()


def wait_until(pred: Callable[[], object], timeout: float = 30, interval: float = 0.1, what: str = "condition"):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        v = pred()
        if v:
            return v
        time.sleep(interval)
    raise AssertionError(f"timed out waiting for {what}")


def login_teacher(c: TestClient, password: str = "changeme") -> None:
    r = c.post("/api/auth/login", json={"username": "teacher", "password": password})
    assert r.status_code == 200, r.text
    if r.json()["must_change_password"]:
        r = c.post("/api/auth/change-password", json={"current_password": password, "new_password": NEW_PW})
        assert r.status_code == 200, r.text


def sample_quiz(c: TestClient, verify: bool = True) -> dict:
    quiz = c.get("/api/quizzes").json()[0]
    full = c.get(f"/api/quizzes/{quiz['id']}").json()
    if verify:
        for q in full["questions"]:
            r = c.post(f"/api/questions/{q['id']}/verify")
            assert r.status_code == 200 and r.json()["ok"], r.text
    return c.get(f"/api/quizzes/{quiz['id']}").json()


def seed_questions(*types: str) -> list[dict]:
    """Pick sample questions by type, in order; 'multiple_choice' may repeat (takes the next one)."""
    used: dict[str, int] = {}
    out = []
    for t in types:
        matches = [q for q in SEED["questions"] if q["type"] == t]
        out.append(matches[used.get(t, 0)])
        used[t] = used.get(t, 0) + 1
    return out


def make_quiz(c: TestClient, *types: str, title: str = "Test quiz", verify: bool = True) -> dict:
    """Import a quiz made of the chosen sample questions and verify it."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("quiz.json", json.dumps({"version": 1, "title": title, "settings": {}, "questions": seed_questions(*types)}))
    r = c.post("/api/quizzes/import", files={"file": ("q.zip", buf.getvalue(), "application/zip")})
    assert r.status_code == 200, r.text
    quiz = c.get(f"/api/quizzes/{r.json()['id']}").json()
    if verify:
        for q in quiz["questions"]:
            v = c.post(f"/api/questions/{q['id']}/verify")
            assert v.status_code == 200 and v.json()["ok"], v.text
        quiz = c.get(f"/api/quizzes/{quiz['id']}").json()
    return quiz


def new_game(c: TestClient, quiz_id: str) -> dict:
    r = c.post("/api/games", json={"quiz_id": quiz_id})
    assert r.status_code == 200, r.text
    return r.json()


def join(c: TestClient, code: str, name: str) -> dict:
    r = c.post("/api/join", json={"code": code, "team_name": name})
    assert r.status_code == 200, r.text
    return r.json()


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def state(c: TestClient, gid: str) -> str:
    return c.get(f"/api/games/{gid}").json()["state"]


def wait_state(c: TestClient, gid: str, target: str, timeout: float = 30) -> None:
    wait_until(lambda: state(c, gid) == target, timeout, what=f"state {target}")


def db(c: TestClient, fn):
    """Run `async fn(session)` on the app's event loop and return its result."""
    from app.db import session_scope

    async def runner():
        async with session_scope() as s:
            return await fn(s)

    return c.portal.call(runner)
