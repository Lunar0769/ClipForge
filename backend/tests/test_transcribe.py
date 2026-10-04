import threading
from types import SimpleNamespace

import pytest

from app.pipeline.errors import StageCancelled, StageError
from app.pipeline.transcribe import FasterWhisperTranscriber, TranscribeStage
from app.pipeline.transcript import Segment, Transcript, Word
from app.workspace import read_json


def fake_segments():
    words1 = [SimpleNamespace(word=" Hello", start=0.0, end=0.4, probability=0.9),
              SimpleNamespace(word=" world.", start=0.4, end=0.9, probability=0.95)]
    words2 = [SimpleNamespace(word=" Bye.", start=1.0, end=1.5, probability=0.99)]
    return [SimpleNamespace(start=0.0, end=0.9, text=" Hello world.", words=words1),
            SimpleNamespace(start=1.0, end=1.5, text=" Bye.", words=words2)]


class FakeModel:
    def __init__(self, fail_with: Exception | None = None):
        self.fail_with = fail_with

    def transcribe(self, audio, **kwargs):
        assert kwargs["word_timestamps"] is True and kwargs["vad_filter"] is True
        if self.fail_with:
            raise self.fail_with
        info = SimpleNamespace(language="en", language_probability=0.98, duration=2.0)
        return iter(fake_segments()), info


def make_transcriber(models: dict, cuda=True):
    created = []

    def factory(name, device, compute_type, download_root):
        created.append((device, compute_type))
        outcome = models[(device, compute_type)]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    t = FasterWhisperTranscriber(
        model_name="large-v3-turbo", device="auto", compute_type="float16",
        download_root="models", model_factory=factory, cuda_available=lambda: cuda,
    )
    return t, created


def test_attempt_order_with_and_without_cuda():
    with_gpu, _ = make_transcriber({}, cuda=True)
    assert with_gpu.attempts() == [("cuda", "float16"), ("cuda", "int8_float16"), ("cpu", "int8")]
    cpu_only, _ = make_transcriber({}, cuda=False)
    assert cpu_only.attempts() == [("cpu", "int8")]


def test_transcribe_builds_words_sentences_and_streams_segments(tmp_path):
    t, _ = make_transcriber({("cuda", "float16"): FakeModel()})
    seen = []
    result = t.transcribe(tmp_path / "a.wav", lambda seg, frac: seen.append((seg.text, frac)), threading.Event())
    assert result.language == "en"
    assert [w.text for w in result.words] == [" Hello", " world.", " Bye."]
    assert [s.text for s in result.sentences] == ["Hello world.", "Bye."]
    assert seen == [("Hello world.", 0.45), ("Bye.", 0.75)]
    assert t.active == ("cuda", "float16")


def test_falls_back_when_model_fails_to_load(tmp_path):
    t, created = make_transcriber({
        ("cuda", "float16"): RuntimeError("Library cublas64_12.dll is not found"),
        ("cuda", "int8_float16"): RuntimeError("still broken"),
        ("cpu", "int8"): FakeModel(),
    })
    t.transcribe(tmp_path / "a.wav", lambda *_: None, threading.Event())
    assert created == [("cuda", "float16"), ("cuda", "int8_float16"), ("cpu", "int8")]
    assert t.active == ("cpu", "int8")


def test_falls_back_on_out_of_memory_during_inference(tmp_path):
    t, _ = make_transcriber({
        ("cuda", "float16"): FakeModel(fail_with=RuntimeError("CUDA failed with error out of memory")),
        ("cuda", "int8_float16"): FakeModel(),
    })
    result = t.transcribe(tmp_path / "a.wav", lambda *_: None, threading.Event())
    assert t.active == ("cuda", "int8_float16")
    assert len(result.segments) == 2


def test_all_attempts_failing_raises_stage_error(tmp_path):
    t, _ = make_transcriber({("cpu", "int8"): RuntimeError("nope")}, cuda=False)
    with pytest.raises(StageError, match="speech recognition model"):
        t.transcribe(tmp_path / "a.wav", lambda *_: None, threading.Event())


def test_cancel_during_transcription(tmp_path):
    t, _ = make_transcriber({("cuda", "float16"): FakeModel()})
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(StageCancelled):
        t.transcribe(tmp_path / "a.wav", lambda *_: None, cancel)


class StubTranscriber:
    def __init__(self, transcript: Transcript):
        self.transcript = transcript

    def transcribe(self, audio, on_segment, cancel):
        for seg in self.transcript.segments:
            on_segment(seg, seg.end / self.transcript.duration_s)
        return self.transcript


def test_stage_writes_transcript_and_streams_partials(make_ctx, bus):
    ctx = make_ctx()
    ctx.video_id = "vid1"
    word = Word(text=" Hi.", start=0, end=0.5)
    transcript = Transcript(language="en", duration_s=1.0,
                            segments=[Segment(id=0, start=0, end=0.5, text="Hi.", words=[word])],
                            words=[word])
    stage = TranscribeStage(StubTranscriber(transcript))
    assert not stage.is_done(ctx)
    stage.run(ctx)
    assert stage.is_done(ctx)
    assert read_json(ctx.video().transcript)["language"] == "en"
    partials = [e.data for e in bus.history(ctx.job_id) if e.type == "partial"]
    assert {"kind": "segment", "start": 0.0, "end": 0.5, "text": "Hi."} in partials
    assert {"kind": "language", "language": "en"} in partials


def test_stage_handles_video_without_speech(make_ctx, bus):
    ctx = make_ctx()
    ctx.video_id = "silent"
    TranscribeStage(StubTranscriber(Transcript(language="en", duration_s=3.0))).run(ctx)
    assert read_json(ctx.video().transcript)["words"] == []
    logs = [e.message for e in bus.history(ctx.job_id) if e.type == "log"]
    assert any("No speech" in m for m in logs)
