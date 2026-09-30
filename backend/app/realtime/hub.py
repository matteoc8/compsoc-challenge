"""WebSocket connection registry and fan-out.

Every message is {"type", "seq", "data"}. `seq` rises by one per message on each
connection; a client that ever sees a gap asks for a fresh snapshot. Each connection
has its own send queue and writer task, so a slow client never delays anyone else.
Single process by design (see the plan): swap `Hub` for a Redis-backed broadcaster
behind the same methods if you ever need several workers.
"""

import asyncio
import contextlib
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime

from fastapi import WebSocket

log = logging.getLogger(__name__)


def _default(o):
    if isinstance(o, datetime):
        return o.isoformat()
    if isinstance(o, uuid.UUID):
        return str(o)
    raise TypeError(f"not JSON serialisable: {type(o)}")


def dumps(o) -> str:
    return json.dumps(o, default=_default, separators=(",", ":"))


@dataclass(eq=False)
class Conn:
    ws: WebSocket
    game_id: str
    role: str  # team | teacher | screen
    team_id: str | None = None
    seq: int = 0
    queue: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(maxsize=500))
    writer: asyncio.Task | None = None
    closed: bool = False

    def send(self, type_: str, data) -> None:
        if self.closed:
            return
        self.seq += 1
        try:
            self.queue.put_nowait(dumps({"type": type_, "seq": self.seq, "data": data}))
        except asyncio.QueueFull:
            # A client this far behind is effectively gone; drop it and let it reconnect.
            log.warning("send queue full, closing %s/%s", self.role, self.team_id)
            self.close(4008, "too slow")

    def close(self, code: int = 1000, reason: str = "") -> None:
        if self.closed:
            return
        self.closed = True
        try:
            self.queue.put_nowait(("__close__", code, reason))
        except asyncio.QueueFull:
            if self.writer:
                self.writer.cancel()
            asyncio.get_running_loop().create_task(self._force_close(code, reason))

    async def _force_close(self, code: int, reason: str) -> None:
        with contextlib.suppress(Exception):
            await self.ws.close(code=code, reason=reason)


class Hub:
    def __init__(self) -> None:
        self.games: dict[str, set[Conn]] = {}

    async def attach(self, conn: Conn) -> None:
        # One live connection per team: a second device takes over the first.
        if conn.role == "team":
            for other in list(self.games.get(conn.game_id, ())):
                if other.role == "team" and other.team_id == conn.team_id:
                    other.send("session.replaced", {"message": "This team was opened on another device."})
                    other.close(4001, "opened on another device")
        self.games.setdefault(conn.game_id, set()).add(conn)
        conn.writer = asyncio.create_task(self._writer(conn))

    def detach(self, conn: Conn) -> None:
        conns = self.games.get(conn.game_id)
        if conns:
            conns.discard(conn)
        conn.closed = True
        if conn.writer and not conn.writer.done():
            conn.writer.cancel()

    async def _writer(self, conn: Conn) -> None:
        try:
            while True:
                item = await conn.queue.get()
                if isinstance(item, tuple):
                    _, code, reason = item
                    with contextlib.suppress(Exception):
                        await conn.ws.close(code=code, reason=reason)
                    return
                await conn.ws.send_text(item)
        except asyncio.CancelledError:
            pass
        except Exception:  # socket died; the reader side will detach
            conn.closed = True

    def conns(self, game_id: str, role: str | None = None, team_id: str | None = None) -> list[Conn]:
        out = []
        for c in self.games.get(game_id, ()):
            if role and c.role != role:
                continue
            if team_id and c.team_id != team_id:
                continue
            out.append(c)
        return out

    def send(self, game_id: str, type_: str, data, role: str | None = None, team_id: str | None = None) -> None:
        for c in self.conns(game_id, role, team_id):
            c.send(type_, data)

    def send_roles(self, game_id: str, type_: str, data, roles: tuple[str, ...]) -> None:
        for c in self.conns(game_id):
            if c.role in roles:
                c.send(type_, data)

    def online_team_ids(self, game_id: str) -> set[str]:
        return {c.team_id for c in self.conns(game_id, "team") if c.team_id}

    def kick_team(self, game_id: str, team_id: str, message: str) -> None:
        for c in self.conns(game_id, "team", team_id):
            c.send("session.ended", {"message": message})
            c.close(4003, "removed")
