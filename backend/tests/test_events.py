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


def test_history_is_capped_and_forgettable():
    bus = EventBus(history_limit=3)
    for i in range(5):
        bus.publish(ev("j1", str(i)))
    assert [e.message for e in bus.history("j1")] == ["2", "3", "4"]
    bus.forget("j1")
    assert bus.history("j1") == []
