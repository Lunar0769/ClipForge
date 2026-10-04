import shutil
import sys
import threading
import time
from types import SimpleNamespace

import pytest

from app import media
from app.media import MediaError, compute_video_id, extract_audio, probe
from app.pipeline.errors import StageCancelled


def test_probe_video_with_audio(sample_video):
    info = probe(sample_video)
    assert info.has_video and info.has_audio
    assert (info.width, info.height) == (640, 360)
    assert info.fps == pytest.approx(30, abs=0.1)
    assert info.duration_s == pytest.approx(3, abs=0.2)


def test_probe_video_without_audio(no_audio_video):
    info = probe(no_audio_video)
    assert info.has_video and not info.has_audio


def test_probe_rejects_non_media(tmp_path):
    bogus = tmp_path / "notes.mp4"
    bogus.write_text("definitely not a video")
    with pytest.raises(MediaError):
        probe(bogus)


def test_extract_audio_writes_mono_wav_atomically(sample_video, tmp_path):
    dst = tmp_path / "out dir ü" / "audio.wav"
    dst.parent.mkdir()
    extract_audio(sample_video, dst)
    info = probe(dst)
    assert info.has_audio and not info.has_video
    assert info.duration_s == pytest.approx(3, abs=0.2)
    assert not list(dst.parent.glob("*.tmp"))


def test_video_id_is_content_based(sample_video, silent_video, tmp_path):
    duration = probe(sample_video).duration_s
    copy = tmp_path / "copy.mp4"
    shutil.copy(sample_video, copy)
    vid = compute_video_id(sample_video, duration)
    assert len(vid) == 20
    assert compute_video_id(copy, duration) == vid
    assert compute_video_id(silent_video, probe(silent_video).duration_s) != vid


@pytest.mark.parametrize("stdout", [
    "this is not json",
    '{"format": {"duration": "N/A"}, "streams": [{"codec_type": "audio"}]}',
])
def test_probe_wraps_unparseable_output_in_media_error(monkeypatch, tmp_path, stdout):
    monkeypatch.setattr(media, "_run", lambda args: SimpleNamespace(stdout=stdout, stderr="", returncode=0))
    with pytest.raises(MediaError):
        probe(tmp_path / "x.mp4")


def _fake_ffmpeg(script: str):
    """Replace the ffmpeg command line with a Python child that writes the .tmp output itself."""
    return lambda src, tmp, sample_rate: [sys.executable, "-c", script, str(tmp)]


def test_cancelled_extraction_raises_and_leaves_no_tmp(monkeypatch, tmp_path):
    started = tmp_path / "started"
    script = (
        "import sys, time, pathlib; pathlib.Path(sys.argv[1]).write_bytes(b'partial'); "
        f"pathlib.Path({str(started)!r}).touch(); time.sleep(30)"
    )
    monkeypatch.setattr(media, "_audio_command", _fake_ffmpeg(script))
    cancel = threading.Event()

    def cancel_once_started():
        deadline = time.monotonic() + 10
        while not started.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        cancel.set()

    threading.Thread(target=cancel_once_started, daemon=True).start()
    dst = tmp_path / "audio.wav"
    t0 = time.monotonic()
    with pytest.raises(StageCancelled):
        extract_audio(tmp_path / "in.mp4", dst, cancel=cancel)
    assert time.monotonic() - t0 < 10
    assert started.exists()
    assert not dst.exists()
    assert not list(tmp_path.glob("*.tmp"))


def test_failed_extraction_raises_media_error_and_leaves_no_tmp(monkeypatch, tmp_path):
    script = "import sys, pathlib; pathlib.Path(sys.argv[1]).write_bytes(b'partial'); sys.stderr.write('boom'); sys.exit(1)"
    monkeypatch.setattr(media, "_audio_command", _fake_ffmpeg(script))
    dst = tmp_path / "audio.wav"
    with pytest.raises(MediaError, match="boom"):
        extract_audio(tmp_path / "in.mp4", dst)
    assert not dst.exists()
    assert not list(tmp_path.glob("*.tmp"))


def test_failed_real_ffmpeg_leaves_no_tmp(tmp_path):
    bogus = tmp_path / "bogus.mp4"
    bogus.write_text("not a video")
    with pytest.raises(MediaError):
        extract_audio(bogus, tmp_path / "audio.wav", cancel=threading.Event())
    assert not list(tmp_path.glob("*.tmp"))
