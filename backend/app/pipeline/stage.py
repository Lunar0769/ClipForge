from typing import Protocol

from app.pipeline.context import PipelineContext


class Stage(Protocol):
    name: str      # stable id used in events and the API, e.g. "transcribe"
    label: str     # human label shown in the UI, e.g. "Transcribing speech"
    weight: float  # relative share of total job time, for the overall progress bar
    uses_gpu: bool # GPU stages run one at a time across all jobs

    def is_done(self, ctx: PipelineContext) -> bool:
        """True if this stage's artifacts already exist (checkpoint/cache hit)."""
        ...

    def run(self, ctx: PipelineContext) -> None:
        """Do the work synchronously. Called in a worker thread."""
        ...
