import threading
import time

from app.pipeline.context import PipelineContext


class RecordingStage:
    """Configurable stage for runner/queue tests."""

    def __init__(
        self,
        name: str,
        *,
        uses_gpu: bool = False,
        weight: float = 1.0,
        done: bool = False,
        fail: Exception | None = None,
        duration: float = 0.0,
    ) -> None:
        self.name = name
        self.label = name.title()
        self.uses_gpu = uses_gpu
        self.weight = weight
        self.done = done
        self.fail = fail
        self.duration = duration
        self.runs = 0
        self.active = 0
        self.max_active = 0
        self._lock = threading.Lock()

    def is_done(self, ctx: PipelineContext) -> bool:
        return self.done

    def run(self, ctx: PipelineContext) -> None:
        with self._lock:
            self.runs += 1
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            deadline = time.monotonic() + self.duration
            while time.monotonic() < deadline:
                ctx.check_cancelled()
                time.sleep(0.01)
            if self.fail is not None:
                raise self.fail
        finally:
            with self._lock:
                self.active -= 1
