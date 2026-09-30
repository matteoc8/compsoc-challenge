"""App factory. Startup: migrate, seed, start the judge queue, re-arm timers."""

import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy import func, select

from .auth import hash_password
from .config import Settings, get_settings
from .db import init_engine, session_scope
from .engine.game import GameError, engine
from .engine import judging
from .judge.client import make_executor
from .judge.queue import JudgeQueue
from .limiter import limiter
from .models import Quiz, Teacher
from .realtime import ws
from .realtime.hub import Hub
from .routers import auth, games, join, media, play, quizzes
from .runtime import rt
from .schemas.ws import WsMessage

log = logging.getLogger("compsoc")
BACKEND_DIR = Path(__file__).resolve().parent.parent


def run_migrations(url: str) -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")


async def seed(settings: Settings) -> None:
    async with session_scope() as s:
        teacher = await s.scalar(select(Teacher).order_by(Teacher.created_at))
        if not teacher:
            teacher = Teacher(
                username=settings.teacher_username,
                password_hash=hash_password(settings.teacher_password),
                must_change_password=True,
            )
            s.add(teacher)
            await s.flush()
            log.warning("Seeded teacher '%s'; the password must be changed on first login", teacher.username)
        if settings.seed_sample_quiz and not await s.scalar(select(func.count()).where(Quiz.owner_id == teacher.id)):
            data = json.loads((BACKEND_DIR / "seed" / "sample_quiz.json").read_text(encoding="utf-8"))
            await quizzes.import_quiz_data(s, teacher, data)
            log.info("Seeded the sample quiz")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if settings.judge_backend == "local":
        log.warning("JUDGE_BACKEND=local runs team code WITHOUT a sandbox. Development only.")
    if settings.secret_key.startswith("dev-secret-change-me") and settings.judge_backend != "local":
        log.warning("SECRET_KEY is the development default; set it in .env")
    if settings.run_migrations:
        await asyncio.to_thread(run_migrations, settings.database_url)
    init_engine(settings.database_url)
    os.makedirs(settings.media_dir, exist_ok=True)
    await seed(settings)
    # Fresh in-memory state bound to this event loop.
    engine.locks.clear()
    engine.timers.clear()
    engine.finishers.clear()
    rt.hub = Hub()
    rt.judge_ok, rt.judge_error = True, None
    judging.reset_run_limits()
    rt.settings = settings
    rt.executor = make_executor(settings)
    rt.queue = JudgeQueue(settings.judge_workers)
    rt.queue.start()
    n = await judging.requeue_pending()
    if n:
        log.info("re-queued %d pending submissions", n)
    await engine.rearm_all()
    try:
        yield
    finally:
        await engine.shutdown()
        await rt.queue.stop()
        await rt.executor.aclose()


MAX_BODY = 1_000_000
MAX_MEDIA_BODY = 5_500_000
MAX_IMPORT_BODY = 20_500_000


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="CompSoc Challenge",
        lifespan=lifespan,
        openapi_url="/api/openapi.json",
        docs_url="/api/docs",
        redoc_url=None,
    )
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    @app.exception_handler(GameError)
    async def game_error(_: Request, exc: GameError):
        return JSONResponse({"detail": exc.message}, status_code=exc.status)

    @app.middleware("http")
    async def body_limit(request: Request, call_next):
        path = request.url.path
        cap = MAX_IMPORT_BODY if path.endswith("/quizzes/import") else MAX_MEDIA_BODY if path == "/api/media" else MAX_BODY
        length = request.headers.get("content-length")
        if length and length.isdigit() and int(length) > cap:
            return JSONResponse({"detail": "Request too large"}, status_code=413)
        return await call_next(request)

    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    for r in (auth.router, quizzes.router, media.router, games.router, join.router, play.router):
        app.include_router(r, prefix="/api")
    app.include_router(ws.router)

    @app.get("/api/health")
    async def health():
        judge = await rt.executor.health() if rt.executor else False
        return {"ok": True, "judge": judge, "judge_backend": settings.judge_backend}

    @app.get("/api/_schemas/ws", response_model=WsMessage, include_in_schema=True, tags=["schemas"])
    async def ws_schema():
        """Never called: exposes the WebSocket message shapes in OpenAPI for `npm run gen:types`."""
        return JSONResponse({"detail": "schema only"}, status_code=404)

    return app


app = create_app()
