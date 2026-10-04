import logging
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from app.pipeline.context import PipelineContext
from app.pipeline.errors import StageCancelled, StageError
from app.pipeline.transcript import Segment, Transcript, Word, build_sentences
from app.workspace import atomic_write_json

logger = logging.getLogger(__name__)

SegmentCallback = Callable[[Segment, float], None]
ModelFactory = Callable[[str, str, str, str], Any]


class Transcriber(Protocol):
    def transcribe(self, audio: Path, on_segment: SegmentCallback, cancel: threading.Event) -> Transcript: ...


def _default_cuda_available() -> bool:
    try:
        import ctranslate2

        return ctranslate2.get_cuda_device_count() > 0
    except Exception:  # missing DLLs, no driver, …
        return False


def _default_model_factory(name: str, device: str, compute_type: str, download_root: str) -> Any:
    from faster_whisper import WhisperModel

    return WhisperModel(name, device=device, compute_type=compute_type, download_root=download_root)


def _is_oom(exc: BaseException) -> bool:
    text = str(exc).lower()
    return "out of memory" in text or "cuda_error_out_of_memory" in text


class FasterWhisperTranscriber:
    """faster-whisper with automatic precision/device fallback (4 GB GPUs can OOM)."""

    def __init__(
        self,
        *,
        model_name: str,
        device: str,
        compute_type: str,
        download_root: Path | str,
        model_factory: ModelFactory | None = None,
        cuda_available: Callable[[], bool] | None = None,
    ) -> None:
        self._model_name = model_name
        self._device = device
        self._compute_type = compute_type
        self._download_root = str(download_root)
        self._factory = model_factory or _default_model_factory
        self._cuda_available = cuda_available or _default_cuda_available
        self._attempts: list[tuple[str, str]] | None = None
        self._index = 0
        self._model: Any = None
        self._lock = threading.Lock()
        self.active: tuple[str, str] | None = None

    def attempts(self) -> list[tuple[str, str]]:
        if self._attempts is None:
            order: list[tuple[str, str]] = []
            if self._device in ("auto", "cuda") and self._cuda_available():
                order += [("cuda", self._compute_type), ("cuda", "int8_float16")]
            order.append(("cpu", "int8"))
            self._attempts = list(dict.fromkeys(order))
        return self._attempts

    def _load(self) -> Any:
        last_error: Exception | None = None
        attempts = self.attempts()
        while self._index < len(attempts):
            device, compute_type = attempts[self._index]
            try:
                self._model = self._factory(self._model_name, device, compute_type, self._download_root)
                self.active = (device, compute_type)
                logger.info("Loaded whisper %s on %s/%s", self._model_name, device, compute_type)
                return self._model
            except (RuntimeError, ValueError, OSError) as exc:
                logger.warning("Whisper load failed on %s/%s: %s", device, compute_type, exc)
                last_error = exc
                self._index += 1
        raise StageError(
            "Couldn't load the speech recognition model.",
            f"Run `uv run python -m app.cli doctor` in backend/ to check your GPU setup. Last error: {last_error}",
        )

    def transcribe(self, audio: Path, on_segment: SegmentCallback, cancel: threading.Event) -> Transcript:
        with self._lock:
            while True:
                model = self._model or self._load()
                try:
                    return self._run(model, audio, on_segment, cancel)
                except RuntimeError as exc:
                    if not _is_oom(exc) or self._index + 1 >= len(self.attempts()):
                        raise
                    logger.warning("Out of GPU memory on %s; falling back", self.active)
                    self._model = None
                    self._index += 1

    def _run(self, model: Any, audio: Path, on_segment: SegmentCallback, cancel: threading.Event) -> Transcript:
        if cancel.is_set():
            raise StageCancelled()
        segments_iter, info = model.transcribe(
            str(audio), word_timestamps=True, vad_filter=True,
            beam_size=5, condition_on_previous_text=False,
        )
        segments: list[Segment] = []
        for raw in segments_iter:
            if cancel.is_set():
                raise StageCancelled()
            words = [Word(text=w.word, start=w.start, end=w.end, prob=w.probability) for w in (raw.words or [])]
            segment = Segment(id=len(segments), start=raw.start, end=raw.end, text=raw.text.strip(), words=words)
            segments.append(segment)
            fraction = min(raw.end / info.duration, 1.0) if info.duration else 0.0
            on_segment(segment, fraction)
        all_words = [w for s in segments for w in s.words]
        return Transcript(
            language=info.language, language_prob=info.language_probability, duration_s=info.duration,
            segments=segments, words=all_words, sentences=build_sentences(all_words),
        )


class TranscribeStage:
    name = "transcribe"
    label = "Transcribing speech"
    weight = 3.0
    uses_gpu = True

    def __init__(self, transcriber: Transcriber) -> None:
        self._transcriber = transcriber

    def is_done(self, ctx: PipelineContext) -> bool:
        return ctx.video_id is not None and ctx.video().transcript.exists()

    def run(self, ctx: PipelineContext) -> None:
        vp = ctx.video()

        def on_segment(segment: Segment, fraction: float) -> None:
            ctx.progress(self.name, fraction)
            ctx.emit("partial", stage=self.name, data={
                "kind": "segment", "start": segment.start, "end": segment.end, "text": segment.text,
            })

        transcript = self._transcriber.transcribe(vp.audio, on_segment, ctx.cancel_event)
        ctx.emit("partial", stage=self.name, data={"kind": "language", "language": transcript.language})
        if not transcript.words:
            ctx.emit("log", stage=self.name, message="No speech was detected in this video.")
        atomic_write_json(vp.transcript, transcript)
