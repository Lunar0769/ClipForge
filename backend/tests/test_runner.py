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
