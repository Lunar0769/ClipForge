import threading
import time

from app import repo
from app.pipeline.context import PipelineContext
from app.pipeline.transcript import Segment, Transcript, Word, build_sentences
from app.workspace import atomic_write_json


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


class FakeIngestStage:
    name, label, weight, uses_gpu = "ingest", "Importing video", 1.0, False

    def is_done(self, ctx: PipelineContext) -> bool:
        return ctx.video_id is not None

    def run(self, ctx: PipelineContext) -> None:
        ctx.video_id = "fakevideo0001"
        repo.update_project(ctx.engine, ctx.project_id, video_id=ctx.video_id, title="Fake video", duration_s=3.0)


class FakeTranscribeStage:
    name, label, weight, uses_gpu = "transcribe", "Transcribing speech", 3.0, True

    def __init__(self, fail_times: int = 0, duration: float = 0.0) -> None:
        self.runs = 0
        self.fail_times = fail_times
        self.duration = duration

    def is_done(self, ctx: PipelineContext) -> bool:
        return ctx.video().transcript.exists()

    def run(self, ctx: PipelineContext) -> None:
        self.runs += 1
        deadline = time.monotonic() + self.duration
        while time.monotonic() < deadline:
            ctx.check_cancelled()
            time.sleep(0.01)
        if self.runs <= self.fail_times:
            from app.pipeline.errors import StageError
            raise StageError("Transient failure", hint="Press Retry")
        words = [Word(text=" Hello", start=0.0, end=0.5), Word(text=" world.", start=0.5, end=1.0)]
        segment = Segment(id=0, start=0.0, end=1.0, text="Hello world.", words=words)
        ctx.emit("partial", stage=self.name, data={"kind": "segment", "start": 0.0, "end": 1.0, "text": "Hello world."})
        atomic_write_json(ctx.video().transcript, Transcript(
            language="en", duration_s=1.0, segments=[segment], words=words, sentences=build_sentences(words),
        ))
