"""/ws?role=team|teacher|screen&token=…&game=…

team: device token (game resolved from it). teacher: session cookie + game id.
screen: game id + the read-only projector token shown on the console.
Failed auth is accepted then closed with 4401 so the client stops reconnecting."""

import json
import secrets
import time
import uuid
from urllib.parse import urlparse

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..auth import COOKIE, team_from_token, teacher_from_cookie
from ..db import session_scope
from ..engine.game import engine
from ..models import Game
from ..runtime import rt
from .hub import Conn

router = APIRouter()


def _same_origin(ws: WebSocket) -> bool:
    origin = ws.headers.get("origin")
    if not origin:
        return True  # non-browser clients (load test) send no Origin
    host = ws.headers.get("x-forwarded-host") or ws.headers.get("host", "")
    return urlparse(origin).netloc == host


async def _authenticate(ws: WebSocket, role: str, token: str | None, game: str | None) -> tuple[str, str | None] | None:
    async with session_scope() as s:
        if role == "team":
            team = await team_from_token(s, token)
            return (str(team.game_id), str(team.id)) if team else None
        try:
            gid = uuid.UUID(game or "")
        except ValueError:
            return None
        g = await s.get(Game, gid)
        if not g:
            return None
        if role == "teacher":
            t = await teacher_from_cookie(s, ws.cookies.get(COOKIE))
            if t and g.owner_id == t.id and not t.must_change_password and _same_origin(ws):
                return str(g.id), None
            return None
        if role == "screen":
            if token and secrets.compare_digest(token, g.screen_token):
                return str(g.id), None
        return None


async def _presence(game_id: str) -> None:
    rt.hub.send_roles(game_id, "presence", {"online": sorted(rt.hub.online_team_ids(game_id))}, ("teacher", "screen"))


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket, role: str = "team", token: str | None = None, game: str | None = None):
    await ws.accept()
    if role not in ("team", "teacher", "screen"):
        await ws.close(4400, "bad role")
        return
    auth = await _authenticate(ws, role, token, game)
    if not auth:
        await ws.close(4401, "unauthorised")
        return
    game_id, team_id = auth
    conn = Conn(ws=ws, game_id=game_id, role=role, team_id=team_id)
    await rt.hub.attach(conn)
    try:
        await engine.send_snapshot(conn)
        if role == "team":
            await _presence(game_id)
        while True:
            raw = await ws.receive_text()
            if len(raw) > 4096:
                continue
            try:
                msg = json.loads(raw)
            except ValueError:
                continue
            kind = msg.get("type") if isinstance(msg, dict) else None
            if kind == "ping":
                data = msg.get("data") or {}
                conn.send("pong", {"t0": data.get("t0"), "server_ms": time.time() * 1000})
            elif kind == "snapshot.request":
                await engine.send_snapshot(conn)
    except (WebSocketDisconnect, RuntimeError):
        pass  # RuntimeError: we closed the socket ourselves (kicked / replaced)
    finally:
        rt.hub.detach(conn)
        if role == "team":
            await _presence(game_id)
