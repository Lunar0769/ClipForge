import asyncio
import threading
import time

import pytest

from app import repo
from app.events import EventBus
from app.jobs.queue import JobQueue
from app.models import JobStatus, SourceType
from app.pipeline.errors import StageError
from tests.fakes import RecordingStage


@pytest.fixture
async def make_queue(settings, workspace, engine):
    queues: list[JobQueue] = []

    async def _make(stages, concurrency=2):
        q = JobQueue(engine=engine, workspace=workspace, settings=settings, bus=EventBus(),
                     stages_factory=lambda: stages, concurrency=concurrency)
        await q.start()
        queues.append(q)
        return q

    yield _make
    for q in queues:
        await q.stop()


def new_job(engine):
    project = repo.create_project(engine, source_type=SourceType.upload)
    return repo.create_job(engine, project.id)


async def wait_status(engine, job_id, *statuses, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = repo.get_job(engine, job_id)
        if job.status in statuses:
            return job
        await asyncio.sleep(0.02)
    raise AssertionError(f"job {job_id} stuck in {repo.get_job(engine, job_id).status}")


async def test_successful_job(make_queue, engine):
    q = await make_queue([RecordingStage("a"), RecordingStage("b")])
    job = new_job(engine)
    q.submit(job.id)
    done = await wait_status(engine, job.id, JobStatus.succeeded)
    assert done.progress == 1.0
    events = q.bus.history(job.id)
    assert events[0].type == "job" and events[0].status == "running"
    assert events[-1].type == "job" and events[-1].status == "succeeded"


async def test_stage_error_marks_failed_with_hint(make_queue, engine):
    q = await make_queue([RecordingStage("a", fail=StageError("Bad video", hint="Use another"))])
    job = new_job(engine)
    q.submit(job.id)
    failed = await wait_status(engine, job.id, JobStatus.failed)
    assert (failed.error, failed.error_hint, failed.stage) == ("Bad video", "Use another", "a")
    last = q.bus.history(job.id)[-1]
    assert last.status == "failed" and last.data == {"hint": "Use another"}


async def test_unexpected_error_marks_failed(make_queue, engine):
    q = await make_queue([RecordingStage("a", fail=ValueError("kaboom"))])
    job = new_job(engine)
    q.submit(job.id)
    failed = await wait_status(engine, job.id, JobStatus.failed)
    assert failed.error == "ValueError: kaboom"


async def test_cancel_running_job(make_queue, engine):
    q = await make_queue([RecordingStage("slow", duration=5)])
    job = new_job(engine)
    q.submit(job.id)
    await wait_status(engine, job.id, JobStatus.running)
    await asyncio.sleep(0.05)
    assert q.cancel(job.id) is True
    await wait_status(engine, job.id, JobStatus.cancelled, timeout=2)


async def test_cancel_queued_job_never_runs(make_queue, engine):
    slow = RecordingStage("slow", duration=0.5)
    q = await make_queue([slow], concurrency=1)
    first, second = new_job(engine), new_job(engine)
    q.submit(first.id)
    q.submit(second.id)
    await wait_status(engine, first.id, JobStatus.running)
    assert q.cancel(second.id) is True
    await wait_status(engine, first.id, JobStatus.succeeded)
    await asyncio.sleep(0.1)
    assert repo.get_job(engine, second.id).status is JobStatus.cancelled
    assert slow.runs == 1


async def test_cancel_unknown_or_finished_job_returns_false(make_queue, engine):
    q = await make_queue([RecordingStage("a")])
    job = new_job(engine)
    q.submit(job.id)
    await wait_status(engine, job.id, JobStatus.succeeded)
    assert q.cancel(job.id) is False
    assert q.cancel("nope") is False


async def test_gpu_stages_never_overlap(make_queue, engine):
    gpu = RecordingStage("gpu", uses_gpu=True, duration=0.2)
    q = await make_queue([gpu], concurrency=2)
    jobs = [new_job(engine), new_job(engine)]
    for j in jobs:
        q.submit(j.id)
    for j in jobs:
        await wait_status(engine, j.id, JobStatus.succeeded)
    assert gpu.runs == 2 and gpu.max_active == 1


async def test_cancel_racing_with_worker_start_still_cancels(make_queue, engine, monkeypatch):
    """cancel() lands between the worker reading the queued job and marking it running."""
    slow = RecordingStage("slow", duration=1.0)
    q = await make_queue([slow], concurrency=1)
    job = new_job(engine)
    real_get_job = repo.get_job
    fired = []

    def get_job_with_concurrent_cancel(eng, job_id):
        result = real_get_job(eng, job_id)
        if not fired and asyncio.current_task() in q._workers:  # the worker, not wait_status()
            fired.append(True)
            canceller = threading.Thread(target=lambda: fired.append(q.cancel(job_id)))
            canceller.start()
            canceller.join(0.3)  # an unguarded cancel() completes here, before the worker marks the job running
        return result

    monkeypatch.setattr(repo, "get_job", get_job_with_concurrent_cancel)
    q.submit(job.id)
    await wait_status(engine, job.id, JobStatus.cancelled, JobStatus.succeeded, timeout=5)
    await asyncio.sleep(0.2)
    assert repo.get_job(engine, job.id).status is JobStatus.cancelled
    assert fired == [True, True]
    assert slow.runs == 0
