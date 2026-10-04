import asyncio

from app.events import EventBus, JobEvent


def ev(job_id: str, message: str) -> JobEvent:
    return JobEvent(job_id=job_id, type="log", message=message)


async def test_subscriber_receives_published_events():
    bus = EventBus()
    bus.bind(asyncio.get_running_loop())
    queue = bus.subscribe("j1")
    bus.publish(ev("j1", "hello"))
    got = await asyncio.wait_for(queue.get(), 1)
    assert got.message == "hello"


async def test_late_subscriber_gets_history_replay_in_order():
    bus = EventBus()
    bus.bind(asyncio.get_running_loop())
    bus.publish(ev("j1", "a"))
    bus.publish(ev("j1", "b"))
    queue = bus.subscribe("j1")
    assert [(await queue.get()).message for _ in range(2)] == ["a", "b"]


async def test_publish_from_worker_thread_is_delivered():
    bus = EventBus()
    bus.bind(asyncio.get_running_loop())
    queue = bus.subscribe("j1")
    await asyncio.to_thread(bus.publish, ev("j1", "from thread"))
    got = await asyncio.wait_for(queue.get(), 1)
    assert got.message == "from thread"


async def test_events_are_isolated_per_job():
    bus = EventBus()
    bus.bind(asyncio.get_running_loop())
    q1 = bus.subscribe("j1")
    bus.publish(ev("j2", "other"))
    assert q1.empty()


def test_unbound_bus_records_history_synchronously():
    bus = EventBus()
    bus.publish(ev("j1", "x"))
    assert [e.message for e in bus.history("j1")] == ["x"]


def partial(job_id: str, text: str) -> JobEvent:
    return JobEvent(job_id=job_id, type="partial", stage="transcribe", data={"kind": "segment", "text": text})


def progress(job_id: str, stage: str, fraction: float) -> JobEvent:
    return JobEvent(job_id=job_id, type="progress", stage=stage, progress=fraction)


def test_partial_history_is_capped_and_forgettable():
    bus = EventBus(history_limit=3)
    for i in range(5):
        bus.publish(partial("j1", str(i)))
    assert [e.data["text"] for e in bus.history("j1")] == ["2", "3", "4"]
    bus.forget("j1")
    assert bus.history("j1") == []


def test_only_latest_progress_per_stage_is_kept():
    bus = EventBus()
    bus.publish(progress("j1", "ingest", 0.1))
    bus.publish(progress("j1", "ingest", 0.5))
    bus.publish(progress("j1", "transcribe", 0.2))
    bus.publish(progress("j1", "ingest", 0.9))
    assert [(e.stage, e.progress) for e in bus.history("j1")] == [("transcribe", 0.2), ("ingest", 0.9)]


def test_stage_job_and_log_events_survive_heavy_traffic_in_order():
    bus = EventBus(history_limit=10)
    bus.publish(JobEvent(job_id="j1", type="job", status="running"))
    bus.publish(JobEvent(job_id="j1", type="stage", stage="ingest", status="running"))
    for i in range(5000):
        bus.publish(progress("j1", "ingest", i / 5000))
    bus.publish(JobEvent(job_id="j1", type="stage", stage="ingest", status="done"))
    bus.publish(JobEvent(job_id="j1", type="stage", stage="transcribe", status="running"))
    for i in range(5000):
        bus.publish(partial("j1", str(i)))
        bus.publish(progress("j1", "transcribe", i / 5000))
    bus.publish(JobEvent(job_id="j1", type="log", message="note"))
    bus.publish(JobEvent(job_id="j1", type="stage", stage="transcribe", status="done"))
    bus.publish(JobEvent(job_id="j1", type="job", status="succeeded"))

    history = bus.history("j1")
    assert [(e.type, e.stage, e.status) for e in history if e.type in ("job", "stage")] == [
        ("job", None, "running"), ("stage", "ingest", "running"), ("stage", "ingest", "done"),
        ("stage", "transcribe", "running"), ("stage", "transcribe", "done"), ("job", None, "succeeded"),
    ]
    assert [e.data["text"] for e in history if e.type == "partial"] == [str(i) for i in range(4990, 5000)]
    assert len([e for e in history if e.type == "progress"]) == 2
    assert any(e.type == "log" for e in history)
    assert [e.ts for e in history] == sorted(e.ts for e in history)  # chronological replay
