"""Judge work queue: a fixed pool of asyncio workers pulling from a priority queue,
so a burst of 15 submissions can't flood Judge0 and Submit is always served before Run."""

import asyncio
import itertools
import logging
from collections.abc import Awaitable, Callable

log = logging.getLogger(__name__)

SUBMIT = 0
RUN = 1


class JudgeQueue:
    def __init__(self, workers: int = 4):
        self.workers = workers
        self.q: asyncio.PriorityQueue = asyncio.PriorityQueue()
        self._counter = itertools.count()
        self._tasks: list[asyncio.Task] = []

    def start(self) -> None:
        self._tasks = [asyncio.create_task(self._worker(i)) for i in range(self.workers)]

    async def stop(self) -> None:
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks = []

    def put(self, priority: int, job: Callable[[], Awaitable[None]]) -> None:
        self.q.put_nowait((priority, next(self._counter), job))

    def pending(self) -> int:
        return self.q.qsize()

    async def _worker(self, i: int) -> None:
        while True:
            _, _, job = await self.q.get()
            try:
                await job()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("judge job failed")
            finally:
                self.q.task_done()
