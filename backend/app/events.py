import asyncio
import time
from collections import defaultdict, deque
from typing import Any, Literal

from pydantic import BaseModel, Field

EventType = Literal["stage", "progress", "log", "partial", "job"]


class JobEvent(BaseModel):
    job_id: str
    type: EventType
    stage: str | None = None
    status: str | None = None
    progress: float | None = None
    message: str | None = None
    data: dict[str, Any] | None = None
    ts: float = Field(default_factory=time.time)


class EventBus:
    """In-memory pub/sub keyed by job id.

    Stages run in worker threads, so publish() hops onto the bound event loop.
    Each job keeps a bounded history that is replayed to new subscribers, so a
    browser that connects (or reconnects) mid-job sees the full picture.
    """

    def __init__(self, history_limit: int = 1000) -> None:
        self._history_limit = history_limit
        self._history: dict[str, deque[JobEvent]] = {}
        self._subscribers: dict[str, set[asyncio.Queue[JobEvent]]] = defaultdict(set)
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def publish(self, event: JobEvent) -> None:
        loop = self._loop
        if loop is None:
            self._deliver(event)
            return
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is loop:
            self._deliver(event)
            return
        try:
            loop.call_soon_threadsafe(self._deliver, event)
        except RuntimeError:  # loop closed during shutdown
            pass

    def _deliver(self, event: JobEvent) -> None:
        history = self._history.setdefault(event.job_id, deque(maxlen=self._history_limit))
        history.append(event)
        for queue in list(self._subscribers.get(event.job_id, ())):
            queue.put_nowait(event)

    def subscribe(self, job_id: str) -> asyncio.Queue[JobEvent]:
        queue: asyncio.Queue[JobEvent] = asyncio.Queue()
        for event in self._history.get(job_id, ()):
            queue.put_nowait(event)
        self._subscribers[job_id].add(queue)
        return queue

    def unsubscribe(self, job_id: str, queue: asyncio.Queue[JobEvent]) -> None:
        self._subscribers.get(job_id, set()).discard(queue)

    def history(self, job_id: str) -> list[JobEvent]:
        return list(self._history.get(job_id, ()))

    def forget(self, job_id: str) -> None:
        self._history.pop(job_id, None)
        self._subscribers.pop(job_id, None)
