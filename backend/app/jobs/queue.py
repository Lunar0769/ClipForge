import asyncio
import logging
import threading
from collections.abc import Callable

from sqlalchemy import Engine
from sqlalchemy.orm.exc import StaleDataError

from app import repo
from app.config import Settings
from app.events import EventBus, JobEvent
from app.models import JobStatus
from app.pipeline.context import PipelineContext
from app.pipeline.errors import StageCancelled, StageError
from app.pipeline.runner import VideoLocks, run_pipeline
from app.pipeline.stage import Stage
from app.workspace import Workspace

logger = logging.getLogger(__name__)

StagesFactory = Callable[[], list[Stage]]


class JobQueue:
    """In-process job queue. `concurrency` jobs run at once; GPU stages share one lock."""

    def __init__(
        self,
        *,
        engine: Engine,
        workspace: Workspace,
        settings: Settings,
        bus: EventBus,
        stages_factory: StagesFactory,
        concurrency: int = 2,
    ) -> None:
        self._engine = engine
        self._workspace = workspace
        self._settings = settings
        self.bus = bus
        self._stages_factory = stages_factory
        self._concurrency = concurrency
        self._queue: asyncio.Queue[str] | None = None
        self._workers: list[asyncio.Task] = []
        self._cancels: dict[str, threading.Event] = {}
        # cancel() runs in a request thread; this makes "is it queued? -> cancel it" atomic with
        # the worker's "is it queued? -> start it", so a job can't be both cancelled and started.
        self._start_lock = threading.Lock()
        self._gpu_lock: asyncio.Lock | None = None
        self._video_locks = VideoLocks()

    async def start(self) -> None:
        self.bus.bind(asyncio.get_running_loop())
        self._queue = asyncio.Queue()
        self._gpu_lock = asyncio.Lock()
        self._workers = [asyncio.create_task(self._worker()) for _ in range(self._concurrency)]

    async def stop(self) -> None:
        for event in self._cancels.values():
            event.set()
        for worker in self._workers:
            worker.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers = []

    def submit(self, job_id: str) -> None:
        assert self._queue is not None, "JobQueue.start() was not awaited"
        self._queue.put_nowait(job_id)

    def cancel(self, job_id: str) -> bool:
        with self._start_lock:
            event = self._cancels.get(job_id)
            if event is not None:
                event.set()
                return True
            job = repo.get_job(self._engine, job_id)
            if job is None or job.status is not JobStatus.queued:
                return False
            repo.update_job(self._engine, job_id, status=JobStatus.cancelled)
        self._publish_job(job_id, JobStatus.cancelled, message="Cancelled before it started.")
        return True

    def _publish_job(self, job_id: str, status: JobStatus, message: str | None = None, hint: str | None = None) -> None:
        self.bus.publish(JobEvent(
            job_id=job_id, type="job", status=status.value, message=message,
            data={"hint": hint} if hint else None,
        ))

    async def _worker(self) -> None:
        assert self._queue is not None
        while True:
            job_id = await self._queue.get()
            try:
                await self._run_job(job_id)
            except Exception:  # never let one job kill the worker
                logger.exception("Unhandled error while running job %s", job_id)
            finally:
                self._queue.task_done()

    def _update_job(self, job_id: str, **fields) -> bool:
        """Update the job row; False means the job was deleted (e.g. its project was removed) mid-run."""
        try:
            repo.update_job(self._engine, job_id, **fields)
        except (KeyError, StaleDataError):
            logger.info("Job %s no longer exists (project deleted); dropping update", job_id)
            return False
        return True

    def _start(self, job_id: str) -> PipelineContext | None:
        """Atomically move a queued job to running; None if it was cancelled/started/deleted meanwhile."""
        with self._start_lock:
            job = repo.get_job(self._engine, job_id)
            if job is None or job.status is not JobStatus.queued:
                return None
            project = repo.get_project(self._engine, job.project_id)
            if project is None:
                self._update_job(job_id, status=JobStatus.failed, error="The project was deleted.")
                return None
            ctx = PipelineContext(
                project_id=project.id, job_id=job_id, settings=self._settings,
                workspace=self._workspace, engine=self._engine, bus=self.bus, video_id=project.video_id,
            )
            self._cancels[job_id] = ctx.cancel_event
            self._update_job(job_id, status=JobStatus.running, progress=0.0, error=None, error_hint=None)
        return ctx

    async def _run_job(self, job_id: str) -> None:
        ctx = self._start(job_id)
        if ctx is None:
            return
        self._publish_job(job_id, JobStatus.running)

        def on_progress(stage: str, overall: float) -> None:
            self._update_job(job_id, stage=stage, progress=overall)

        assert self._gpu_lock is not None
        try:
            await run_pipeline(
                self._stages_factory(), ctx,
                gpu_lock=self._gpu_lock, video_locks=self._video_locks, on_progress=on_progress,
            )
        except StageCancelled:
            if self._update_job(job_id, status=JobStatus.cancelled):
                self._publish_job(job_id, JobStatus.cancelled, message="Cancelled.")
        except StageError as exc:
            if self._update_job(job_id, status=JobStatus.failed, error=exc.message, error_hint=exc.hint):
                self._publish_job(job_id, JobStatus.failed, message=exc.message, hint=exc.hint)
        except Exception as exc:
            logger.exception("Job %s failed", job_id)
            error = f"{type(exc).__name__}: {exc}"
            hint = "This looks like a bug. Check the API window's log, then press Retry."
            if self._update_job(job_id, status=JobStatus.failed, error=error, error_hint=hint):
                self._publish_job(job_id, JobStatus.failed, message=error, hint=hint)
        else:
            if self._update_job(job_id, status=JobStatus.succeeded, progress=1.0):
                self._publish_job(job_id, JobStatus.succeeded)
        finally:
            self._cancels.pop(job_id, None)
