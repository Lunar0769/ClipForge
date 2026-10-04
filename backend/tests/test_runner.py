import asyncio

import pytest

from app.pipeline.errors import StageCancelled, StageError
from app.pipeline.runner import VideoLocks, run_pipeline
from tests.fakes import RecordingStage


def statuses(bus, job_id):
    return [(e.stage, e.status) for e in bus.history(job_id) if e.type == "stage"]


async def run(stages, ctx, **kw):
    return await run_pipeline(
        stages, ctx, gpu_lock=kw.pop("gpu_lock", asyncio.Lock()),
        video_locks=kw.pop("video_locks", VideoLocks()), **kw,
    )


async def test_runs_stages_in_order_and_emits_lifecycle(make_ctx, bus):
    ctx = make_ctx()
    a, b = RecordingStage("a"), RecordingStage("b")
    await run([a, b], ctx)
    assert (a.runs, b.runs) == (1, 1)
    assert statuses(bus, ctx.job_id) == [("a", "running"), ("a", "done"), ("b", "running"), ("b", "done")]


async def test_skips_completed_stage(make_ctx, bus):
    ctx = make_ctx()
    cached = RecordingStage("a", done=True)
    await run([cached], ctx)
    assert cached.runs == 0
    assert statuses(bus, ctx.job_id) == [("a", "cached")]


async def test_stage_error_emits_failed_and_propagates(make_ctx, bus):
    ctx = make_ctx()
    boom = RecordingStage("a", fail=StageError("Bad video", hint="Try another"))
    after = RecordingStage("b")
    with pytest.raises(StageError):
        await run([boom, after], ctx)
    assert after.runs == 0
    failed = [e for e in bus.history(ctx.job_id) if e.status == "failed"][0]
    assert failed.message == "Bad video"


async def test_cancel_stops_before_next_stage(make_ctx):
    ctx = make_ctx()
    slow = RecordingStage("a", duration=5.0)
    after = RecordingStage("b")
    task = asyncio.create_task(run([slow, after], ctx))
    await asyncio.sleep(0.1)
    ctx.cancel_event.set()
    with pytest.raises(StageCancelled):
        await asyncio.wait_for(task, 2)
    assert after.runs == 0
    assert ("a", "cancelled") in statuses(ctx.bus, ctx.job_id)


async def test_gpu_stages_are_serialized_across_jobs(make_ctx):
    gpu_stage = RecordingStage("gpu", uses_gpu=True, duration=0.2)
    gpu_lock, locks = asyncio.Lock(), VideoLocks()
    await asyncio.gather(
        run([gpu_stage], make_ctx(), gpu_lock=gpu_lock, video_locks=locks),
        run([gpu_stage], make_ctx(), gpu_lock=gpu_lock, video_locks=locks),
    )
    assert gpu_stage.runs == 2
    assert gpu_stage.max_active == 1


async def test_same_video_stages_are_serialized(make_ctx):
    cpu_stage = RecordingStage("cpu", duration=0.2)
    c1, c2 = make_ctx(), make_ctx()
    c1.video_id = c2.video_id = "samevideo"
    locks = VideoLocks()
    await asyncio.gather(run([cpu_stage], c1, video_locks=locks), run([cpu_stage], c2, video_locks=locks))
    assert cpu_stage.max_active == 1


async def test_on_progress_reports_weighted_overall_progress(make_ctx):
    calls = []
    await run(
        [RecordingStage("a", weight=1), RecordingStage("b", weight=3)],
        make_ctx(),
        on_progress=lambda stage, overall: calls.append((stage, overall)),
    )
    assert calls == [("a", 0.0), ("a", 0.25), ("b", 0.25), ("b", 1.0)]


async def test_cancel_while_waiting_for_gpu_lock(make_ctx):
    gpu_lock = asyncio.Lock()
    await gpu_lock.acquire()  # Another job holds the GPU for the whole test

    ctx = make_ctx()
    gpu_stage = RecordingStage("gpu", uses_gpu=True)
    task = asyncio.create_task(run([gpu_stage], ctx, gpu_lock=gpu_lock, video_locks=VideoLocks()))
    await asyncio.sleep(0.1)  # Let it start waiting
    ctx.cancel_event.set()

    with pytest.raises(StageCancelled):
        await asyncio.wait_for(task, 1.5)  # observed while the lock is still held
    assert gpu_lock.locked()
    gpu_lock.release()
    assert gpu_stage.runs == 0
    assert ("gpu", "cancelled") in statuses(ctx.bus, ctx.job_id)
    waiting = [e.message for e in ctx.bus.history(ctx.job_id) if e.type == "progress" and e.stage == "gpu"]
    assert waiting == ["Waiting for the GPU…"]


async def test_cancel_while_waiting_for_video_lock(make_ctx):
    locks = VideoLocks()
    held = locks.get("samevideo")
    await held.acquire()  # Another job is building artifacts for this video

    ctx = make_ctx()
    ctx.video_id = "samevideo"
    stage = RecordingStage("cpu")
    task = asyncio.create_task(run([stage], ctx, video_locks=locks))
    await asyncio.sleep(0.1)
    ctx.cancel_event.set()

    with pytest.raises(StageCancelled):
        await asyncio.wait_for(task, 1.5)
    assert held.locked()
    held.release()
    assert stage.runs == 0
    waiting = [e.message for e in ctx.bus.history(ctx.job_id) if e.type == "progress"]
    assert waiting == ["Waiting for another job on this video…"]


async def test_locks_are_released_after_waiting(make_ctx):
    gpu_lock = asyncio.Lock()
    await gpu_lock.acquire()
    ctx = make_ctx()
    gpu_stage = RecordingStage("gpu", uses_gpu=True)
    task = asyncio.create_task(run([gpu_stage], ctx, gpu_lock=gpu_lock))
    await asyncio.sleep(0.1)
    gpu_lock.release()
    await asyncio.wait_for(task, 2)
    assert gpu_stage.runs == 1
    assert not gpu_lock.locked()


async def test_cached_after_first_job_on_same_video(make_ctx):
    """Two jobs on same video_id: first runs stage, second caches when is_done becomes True."""

    class FlipDoneStage(RecordingStage):
        def __init__(self, name):
            super().__init__(name)
            self.done_after_run = False

        def is_done(self, ctx):
            return self.done_after_run

        def run(self, ctx):
            super().run(ctx)
            self.done_after_run = True

    stage = FlipDoneStage("reuse")
    locks = VideoLocks()
    c1, c2 = make_ctx(), make_ctx()
    c1.video_id = c2.video_id = "samevideo"

    await run([stage], c1, video_locks=locks)
    await run([stage], c2, video_locks=locks)

    assert stage.runs == 1
    assert stage.done_after_run
    c1_statuses = statuses(c1.bus, c1.job_id)
    c2_statuses = statuses(c2.bus, c2.job_id)
    assert ("reuse", "done") in c1_statuses
    assert ("reuse", "cached") in c2_statuses
