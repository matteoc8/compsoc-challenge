"""Process-wide singletons, created in the app lifespan."""

from dataclasses import dataclass, field

from .config import Settings
from .judge.client import Executor
from .judge.queue import JudgeQueue
from .realtime.hub import Hub


@dataclass
class Runtime:
    settings: Settings | None = None
    executor: Executor | None = None
    hub: Hub = field(default_factory=Hub)
    queue: JudgeQueue | None = None
    judge_ok: bool = True
    judge_error: str | None = None


rt = Runtime()
