import threading

import pytest

from app.gpu import register_cuda_dlls
from app.media import extract_audio
from app.pipeline.transcribe import FasterWhisperTranscriber


@pytest.mark.gpu
def test_real_model_runs_on_gpu(sample_video, tmp_path, settings):
    """Run with: uv run pytest -m gpu  (needs `python -m app.cli download-models` first)."""
    from app.config import REPO_ROOT

    register_cuda_dlls()
    audio = tmp_path / "audio.wav"
    extract_audio(sample_video, audio)
    t = FasterWhisperTranscriber(
        model_name=settings.whisper_model, device="auto", compute_type="float16",
        download_root=REPO_ROOT / "models" / "whisper",
    )
    result = t.transcribe(audio, lambda *_: None, threading.Event())
    assert result.duration_s == pytest.approx(3, abs=0.3)
    assert t.active[0] == "cuda", f"expected GPU, got {t.active}"
