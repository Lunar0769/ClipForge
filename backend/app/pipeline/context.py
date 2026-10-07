import threading
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import Engine

from app.config import Settings
from app.events import EventBus, EventType, JobEvent
from app.pipeline.errors import StageCancelled
from app.workspace import VideoPaths, Workspace


@dataclass
class PipelineContext:
    project_id: str
    job_id: str
    settings: Settings
    workspace: Workspace
    engine: Engine
    bus: EventBus
    video_id: str | None = None
    cancel_event: threading.Event = field(default_factory=threading.Event)

    def video(self) -> VideoPaths:
        if self.video_id is None:
            raise RuntimeError("video_id is not set; the ingest stage must run first")
        return self.workspace.video(self.video_id)

    def emit(self, type: EventType, **fields: Any) -> None:
        self.bus.publish(JobEvent(job_id=self.job_id, type=type, **fields))

    def progress(self, stage: str, fraction: float, message: str | None = None) -> None:
        self.emit("progress", stage=stage, progress=max(0.0, min(1.0, fraction)), message=message)

    @property
    def cancel(self) -> threading.Event:
        return self.cancel_event

    def check_cancelled(self) -> None:
        if self.cancel_event.is_set():
            raise StageCancelled()
