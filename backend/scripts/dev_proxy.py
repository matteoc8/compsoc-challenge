"""Stand-in for Caddy when running locally: one URL for everything. /api and /ws go to the
backend, everything else to the Next.js server. Development only (run_local.py starts it)."""

import argparse
import asyncio

import httpx
import uvicorn
import websockets
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Route, WebSocketRoute
from starlette.websockets import WebSocket, WebSocketDisconnect

BACKEND = "127.0.0.1:8000"
FRONTEND = "127.0.0.1:3000"
HOP = {"connection", "keep-alive", "transfer-encoding", "upgrade", "content-encoding", "content-length", "host"}
# One connection pool, but a fresh client per request: a shared client would keep a cookie
# jar and log every browser in as whoever logged in last.
transport = httpx.AsyncHTTPTransport()


async def http(request: Request) -> Response:
    path = request.url.path
    upstream = BACKEND if path.startswith("/api") else FRONTEND
    headers = {k: v for k, v in request.headers.items() if k.lower() not in HOP}
    headers["host"] = request.headers.get("host", "localhost")
    headers["x-forwarded-for"] = request.client.host if request.client else "127.0.0.1"
    client = httpx.AsyncClient(transport=transport, timeout=120)  # not closed: that would close the shared pool
    r = await client.request(request.method, f"http://{upstream}{path}", params=request.query_params, content=await request.body(), headers=headers)
    out = Response(r.content, status_code=r.status_code)
    for k, v in r.headers.multi_items():
        if k.lower() not in HOP:
            out.headers.append(k, v)
    return out


async def ws(socket: WebSocket) -> None:
    headers = {k: v for k, v in socket.headers.items() if k.lower() in ("origin", "cookie")}
    headers["x-forwarded-host"] = socket.headers.get("host", "")  # the backend checks Origin against this
    await socket.accept()
    try:
        async with websockets.connect(f"ws://{BACKEND}/ws?{socket.url.query}", additional_headers=headers) as up:

            async def down():
                async for m in up:
                    await socket.send_text(m)

            async def upward():
                while True:
                    await up.send(await socket.receive_text())

            await asyncio.gather(down(), upward())
    except (WebSocketDisconnect, websockets.ConnectionClosed, OSError):
        pass
    finally:
        try:
            await socket.close()
        except RuntimeError:
            pass


app = Starlette(routes=[WebSocketRoute("/ws", ws), Route("/{path:path}", http, methods=["GET", "POST", "PUT", "DELETE", "PATCH"])])

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8080)
    a = ap.parse_args()
    uvicorn.run(app, host=a.host, port=a.port, log_level="warning")
