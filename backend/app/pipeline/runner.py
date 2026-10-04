import asyncio
import contextlib
from collections.abc import Callable, Sequence

from app.pipeline.context import PipelineContext
from app.pipeline.errors import StageCancelled, StageError
from app.pipeline.stage import Stage

ProgressCallback = Callable[[str, float], None]


class VideoLocks:
    """One asyncio.Lock per video_id so two jobs never build the same artifacts at once."""

    def __init__(self) -> None:
        self._locks: dict[str, asyncio.Lock] = {}

    def get(self, video_id: str) -> asyncio.Lock:
        return self._locks.setdefault(video_id, asyncio.Lock())


async def run_pipeline(
    stages: Sequence[Stage],
    ctx: PipelineContext,
    *,
    gpu_lock: asyncio.Lock,
    video_locks: VideoLocks,
    on_progress: ProgressCallback | None = None,
) -> None:
    total = sum(s.weight for s in stages) or 1.0
    completed = 0.0
    for stage in stages:
        if on_progress:
            on_progress(stage.name, completed / total)
        video_lock = video_locks.get(ctx.video_id) if ctx.video_id else contextlib.nullcontext()
        gpu = gpu_lock if stage.uses_gpu else contextlib.nullcontext()
        try:
            ctx.check_cancelled()
            async with video_lock, gpu:
                ctx.check_cancelled()
                # Checked inside the locks: another job may have just produced the artifact.
                if await asyncio.to_thread(stage.is_done, ctx):
                    ctx.emit("stage", stage=stage.name, status="cached", progress=1.0)
                else:
                    ctx.emit("stage", stage=stage.name, status="running", progress=0.0)
                    await asyncio.to_thread(stage.run, ctx)
                    ctx.emit("stage", stage=stage.name, status="done", progress=1.0)
        except StageCancelled:
            ctx.emit("stage", stage=stage.name, status="cancelled")
            raise
        except Exception as exc:
            message = exc.message if isinstance(exc, StageError) else str(exc)
            ctx.emit("stage", stage=stage.name, status="failed", message=message)
            raise
        completed += stage.weight
        if on_progress:
            on_progress(stage.name, completed / total)
